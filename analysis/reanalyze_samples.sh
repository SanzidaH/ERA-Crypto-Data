#!/usr/bin/env bash
# Recompute original per-sample pcap_summary.json without modifying archived evidence.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
command -v python3 >/dev/null || { echo '[ERROR] Install Python 3' >&2; exit 2; }
command -v tshark >/dev/null || { echo '[ERROR] Install tshark' >&2; exit 2; }
ANALYZER=code/vm1/runtime/era7h_pcap_metrics.py
[[ -f "$ANALYZER" ]] || { echo "[ERROR] Missing actual frozen analyzer: $ANALYZER" >&2; exit 2; }
shopt -s nullglob
pcaps=(data/pcap_samples/*/ue2/crypto_measured.pcap)
((${#pcaps[@]})) || { echo '[ERROR] No measured PCAP samples found' >&2; exit 2; }
failed=0
for pcap in "${pcaps[@]}"; do
  d="$(dirname "$(dirname "$pcap")")"; run="$(basename "$d")"
  [[ -f "$d/VALID.ok" && -f "$d/COMPLETE.ok" ]] || { echo "[FAIL] $run missing validation marker"; failed=1; continue; }
  csv="$d/ue2/crypto_log_measured.csv"
  [[ -f "$csv" && -f "$d/pcap_summary.json" ]] || { echo "[FAIL] $run missing matching CSV/summary"; failed=1; continue; }
  out="derived/$run"; mkdir -p "$out"
  echo "[RUN] $run"
  if ! python3 "$ANALYZER" --pcap "$pcap" --crypto-csv "$csv" --outdir "$out"; then
    echo "[FAIL] analysis error: $run"; failed=1; continue
  fi
  if python3 - "$d/pcap_summary.json" "$out/pcap_summary.json" <<'PY'
import json, math, sys
orig,new=(json.load(open(p)) for p in sys.argv[1:])
keys=('streams','total_capture_bytes','total_packets','bytes_per_handshake_mean',
      'packets_per_handshake_mean','flow_duration_ms_median','tcp_syn_rtt_ms_median',
      'tcp_retransmissions_total','tcp_syn_rtt_missing')
for k in keys:
  if k not in orig or k not in new:
    print(f'[MISSING KEY] {k}');sys.exit(1)
  a,b=orig[k],new[k]
  if isinstance(a,(int,float)) and isinstance(b,(int,float)):
    if not math.isclose(a,b,rel_tol=1e-8,abs_tol=0.001):
      print(f'[DIFF] {k} original={a} recomputed={b}');sys.exit(1)
  elif a != b:
    print(f'[DIFF] {k} original={a} recomputed={b}');sys.exit(1)
print('[MATCH] Recomputed values agree with original summary')
PY
  then echo "[PASS] $run"; else echo "[FAIL] summary mismatch $run"; failed=1; fi
done
exit "$failed"
