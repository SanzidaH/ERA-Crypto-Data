#!/usr/bin/env bash
# VM1 helper: safely restart decision.py in one final policy mode.
set -euo pipefail

MODE="${1:-}"
case "$MODE" in
  dual|battery_only|ran_only) ;;
  *) echo "Usage: $0 {dual|battery_only|ran_only}" >&2; exit 2 ;;
esac

grep -q 'THP_HI, BATT_LO = 322.4, 30.0' "$HOME/decision.py" || {
  echo "[FAIL] frozen threshold 322.4 not found in ~/decision.py" >&2
  exit 2
}

python3 -m py_compile "$HOME/decision.py"

pkill -f '[d]ecision.py' 2>/dev/null || true
sleep 1
: > "$HOME/era_audit.log"

nohup env ERA_MODE="$MODE" python3 "$HOME/decision.py" \
  > "$HOME/decision_console.log" 2>&1 &
PID=$!
echo "$PID" > "$HOME/decision.pid"

sleep 4
kill -0 "$PID" 2>/dev/null || {
  echo "[FAIL] decision.py exited"
  tail -50 "$HOME/decision_console.log"
  exit 2
}

echo "[PASS] decision.py pid=$PID mode=$MODE"
tail -8 "$HOME/decision_console.log"

echo "=== process environment ==="
tr '\0' '\n' < "/proc/$PID/environ" | grep '^ERA_MODE=' || true
