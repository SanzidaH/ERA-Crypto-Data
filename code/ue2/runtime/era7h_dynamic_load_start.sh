#!/usr/bin/env bash
# Start forward UDP load inside an EXISTING dynamic run directory. Root-worker only.
set -euo pipefail
RUN=${1:?run}; RATE=${2:-0.712M}
D=/home/ue2/era7h_runs/$RUN; ACTIVE=/home/ue2/era7h_active_load.pid
[[ -d "$D" ]] || { echo "[FAIL] missing dynamic run dir $D" >&2; exit 60; }
if [[ -f "$ACTIVE" ]]; then
  old=$(cat "$ACTIVE" 2>/dev/null || true)
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then echo "[FAIL] ERA7H load already alive pid=$old" >&2; exit 61; fi
  rm -f "$ACTIVE"
fi
start=$(date +%s.%N)
ip netns exec ue2 iperf3 -c 10.45.1.2 -u -b "$RATE" -t 3600 -i 1 -J \
  > "$D/dynamic_iperf_client.json" 2> "$D/dynamic_iperf_client.err" &
pid=$!
echo "$pid" > "$D/dynamic_iperf.pid"; echo "$pid" > "$ACTIVE"; echo "$start" > "$D/dynamic_load_start_epoch.txt"
sleep 3
kill -0 "$pid" 2>/dev/null || { echo '[FAIL] dynamic iperf exited early' >&2; cat "$D/dynamic_iperf_client.err" >&2; exit 62; }
cmd=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null || true)
[[ "$cmd" == *iperf3* && "$cmd" == *10.45.1.2* ]] || { echo "[FAIL] unexpected dynamic load pid=$pid cmd=$cmd" >&2; exit 63; }
chown -R ue2:ue2 "$D"
echo "[PASS] dynamic forward load active pid=$pid rate=$RATE"
