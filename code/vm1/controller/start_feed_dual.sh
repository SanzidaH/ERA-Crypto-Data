#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/oran-sc-ric"

GNB1="gnbd_001_001_00019b_0"
GNB2="gnbd_001_001_00019c_0"

APPDIR=$(docker compose exec -T python_xapp_runner \
  sh -lc 'dirname "$(readlink -f ./kpm_mon_xapp.py)"' \
  | tr -d '\r')

CID=$(docker compose ps -q python_xapp_runner)

echo "[feed] APPDIR=$APPDIR"
echo "[feed] gNB1=$GNB1"
echo "[feed] gNB2=$GNB2"

# ------------------------------------------------------------
# Kill stale KPM monitor INSIDE container.
# Uses /proc, so container does not need ps/pkill installed.
# ------------------------------------------------------------
kill_old_xapp () {
docker compose exec -T python_xapp_runner python3 - <<'PY'
import os, signal, time

targets = []

for p in os.listdir("/proc"):
    if not p.isdigit():
        continue
    try:
        with open(f"/proc/{p}/cmdline", "rb") as f:
            cmd = f.read().replace(b"\0", b" ").decode(errors="ignore")

        if "kpm_mon_xapp" in cmd:
            targets.append(int(p))
    except Exception:
        pass

for pid in targets:
    try:
        print(f"[feed] stopping stale xApp PID {pid}", flush=True)
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

time.sleep(2)

for pid in targets:
    try:
        os.kill(pid, 0)
        print(f"[feed] force killing stale xApp PID {pid}", flush=True)
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
PY
}

kill_old_xapp

# ------------------------------------------------------------
# Copy current dual-node xApp into running container
# ------------------------------------------------------------
docker cp \
  "$HOME/kpm_mon_xapp_dual.py" \
  "$CID:$APPDIR/kpm_mon_xapp_dual.py"

# ------------------------------------------------------------
# Fresh measurement files for this run
# ------------------------------------------------------------
rm -f "$HOME/ran_log.csv"
rm -f "$HOME/kpm_raw.log"

cleanup () {
    echo "[feed] stopping KPM xApp"
    kill_old_xapp || true
}

trap cleanup EXIT INT TERM

echo "[feed] starting dual-gNB KPM collection..."

docker compose exec -T \
  -w "$APPDIR" \
  -e PYTHONUNBUFFERED=1 \
  python_xapp_runner \
  python3 ./kpm_mon_xapp_dual.py \
  --e2_node_id "$GNB1,$GNB2" \
  --metrics DRB.UEThpDl,DRB.UEThpUl \
  --kpm_report_style 1 \
| tee -a "$HOME/kpm_raw.log" \
| python3 "$HOME/kpm_to_csv.py" "$HOME/ran_log.csv"
