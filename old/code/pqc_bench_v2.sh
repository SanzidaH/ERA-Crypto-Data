#!/usr/bin/env bash
# ERA7H FINAL PQC-TLS client benchmark.
# v2: sub-millisecond client_elapsed_ms; tcpdump in immediate mode, started-and-listening before the first handshake,
#     drained after the last one, and rejected unless captured == received-by-filter with zero kernel/interface drops.
#     (Without immediate mode libpcap buffers up to ~1 s; SIGINT then discards the tail of the capture.)
set -euo pipefail
NS=${1:?netns}; UE=${2:?ue}; HOST=${3:?server_ip}; N=${4:?N}; LABEL=${5:?label}
IFACE=${6:-tun_srsue}; FORCE_KEM=${7:-}; FORCE_SIG=${8:-}; SLEEP_S=${9:-0.7}
export HOME=/home/$UE
BSSL=${ERA7H_BSSL:-/home/$UE/Downloads/boringssl/build/tool/bssl}
OUTDIR=${ERA7H_OUTDIR:-/home/$UE/era7h_runs/$LABEL}
CAPTURE=${ERA7H_CAPTURE:-1}
OUT="$OUTDIR/crypto_log_${LABEL}.csv"
PCAP="$OUTDIR/crypto_${LABEL}.pcap"
TCPD_ERR="$OUTDIR/tcpdump_${LABEL}.err"
META="$OUTDIR/bench_${LABEL}_meta.json"
mkdir -p "$OUTDIR"
port_for(){ case "$1" in falcon512) echo 4433;; mldsa44) echo 4434;; *) echo "[FAIL] unsupported signature $1" >&2; return 2;; esac; }
[[ -x "$BSSL" ]] || { echo "[FAIL] bssl not found: $BSSL" >&2; exit 2; }
command -v /usr/bin/time >/dev/null || { echo "[FAIL] /usr/bin/time missing" >&2; exit 2; }
printf '%s\n' 'index,start_epoch,end_epoch,ue,req_kem,req_sig,port,neg_kem,neg_sig,client_elapsed_ms,user_cpu_s,sys_cpu_s,max_rss_kb,rc,result' > "$OUT"
TCPD=""
cleanup(){ if [[ -n "$TCPD" ]] && kill -0 "$TCPD" 2>/dev/null; then kill -INT "$TCPD" 2>/dev/null || true; wait "$TCPD" 2>/dev/null || true; fi; }
trap cleanup EXIT INT TERM
if [[ "$CAPTURE" == "1" ]]; then
  # stderr is kept: tcpdump prints captured/received/dropped counters on SIGINT.
  ip netns exec "$NS" tcpdump --immediate-mode -i "$IFACE" -nn -s 0 -U -w "$PCAP" "host $HOST and tcp and (port 4433 or port 4434)" >/dev/null 2>"$TCPD_ERR" &
  TCPD=$!
  for _ in $(seq 1 50); do grep -q 'listening on' "$TCPD_ERR" 2>/dev/null && break; kill -0 "$TCPD" 2>/dev/null || break; sleep 0.1; done
  kill -0 "$TCPD" 2>/dev/null && grep -q 'listening on' "$TCPD_ERR" || { echo "[FAIL] tcpdump did not start listening within 5 s" >&2; cat "$TCPD_ERR" >&2; exit 3; }
  sleep 0.3
fi
run_start=$(date +%s.%N); ok=0; fail=0
for i in $(seq 1 "$N"); do
  if [[ -n "$FORCE_KEM" && -n "$FORCE_SIG" ]]; then KEM="$FORCE_KEM"; SIG="$FORCE_SIG";
  elif [[ -z "$FORCE_KEM" && -z "$FORCE_SIG" ]]; then KEM=$(cat /tmp/current_kem 2>/dev/null || true); SIG=$(cat /tmp/current_sig 2>/dev/null || true); [[ -n "$KEM" && -n "$SIG" ]] || { echo "[FAIL] adaptive selection files missing" >&2; exit 4; };
  else echo "[FAIL] force_kem and force_sig must be supplied together" >&2; exit 4; fi
  PORT=$(port_for "$SIG"); tf="$OUTDIR/.time_${LABEL}_${i}.txt"
  start_epoch=$(date +%s.%N); s_ns=$(date +%s%N)
  set +e
  out=$(printf 'QUIT\n' | /usr/bin/time -f '%U,%S,%M' -o "$tf" timeout 15s ip netns exec "$NS" "$BSSL" client -connect "$HOST:$PORT" -curves "$KEM" -sigalgs "$SIG" 2>&1)
  rc=$?
  set -e
  e_ns=$(date +%s%N); end_epoch=$(date +%s.%N)
  d_ns=$(( e_ns - s_ns )); elapsed_ms=$(printf '%d.%06d' $(( d_ns / 1000000 )) $(( d_ns % 1000000 )))
  IFS=',' read -r user_cpu sys_cpu maxrss < "$tf" || true; rm -f "$tf"
  user_cpu=${user_cpu:-NA}; sys_cpu=${sys_cpu:-NA}; maxrss=${maxrss:-NA}
  nkem=$(printf '%s\n' "$out" | grep -i 'ECDHE group' | tail -1 | awk -F': ' '{print $2}' | tr -d ' \r' || true)
  nsig=$(printf '%s\n' "$out" | grep -i 'Signature algorithm' | tail -1 | awk -F': ' '{print $2}' | tr -d ' \r' || true)
  res=fail
  if [[ "$rc" -eq 0 && -n "$nkem" && -n "$nsig" ]]; then if [[ "$nkem" == "$KEM" && "$nsig" == "$SIG" ]]; then res=ok; ok=$((ok+1)); else res=mismatch; fail=$((fail+1)); fi; else fail=$((fail+1)); fi
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$i" "$start_epoch" "$end_epoch" "$UE" "$KEM" "$SIG" "$PORT" "${nkem:-NA}" "${nsig:-NA}" "$elapsed_ms" "$user_cpu" "$sys_cpu" "$maxrss" "$rc" "$res" >> "$OUT"
  [[ "$res" == ok ]] || echo "[WARN] hs=$i rc=$rc req=$KEM/$SIG neg=${nkem:-NA}/${nsig:-NA} elapsed=${elapsed_ms}ms" >&2
  sleep "$SLEEP_S"
done
run_end=$(date +%s.%N)
[[ "$CAPTURE" == "1" ]] && sleep 1.5   # drain: let the last connection's FIN/ACKs reach the capture before SIGINT
cleanup; TCPD=""
captured=NA; recv=NA; kdrop=NA; idrop=NA
if [[ "$CAPTURE" == "1" ]]; then
  captured=$(grep -Eo '^[0-9]+ packets? captured' "$TCPD_ERR" | awk '{print $1}' | tail -1 || true)
  kdrop=$(grep -Eo '^[0-9]+ packets? dropped by kernel' "$TCPD_ERR" | awk '{print $1}' | tail -1 || true)
  idrop=$(grep -Eo '^[0-9]+ packets? dropped by interface' "$TCPD_ERR" | awk '{print $1}' | tail -1 || true)
  recv=$(grep -Eo '^[0-9]+ packets? received by filter' "$TCPD_ERR" | awk '{print $1}' | tail -1 || true)
  captured=${captured:-NA}; recv=${recv:-NA}; kdrop=${kdrop:-NA}; idrop=${idrop:-0}
fi
python3 - "$META" "$LABEL" "$N" "$ok" "$fail" "$run_start" "$run_end" "$SLEEP_S" "$CAPTURE" "$captured" "$recv" "$kdrop" "$idrop" <<'PY'
import json,sys
p,label,n,ok,fail,start,end,sleep_s,capture,cap,rcv,kd,idr=sys.argv[1:]
def iv(x):
    try: return int(x)
    except Exception: return None
json.dump({"label":label,"requested_n":int(n),"ok":int(ok),"fail":int(fail),"run_start_epoch":float(start),"run_end_epoch":float(end),
           "inter_handshake_sleep_s":float(sleep_s),"capture":bool(int(capture)),
           "tcpdump_captured":iv(cap),"tcpdump_received_by_filter":iv(rcv),"tcpdump_dropped_kernel":iv(kd),"tcpdump_dropped_interface":iv(idr)},open(p,"w"),indent=2,sort_keys=True)
PY
if [[ "$CAPTURE" == "1" ]]; then
  [[ -s "$PCAP" ]] || { echo "[FAIL] pcap empty" >&2; exit 5; }
  [[ "$kdrop" =~ ^[0-9]+$ ]] || { echo "[FAIL] could not read tcpdump drop counter; see $TCPD_ERR" >&2; exit 6; }
  (( kdrop == 0 && idrop == 0 )) || { echo "[FAIL] tcpdump dropped packets kernel=$kdrop interface=$idrop" >&2; exit 6; }
  [[ "$captured" =~ ^[0-9]+$ && "$recv" =~ ^[0-9]+$ ]] && (( captured == recv )) || { echo "[FAIL] tcpdump captured=$captured != received_by_filter=$recv (capture tail lost)" >&2; exit 6; }
fi
echo "[DONE] label=$LABEL ok=$ok fail=$fail csv=$OUT pcap=$PCAP tcpdump_captured=$captured dropped=$kdrop"
[[ "$fail" -eq 0 && "$ok" -eq "$N" ]]
