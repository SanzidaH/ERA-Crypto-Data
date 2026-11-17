#!/usr/bin/env bash
# Optional supporting characterization: liboqs primitive cost. Run as ue2 (no sudo required).
# This is NOT the end-to-end TLS metric. Repeat count defaults to 10 complete tool invocations/algorithm.
set -euo pipefail
REPS=${1:-10}; DUR=${2:-5}; OUTDIR=${3:-$HOME/era7h_primitives}
KEM_BIN=${KEM_BIN:-$HOME/Downloads/liboqs/build/tests/speed_kem}
SIG_BIN=${SIG_BIN:-$HOME/Downloads/liboqs/build/tests/speed_sig}
[[ -x "$KEM_BIN" ]] || { echo "[FAIL] missing $KEM_BIN" >&2; exit 2; }
[[ -x "$SIG_BIN" ]] || { echo "[FAIL] missing $SIG_BIN" >&2; exit 2; }
mkdir -p "$OUTDIR"; F="$OUTDIR/primitives_$(date +%Y%m%d_%H%M%S).txt"
{
  echo "timestamp=$(date -Is)"; echo "host=$(uname -a)"; echo "liboqs_git=$(git -C $HOME/Downloads/liboqs rev-parse HEAD 2>/dev/null || true)"; echo "reps=$REPS duration_s=$DUR"
} > "$F"
run_alg(){ local tool=$1 alg=$2; for i in $(seq 1 "$REPS"); do echo "===== $tool $alg rep=$i =====" | tee -a "$F"; "$tool" -d "$DUR" "$alg" 2>&1 | tee -a "$F"; done; }
run_alg "$KEM_BIN" ML-KEM-768
run_alg "$KEM_BIN" ML-KEM-1024
run_alg "$SIG_BIN" Falcon-512
run_alg "$SIG_BIN" ML-DSA-44
echo "[PASS] primitive benchmark saved $F"
