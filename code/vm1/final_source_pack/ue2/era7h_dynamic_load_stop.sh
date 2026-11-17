#!/usr/bin/env bash
# Stop only the dynamic iperf PID created by era7h_dynamic_load_start.sh.
set -euo pipefail
RUN=${1:?run}; D=/home/ue2/era7h_runs/$RUN; ACTIVE=/home/ue2/era7h_active_load.pid
[[ -d "$D" ]] || { echo "[FAIL] missing dynamic run dir $D" >&2; exit 70; }
[[ -f "$D/dynamic_iperf.pid" ]] || { echo '[FAIL] dynamic iperf pid missing' >&2; exit 71; }
pid=$(cat "$D/dynamic_iperf.pid")
if kill -0 "$pid" 2>/dev/null; then
  cmd=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null || true)
  [[ "$cmd" == *iperf3* && "$cmd" == *10.45.1.2* ]] || { echo "[FAIL] refusing unexpected pid=$pid cmd=$cmd" >&2; exit 72; }
  echo "$(date +%s.%N)" > "$D/dynamic_load_stop_epoch.txt"
  kill -INT "$pid" 2>/dev/null || true
  for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  kill -0 "$pid" 2>/dev/null && kill -TERM "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
else
  echo '[FAIL] dynamic iperf died before requested stop' >&2; rm -f "$ACTIVE"; exit 73
fi
rm -f "$ACTIVE"
chown -R ue2:ue2 "$D"
echo '[PASS] dynamic forward load stopped'
