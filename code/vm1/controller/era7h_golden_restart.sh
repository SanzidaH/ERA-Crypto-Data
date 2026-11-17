#!/usr/bin/env bash
set -Eeuo pipefail

###############################################################################
# ERA-Crypto FINAL GOLDEN RESTART — TMUX SAFE VERSION
#
# Orchestrator: VM1
#
# Remote nodes:
#   VM2 = 192.168.0.5
#   UE1 = 192.168.0.10
#   UE2 = 192.168.0.20
#
# This script:
#   - NEVER starts the final experiment driver
#   - NEVER creates a new experiment result root
#   - NEVER deletes accepted experiment data
#   - verifies the frozen 101-run SHA256 snapshot before and after restart
#
###############################################################################

VM2="srsran@192.168.0.5"
UE1="ue1@192.168.0.10"
UE2="ue2@192.168.0.20"

ROOT_FILE="$HOME/ERA7H_E2_ROOT.txt"

stage() {
    echo
    echo "================================================================"
    echo "$*"
    echo "================================================================"
}

pass() {
    echo "[PASS] $*"
}

die() {
    echo
    echo "[ABORT] $*" >&2
    exit 1
}

trap 'rc=$?; echo; echo "[ERROR] Golden Start failed at line $LINENO (rc=$rc)." >&2' ERR

###############################################################################
# 0. DATA SAFETY
###############################################################################

stage "0. VERIFY EXISTING FINAL DATASET"

[ -f "$ROOT_FILE" ] || die "Missing $ROOT_FILE"

ROOT="$(cat "$ROOT_FILE")"

[ -d "$ROOT" ] || die "Result root missing: $ROOT"
[ -d "$ROOT/raw" ] || die "Missing $ROOT/raw"

echo "ROOT=$ROOT"

VALID="$(find "$ROOT/raw" -name VALID.ok | wc -l)"

echo "VALID runs = $VALID"

[ "$VALID" -eq 101 ] \
    || die "Expected 101 accepted runs before resume; found $VALID"

MANIFEST="$ROOT/meta/valid101_SHA256_before_resume.txt"

[ -f "$MANIFEST" ] \
    || die "Missing frozen SHA256 manifest: $MANIFEST"

if pgrep -af '[e]ra7h_driver.py' >/dev/null 2>&1; then
    echo "Existing ERA7H driver:"
    pgrep -af '[e]ra7h_driver.py'
    die "Experiment driver is still running"
fi

TMPCHK="$(mktemp)"

if ! (
    cd "$ROOT"
    sha256sum -c meta/valid101_SHA256_before_resume.txt
) >"$TMPCHK" 2>&1; then

    echo "===== SHA256 FAILURES ====="
    grep -v ': OK$' "$TMPCHK" || cat "$TMPCHK"
    rm -f "$TMPCHK"
    die "Frozen 101-run dataset failed checksum verification"
fi

if grep -v ': OK$' "$TMPCHK" | grep -q .; then
    echo "===== UNEXPECTED SHA256 OUTPUT ====="
    grep -v ': OK$' "$TMPCHK"
    rm -f "$TMPCHK"
    die "Unexpected checksum verification output"
fi

rm -f "$TMPCHK"

pass "101 accepted runs are byte-identical to frozen snapshot"

###############################################################################
# 1. MANAGEMENT SSH
###############################################################################

stage "1. VERIFY VM1 -> VM2 / UE1 / UE2 SSH"

for H in "$VM2" "$UE1" "$UE2"; do
    echo
    echo "===== $H ====="

    ssh \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      "$H" \
      'echo "hostname=$(hostname)"; echo "[SSH PASS]"' \
      || die "SSH failed: $H"
done

pass "all management SSH paths work"

###############################################################################
# 2. COMPLETE CONTROLLED TEARDOWN
###############################################################################

stage "2. CONTROLLED TEARDOWN"

echo "You may be prompted for sudo passwords during teardown/startup."

###############################################################################
# VM1 experiment-side processes
###############################################################################

echo
echo "===== VM1 cleanup ====="

sudo -v

tmux kill-session -t kpm 2>/dev/null || true
tmux kill-session -t era7h_resume 2>/dev/null || true

sudo tmux kill-session -t gnb1 2>/dev/null || true

pkill -f '[s]tart_feed_dual.sh' 2>/dev/null || true
pkill -f '[k]pm_to_csv.py' 2>/dev/null || true
pkill -f '[k]pm_mon_xapp_dual.py' 2>/dev/null || true
pkill -f '[d]ecision.py' 2>/dev/null || true

sudo pkill -INT -x gnb 2>/dev/null || true

sleep 2

###############################################################################
# VM2
###############################################################################

echo
echo "===== VM2 cleanup ====="

ssh -tt "$VM2" '
set -e

sudo -v

tmux kill-session -t gnb2 2>/dev/null || true
sudo tmux kill-session -t gnb2 2>/dev/null || true

sudo pkill -INT -x gnb 2>/dev/null || true

sleep 2

echo "[PASS] VM2 runtime cleaned"
'

###############################################################################
# UE1
###############################################################################

echo
echo "===== UE1 cleanup ====="

ssh -tt "$UE1" '
set -e

sudo -v

tmux kill-session -t srsue 2>/dev/null || true
tmux kill-session -t pqc_servers 2>/dev/null || true
tmux kill-session -t iperf 2>/dev/null || true

sudo tmux kill-session -t srsue 2>/dev/null || true
sudo tmux kill-session -t pqc_servers 2>/dev/null || true
sudo tmux kill-session -t iperf 2>/dev/null || true

sudo pkill -INT -x srsue 2>/dev/null || true
sudo pkill -x bssl 2>/dev/null || true
sudo pkill -x iperf3 2>/dev/null || true
sudo pkill -f "[s]erver_battery_agent.sh" 2>/dev/null || true

# Remove stale runtime-only UE1 server logs.
# Accepted experiment artifacts are stored under the final result root,
# so these /tmp files are not part of the frozen 101-run dataset.
sudo rm -f     /tmp/sbatt.log     /tmp/srv_falcon512.log     /tmp/srv_mldsa44.log

sudo ip netns del ue1 2>/dev/null || true

sleep 2

echo "[PASS] UE1 runtime cleaned"
'

###############################################################################
# UE2
###############################################################################

echo
echo "===== UE2 cleanup ====="

ssh -tt "$UE2" '
set -e

sudo -v

tmux kill-session -t srsue 2>/dev/null || true
tmux kill-session -t keepalive 2>/dev/null || true
tmux kill-session -t agent 2>/dev/null || true
tmux kill-session -t era7h_worker 2>/dev/null || true

sudo tmux kill-session -t srsue 2>/dev/null || true
sudo tmux kill-session -t keepalive 2>/dev/null || true
sudo tmux kill-session -t era7h_worker 2>/dev/null || true

pkill -f "[a]gent.sh ue2" 2>/dev/null || true

sudo pkill -INT -x srsue 2>/dev/null || true
sudo pkill -f "[e]ra7h_worker_daemon.py" 2>/dev/null || true
sudo pkill -x iperf3 2>/dev/null || true
sudo pkill -f "[p]ing -i 1 10.45.1.2" 2>/dev/null || true

sudo rm -f /tmp/era7h_worker.sock
sudo ip netns del ue2 2>/dev/null || true

sleep 2

echo "[PASS] UE2 runtime cleaned"
'

###############################################################################
# Core/RIC last
###############################################################################

echo
echo "===== VM1 core/RIC teardown ====="

cd "$HOME"
./vm_teardown.sh

pass "old testbed completely stopped"

###############################################################################
# 3. CORE + RIC
###############################################################################

stage "3. VM1 — START CORE + NEAR-RT RIC"

cd "$HOME"

./vm_up.sh

echo
echo "Waiting for RIC SCTP :36421 ..."

RIC_READY=0

for i in $(seq 1 30); do

    if sudo ss -ln 2>/dev/null | grep -q ':36421'; then
        RIC_READY=1
        break
    fi

    echo "waiting for RIC E2 termination ... ($i/30)"
    sleep 2
done

[ "$RIC_READY" -eq 1 ] \
    || die "RIC SCTP port 36421 never became ready"

cd "$HOME/oran-sc-ric"

docker compose ps

pass "core/RIC running and SCTP 36421 ready"

###############################################################################
# 4. VM1 gNB1 — ROOT TMUX
###############################################################################

stage "4. VM1 — START gNB1 IN ROOT TMUX"

sudo -v

sudo tmux kill-session -t gnb1 2>/dev/null || true

sudo tmux new-session -d -s gnb1 \
"cd /home/srsran/ocudu/build_e2/apps/gnb && exec ./gnb -c /home/srsran/configs/gnb1_direct_ue2_ric.yaml"

sleep 5

sudo tmux has-session -t gnb1 \
    || die "gNB1 tmux died"

echo "===== gNB1 console ====="

sudo tmux capture-pane -p -t gnb1 -S -40 | tail -40

sudo systemctl restart gnb2-open5gs-forward.service

pass "gNB1 root tmux alive"

###############################################################################
# 5. VM2 gNB2 — ROOT TMUX
###############################################################################

stage "5. VM2 — ROUTE + START gNB2 IN ROOT TMUX"

ssh -tt "$VM2" '
set -e

sudo -v

echo "=== restore Open5GS route ==="

sudo ip route replace \
10.53.1.0/24 via 192.168.0.4 dev ens37

ping -c 3 10.53.1.2

echo "=== start root tmux gNB2 ==="

sudo tmux kill-session -t gnb2 2>/dev/null || true
sudo pkill -INT -x gnb 2>/dev/null || true

sleep 2

sudo tmux new-session -d -s gnb2 \
"cd /home/srsran/ocudu/build_e2/apps/gnb && exec ./gnb -c /home/srsran/configs/gnb2_direct_ue1.yaml"

sleep 5

sudo tmux has-session -t gnb2

echo "===== gNB2 console ====="

sudo tmux capture-pane -p -t gnb2 -S -40 | tail -40
'

pass "gNB2 root tmux alive"

###############################################################################
# 6. VERIFY BOTH E2 NODES
###############################################################################

stage "6. VERIFY E2 19b + 19c"

cd "$HOME/oran-sc-ric"

E2_OK=0

for i in $(seq 1 30); do

    LOG="$(docker compose logs --since=5m 2>&1 || true)"

    if echo "$LOG" | grep -q '00019b_0' \
       && echo "$LOG" | grep -q '00019c_0'; then

        echo "$LOG" \
        | grep 'associate-ran-to-e2t' \
        | grep -E '00019b_0|00019c_0' \
        | tail -10

        E2_OK=1
        break
    fi

    echo "waiting for E2 19b + 19c ... ($i/30)"
    sleep 2
done

if [ "$E2_OK" -ne 1 ]; then

    echo
    echo "===== gNB1 tmux ====="
    sudo tmux capture-pane -p -t gnb1 -S -80 2>/dev/null || true

    echo
    echo "===== RIC recent E2 ====="
    docker compose logs --since=10m 2>&1 \
    | grep -Ei '19b|19c|e2|sctp|associate' \
    | tail -150 || true

    echo
    echo "===== gNB2 tmux ====="
    ssh -tt "$VM2" \
    'sudo tmux capture-pane -p -t gnb2 -S -80 2>/dev/null || true'

    die "both E2 nodes did not register"
fi

pass "gNB1=19b and gNB2=19c registered"

###############################################################################
# 7. UE2 — ROOT TMUX
###############################################################################

stage "7. UE2 — ATTACH TO gNB1 IN ROOT TMUX"

ssh -tt "$UE2" '
set -e

sudo -v

sudo tmux kill-session -t srsue 2>/dev/null || true

sudo pkill -INT -x srsue 2>/dev/null || true
sudo ip netns del ue2 2>/dev/null || true
sudo ip netns add ue2

sudo tmux new-session -d -s srsue \
"cd /home/ue2/srsRAN_4G/build/srsue/src && exec ./srsue ue2_gnb1.conf"

OK=0

for i in $(seq 1 45); do

    if sudo ip netns exec ue2 \
       ip -br addr show tun_srsue 2>/dev/null \
       | grep -q "10.45.1.3/24"; then

        sudo ip netns exec ue2 \
        ip -br addr show tun_srsue

        OK=1
        break
    fi

    if ! sudo tmux has-session -t srsue 2>/dev/null; then
        echo "[FAIL] UE2 srsUE tmux exited"
        exit 1
    fi

    echo "waiting for UE2 attach ... ($i/45)"
    sleep 2
done

if [ "$OK" -ne 1 ]; then
    echo "===== UE2 srsUE console ====="
    sudo tmux capture-pane -p -t srsue -S -100 || true
    exit 1
fi
'

pass "UE2 attached as 10.45.1.3"

###############################################################################
# 8. UE1 — ROOT TMUX
###############################################################################

stage "8. UE1 — ATTACH TO gNB2 IN ROOT TMUX"

ssh -tt "$UE1" '
set -e

sudo -v

sudo tmux kill-session -t srsue 2>/dev/null || true

sudo pkill -INT -x srsue 2>/dev/null || true
sudo ip netns del ue1 2>/dev/null || true
sudo ip netns add ue1

sudo tmux new-session -d -s srsue \
"cd /home/ue1/srsRAN_4G/build/srsue/src && exec ./srsue ue1_gnb2.conf"

OK=0

for i in $(seq 1 45); do

    if sudo ip netns exec ue1 \
       ip -br addr show tun_srsue 2>/dev/null \
       | grep -q "10.45.1.2/24"; then

        sudo ip netns exec ue1 \
        ip -br addr show tun_srsue

        OK=1
        break
    fi

    if ! sudo tmux has-session -t srsue 2>/dev/null; then
        echo "[FAIL] UE1 srsUE tmux exited"
        exit 1
    fi

    echo "waiting for UE1 attach ... ($i/45)"
    sleep 2
done

if [ "$OK" -ne 1 ]; then
    echo "===== UE1 srsUE console ====="
    sudo tmux capture-pane -p -t srsue -S -100 || true
    exit 1
fi
'

pass "UE1 attached as 10.45.1.2"

###############################################################################
# 9. VERIFY BIDIRECTIONAL 5G PATH
###############################################################################

stage "9. VERIFY UE2 <-> UE1 5G PATH"

echo "===== UE2 -> UE1 ====="

ssh -tt "$UE2" '
sudo -v
sudo ip netns exec ue2 ping -c 5 10.45.1.2
'

echo
echo "===== UE1 -> UE2 ====="

ssh -tt "$UE1" '
sudo -v
sudo ip netns exec ue1 ping -c 5 10.45.1.3
'

pass "bidirectional 5G ping works"

###############################################################################
# 10. UE2 KEEPALIVE — ROOT TMUX
###############################################################################

stage "10. UE2 — START 1-Hz KEEPALIVE IN ROOT TMUX"

ssh -tt "$UE2" '
set -e

sudo -v

sudo tmux kill-session -t keepalive 2>/dev/null || true

sudo tmux new-session -d -s keepalive \
"exec ip netns exec ue2 ping -i 1 10.45.1.2"

sleep 3

sudo tmux has-session -t keepalive

echo "===== keepalive ====="

sudo tmux capture-pane -p -t keepalive -S -10 | tail -10
'

pass "persistent keepalive running"

###############################################################################
# 11. KPM — VM1 TMUX
###############################################################################

stage "11. VM1 — START DUAL-gNB KPM FEED IN TMUX"

tmux kill-session -t kpm 2>/dev/null || true

pkill -f '[s]tart_feed_dual.sh' 2>/dev/null || true
pkill -f '[k]pm_to_csv.py' 2>/dev/null || true
pkill -f '[k]pm_mon_xapp_dual.py' 2>/dev/null || true

sleep 2

tmux new-session -d -s kpm \
"exec /home/srsran/start_feed_dual.sh"

sleep 3

tmux has-session -t kpm \
    || die "KPM tmux exited"

KPM_OK=0

for i in $(seq 1 30); do

    sleep 2

    if [ ! -f "$HOME/ran_log.csv" ]; then
        echo "waiting for ran_log.csv ... ($i/30)"
        continue
    fi

    AGE=$(( $(date +%s) - $(stat -c %Y "$HOME/ran_log.csv") ))

    RECENT="$(tail -n 40 "$HOME/ran_log.csv" 2>/dev/null || true)"

    if [ "$AGE" -le 15 ] \
       && echo "$RECENT" | grep -q '00019b_0' \
       && echo "$RECENT" | grep -q '00019c_0'; then

        echo "ran_log age=${AGE}s"
        echo "$RECENT" \
        | grep -E '00019b_0|00019c_0' \
        | tail -10

        KPM_OK=1
        break
    fi

    echo "waiting for fresh dual KPM ... ($i/30), age=${AGE}s"
done

if [ "$KPM_OK" -ne 1 ]; then
    echo "===== KPM tmux ====="
    tmux capture-pane -p -t kpm -S -100 2>/dev/null || true
    die "dual-gNB KPM did not become fresh"
fi

pass "fresh 19b + 19c KPM available"

###############################################################################
# 12. DECISION SERVER
###############################################################################

stage "12. VM1 — START ERA CONTROLLER IN DUAL MODE"

"$HOME/era_set_mode.sh" dual

sleep 3

pgrep -af '[d]ecision.py' \
    || die "decision.py is not running"

echo "===== decision test ====="

curl -fsS \
-X POST http://127.0.0.1:8080/decide \
-H 'Content-Type: application/json' \
-d '{"ue":"ue2","battery_pct":90}' \
| python3 -m json.tool

pass "decision server operational"

###############################################################################
# 13. UE1 TLS SERVERS — ROOT TMUX
###############################################################################

stage "13. UE1 — START PQC TLS SERVERS IN ROOT TMUX"

ssh -tt "$UE1" '
set -e

python3 /home/ue1/set_battery.py 90

sudo -v

echo performance \
| sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor \
>/dev/null

sudo tmux kill-session -t pqc_servers 2>/dev/null || true
sudo pkill -x bssl 2>/dev/null || true
sudo pkill -f "[s]erver_battery_agent.sh" 2>/dev/null || true

sudo tmux new-session -d -s pqc_servers \
"export HOME=/home/ue1; cd /home/ue1 && exec ./ue1_servers.sh"

sleep 6

sudo tmux has-session -t pqc_servers

echo "===== PQC server console ====="

sudo tmux capture-pane \
-p -t pqc_servers -S -40 | tail -40

echo "===== listeners ====="

sudo ip netns exec ue1 \
ss -ltn | grep -E ":4433|:4434"
'

pass "UE1 Falcon-512 + ML-DSA-44 servers running"

###############################################################################
# 14. UE1 IPERF — ROOT TMUX
###############################################################################

stage "14. UE1 — START SINGLE FINAL IPERF SERVER IN ROOT TMUX"

ssh -tt "$UE1" '
set -e

sudo -v

sudo tmux kill-session -t iperf 2>/dev/null || true
sudo pkill -x iperf3 2>/dev/null || true

TS=$(date +%Y%m%d_%H%M%S)

if [ -f /home/ue1/era7h_iperf_server.json ]; then
    mv /home/ue1/era7h_iperf_server.json \
       /home/ue1/era7h_iperf_server.pre_golden_${TS}.json
fi

sudo tmux new-session -d -s iperf \
"exec ip netns exec ue1 iperf3 -s -J --logfile /home/ue1/era7h_iperf_server.json"

sleep 3

sudo tmux has-session -t iperf

echo "===== iperf processes ====="

pgrep -af "iperf3 -s"
'

pass "single UE1 iperf server running"

###############################################################################
# 15. UE2 AGENT — USER TMUX
###############################################################################

stage "15. UE2 — START ERA AGENT IN USER TMUX"

ssh "$UE2" '
set -e

python3 /home/ue2/set_battery.py 90

tmux kill-session -t agent 2>/dev/null || true

sleep 1

tmux new-session -d -s agent \
"cd /home/ue2 && exec ./agent.sh ue2"

sleep 4

tmux has-session -t agent

echo "===== agent console ====="

tmux capture-pane -p -t agent -S -20 | tail -20

echo "===== selected crypto ====="

cat /tmp/current_kem
cat /tmp/current_sig
'

pass "UE2 agent running"

###############################################################################
# 16. UE2 ROOT WORKER — ROOT TMUX
###############################################################################

stage "16. UE2 — START ROOT WORKER IN ROOT TMUX"

ssh -tt "$UE2" '
set -e

sudo -v

echo performance \
| sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor \
>/dev/null

sudo tmux kill-session -t era7h_worker 2>/dev/null || true

sudo rm -f /tmp/era7h_worker.sock

sudo tmux new-session -d -s era7h_worker \
"exec /home/ue2/era7h/era7h_worker_daemon.py"

sleep 3

sudo tmux has-session -t era7h_worker

test -S /tmp/era7h_worker.sock

echo "===== worker console ====="

sudo tmux capture-pane \
-p -t era7h_worker -S -30 | tail -30
'

echo "===== worker ping ====="

ssh "$UE2" \
'python3 /home/ue2/era7h/era7h_worker_client.py ping'

echo
echo "===== worker snapshot ====="

ssh "$UE2" \
'python3 /home/ue2/era7h/era7h_worker_client.py snapshot'

pass "root worker operational"

###############################################################################
# 17. IDLE CONTEXT GATE
###############################################################################

stage "17. VERIFY IDLE CONTEXT"

ssh "$UE2" \
'python3 /home/ue2/era7h/era7h_worker_client.py cleanup' \
|| true

sleep 5

python3 "$HOME/era7h/era7h_context_gate.py" \
--state idle \
--timeout 60

pass "idle context gate passed"

###############################################################################
# 18. FINAL PRE-FLIGHT
###############################################################################

stage "18. ERA7H FINAL PRE-FLIGHT"

PREFLIGHT="$ROOT/meta/preflight_golden_tmux_$(date +%Y%m%d_%H%M%S).log"

set +e

"$HOME/era7h/era7h_preflight.sh" \
2>&1 | tee "$PREFLIGHT"

RC=${PIPESTATUS[0]}

set -e

[ "$RC" -eq 0 ] \
    || die "ERA7H preflight returned rc=$RC"

grep -q '\[READY\] ERA7H FINAL preflight passed' "$PREFLIGHT" \
    || die "preflight did not report FINAL READY"

pass "ERA7H final preflight passed"

###############################################################################
# 19. VERIFY FROZEN 101 AGAIN
###############################################################################

stage "19. VERIFY ORIGINAL 101 RUNS AGAIN"

VALID_AFTER="$(find "$ROOT/raw" -name VALID.ok | wc -l)"

echo "VALID after Golden Start = $VALID_AFTER"

[ "$VALID_AFTER" -eq 101 ] \
    || die "Expected 101 before resume; found $VALID_AFTER"

CHECKLOG="$ROOT/meta/valid101_SHA256_after_golden_$(date +%Y%m%d_%H%M%S).log"

if ! (
    cd "$ROOT"
    sha256sum -c meta/valid101_SHA256_before_resume.txt
) >"$CHECKLOG" 2>&1; then

    echo "===== CHECKSUM FAILURE ====="
    grep -v ': OK$' "$CHECKLOG" || cat "$CHECKLOG"

    die "original frozen runs changed"
fi

if grep -v ': OK$' "$CHECKLOG" | grep -q .; then

    grep -v ': OK$' "$CHECKLOG"

    die "unexpected checksum verification output"
fi

pass "all original 101 accepted runs remain byte-identical"

###############################################################################
# 20. TMUX INVENTORY
###############################################################################

stage "20. FINAL PROCESS/TMUX INVENTORY"

echo
echo "===== VM1 USER TMUX ====="
tmux ls 2>/dev/null || true

echo
echo "===== VM1 ROOT TMUX ====="
sudo tmux ls 2>/dev/null || true

echo
echo "===== VM2 ROOT TMUX ====="

ssh -tt "$VM2" '
sudo -v
sudo tmux ls 2>/dev/null || true
'

echo
echo "===== UE1 ROOT TMUX ====="

ssh -tt "$UE1" '
sudo -v
sudo tmux ls 2>/dev/null || true
'

echo
echo "===== UE2 USER TMUX ====="

ssh "$UE2" \
'tmux ls 2>/dev/null || true'

echo
echo "===== UE2 ROOT TMUX ====="

ssh -tt "$UE2" '
sudo -v
sudo tmux ls 2>/dev/null || true
'


###############################################################################
# 21. FRESH-SSH PERSISTENCE PROOF
###############################################################################

stage "21. FRESH-SSH PERSISTENCE PROOF"

echo "Waiting briefly after all setup SSH sessions have closed..."
sleep 10

echo
echo "===== VM1 gNB1 ====="
sudo tmux has-session -t gnb1 \
    || die "VM1 gNB1 tmux disappeared"

sudo tmux capture-pane -p -t gnb1 -S -8 | tail -8

echo
echo "===== VM2 gNB2 after fresh SSH ====="

ssh -tt "$VM2" '
set -e
sudo -v
sudo tmux has-session -t gnb2
pgrep -af "gnb2_direct_ue1|[.]\/gnb"
'

echo
echo "===== UE1 after fresh SSH ====="

ssh -tt "$UE1" '
set -e
sudo -v

sudo tmux has-session -t srsue
sudo tmux has-session -t pqc_servers
sudo tmux has-session -t iperf

sudo ip netns exec ue1 \
ip -br addr show tun_srsue | grep "10.45.1.2/24"

echo "[PASS] UE1 persistent sessions survived SSH disconnect"
'

echo
echo "===== UE2 after fresh SSH ====="

ssh -tt "$UE2" '
set -e
sudo -v

sudo tmux has-session -t srsue
sudo tmux has-session -t keepalive
sudo tmux has-session -t era7h_worker

sudo ip netns exec ue2 \
ip -br addr show tun_srsue | grep "10.45.1.3/24"

echo "[PASS] UE2 root sessions survived SSH disconnect"
'

echo
echo "===== UE2 user agent ====="

ssh "$UE2" '
set -e
tmux has-session -t agent
echo "[PASS] UE2 agent survived SSH disconnect"
'

echo
echo "===== UE2 worker API ====="

ssh "$UE2" \
'python3 /home/ue2/era7h/era7h_worker_client.py ping'

echo
echo "===== final UE2 -> UE1 path ====="

ssh -tt "$UE2" '
set -e
sudo -v
sudo ip netns exec ue2 ping -c 3 10.45.1.2
'

echo
echo "===== final E2 evidence ====="

cd "$HOME/oran-sc-ric"

FINAL_E2="$(docker compose logs --since=30m 2>&1 || true)"

echo "$FINAL_E2" \
| grep 'associate-ran-to-e2t' \
| grep -E '00019b_0|00019c_0' \
| tail -10

echo "$FINAL_E2" | grep -q '00019b_0' \
    || die "19b missing from final E2 evidence"

echo "$FINAL_E2" | grep -q '00019c_0' \
    || die "19c missing from final E2 evidence"

pass "all persistent components survived fresh SSH reconnection checks"

###############################################################################
# RECORD SUCCESSFUL INTERVENTION
###############################################################################

printf '%s | Golden Restart TMUX-safe complete; core/RIC, both gNBs, both UEs, KPM, controller, TLS, iperf, agent and root worker restored; idle gate and preflight PASS; frozen 101 SHA256 PASS; ready to resume same schedule\n' \
"$(date -Is)" >> "$ROOT/meta/operator_interventions.log"

###############################################################################
# DONE
###############################################################################

echo
echo "================================================================"
echo "                 ERA7H GOLDEN READY"
echo "================================================================"
echo "Core / Near-RT RIC       : PASS"
echo "gNB1 root tmux           : PASS"
echo "gNB2 root tmux           : PASS"
echo "E2 node 19b              : PASS"
echo "E2 node 19c              : PASS"
echo "UE2 srsUE root tmux      : PASS"
echo "UE1 srsUE root tmux      : PASS"
echo "UE2 <-> UE1 ping         : PASS"
echo "keepalive root tmux      : PASS"
echo "dual-gNB KPM tmux        : PASS"
echo "ERA controller           : PASS"
echo "UE1 PQC TLS root tmux    : PASS"
echo "UE1 iperf root tmux      : PASS"
echo "UE2 agent user tmux      : PASS"
echo "UE2 worker root tmux     : PASS"
echo "idle context gate        : PASS"
echo "ERA7H preflight          : PASS"
echo "frozen 101 SHA256        : PASS"
echo "================================================================"
echo
echo "RESULT ROOT:"
echo "$ROOT"
echo
echo "DO NOT CREATE A NEW RESULT ROOT."
echo
echo "Golden Start complete. Start the final driver separately in VM1 tmux."
