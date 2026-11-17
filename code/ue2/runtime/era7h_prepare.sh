#!/usr/bin/env bash
# Run as root by the ERA7H worker. Creates a fresh per-run work directory and starts controlled load if needed.
# v2: client JSON is named iperf_client.json; receiver-side statistics come from the UE1 server log (see driver).
set -euo pipefail
RUN=${1:?run}; CTX=${2:?context}; COND=${3:?condition}; RATE=${4:-0.712M}
BASE=/home/ue2/era7h_runs; D="$BASE/$RUN"; ACTIVE=/home/ue2/era7h_active_load.pid
mkdir -p "$BASE"
if [[ -e "$D" ]]; then
  mv "$D" "${D}.stale.$(date +%Y%m%d_%H%M%S)"
fi
mkdir -p "$D"
printf 'run=%s\ncontext=%s\ncondition=%s\nload_rate=%s\nprepare_epoch=%s\n' "$RUN" "$CTX" "$COND" "$RATE" "$(date +%s.%N)" > "$D/prepare.env"

if [[ -f "$ACTIVE" ]]; then
  old=$(cat "$ACTIVE" 2>/dev/null || true)
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
    echo "[FAIL] previous ERA7H load is still alive pid=$old" >&2; exit 10
  fi
  rm -f "$ACTIVE"
fi

case "$CTX" in
  C0F|CBF)
    start=$(date +%s.%N)
    ip netns exec ue2 iperf3 -c 10.45.1.2 -u -b "$RATE" -t 3600 -i 1 -J \
      > "$D/iperf_client.json" 2> "$D/iperf_client.err" &
    pid=$!
    echo "$pid" > "$D/iperf_load.pid"; echo "$pid" > "$ACTIVE"; echo "$start" > "$D/iperf_load_start_epoch.txt"
    sleep 3
    kill -0 "$pid" 2>/dev/null || { echo "[FAIL] iperf load exited early (is the UE1 iperf3 server running in netns ue1?)" >&2; cat "$D/iperf_client.err" "$D/iperf_client.json" >&2; exit 11; }
    cmd=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null || true)
    [[ "$cmd" == *"iperf3"* && "$cmd" == *"10.45.1.2"* ]] || { echo "[FAIL] unexpected load pid command: $cmd" >&2; exit 12; }
    echo "[PASS] loaded context active pid=$pid rate=$RATE"
    ;;
  C00|CB0|E1L0)
    echo "[PASS] idle context: no controlled iperf load"
    ;;
  *) echo "[FAIL] unknown context $CTX" >&2; exit 13;;
esac
chown -R ue2:ue2 "$D"
