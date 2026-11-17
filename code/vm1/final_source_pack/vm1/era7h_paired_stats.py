#!/usr/bin/env python3
"""ERA7H FINAL: paired within-block comparisons for the E2 randomized complete block design.

The experimental unit is one independent run. For every context, comparison (A vs B) and metric, runs are
paired by block b and the per-block difference d_b = A_b - B_b is analysed (n = number of complete pairs,
at most --blocks). Reported per test:
  mean diff with 95% t-CI, median diff, Hodges-Lehmann estimate, median per-block relative change (%),
  paired t-test p, exact Wilcoxon signed-rank p (zero differences dropped; midranks for ties), and
  Holm-adjusted p-values within a family = (metric x tier), plus a conservative global Holm correction across all inferential tests. Tier 'primary' = era_dual vs static_high
  (4 contexts -> 4 tests per metric); tier 'secondary' = the other axis-isolating comparisons.
Comparisons whose two policies select the SAME wire pair in that context are flagged same_wire_pair=True:
they are negative controls and are expected to be null.
No third-party packages are required.
"""
import argparse, csv, math, os, statistics, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from era7h_validate_run import EXPECTED  # single source of truth for policy/context -> wire pair

COMPARISONS = [  # (A, B, tier, question)
    ('era_dual', 'static_high', 'primary', 'total adaptive-policy effect vs always-strong'),
    ('battery_only', 'static_high', 'secondary', 'battery/signature axis alone'),
    ('ran_only', 'static_high', 'secondary', 'RAN/KEM axis alone'),
    ('era_dual', 'battery_only', 'secondary', 'incremental RAN axis'),
    ('era_dual', 'ran_only', 'secondary', 'incremental battery axis'),
    ('era_dual', 'static_low', 'secondary', 'cost relative to always-light'),
]
METRICS = ['conn_latency_median_ms', 'conn_latency_p95_ms', 'capture_bytes_per_hs', 'packets_per_hs', 'flow_duration_median_ms',
           'tcp_syn_rtt_median_ms', 'ping_rtt_median_ms', 'udp_receiver_mbps', 'udp_loss_pct', 'udp_jitter_ms', 'cpu_user_s_mean']

# ---------- distributions (no scipy) ----------
def _betacf(a, b, x):
    MAXIT, EPS, FPMIN = 300, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > FPMIN else FPMIN); h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > FPMIN else FPMIN)
        c = 1 + aa / c; c = c if abs(c) > FPMIN else FPMIN; h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > FPMIN else FPMIN)
        c = 1 + aa / c; c = c if abs(c) > FPMIN else FPMIN
        de = d * c; h *= de
        if abs(de - 1) < EPS: break
    return h
def betainc(a, b, x):
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    bt = math.exp(lbt)
    return bt * _betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - bt * _betacf(b, a, 1 - x) / b
def t_two_sided_p(t, df):
    return betainc(df / 2, 0.5, df / (df + t * t))
def t_crit95(df):
    lo, hi = 0.0, 100.0  # invert two-sided p = 0.05
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_two_sided_p(mid, df) > 0.05: lo = mid
        else: hi = mid
    return (lo + hi) / 2

def wilcoxon_exact(d):
    """Two-sided exact signed-rank p; zeros dropped, midranks for ties (exact conditional distribution)."""
    nz = [x for x in d if x != 0]
    n = len(nz)
    if n == 0: return 1.0, 0
    order = sorted(range(n), key=lambda i: abs(nz[i]))
    ranks2 = [0] * n  # doubled midranks -> integers
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(nz[order[j + 1]]) == abs(nz[order[i]]): j += 1
        r2 = (i + 1) + (j + 1)  # 2 * midrank
        for k in range(i, j + 1): ranks2[order[k]] = r2
        i = j + 1
    w = sum(r for r, x in zip(ranks2, nz) if x > 0)
    dist = {0: 1}
    for r in ranks2:
        nd = defaultdict(int)
        for s, c in dist.items(): nd[s] += c; nd[s + r] += c
        dist = nd
    tot = 2 ** n
    le = sum(c for s, c in dist.items() if s <= w) / tot
    ge = sum(c for s, c in dist.items() if s >= w) / tot
    return min(1.0, 2 * min(le, ge)), n

def hodges_lehmann(d):
    w = [(d[i] + d[j]) / 2 for i in range(len(d)) for j in range(i, len(d))]
    return statistics.median(w) if w else None

def holm(ps):
    idx = [i for i, p in enumerate(ps) if p is not None]
    out = [None] * len(ps); m = len(idx); running = 0.0
    for rank, i in enumerate(sorted(idx, key=lambda i: ps[i])):
        running = max(running, min(1.0, (m - rank) * ps[i])); out[i] = running
    return out

def num(x):
    try:
        v = float(x); return v if math.isfinite(v) else None
    except Exception: return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('root'); a = ap.parse_args()
    root = os.path.abspath(a.root); pf = os.path.join(root, 'processed', 'run_summary.csv')
    if not os.path.exists(pf): raise SystemExit('run era7h_analyze.py first (processed/run_summary.csv missing)')
    rows = [r for r in csv.DictReader(open(pf)) if r['experiment'] == 'E2']
    by = {(r['context'], r['condition'], int(r['block'])): r for r in rows}
    contexts = sorted({r['context'] for r in rows}); blocks = sorted({int(r['block']) for r in rows})
    out = []
    for metric in METRICS:
        for (A, B, tier, q) in COMPARISONS:
            for ctx in contexts:
                pairs = []
                for b in blocks:
                    ra, rb = by.get((ctx, A, b)), by.get((ctx, B, b))
                    if not ra or not rb: continue
                    va, vb = num(ra.get(metric)), num(rb.get(metric))
                    if va is None or vb is None: continue
                    pairs.append((b, va, vb))
                if not pairs: continue
                d = [va - vb for _, va, vb in pairs]; n = len(d)
                rel = [100 * (va - vb) / vb for _, va, vb in pairs if vb not in (0, None)]
                mean = statistics.mean(d); sd = statistics.stdev(d) if n > 1 else None
                if n > 1 and sd and sd > 0:
                    tc = t_crit95(n - 1); se = sd / math.sqrt(n)
                    ci = (mean - tc * se, mean + tc * se); pt = t_two_sided_p(mean / se, n - 1)
                elif n > 1:
                    ci = (mean, mean); pt = 1.0 if mean == 0 else 0.0
                else:
                    ci = (None, None); pt = None
                pw, nw = wilcoxon_exact(d) if n > 1 else (None, 0)
                out.append({'metric': metric, 'tier': tier, 'context': ctx, 'A': A, 'B': B, 'question': q,
                            'same_wire_pair': EXPECTED[ctx][A] == EXPECTED[ctx][B],
                            'wire_A': '/'.join(EXPECTED[ctx][A]), 'wire_B': '/'.join(EXPECTED[ctx][B]),
                            'n_pairs': n, 'mean_A': statistics.mean(x for _, x, _ in pairs), 'mean_B': statistics.mean(x for _, _, x in pairs),
                            'mean_diff': mean, 'sd_diff': sd, 'ci95_lo': ci[0], 'ci95_hi': ci[1],
                            'median_diff': statistics.median(d), 'hodges_lehmann': hodges_lehmann(d),
                            'median_rel_change_pct': statistics.median(rel) if rel else None,
                            'blocks_A_lower': sum(1 for x in d if x < 0), 'blocks_A_higher': sum(1 for x in d if x > 0),
                            'p_paired_t': pt, 'p_wilcoxon_exact': pw, 'n_nonzero_wilcoxon': nw})
    fam = defaultdict(list)
    for i, r in enumerate(out): fam[(r['metric'], r['tier'])].append(i)
    for idx in fam.values():
        for key in ('p_paired_t', 'p_wilcoxon_exact'):
            adj = holm([out[i][key] for i in idx])
            for i, v in zip(idx, adj): out[i][key + '_holm'] = v
    # Conservative global family across all inferential comparisons/contexts/metrics.
    # era_dual vs static_low is retained as a descriptive lower-cost reference, not part of the global hypothesis family.
    infer_idx=[i for i,r in enumerate(out) if r['B'] != 'static_low']
    for key in ('p_paired_t','p_wilcoxon_exact'):
        adj=holm([out[i][key] for i in infer_idx])
        for i,v in zip(infer_idx,adj): out[i][key+'_holm_global']=v
    for i,r in enumerate(out):
        if 'p_paired_t_holm_global' not in r: r['p_paired_t_holm_global']=None
        if 'p_wilcoxon_exact_holm_global' not in r: r['p_wilcoxon_exact_holm_global']=None
    os.makedirs(os.path.join(root, 'processed'), exist_ok=True)
    f1 = os.path.join(root, 'processed', 'paired_tests.csv')
    with open(f1, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    head = [r for r in out if r['tier'] == 'primary' and r['metric'] in ('conn_latency_median_ms', 'capture_bytes_per_hs', 'packets_per_hs', 'conn_latency_p95_ms')]
    f2 = os.path.join(root, 'processed', 'paired_headline.csv')
    with open(f2, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(head)
    print('[PASS] wrote', f1); print('[PASS] wrote', f2)
    minp = 2 / 2 ** max(len(blocks), 1)
    print(f'[NOTE] with n={len(blocks)} pairs the smallest attainable two-sided Wilcoxon p is {minp:.4g}; Holm families: '
          f'primary=4 tests/metric, secondary={len([c for c in COMPARISONS if c[2]=="secondary"])*len(contexts)} tests/metric.')
    for r in head:
        if r['metric'] in ('conn_latency_median_ms', 'capture_bytes_per_hs'):
            print(f"  {r['context']} {r['metric']}: A-B mean {r['mean_diff']:.3f} [{(r['ci95_lo'] or 0):.3f}, {(r['ci95_hi'] or 0):.3f}] "
                  f"rel {r['median_rel_change_pct'] if r['median_rel_change_pct'] is None else round(r['median_rel_change_pct'],2)}% "
                  f"p_W(Holm)={r['p_wilcoxon_exact_holm']} same_wire={r['same_wire_pair']}")

if __name__ == '__main__': raise SystemExit(main())
