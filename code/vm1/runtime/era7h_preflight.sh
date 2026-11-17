#!/usr/bin/env bash
# ERA7H FINAL fail-fast preflight. Does NOT restart a healthy 5G/RIC stack.
set -euo pipefail
ENVF=~/era7h/era7h.env; [[ -f "$ENVF" ]] || { echo "[FAIL] $ENVF missing; run install_from_vm1.sh with UE1_SSH/UE2_SSH" >&2; exit 1; }
# shellcheck disable=SC1090
source "$ENVF"
UE1=${UE1_SSH:?}; UE2=${UE2_SSH:?}; IPLOG=${UE1_IPERF_LOG:-~/era7h_iperf_server.json}
ok(){ echo "[PASS] $*"; }; die(){ echo "[FAIL] $*" >&2; exit 1; }
for c in python3 ssh scp tshark curl sha256sum tar; do command -v "$c" >/dev/null || die "VM1 missing $c"; done
echo "[INFO] VM1 $(tshark --version | head -1)"
for f in ~/decision.py ~/policy_envelope.json ~/era_set_mode.sh ~/ran_log.csv ~/era_audit.log ~/era7h/era7h_context_gate.py ~/era7h/era7h_iperf_fetch_remote.py; do [[ -e "$f" ]] || die "missing $f"; done
grep -q '322.4' ~/decision.py || die 'decision.py does not visibly contain frozen threshold 322.4'
grep -q 'ERA_MODE' ~/decision.py || die 'decision.py does not contain ERA_MODE support'
python3 -m py_compile ~/decision.py || die 'decision.py syntax error'
ssh -o BatchMode=yes -o ConnectTimeout=5 "$UE1" 'true' >/dev/null || die "passwordless SSH to UE1 ($UE1) not ready"
ssh -o BatchMode=yes -o ConnectTimeout=5 "$UE2" 'true' >/dev/null || die "passwordless SSH to UE2 ($UE2) not ready"
ok "passwordless SSH to UE1=$UE1 UE2=$UE2"
ssh "$UE2" 'for c in iperf3 tcpdump ping timeout /usr/bin/time tar; do command -v $c >/dev/null || exit 2; done; test -x ~/Downloads/boringssl/build/tool/bssl; test -x ~/era7h/era7h_worker_client.py' || die 'UE2 missing tool/script/bssl'
ok 'UE2 tools available'
# CPU governor + thermal telemetry: DVFS/throttling changes long-run latency.
for h in "$UE1" "$UE2"; do
  g=$(ssh "$h" 'cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | sort -u | tr "\n" " "; true' || true)
  if [[ "$g" != "performance " && "${ERA7H_ALLOW_GOVERNOR:-0}" != "1" ]]; then
    die "$h CPU governor is '$g' (want performance). On that endpoint: echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"
  fi
  t=$(ssh "$h" 'command -v vcgencmd >/dev/null && vcgencmd measure_temp && vcgencmd get_throttled' 2>/dev/null || true)
  if [[ -z "$t" && "${ERA7H_ALLOW_NO_VCGENCMD:-0}" != "1" ]]; then
    die "$h vcgencmd thermal/throttle telemetry unavailable. Fix permissions/path, or explicitly export ERA7H_ALLOW_NO_VCGENCMD=1 and document the limitation."
  fi
  echo "[INFO] $h governor=$g $(echo "$t" | tr '\n' ' ')"
  if echo "$t" | grep -Eq 'throttled=0x[1-9a-fA-F]'; then
    echo "[WARN] $h get_throttled is non-zero. If only historical bits are set this can be documented, but active throttling during a run will invalidate that run."
  fi
done
ok 'CPU governor and thermal telemetry checked on both endpoints'
ssh "$UE2" 'python3 ~/era7h/era7h_worker_client.py ping' >/dev/null || die 'ERA7H root worker not running; on UE2 inside tmux: sudo /home/ue2/era7h/era7h_worker_daemon.py'
ok 'UE2 root worker reachable'
snap=$(ssh "$UE2" 'python3 ~/era7h/era7h_worker_client.py snapshot') || die 'UE2 root worker is executing stale scripts; restart it in tmux'
python3 -c 'import json,sys; j=json.loads(sys.argv[1]); assert j.get("match") is True; print("[PASS] worker snapshot matches installed scripts:",len(j.get("root",{})),"files")' "$snap" || die 'worker snapshot verification failed'
ac=$(ssh "$UE2" "pgrep -af 'agent.sh ue2' | grep -v 'pgrep' | wc -l")
[[ "$ac" -eq 1 ]] || die "expected exactly one UE2 agent.sh ue2 process; found $ac"
ssh "$UE1" "pgrep -af 'server_battery_agent.sh' | grep -v 'pgrep' >/dev/null" || die 'UE1 server_battery_agent not running'
ok 'one UE2 agent + UE1 server battery reporter'
ssh "$UE2" 'python3 ~/era7h/era7h_worker_client.py netcheck' || die '5G path or UE1 TLS ports failed'
ok '5G path and both TLS servers reachable'
# v2: UE1 iperf3 server must be a persistent JSON-logging server inside netns ue1.
ssh "$UE1" "pgrep -af 'iperf3 -s' | grep -v pgrep | grep -q -- '-J' && pgrep -af 'iperf3 -s' | grep -v pgrep | grep -q -- '--logfile'" \
  || die "UE1 iperf3 server with JSON log not running. On UE1 (tmux): sudo ip netns exec ue1 iperf3 -s -J --logfile /home/ue1/era7h_iperf_server.json"
chk=$(ssh "$UE2" 'python3 ~/era7h/era7h_worker_client.py iperfcheck') || die "short UE2->UE1 iperf3 test failed: $chk"
cookie=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["cookie"])' "$chk")
srv=$(ssh "$UE1" "python3 - $cookie $IPLOG 20" < ~/era7h/era7h_iperf_fetch_remote.py) || die "UE1 server log $IPLOG has no entry for cookie $cookie (wrong --logfile path?)"
rx=$(python3 -c 'import json,sys; j=json.loads(sys.argv[1]); print((j["end"]["sum_received"]["bits_per_second"] or 0)/1e6)' "$srv")
python3 -c "import sys; sys.exit(0 if float('$rx')>0 else 1)" || die "UE1 server log entry shows zero received throughput"
ok "UE1 iperf3 server log matched by cookie; check test received ${rx} Mbit/s"
curl -fsS -X POST http://127.0.0.1:8080/decide -H 'Content-Type: application/json' -d '{"ue":"ue2","battery_pct":90}' >/dev/null || die 'decision server not responding on :8080'
pgrep -af 'start_feed_dual|kpm_to_csv' >/dev/null || die 'dual KPM feed process not found'
python3 ~/era7h/era7h_context_gate.py --state idle --timeout 45 >/tmp/era7h_preflight_gate.json || { cat /tmp/era7h_preflight_gate.json; die 'RAN preflight is not clean idle/fresh'; }
cat /tmp/era7h_preflight_gate.json
ok 'fresh dual-gNB KPM and idle gate'
tail -1 ~/era_audit.log | python3 -c 'import json,sys; j=json.loads(sys.stdin.read()); print("[INFO] latest audit keys:", sorted(j.keys()))' || echo '[WARN] could not parse last era_audit.log line'
ssh "$UE2" 'python3 ~/era7h/era7h_worker_client.py cleanup' >/dev/null || true
ok 'campaign load marker clean'
echo '[INFO] software fingerprints:'
ssh "$UE2" 'printf "UE2 bssl_sha="; sha256sum ~/Downloads/boringssl/build/tool/bssl 2>/dev/null | awk "{print \$1}"; printf "UE2 boringssl_git="; git -C ~/Downloads/boringssl rev-parse HEAD 2>/dev/null || true; printf "UE2 liboqs_git="; git -C ~/Downloads/liboqs rev-parse HEAD 2>/dev/null || true; printf "UE2 srsran_git="; git -C ~/srsRAN_4G rev-parse HEAD 2>/dev/null || true; iperf3 --version 2>/dev/null | head -1'
ssh "$UE1" 'printf "UE1 bssl_sha="; sha256sum ~/Downloads/boringssl/build/tool/bssl 2>/dev/null | awk "{print \$1}"; printf "UE1 boringssl_git="; git -C ~/Downloads/boringssl rev-parse HEAD 2>/dev/null || true; printf "UE1 liboqs_git="; git -C ~/Downloads/liboqs rev-parse HEAD 2>/dev/null || true; printf "UE1 srsran_git="; git -C ~/srsRAN_4G rev-parse HEAD 2>/dev/null || true; iperf3 --version 2>/dev/null | head -1'
echo "[INFO] VM1 $(tshark --version | head -1); ocudu_git=$(git -C ~/ocudu rev-parse HEAD 2>/dev/null || true)"
echo '[READY] ERA7H FINAL preflight passed. Do not restart working gNB/RIC/core processes.'
