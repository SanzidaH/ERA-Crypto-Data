#!/usr/bin/env bash
# Stops only the load PID created for this run. Expected SIGINT termination is explicitly recognized.
# v2: the client JSON is used ONLY for sender-side data and the test cookie. Under SIGINT the client never
# receives the server's results, so its sum_received is all-zero; receiver throughput/loss/jitter are taken
# from the UE1 iperf3 server log, matched by cookie, by the VM1 driver.
set -euo pipefail
RUN=${1:?run}; CTX=${2:?context}
D=/home/ue2/era7h_runs/$RUN; ACTIVE=/home/ue2/era7h_active_load.pid
[[ -d "$D" ]] || { echo "[FAIL] missing run dir $D" >&2; exit 40; }
case "$CTX" in
  C0F|CBF)
    if [[ -f "$D/iperf_client_summary.json" ]]; then echo "[PASS] UE2 run already finished $RUN (idempotent)"; exit 0; fi
    [[ -f "$D/iperf_load.pid" ]] || { echo "[FAIL] missing iperf pid" >&2; exit 41; }
    pid=$(cat "$D/iperf_load.pid")
    if kill -0 "$pid" 2>/dev/null; then
      cmd=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null || true)
      [[ "$cmd" == *"iperf3"* && "$cmd" == *"10.45.1.2"* ]] || { echo "[FAIL] refusing to signal unexpected pid=$pid cmd=$cmd" >&2; exit 42; }
      echo "$(date +%s.%N)" > "$D/iperf_load_stop_epoch.txt"
      kill -INT "$pid" 2>/dev/null || true
      for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
      if kill -0 "$pid" 2>/dev/null; then kill -TERM "$pid" 2>/dev/null || true; sleep 1; fi
      wait "$pid" 2>/dev/null || true
    else
      echo "[FAIL] iperf load died before finish (load was not continuous)" >&2
      rm -f "$ACTIVE"; exit 45
    fi
    rm -f "$ACTIVE"
    python3 - "$D/iperf_client.json" "$D/iperf_client_summary.json" <<'PY'
import json,sys
p,out=sys.argv[1:]
j=json.load(open(p))
err=(j.get('error') or '').strip()
allowed={'','interrupt - the client has terminated'}
if err not in allowed:
    raise SystemExit(f'[FAIL] unexpected iperf client error: {err}')
ints=j.get('intervals') or []
if len(ints)<5:
    raise SystemExit(f'[FAIL] too few iperf client intervals: {len(ints)}')
st=j.get('start') or {}
cookie=st.get('cookie')
if not cookie:
    raise SystemExit('[FAIL] iperf client JSON has no start.cookie; cannot match UE1 server log')
e=j.get('end') or {}
tx=e.get('sum_sent') or e.get('sum') or {}
summary={
 'cookie':cookie,
 'client_error':err,
 'client_interval_count':len(ints),
 'client_start_timesecs':(st.get('timestamp') or {}).get('timesecs'),
 'sender_mbps':(tx.get('bits_per_second') or 0)/1e6,
 'sender_packets':tx.get('packets'),
 'sender_seconds':tx.get('seconds'),
 'interval_sender_mbps':[(x.get('sum') or {}).get('bits_per_second',0)/1e6 for x in ints],
}
json.dump(summary,open(out,'w'),indent=2,sort_keys=True)
print('[PASS] iperf client summary cookie=%s sender_mbps=%.4f intervals=%d'%(cookie,summary['sender_mbps'],len(ints)))
PY
    ;;
  C00|CB0|E1L0) [[ ! -f "$D/iperf_load.pid" ]] || { echo "[FAIL] idle run unexpectedly has load pid" >&2; exit 43; };;
  *) echo "[FAIL] unknown context $CTX" >&2; exit 44;;
esac
chown -R ue2:ue2 "$D"
echo "$(date +%s.%N)" > "$D/finish_epoch.txt"
echo "[PASS] UE2 run finish $RUN"
