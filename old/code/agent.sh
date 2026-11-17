#!/usr/bin/env bash
# agent.sh <ue> — poll decision server, write /tmp/current_kem and /tmp/current_sig
UE="${1:-ue2}"; export HOME=/home/$UE
URL="http://192.168.0.4:8080/decide"
echo "[agent $UE] starting; POST $URL every 2s"
if curl -s -m3 -X POST "$URL" -H 'Content-Type: application/json' -d "{\"ue\":\"$UE\",\"battery_pct\":100}" | grep -qi '"kem"'; then
  echo "[agent $UE][PASS] decision server reachable"
else
  echo "[agent $UE][FAIL] cannot reach/parse decision server at $URL — is decision.py running on the VM?"
fi
while true; do
  pct=$(python3 /home/$UE/battery.py 2>/dev/null)
  [ -z "$pct" ] && { echo "[agent $UE][WARN] battery.py no reading; using 100"; pct=100; }
  resp=$(curl -s -m3 -X POST "$URL" -H 'Content-Type: application/json' -d "{\"ue\":\"$UE\",\"battery_pct\":$pct}")
  kem=$(echo "$resp" | python3 -c 'import sys,json;print(json.load(sys.stdin)["kem"])' 2>/dev/null)
  sig=$(echo "$resp" | python3 -c 'import sys,json;print(json.load(sys.stdin)["sig"])' 2>/dev/null)
  if [ -n "$kem" ] && [ -n "$sig" ]; then
    # Individual files retained for inspection/backward compatibility
    echo "$kem" > /tmp/current_kem
    echo "$sig" > /tmp/current_sig

    # Atomic KEM+SIG pair used by pqc_bench.sh
    tmp="/tmp/current_crypto.$$"
    printf '%s %s\n' "$kem" "$sig" > "$tmp"
    mv "$tmp" /tmp/current_crypto
    echo "[agent $UE] batt=${pct}%  ->  kem=$kem  sig=$sig"
  else
    echo "[agent $UE][WARN] bad/empty response: $resp"
  fi
  sleep 2
done
