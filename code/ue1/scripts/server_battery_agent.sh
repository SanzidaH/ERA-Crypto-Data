#!/usr/bin/env bash
# ue1: report own battery to the decision server (does NOT pick crypto)
export HOME=/home/ue1
URL="http://192.168.0.4:8080/server_battery"
while true; do
  pct=$(python3 /home/ue1/battery.py 2>/dev/null); [ -z "$pct" ] && pct=100
  curl -s -m3 -X POST "$URL" -H 'Content-Type: application/json' -d "{\"battery_pct\":$pct}" >/dev/null
  echo "$(date +%T) server_batt=${pct}%"
  sleep 2
done
