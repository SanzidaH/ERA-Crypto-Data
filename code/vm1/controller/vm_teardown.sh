#!/usr/bin/env bash
# ERA-Crypto VM1 clean teardown for the direct two-gNB topology.
#
# Stops VM1-side experiment processes, gNB1, RIC and Open5GS.
# UE1, UE2 and gNB2 must be stopped on their own machines.

set -u
export HOME=/home/srsran

echo "============================================================"
echo " ERA-Crypto VM1 teardown"
echo "============================================================"


# ------------------------------------------------------------
# Experiment/control processes
# ------------------------------------------------------------
echo
echo "[1/4] Stopping experiment/control processes..."

pkill -f '[d]ecision.py'       2>/dev/null || true
pkill -f '[s]tart_feed_dual.sh' 2>/dev/null || true
pkill -f '[k]pm_to_csv.py'     2>/dev/null || true

sleep 1

echo "   [PASS] decision/feed/parser stop requested"


# ------------------------------------------------------------
# VM1 gNB1
# ------------------------------------------------------------
echo
echo "[2/4] Stopping VM1 gNB1..."

sudo pkill -INT -x gnb 2>/dev/null || true
sleep 3

if pgrep -x gnb >/dev/null 2>&1; then
    echo "   [WARN] gNB still alive; force stopping"
    sudo pkill -KILL -x gnb 2>/dev/null || true
else
    echo "   [PASS] gNB1 stopped"
fi


# ------------------------------------------------------------
# RIC
# ------------------------------------------------------------
echo
echo "[3/4] Stopping Near-RT RIC..."

if [ -d "$HOME/oran-sc-ric" ]; then
    (
        cd "$HOME/oran-sc-ric" &&
        docker compose down
    ) || true
fi

echo "   [PASS] RIC stop requested"


# ------------------------------------------------------------
# Open5GS
# ------------------------------------------------------------
echo
echo "[4/4] Stopping Open5GS..."

if [ -d "$HOME/ocudu/docker" ]; then
    (
        cd "$HOME/ocudu/docker" &&
        docker compose down
    ) || true
fi

sudo fuser -k 2152/udp  2>/dev/null || true
sudo fuser -k 38412/sctp 2>/dev/null || true

sleep 2


echo
echo "================ VERIFY VM1 ================="

echo "-- Docker --"
docker ps

echo
echo "-- Remaining relevant host processes --"

pgrep -af '(^|/)(gnb)( |$)|decision.py|start_feed_dual|kpm_to_csv' \
    || echo "   [PASS] no relevant VM1 host processes"

echo
echo "============================================================"
echo " VM1 teardown complete"
echo
echo "REMEMBER to stop separately:"
echo
echo "  UE2:"
echo "    sudo pkill -INT -f srsue 2>/dev/null || true"
echo "    sudo ip netns del ue2 2>/dev/null || true"
echo
echo "  UE1:"
echo "    sudo pkill -INT -f srsue 2>/dev/null || true"
echo "    sudo ip netns del ue1 2>/dev/null || true"
echo
echo "  VM2:"
echo "    sudo pkill -INT -x gnb 2>/dev/null || true"
echo "============================================================"
