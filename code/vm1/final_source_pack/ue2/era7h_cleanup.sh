#!/usr/bin/env bash
# Manual emergency cleanup. Stops ONLY the campaign load recorded in era7h_active_load.pid.
set -euo pipefail
ACTIVE=/home/ue2/era7h_active_load.pid
if [[ ! -f "$ACTIVE" ]]; then echo '[PASS] no ERA7H load marker'; exit 0; fi
pid=$(cat "$ACTIVE" 2>/dev/null || true)
if [[ -z "$pid" ]]; then rm -f "$ACTIVE"; exit 0; fi
if kill -0 "$pid" 2>/dev/null; then
  cmd=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null || true)
  if [[ "$cmd" != *iperf3* || "$cmd" != *10.45.1.2* ]]; then echo "[FAIL] refusing unexpected pid=$pid cmd=$cmd" >&2; exit 2; fi
  kill -INT "$pid" 2>/dev/null || true; sleep 2
  kill -0 "$pid" 2>/dev/null && kill -TERM "$pid" 2>/dev/null || true
fi
rm -f "$ACTIVE"
echo '[PASS] ERA7H controlled load cleaned up'
