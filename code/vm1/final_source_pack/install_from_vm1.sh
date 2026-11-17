#!/usr/bin/env bash
# ERA7H FINAL installer. Run on VM1 from the extracted pack directory, with BOTH SSH targets given explicitly:
#   UE1_SSH=<user>@<ue1-mgmt-ip> UE2_SSH=<user>@<ue2-mgmt-ip> bash ./install_from_vm1.sh
# Writes ~/era7h/era7h.env, which the driver and preflight read, so the targets are set in exactly one place.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
: "${UE1_SSH:?set UE1_SSH=user@ue1-management-ip (no default in FINAL)}"
: "${UE2_SSH:?set UE2_SSH=user@ue2-management-ip (no default in FINAL)}"
UE1_IPERF_LOG=${UE1_IPERF_LOG:-'~/era7h_iperf_server.json'}   # literal ~ : expanded on UE1, not VM1
for h in "$UE1_SSH" "$UE2_SSH"; do ssh -o BatchMode=yes -o ConnectTimeout=5 "$h" true || { echo "[FAIL] passwordless SSH to $h"; exit 1; }; done
mkdir -p ~/era7h
find "$HERE/vm1" -maxdepth 1 -type f \( -name "*.py" -o -name "*.sh" \) -exec cp {} ~/era7h/ \;
chmod +x ~/era7h/era7h_*
printf "UE1_SSH=%s\nUE2_SSH=%s\nUE1_IPERF_LOG='%s'\n" "$UE1_SSH" "$UE2_SSH" "$UE1_IPERF_LOG" > ~/era7h/era7h.env
ssh -o BatchMode=yes "$UE2_SSH" 'mkdir -p ~/era7h ~/era7h_runs'
scp -q $(find "$HERE/ue2" -maxdepth 1 -type f \( -name "*.py" -o -name "*.sh" \)) "$UE2_SSH":~/era7h/
ssh "$UE2_SSH" 'chmod +x ~/era7h/*.py ~/era7h/*.sh'
echo "[PASS] installed FINAL: VM1 ~/era7h (env: $(tr '\n' ' ' < ~/era7h/era7h.env)), UE2 ~/era7h. Nothing is installed on UE1."
echo "[NEXT] restart the UE2 root worker (inside tmux) so it snapshots the FINAL scripts."
