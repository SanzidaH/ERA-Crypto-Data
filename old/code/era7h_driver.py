#!/usr/bin/env python3
"""ERA7H FINAL campaign driver (runs on VM1).

FINAL hardening:
  * SSH targets come from ~/era7h/era7h.env (written by install_from_vm1.sh); no silent defaults.
  * Bounded automatic retry per run (--max-attempts, default 2). Every attempt, failed or not, is logged in
    meta/attempts.csv and failed attempts are kept under quarantine/ so retries are reportable, not hidden.
  * Frozen environment (VM1 controller/config files, UE1/UE2 scripts and bssl binary) is hashed at first start
    and RE-CHECKED on every resume; any change aborts (use a new root instead).
  * Receiver-side UDP metrics come from the UE1 iperf3 server log, matched by the iperf cookie.
  * Pi thermal / throttle / governor state recorded before and after each measured window (host_state.json).
  * Running ETA printed after every completed run.
"""
import argparse, csv, json, os, random, subprocess, time, shutil, hashlib, sys, glob, shlex
from pathlib import Path

HOME = Path.home(); SCRIPT = HOME / 'era7h'
ENVF = SCRIPT / 'era7h.env'
if ENVF.exists():
    for line in ENVF.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"\''))
UE1 = os.environ.get('UE1_SSH'); UE2 = os.environ.get('UE2_SSH')
UE1_IPERF_LOG = os.environ.get('UE1_IPERF_LOG', '~/era7h_iperf_server.json')
LOADED = ('C0F', 'CBF')

def run(cmd, check=True, capture=False, stdin=None):
    print('+', cmd if isinstance(cmd, str) else ' '.join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, shell=isinstance(cmd, str), check=check, text=True, capture_output=capture, stdin=stdin)
def ssh(host, cmd, check=True, capture=False, stdin=None):
    return run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host, cmd], check, capture, stdin)
def worker(action, *args, check=True, capture=False):
    cmd = shlex.join(['python3', '/home/ue2/era7h/era7h_worker_client.py', action, *map(str, args)])
    return ssh(UE2, cmd, check=check, capture=capture)

def mode_for(exp, cond):
    if exp == 'E1' or cond in ('static_low', 'static_high'): return 'dual'
    return {'battery_only': 'battery_only', 'ran_only': 'ran_only', 'era_dual': 'dual'}[cond]
def context(exp, ctx):
    if exp == 'E1': return (90, 90, 'idle')
    return {'C00': (90, 90, 'idle'), 'CB0': (15, 90, 'idle'), 'C0F': (90, 90, 'loaded'), 'CBF': (15, 90, 'loaded')}[ctx]
def expected(exp, ctx, cond):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from era7h_validate_run import expected_pair
    return expected_pair(exp, ctx, cond)

def make_schedule(exp, blocks, seed, contexts=None, conditions=None):
    rng = random.Random(seed); rows = []; order = 0
    if exp == 'E1':
        base = conditions or ['M1', 'M2', 'M3', 'M4']
        for b in range(1, blocks + 1):
            cs = list(base); rng.shuffle(cs)
            for c in cs: order += 1; rows.append({'order': order, 'block': b, 'context': 'E1L0', 'condition': c, 'run': f'E1_{c}_b{b:02d}'})
    else:
        base_ctx = contexts or ['C00', 'CB0', 'C0F', 'CBF']; base_cond = conditions or ['static_low', 'static_high', 'battery_only', 'ran_only', 'era_dual']
        for b in range(1, blocks + 1):
            ctxs = list(base_ctx); rng.shuffle(ctxs)
            for ctx in ctxs:
                cs = list(base_cond); rng.shuffle(cs)
                for c in cs: order += 1; rows.append({'order': order, 'block': b, 'context': ctx, 'condition': c, 'run': f'E2_{ctx}_{c}_b{b:02d}'})
    return rows

def gate(state, outfile):
    r = run(['python3', str(SCRIPT / 'era7h_context_gate.py'), '--state', state, '--timeout', '60'], check=False, capture=True)
    print(r.stdout.strip())
    Path(outfile).write_text(r.stdout.strip() + '\n')
    if r.returncode != 0: raise RuntimeError(f'RAN context gate failed for {state}')
    j = json.loads(r.stdout.strip().splitlines()[-1]); json.dump(j, open(outfile, 'w'), indent=2, sort_keys=True)
    return j

def pull_ue2(runid, dest):
    dest.mkdir(parents=True, exist_ok=True)
    remote = f'tar -C /home/ue2/era7h_runs/{runid} -cf - .'
    print('+ ssh', UE2, remote, '| tar -C', dest, '-xf -', flush=True)
    p1 = subprocess.Popen(['ssh', '-o', 'BatchMode=yes', UE2, remote], stdout=subprocess.PIPE)
    p2 = subprocess.run(['tar', '-C', str(dest), '-xf', '-'], stdin=p1.stdout)
    if p1.stdout: p1.stdout.close()
    rc1 = p1.wait()
    if rc1 or p2.returncode: raise RuntimeError(f'artifact pull failed ssh={rc1} tar={p2.returncode}')

# ---------- host state (thermal / throttling / DVFS) ----------
HOSTCMD = ("printf '%s\\n%s\\n%s\\n%s\\n%s\\n' \"$(vcgencmd measure_temp 2>/dev/null)\" \"$(vcgencmd get_throttled 2>/dev/null)\" "
           "\"$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)\" "
           "\"$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null)\" \"$(cut -d' ' -f1-3 /proc/loadavg)\"")
def host_state(host):
    out = {'ts_vm1': time.time()}
    try:
        r = ssh(host, HOSTCMD, check=True, capture=True); L = (r.stdout.splitlines() + [''] * 5)[:5]
        t = L[0].replace('temp=', '').replace("'C", '').strip()
        out['temp_c'] = float(t) if t else None
        thr = L[1].split('=')[-1].strip()
        v = int(thr, 16) if thr.startswith('0x') else None
        out.update({'throttled_raw': thr or None,
                    'throttled_now': bool(v & 0xF) if v is not None else None,
                    'throttled_since_boot': bool((v >> 16) & 0xF) if v is not None else None,
                    'governor': L[2].strip() or None,
                    'cur_freq_khz': int(L[3]) if L[3].strip().isdigit() else None,
                    'loadavg': L[4].strip()})
    except Exception as e:
        out['error'] = repr(e)
    return out

# ---------- root-worker snapshot integrity ----------
def verify_worker_snapshot():
    r = worker('snapshot', check=False, capture=True)
    if r.returncode != 0:
        msg = '[ABORT] UE2 root-worker script snapshot mismatch. Restart it in tmux with:\n  sudo /home/ue2/era7h/era7h_worker_daemon.py\n' + (r.stderr or '')
        raise SystemExit(msg)
    try:
        rep = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        raise SystemExit(f'[ABORT] cannot parse worker snapshot report: {e}: {r.stdout!r}')
    if not rep.get('match'):
        raise SystemExit('[ABORT] UE2 root worker is executing a stale script snapshot; restart worker before campaign')
    print(f"[PASS] UE2 root-worker snapshot matches installed scripts ({len(rep.get('root',{}))} files)")
    return rep

# ---------- frozen environment ----------
VM1_FROZEN = [HOME / 'decision.py', HOME / 'policy_envelope.json', HOME / 'era_set_mode.sh', HOME / 'configs/gnb1_direct_ue2_ric.yaml',
              HOME / 'results/calibration/final_kpm/final_rates.env']
UE2_FROZEN = 'cd ~ && sha256sum Downloads/boringssl/build/tool/bssl agent.sh set_battery.py era7h/* 2>/dev/null; true'
UE1_FROZEN = 'cd ~ && sha256sum Downloads/boringssl/build/tool/bssl ue1_servers.sh server_battery_agent.sh set_battery.py 2>/dev/null; true'
def _parse_sums(txt):
    d = {}
    for line in txt.splitlines():
        p = line.split(None, 1)
        if len(p) == 2: d[p[1].strip()] = p[0]
    return d
def frozen_env():
    vm1 = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in VM1_FROZEN if p.exists()}
    for p in sorted(SCRIPT.glob('era7h_*')):
        if p.is_file() and p.suffix in ('.py', '.sh'): vm1[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    snap=verify_worker_snapshot()
    return {'vm1': vm1,
            'ue2': _parse_sums(ssh(UE2, UE2_FROZEN, capture=True).stdout),
            'ue2_root_worker_snapshot': snap.get('root',{}),
            'ue1': _parse_sums(ssh(UE1, UE1_FROZEN, capture=True).stdout)}
def env_info():
    def sh(c):
        try: return subprocess.run(c, shell=True, text=True, capture_output=True, timeout=30).stdout.strip()
        except Exception as e: return repr(e)
    info = {
      'vm1_tshark': sh('tshark --version | head -1'), 'vm1_uname': sh('uname -a'), 'vm1_python': sys.version,
      'vm1_ocudu_git': sh('git -C ~/ocudu rev-parse HEAD 2>/dev/null || true'),
      'vm1_ric_images': sh("docker ps --format '{{.Image}}' 2>/dev/null | sort -u"),
      'vm1_decision_sha256': sh('sha256sum ~/decision.py 2>/dev/null || true'),
      'vm1_policy_sha256': sh('sha256sum ~/policy_envelope.json 2>/dev/null || true')
    }
    remote = r'''set +e
echo "uname=$(uname -a)"
echo "iperf=$(iperf3 --version 2>/dev/null | head -1)"
echo "bssl_sha=$(sha256sum ~/Downloads/boringssl/build/tool/bssl 2>/dev/null | awk '{print $1}')"
echo "boringssl_git=$(git -C ~/Downloads/boringssl rev-parse HEAD 2>/dev/null)"
echo "liboqs_git=$(git -C ~/Downloads/liboqs rev-parse HEAD 2>/dev/null)"
echo "srsran_git=$(git -C ~/srsRAN_4G rev-parse HEAD 2>/dev/null)"
echo "governor=$(cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | sort -u | tr '\n' ' ')"
echo "vc_temp=$(vcgencmd measure_temp 2>/dev/null)"
echo "vc_throttle=$(vcgencmd get_throttled 2>/dev/null)"'''
    for name, host in (('ue1', UE1), ('ue2', UE2)):
        r = ssh(host, remote, check=False, capture=True); info[name] = r.stdout.strip()
    return info
def check_frozen(root):
    meta = root / 'meta'; fp = meta / 'env_frozen.json'
    cur = frozen_env()
    if fp.exists():
        old = json.load(open(fp))
        if old != cur:
            diff = []
            for host in sorted(set(old) | set(cur)):
                o, c = old.get(host, {}), cur.get(host, {})
                for f in sorted(set(o) | set(c)):
                    if o.get(f) != c.get(f): diff.append(f'{host}:{f} {o.get(f, "absent")[:12]} -> {c.get(f, "absent")[:12]}')
            raise SystemExit('[ABORT] frozen environment changed since this campaign started:\n  ' + '\n  '.join(diff) +
                             '\nUse a NEW result root (or restore the original files).')
        print('[PASS] frozen environment unchanged since campaign start')
    else:
        json.dump(cur, open(fp, 'w'), indent=2, sort_keys=True)
        json.dump(env_info(), open(meta / 'env_info.json', 'w'), indent=2, sort_keys=True)
        print('[PASS] frozen environment recorded:', sum(len(v) for v in cur.values()), 'files')

# ---------- server-side iperf ----------
def fetch_server_iperf(rdir):
    cs = json.load(open(rdir / 'ue2' / 'iperf_client_summary.json'))
    cookie = cs['cookie']
    with open(SCRIPT / 'era7h_iperf_fetch_remote.py') as f:
        r = ssh(UE1, shlex.join(['python3', '-', cookie, UE1_IPERF_LOG, '20']), check=False, capture=True, stdin=f)
    if r.returncode: raise RuntimeError(f'UE1 iperf server object for cookie {cookie} not found: {r.stderr.strip()}')
    (rdir / 'iperf_server.json').write_text(r.stdout)
    run(['python3', str(SCRIPT / 'era7h_iperf_metrics.py'), '--server-json', str(rdir / 'iperf_server.json'),
         '--client-summary', str(rdir / 'ue2' / 'iperf_client_summary.json'),
         '--load-start-epoch-file', str(rdir / 'ue2' / 'iperf_load_start_epoch.txt'),
         '--bench-meta', str(rdir / 'ue2' / 'bench_measured_meta.json'), '--out', str(rdir / 'iperf_summary.json')])

# ---------- one attempt ----------
class State: current_mode = None

def do_attempt(a, row, rdir, attempt):
    runid = row['run']; ctx = row['context']; cond = row['condition']; block = int(row['block'])
    rdir.mkdir(parents=True); (rdir / 'ue2').mkdir()
    ue2b, ue1b, state = context(a.experiment, ctx); mode = mode_for(a.experiment, cond); ek, es = expected(a.experiment, ctx, cond)
    meta = {'run': runid, 'experiment': a.experiment, 'block': block, 'context': ctx, 'condition': cond, 'mode': mode, 'attempt': attempt,
            'ue2_batt_target': ue2b, 'ue1_batt_target': ue1b, 'ran_state_target': state, 'expected_kem': ek, 'expected_sig': es,
            'measured_n': a.measured, 'warmup_n': a.warmup, 'inter_handshake_sleep_s': a.sleep, 'load_rate': a.load_rate}
    def save(): json.dump(meta, open(rdir / 'metadata.json', 'w'), indent=2, sort_keys=True)
    save()
    print(f'===== {runid} attempt={attempt} state={state} batt={ue2b}/{ue1b} expected={ek}/{es} =====', flush=True)
    if State.current_mode != mode:
        run([str(HOME / 'era_set_mode.sh'), mode]); State.current_mode = mode; time.sleep(3)
    ssh(UE1, f'python3 ~/set_battery.py {ue1b}')
    ssh(UE2, f'python3 ~/set_battery.py {ue2b}')
    time.sleep(4)
    hs = {'ue1_before': host_state(UE1), 'ue2_before': host_state(UE2)}
    worker('prepare', runid, ctx, cond, a.load_rate)
    gate(state, rdir / 'context_gate_before.json')
    worker('warmup', runid, a.warmup, cond, a.sleep)
    if a.experiment == 'E2' and cond in ('battery_only', 'ran_only', 'era_dual'):
        rr = ssh(UE2, "printf '%s,%s' \"$(cat /tmp/current_kem)\" \"$(cat /tmp/current_sig)\"", capture=True)
        got = rr.stdout.strip(); want = f'{ek},{es}'
        if got != want: raise RuntimeError(f'agent selection before measure {got} != expected {want}')
    t0 = time.time(); meta['vm1_measure_start_epoch'] = t0; save()
    worker('measure', runid, a.measured, cond, a.sleep)
    t1 = time.time(); meta['vm1_measure_end_epoch'] = t1; save()
    gate(state, rdir / 'context_gate_after.json')
    hs.update({'ue1_after': host_state(UE1), 'ue2_after': host_state(UE2)})
    json.dump(hs, open(rdir / 'host_state.json', 'w'), indent=2, sort_keys=True)
    worker('finish', runid, ctx)
    pull_ue2(runid, rdir / 'ue2')
    if ctx in LOADED: fetch_server_iperf(rdir)
    run(['python3', str(SCRIPT / 'era7h_slice_logs.py'), '--start', str(t0), '--end', str(t1), '--outdir', str(rdir)])
    run(['python3', str(SCRIPT / 'era7h_pcap_metrics.py'), '--pcap', str(rdir / 'ue2/crypto_measured.pcap'),
         '--crypto-csv', str(rdir / 'ue2/crypto_log_measured.csv'), '--outdir', str(rdir)])
    run(['python3', str(SCRIPT / 'era7h_validate_run.py'), str(rdir)])
    (rdir / 'COMPLETE.ok').write_text('COMPLETE\n')

def log_attempt(root, row, attempt, outcome, reason, t_start):
    p = root / 'meta' / 'attempts.csv'; new = not p.exists()
    with open(p, 'a', newline='') as f:
        w = csv.writer(f)
        if new: w.writerow(['run', 'block', 'context', 'condition', 'attempt', 'outcome', 'reason', 'start_epoch', 'end_epoch'])
        w.writerow([row['run'], row['block'], row['context'], row['condition'], attempt, outcome, str(reason).replace('\n', ' ')[:500], f'{t_start:.3f}', f'{time.time():.3f}'])

def quarantine(root, rdir, tag):
    q = root / 'quarantine' / f'{rdir.name}_{tag}_{time.strftime("%Y%m%d_%H%M%S")}'
    shutil.move(str(rdir), q); print('[QUARANTINE]', q, flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--experiment', choices=['E1', 'E2'], default='E2'); ap.add_argument('--root', required=True); ap.add_argument('--blocks', type=int, default=10)
    ap.add_argument('--measured', type=int, default=50); ap.add_argument('--warmup', type=int, default=5); ap.add_argument('--seed', type=int, default=20261017)
    ap.add_argument('--sleep', type=float, default=0.7); ap.add_argument('--load-rate', default='0.712M')
    ap.add_argument('--contexts', default=''); ap.add_argument('--conditions', default='')
    ap.add_argument('--smoke', action='store_true', help='representative full-size E2 smoke: C00+CBF x static_high+era_dual, one block')
    ap.add_argument('--max-attempts', type=int, default=2, help='attempts per run before the campaign stops (failed attempts are logged + quarantined)')
    ap.add_argument('--retry-wait', type=float, default=20.0)
    a = ap.parse_args()
    if not UE1 or not UE2: raise SystemExit(f'[ABORT] UE1_SSH/UE2_SSH not set (expected in {ENVF}); rerun install_from_vm1.sh with both set')
    root = Path(os.path.expanduser(a.root)).resolve(); (root / 'raw').mkdir(parents=True, exist_ok=True); (root / 'quarantine').mkdir(exist_ok=True); (root / 'meta').mkdir(exist_ok=True)
    contexts = [x for x in a.contexts.split(',') if x] or None; conditions = [x for x in a.conditions.split(',') if x] or None
    if a.smoke:
        if a.experiment != 'E2': raise SystemExit('[ABORT] --smoke is defined for E2 only')
        contexts=['C00','CBF']; conditions=['static_high','era_dual']; a.blocks=1
        if a.measured != 50 or a.warmup != 5:
            print(f'[WARN] smoke uses measured/warmup={a.measured}/{a.warmup}; runtime projection should use final-size 50/5')
    cfg = {'experiment': a.experiment, 'blocks': a.blocks, 'measured': a.measured, 'warmup': a.warmup, 'seed': a.seed, 'sleep': a.sleep,
           'load_rate': a.load_rate, 'contexts': contexts, 'conditions': conditions, 'smoke': a.smoke}
    cp = root / 'meta/campaign_config.json'
    if cp.exists() and json.load(open(cp)) != cfg: raise SystemExit('[ABORT] campaign_config.json differs; use a new result root')
    json.dump(cfg, open(cp, 'w'), indent=2, sort_keys=True)
    check_frozen(root)
    schedp = root / 'meta/schedule.csv'; schedule = make_schedule(a.experiment, a.blocks, a.seed, contexts, conditions)
    if not schedp.exists():
        with open(schedp, 'w', newline='') as f: w = csv.DictWriter(f, fieldnames=schedule[0].keys()); w.writeheader(); w.writerows(schedule)
    else: schedule = list(csv.DictReader(open(schedp)))
    comp = root / 'meta/completed_runs.csv'
    if not comp.exists(): comp.write_text('run,completed_epoch\n')
    print(f'[CAMPAIGN] {a.experiment} runs={len(schedule)} root={root} max_attempts={a.max_attempts}', flush=True)
    durations = []
    for ix, row in enumerate(schedule, 1):
        runid = row['run']; rdir = root / 'raw' / runid
        if (rdir / 'VALID.ok').exists(): print(f'[SKIP {ix}/{len(schedule)}] {runid} already valid'); continue
        if rdir.exists():
            log_attempt(root, row, 0, 'interrupted_previous_session', 'partial directory found at resume', time.time())
            quarantine(root, rdir, 'partial')
        print(f'\n[{ix}/{len(schedule)}]', flush=True)
        for attempt in range(1, a.max_attempts + 1):
            ts = time.time()
            try:
                do_attempt(a, row, rdir, attempt)
                log_attempt(root, row, attempt, 'valid', '', ts)
                with open(comp, 'a') as f: f.write(f'{runid},{time.time()}\n')
                durations.append(time.time() - ts)
                remaining = sum(1 for r in schedule if not (root / 'raw' / r['run'] / 'VALID.ok').exists())
                eta = statistics_mean(durations) * remaining
                print(f'[COMPLETE] {runid} in {durations[-1]:.0f}s | remaining={remaining} | ETA ~{eta/3600:.2f} h '
                      f'(finish ~{time.strftime("%H:%M", time.localtime(time.time()+eta))})', flush=True)
                time.sleep(2)
                break
            except KeyboardInterrupt:
                print(f'[ABORT] {runid}: interrupted by user', file=sys.stderr)
                worker('finish', runid, row['context'], check=False)
                log_attempt(root, row, attempt, 'interrupted', 'KeyboardInterrupt', ts)
                try: pull_ue2(runid, rdir / 'ue2')
                except Exception: pass
                return 130
            except Exception as e:
                print(f'[FAIL] {runid} attempt {attempt}: {e}', file=sys.stderr, flush=True)
                worker('finish', runid, row['context'], check=False)
                worker('cleanup', check=False)
                try: pull_ue2(runid, rdir / 'ue2')
                except Exception: pass
                reason = str(e)
                vj = rdir / 'validation.json'
                if vj.exists():
                    try: reason = 'validation: ' + '; '.join(json.load(open(vj)).get('failures', []))
                    except Exception: pass
                if rdir.exists():
                    (rdir / 'FAILED.txt').write_text(reason + '\n')
                    quarantine(root, rdir, f'attempt{attempt}')
                log_attempt(root, row, attempt, 'failed', reason, ts)
                State.current_mode = None
                if attempt < a.max_attempts:
                    print(f'[RETRY] {runid} in {a.retry_wait:.0f}s (attempt {attempt+1}/{a.max_attempts}); failure is logged in meta/attempts.csv', flush=True)
                    time.sleep(a.retry_wait)
                    continue
                print('[STOP] attempts exhausted. Fix the cause, run preflight, then rerun the SAME command; valid runs are skipped.', file=sys.stderr)
                return 2
    print('[DONE] all scheduled runs complete')
    run(['python3', str(SCRIPT / 'era7h_analyze.py'), str(root)])
    if a.experiment == 'E2':
        run(['python3', str(SCRIPT / 'era7h_paired_stats.py'), str(root)], check=False)
    return 0

def statistics_mean(v): return sum(v) / len(v) if v else 0.0

if __name__ == '__main__': raise SystemExit(main())
