#!/bin/bash
# ue1_servers.sh — one BoringSSL server per PQC signature (own port) + server-battery agent.
# Live counter table: each completed handshake prints  # | sig | port | KEM | client-IP
set -u
cd ~/Downloads/boringssl/build || { echo "[ue1][FAIL] boringssl path not found"; exit 1; }

# signature -> port (MUST match pqc_bench.sh port_for() and policy_envelope.json sig_allowed)
declare -A PORTS=( [falcon512]=4433 [mldsa44]=4434 )

PIDS=()
cleanup(){ echo; echo "[ue1] stopping..."; for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
           sudo pkill -f "bssl server" 2>/dev/null; pkill -f server_battery_agent 2>/dev/null; exit 0; }
trap cleanup SIGINT

peer_ip(){ # $1 = port -> most recent connected client IP on that port
  sudo ip netns exec ue1 ss -tn 2>/dev/null | awk -v p=":$1" '$0 ~ p {print $4}' \
    | grep -v "$1\$" >/dev/null 2>&1
  sudo ip netns exec ue1 ss -tn state established "( sport = :$1 )" 2>/dev/null \
    | awk 'NR>1{print $4}' | sed 's/:[0-9]*$//' | head -1
}

# server-battery agent
pkill -f server_battery_agent 2>/dev/null
( cd ~ && ./server_battery_agent.sh >/tmp/sbatt.log 2>&1 ) & PIDS+=($!)
echo "[ue1][info] server-battery agent started (log /tmp/sbatt.log)"

echo "-------------------------------------------------------------"
printf "  %-4s %-10s %-5s %-11s %-15s\n" "#" "SIG" "PORT" "KEM" "CLIENT-IP"
echo "-------------------------------------------------------------"

for SIG in "${!PORTS[@]}"; do
  P=${PORTS[$SIG]}
  LOG=/tmp/srv_${SIG}.log
  sudo fuser -k ${P}/tcp 2>/dev/null
  : > "$LOG"
  sudo ip netns exec ue1 ./tool/bssl server -accept "$P" -sig-alg "$SIG" -loop -debug >>"$LOG" 2>&1 &
  PIDS+=($!)
  sleep 2
  if sudo ip netns exec ue1 pgrep -f "bssl server -accept $P" >/dev/null 2>&1; then
    echo "[ue1][PASS] $SIG listening on $P"
  else
    echo "[ue1][FAIL] $SIG NOT up on $P — check $LOG"; grep -i "error\|use" "$LOG" | head -2
  fi

  # per-server live counter: on each completed handshake, grab negotiated KEM + client IP
  ( CNT=0; KEM="?"
    stdbuf -oL tail -n0 -F "$LOG" 2>/dev/null | while read -r line; do
      case "$line" in
        *"ECDHE group"*) KEM=$(echo "$line" | awk -F': ' '{print $2}' | tr -d ' \r') ;;
        *"TLS server done"*|*"Handshake done"*)
          CNT=$((CNT+1))
          IP=$(sudo ip netns exec ue1 ss -tn state established "( sport = :$P )" 2>/dev/null \
                | awk 'NR>1{print $4}' | sed 's/:[0-9]*$//' | head -1)
          [ -z "$IP" ] && IP="(closed)"
          printf "  %-4s %-10s %-5s %-11s %-15s\n" "$CNT" "$SIG" "$P" "$KEM" "$IP"
          ;;
      esac
    done ) & PIDS+=($!)
done

echo "[ue1][info] servers up. falcon512->4433  mldsa44->4434 . Rows print as clients connect. Ctrl+C to stop."
wait
