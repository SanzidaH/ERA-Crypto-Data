#!/usr/bin/env bash
set -euo pipefail
RUN=${1:?run}; N=${2:-50}; COND=${3:?condition}; SLEEP_S=${4:-0.7}
D=/home/ue2/era7h_runs/$RUN
[[ -d "$D" ]] || { echo "[FAIL] missing run dir $D" >&2; exit 30; }
KEM=""; SIG=""
case "$COND" in
  static_low|M1) KEM=mlkem768; SIG=falcon512;;
  static_high|M4) KEM=mlkem1024; SIG=mldsa44;;
  M2) KEM=mlkem768; SIG=mldsa44;;
  M3) KEM=mlkem1024; SIG=falcon512;;
  battery_only|ran_only|era_dual) ;;
  *) echo "[FAIL] unknown condition $COND" >&2; exit 31;;
esac

# Low-rate RTT probe runs identically in every policy, only during measured handshakes.
echo "$(date +%s.%N)" > "$D/ping_start_epoch.txt"
ip netns exec ue2 ping -D -n -i 1 -W 2 10.45.1.2 > "$D/ping.txt" 2>&1 &
PINGPID=$!
echo "$PINGPID" > "$D/ping.pid"
sleep 0.5

export ERA7H_OUTDIR="$D" ERA7H_CAPTURE=1
set +e
${ERA7H_BIN:-/home/ue2/era7h}/pqc_bench_v2.sh ue2 ue2 10.45.1.2 "$N" measured tun_srsue "$KEM" "$SIG" "$SLEEP_S"
rc=$?
set -e
kill -INT "$PINGPID" 2>/dev/null || true
wait "$PINGPID" 2>/dev/null || true
echo "$(date +%s.%N)" > "$D/ping_end_epoch.txt"
chown -R ue2:ue2 "$D"
exit "$rc"
