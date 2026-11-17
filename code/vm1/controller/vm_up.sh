#!/usr/bin/env bash
# ERA-Crypto direct two-gNB stack bring-up
#
# This script starts ONLY:
#   1. Open5GS
#   2. gNB2 forwarding rule/service
#   3. Near-RT RIC
#
# It intentionally does NOT start:
#   - GNU Radio broker
#   - gNB1
#   - gNB2
#   - UEs
#   - KPM feed
#   - decision.py
#
# Those are started in controlled order after infrastructure is healthy.

set -euo pipefail
export HOME=/home/srsran

LOGDIR="$HOME/era_run_logs"
mkdir -p "$LOGDIR"

echo "============================================================"
echo " ERA-Crypto VM1 infrastructure bring-up"
echo " Direct two-gNB topology — NO GNU Radio broker"
echo "============================================================"

sudo sysctl vm.overcommit_memory=1 >/dev/null 2>&1 || true


# ------------------------------------------------------------
# 1. Open5GS
# ------------------------------------------------------------
echo
echo "[1/3] Starting Open5GS..."

cd "$HOME/ocudu/docker"
docker compose up -d 5gc

CORE_OK=0

for i in $(seq 1 30); do
    if docker ps --format '{{.Names}}' | grep -qx 'open5gs_5gc'; then
        CORE_OK=1
        break
    fi
    sleep 1
done

if [ "$CORE_OK" -eq 1 ]; then
    echo "   [PASS] open5gs_5gc running"
else
    echo "   [FAIL] open5gs_5gc not running"
    docker compose ps
    exit 1
fi


# ------------------------------------------------------------
# 2. Restore VM2 -> Open5GS forwarding
# ------------------------------------------------------------
echo
echo "[2/3] Restoring gNB2 -> Open5GS forwarding..."

if sudo systemctl restart gnb2-open5gs-forward.service; then
    echo "   [PASS] gnb2-open5gs-forward.service restarted"
else
    echo "   [FAIL] forwarding service failed"
    sudo systemctl status gnb2-open5gs-forward.service --no-pager || true
    exit 1
fi

sleep 2

if ping -c 1 -W 2 10.53.1.2 >/dev/null 2>&1; then
    echo "   [PASS] VM1 can reach Open5GS at 10.53.1.2"
else
    echo "   [WARN] ping to 10.53.1.2 failed"
    echo "          Check Docker/core before starting gNBs."
fi


# ------------------------------------------------------------
# 3. Near-RT RIC
# ------------------------------------------------------------
echo
echo "[3/3] Starting full Near-RT RIC..."

cd "$HOME/oran-sc-ric"
docker compose up -d

RIC_OK=0

for i in $(seq 1 45); do
    if docker ps --format '{{.Names}}' | grep -qi 'e2term'; then
        RIC_OK=1
        break
    fi
    sleep 1
done

if [ "$RIC_OK" -eq 1 ]; then
    echo "   [PASS] RIC E2 termination container running"
else
    echo "   [WARN] E2 termination container not detected yet"
fi

sleep 5

echo
echo "================ CONTAINER STATUS ================="
docker compose ps

echo
echo "============================================================"
echo " CORE + RIC READY"
echo "============================================================"
echo
echo "============================================================"
echo "============================================================"
echo " NEXT — DIRECT TWO-gNB START ORDER"
echo "============================================================"

echo
echo "1. VM1 — START gNB1"
echo "   Open a NEW VM1 terminal:"
echo
echo "   cd ~/ocudu/build_e2/apps/gnb"
echo "   sudo ./gnb -c ~/configs/gnb1_direct_ue2_ric.yaml"
echo
echo "   Leave this terminal running."

echo
echo "------------------------------------------------------------"
echo "2. VM2 — VERIFY CORE ROUTE + START gNB2"
echo "   Open a VM2 terminal:"
echo
echo "   sudo ip route replace 10.53.1.0/24 via 192.168.0.4 dev ens37"
echo "   ping -c 3 10.53.1.2"
echo
echo "   cd ~/ocudu/build_e2/apps/gnb"
echo "   sudo ./gnb -c ~/configs/gnb2_direct_ue1.yaml"
echo
echo "   Leave this terminal running."

echo
echo "------------------------------------------------------------"
echo "3. VM1 — VERIFY BOTH E2 NODES REGISTERED"
echo "   Open another VM1 terminal:"
echo
echo "   cd ~/oran-sc-ric"
echo "   docker compose logs --since=3m | grep 'associate-ran-to-e2t'"
echo
echo "   EXPECT BOTH:"
echo "     gnbd_001_001_00019b_0"
echo "     gnbd_001_001_00019c_0"
echo
echo "   Do NOT continue until both appear."

echo
echo "------------------------------------------------------------"
echo "4. UE2 — FRESH ATTACH TO gNB1"
echo "   On UE2:"
echo
echo "   sudo pkill -INT -f srsue 2>/dev/null || true"
echo "   sudo ip netns del ue2 2>/dev/null || true"
echo "   sudo ip netns add ue2"
echo "   cd ~/srsRAN_4G/build/srsue/src"
echo "   sudo ./srsue ue2_gnb1.conf"
echo
echo "   Leave this terminal running."
echo
echo "   In another UE2 terminal verify:"
echo "   sudo ip netns exec ue2 ip -br addr show tun_srsue"
echo "   EXPECT: 10.45.1.3"

echo
echo "------------------------------------------------------------"
echo "5. UE1 — FRESH ATTACH TO gNB2"
echo "   On UE1:"
echo
echo "   sudo pkill -INT -f srsue 2>/dev/null || true"
echo "   sudo ip netns del ue1 2>/dev/null || true"
echo "   sudo ip netns add ue1"
echo "   cd ~/srsRAN_4G/build/srsue/src"
echo "   sudo ./srsue ue1_gnb2.conf"
echo
echo "   Leave this terminal running."
echo
echo "   In another UE1 terminal verify:"
echo "   sudo ip netns exec ue1 ip -br addr show tun_srsue"
echo "   EXPECT: 10.45.1.2"

echo
echo
echo "------------------------------------------------------------"
echo "6. UE2 — START KEEPALIVE IMMEDIATELY"
echo "   After UE1 has 10.45.1.2, on UE2:"
echo
echo "   sudo pkill -f '[p]ing -i 1 10.45.1.2' 2>/dev/null || true"
echo
echo "   sudo ip netns exec ue2 \\"
echo "     nohup ping -i 1 10.45.1.2 \\"
echo "     > ~/ue2_keepalive.log 2>&1 &"
echo
echo "   echo \$! > ~/ue2_keepalive.pid"
echo
echo "   sleep 3"
echo
echo "   Verify:"
echo "   pgrep -af 'ping -i 1 10.45.1.2'"
echo "   tail -5 ~/ue2_keepalive.log"

echo
echo "------------------------------------------------------------"
echo "7. VM1 — START DUAL-gNB KPM FEED"
echo "   On VM1:"
echo
echo "   pkill -f '[s]tart_feed_dual.sh' 2>/dev/null || true"
echo "   pkill -f '[k]pm_to_csv.py' 2>/dev/null || true"
echo
echo "   nohup ~/start_feed_dual.sh > ~/kpm_feed.log 2>&1 &"
echo "   echo \$! > ~/kpm_feed.pid"
echo "   sleep 10"
echo
echo "   Verify BOTH nodes are producing rows:"
echo "   echo '=== 19b ==='"
echo "   grep '00019b_0' ~/ran_log.csv | tail -2"
echo "   echo '=== 19c ==='"
echo "   grep '00019c_0' ~/ran_log.csv | tail -2"
echo
echo "   Also inspect:"
echo "   tail -20 ~/kpm_feed.log"

echo
echo "------------------------------------------------------------"
echo "8. VM1 — START decision.py"
echo "   On VM1:"
echo
echo "   pkill -f '[d]ecision.py' 2>/dev/null || true"
echo "   : > ~/era_audit.log"
echo "   nohup python3 ~/decision.py > ~/decision_console.log 2>&1 &"
echo "   echo \$! > ~/decision.pid"
echo "   sleep 2"
echo "   tail -5 ~/decision_console.log"

echo
echo "------------------------------------------------------------"
echo "9. UE1 — SET BATTERY + START PQC SERVERS"
echo "   On UE1:"
echo
echo "   python3 ~/set_battery.py 90"
echo "   python3 ~/battery.py"
echo
echo "   cd ~"
echo "   ./ue1_servers.sh"
echo
echo "   This starts:"
echo "     falcon512 server :4433"
echo "     mldsa44 server   :4434"
echo "     server_battery_agent.sh"
echo
echo "   Leave this terminal running."

echo
echo "------------------------------------------------------------"
echo "10. UE2 — SET BATTERY + START ERA AGENT"
echo "    Open another UE2 terminal:"
echo
echo "    python3 ~/set_battery.py 90"
echo "    python3 ~/battery.py"
echo
echo "    pkill -f '[a]gent.sh ue2' 2>/dev/null || true"
echo "    cd ~"
echo "    nohup ./agent.sh ue2 > ~/agent_ue2.log 2>&1 &"
echo "    echo \$! > ~/agent_ue2.pid"
echo "    sleep 4"
echo
echo "    cat /tmp/current_kem"
echo "    cat /tmp/current_sig"
echo "    cat /tmp/current_crypto 2>/dev/null || true"
echo "    tail -5 ~/agent_ue2.log"

echo
echo "------------------------------------------------------------"
echo "11. VM1 — VERIFY COMPLETE ERA DECISION"
echo "    On VM1:"
echo
echo "    curl -s -X POST http://127.0.0.1:8080/decide \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"ue\":\"ue2\",\"battery_pct\":90}' | python3 -m json.tool"
echo
echo
echo "    tail -1 ~/era_audit.log | python3 -m json.tool"
echo
echo "    Check for:"
echo "      client_batt"
echo "      server_batt"
echo "      gnb1_dl / gnb1_ul"
echo "      gnb2_dl / gnb2_ul"
echo "      forward_thp / reverse_thp"
echo "      KEM + signature"

echo
echo "------------------------------------------------------------"
echo "12. UE2 — SHORT ADAPTIVE PQC SMOKE TEST"
echo "    On UE2:"
echo
echo "    cd ~"
echo "    sudo ./pqc_bench.sh ue2 ue2 10.45.1.2 10 adapt"
echo
echo "    EXPECT:"
echo "      successful handshakes"
echo "      requested KEM == negotiated KEM"
echo "      requested SIG == negotiated SIG"

echo
echo "============================================================"
echo " AFTER THE 10-HANDSHAKE TEST PASSES:"
echo "   DO NOT restart core/RIC/gNBs/UEs."
echo "   Go immediately to forward + reverse iperf/KPM calibration."
echo "============================================================"
