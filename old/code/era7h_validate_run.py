#!/usr/bin/env python3
"""ERA7H FINAL run validator. A run gets VALID.ok only if every check passes.
v2 changes: battery fields must be PRESENT (no silent default); audit rows filtered to ue2 when a UE field exists;
loaded runs validated against server-side iperf receiver data; tcpdump drop counters and SYN-RTT completeness
checked; host thermal/throttle state recorded as notes (not failures)."""
import argparse, csv, json, os, sys

EXPECTED = {
  'C00': {'static_low': ('mlkem768','falcon512'), 'static_high': ('mlkem1024','mldsa44'), 'battery_only': ('mlkem1024','mldsa44'), 'ran_only': ('mlkem1024','mldsa44'), 'era_dual': ('mlkem1024','mldsa44')},
  'CB0': {'static_low': ('mlkem768','falcon512'), 'static_high': ('mlkem1024','mldsa44'), 'battery_only': ('mlkem1024','falcon512'), 'ran_only': ('mlkem1024','mldsa44'), 'era_dual': ('mlkem1024','falcon512')},
  'C0F': {'static_low': ('mlkem768','falcon512'), 'static_high': ('mlkem1024','mldsa44'), 'battery_only': ('mlkem1024','mldsa44'), 'ran_only': ('mlkem768','mldsa44'), 'era_dual': ('mlkem768','mldsa44')},
  'CBF': {'static_low': ('mlkem768','falcon512'), 'static_high': ('mlkem1024','mldsa44'), 'battery_only': ('mlkem1024','falcon512'), 'ran_only': ('mlkem768','mldsa44'), 'era_dual': ('mlkem768','falcon512')},
}
E1 = {'M1': ('mlkem768','falcon512'), 'M2': ('mlkem768','mldsa44'), 'M3': ('mlkem1024','falcon512'), 'M4': ('mlkem1024','mldsa44')}
# Candidate key names in era_audit.log. The first one present is used; if none is present the run FAILS.
CLIENT_BATT_KEYS = ('client_batt', 'client_battery', 'battery_pct', 'ue_batt')
SERVER_BATT_KEYS = ('server_batt', 'server_battery')
UE_KEYS = ('ue', 'client', 'ue_id')

def expected_pair(exp, ctx, cond):
    return E1[cond] if exp == 'E1' else EXPECTED[ctx][cond]

def first_key(d, keys):
    for k in keys:
        if k in d and d[k] is not None:
            return k
    return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('run_dir'); a = ap.parse_args(); d = a.run_dir
    fails = []; notes = []
    def req(path):
        p = os.path.join(d, path)
        if not os.path.exists(p): fails.append(f'missing {path}')
        return p
    meta_p = req('metadata.json')
    if fails: print('\n'.join('[FAIL] ' + x for x in fails)); return 2
    m = json.load(open(meta_p)); exp = m['experiment']; ctx = m['context']; cond = m['condition']
    n = int(m['measured_n']); warm = int(m['warmup_n'])
    csvp = req('ue2/crypto_log_measured.csv'); warmp = req('ue2/crypto_log_warmup.csv'); pcap = req('ue2/crypto_measured.pcap')
    bmeta = req('ue2/bench_measured_meta.json'); req('pcap_summary.json')
    req('era_audit_measured.jsonl'); req('ran_measured.csv'); req('context_gate_before.json'); req('context_gate_after.json')
    if fails: print('\n'.join('[FAIL] ' + x for x in fails)); return 2

    # --- crypto correctness
    rows = list(csv.DictReader(open(csvp))); wrows = list(csv.DictReader(open(warmp)))
    if len(rows) != n: fails.append(f'measured rows {len(rows)} != {n}')
    if len(wrows) != warm: fails.append(f'warmup rows {len(wrows)} != {warm}')
    if any(r.get('result') != 'ok' for r in rows): fails.append('one or more measured handshakes not ok')
    if any(r.get('req_kem') != r.get('neg_kem') or r.get('req_sig') != r.get('neg_sig') for r in rows): fails.append('requested != negotiated in measured handshakes')
    ek, es = expected_pair(exp, ctx, cond)
    bad = [(r.get('req_kem'), r.get('req_sig')) for r in rows if (r.get('req_kem'), r.get('req_sig')) != (ek, es)]
    if bad: fails.append(f'expected {ek}/{es}; mismatching measured choices={bad[:5]}')

    # --- capture integrity
    if not os.path.getsize(pcap): fails.append('pcap is empty')
    bm = json.load(open(bmeta))
    if bm.get('tcpdump_dropped_kernel') != 0: fails.append(f"tcpdump kernel drops = {bm.get('tcpdump_dropped_kernel')} (must be 0)")
    if (bm.get('tcpdump_dropped_interface') or 0) != 0: fails.append(f"tcpdump interface drops = {bm.get('tcpdump_dropped_interface')}")
    if bm.get('tcpdump_captured') is None or bm.get('tcpdump_captured') != bm.get('tcpdump_received_by_filter'):
        fails.append(f"tcpdump captured {bm.get('tcpdump_captured')} != received_by_filter {bm.get('tcpdump_received_by_filter')}")
    ps = json.load(open(os.path.join(d, 'pcap_summary.json')))
    if ps.get('streams') != n: fails.append(f"pcap streams {ps.get('streams')} != {n}")
    if ps.get('tcp_syn_rtt_missing', 1) != 0: fails.append('TCP SYN RTT missing for some streams')

    # --- RAN context gates
    for gatef in ('context_gate_before.json', 'context_gate_after.json'):
        try: g = json.load(open(os.path.join(d, gatef)))
        except Exception as e: fails.append(f'{gatef} unreadable: {e}'); continue
        if g.get('status') != 'PASS': fails.append(f'{gatef} status != PASS')
        if g.get('expected_state') != m.get('ran_state_target'): fails.append(f"{gatef} state {g.get('expected_state')} != target {m.get('ran_state_target')}")
    rr = list(csv.DictReader(open(os.path.join(d, 'ran_measured.csv'))))
    n19b = sum('19b' in (r.get('node') or '').lower() for r in rr); n19c = sum('19c' in (r.get('node') or '').lower() for r in rr)
    if n19b < 3 or n19c < 3: fails.append(f'insufficient measured KPM rows 19b={n19b} 19c={n19c}')

    # --- battery context from measured audit (fields must exist)
    audits = []
    for line in open(os.path.join(d, 'era_audit_measured.jsonl')):
        try: audits.append(json.loads(line))
        except Exception: pass
    uek = next((first_key(x, UE_KEYS) for x in audits if first_key(x, UE_KEYS)), None)
    if uek: audits = [x for x in audits if str(x.get(uek)) == 'ue2']
    if not audits: fails.append('no measured ERA audit rows for ue2')
    else:
        ck = first_key(audits[0], CLIENT_BATT_KEYS); sk = first_key(audits[0], SERVER_BATT_KEYS)
        if not ck or not sk:
            fails.append(f'audit rows lack battery fields (looked for {CLIENT_BATT_KEYS} / {SERVER_BATT_KEYS}); keys present: {sorted(audits[0].keys())}')
        else:
            try:
                c = [float(x[ck]) for x in audits]; s = [float(x[sk]) for x in audits]
            except Exception as e:
                fails.append(f'battery fields not numeric in every audit row: {e!r}'); c = s = []
            if c:
                tc = float(m['ue2_batt_target']); ts = float(m['ue1_batt_target'])
                if tc < 30 and not all(x < 30 for x in c): fails.append(f'low UE2 battery crossed >=30: range {min(c):.1f}-{max(c):.1f}')
                if tc >= 30 and not all(x >= 30 for x in c): fails.append(f'high UE2 battery crossed <30: range {min(c):.1f}-{max(c):.1f}')
                if ts < 30 and not all(x < 30 for x in s): fails.append('low UE1 battery crossed >=30')
                if ts >= 30 and not all(x >= 30 for x in s): fails.append('high UE1 battery crossed <30')
                notes.append(f'audit rows={len(audits)} client_batt_key={ck} server_batt_key={sk}')

        # --- controller-policy evidence (adaptive conditions only)
        if exp == 'E2' and cond in ('battery_only','ran_only','era_dual'):
            need_keys=('policy_mode','kem_result','sig_result','kem_bound_by','sig_bound_by','kem','sig')
            miss=[k for k in need_keys if any(k not in x or x.get(k) is None for x in audits)]
            if miss: fails.append(f'adaptive audit rows missing policy fields: {sorted(set(miss))}')
            else:
                expected_mode={'battery_only':'battery_only','ran_only':'ran_only','era_dual':'dual'}[cond]
                if any(x.get('policy_mode') != expected_mode for x in audits):
                    fails.append(f'policy_mode mismatch for {cond}; expected {expected_mode}')
                if any(x.get('kem_result') != 'accepted' or x.get('sig_result') != 'accepted' for x in audits):
                    fails.append('one or more adaptive controller selections were not policy-accepted')
                if any((x.get('kem'),x.get('sig')) != (ek,es) for x in audits):
                    fails.append(f'controller audit choice differs from expected {ek}/{es}')
                kb={x.get('kem_bound_by') for x in audits}; sb={x.get('sig_bound_by') for x in audits}
                if cond == 'battery_only':
                    if kb != {'fixed_high'}: fails.append(f'battery_only KEM binding should be fixed_high, got {sorted(kb)}')
                    if not sb.issubset({'client_batt','server_batt'}): fails.append(f'battery_only signature binding unexpected: {sorted(sb)}')
                elif cond == 'ran_only':
                    if kb != {'ran_context'}: fails.append(f'ran_only KEM binding should be ran_context, got {sorted(kb)}')
                    if sb != {'fixed_high'}: fails.append(f'ran_only signature binding should be fixed_high, got {sorted(sb)}')
                elif cond == 'era_dual':
                    if kb != {'ran_context'}: fails.append(f'era_dual KEM binding should be ran_context, got {sorted(kb)}')
                    if not sb.issubset({'client_batt','server_batt'}): fails.append(f'era_dual signature binding unexpected: {sorted(sb)}')
                notes.append(f'policy_mode={expected_mode} kem_bound_by={sorted(kb)} sig_bound_by={sorted(sb)}')

    # --- controlled load (server-side receiver data)
    loaded = ctx in ('C0F', 'CBF')
    ip = os.path.join(d, 'iperf_summary.json')
    if loaded:
        if not os.path.exists(ip): fails.append('loaded run missing iperf_summary.json (server-side)')
        else:
            x = json.load(open(ip))
            span = (x.get('window_rel_end_s') or 0) - (x.get('window_rel_start_s') or 0)
            need = max(1, int(span) - 2)   # whole 1-s server intervals expected inside the window, minus edge slack
            if (x.get('window_interval_count') or 0) < need:
                fails.append(f"load not continuous in measured window: {x.get('window_interval_count')} server intervals, need >= {need} for {span:.1f} s")
            if not (x.get('window_receiver_mbps') or 0) > 0: fails.append('server-side receiver throughput in measured window <= 0')
    elif os.path.exists(ip) or os.path.exists(os.path.join(d, 'ue2', 'iperf_client.json')):
        fails.append('idle run unexpectedly has iperf data')

    # --- host state: final campaign requires stable performance governor and no active throttling
    hs = os.path.join(d, 'host_state.json')
    if not os.path.exists(hs):
        fails.append('host_state.json missing')
    else:
        h = json.load(open(hs))
        for k in ('ue1_before','ue1_after','ue2_before','ue2_after'):
            v=h.get(k) or {}
            if not v: fails.append(f'{k} host-state snapshot missing'); continue
            if v.get('governor') != 'performance': fails.append(f"{k} governor={v.get('governor')!r}, expected performance")
            if v.get('throttled_now') is True: fails.append(f"{k} active throttling detected ({v.get('throttled_raw')})")
            if v.get('temp_c') is None: fails.append(f'{k} temperature telemetry missing')
            if v.get('throttled_since_boot') is True: notes.append(f"{k}: historical throttle bits set ({v.get('throttled_raw')}); no active throttle allowed")

    report = {'run': os.path.basename(os.path.abspath(d)), 'expected_crypto': [ek, es], 'measured_rows': len(rows), 'warmup_rows': len(wrows),
              'kpm_19b': n19b, 'kpm_19c': n19c, 'failures': fails, 'notes': notes}
    json.dump(report, open(os.path.join(d, 'validation.json'), 'w'), indent=2, sort_keys=True)
    if fails:
        print(json.dumps(report, indent=2)); return 2
    open(os.path.join(d, 'VALID.ok'), 'w').write('VALID\n')
    print('[PASS]', json.dumps(report, sort_keys=True)); return 0

if __name__ == '__main__': raise SystemExit(main())
