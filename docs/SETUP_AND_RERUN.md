# Setup and full reproduction (advanced)

## Reproduction levels

1. **PCAP reanalysis:** needs only the GitHub candidate, Python 3, TShark, matched measured CSVs. Run `bash analysis/reanalyze_samples.sh`.
2. **Processed-data verification:** inspect `data/processed/*.csv`, `integrity/campaign_config.json`, `integrity/schedule.csv`, and valid-run manifests. The complete raw evidence is kept separately.
3. **Full four-machine E2 rerun:** requires restored private runtime components and a compatible network/testbed. The repository **is not self-contained** for this level.

## Machine roles and original paths

| Node | Management address | Role | Working path |
|---|---|---|---|
| Alienware Ubuntu host | host LAN | VMware guests and ZMQ environment | `/home/fltech` (host-dependent) |
| VM1 | `192.168.0.4` | gNB1, Open5GS/RIC, controller, E2 driver | `/home/srsran/era7h/` |
| VM2 | `192.168.0.5` | gNB2 | `/home/srsran/configs/gnb2_direct_ue1.yaml` |
| UE1 (Raspberry Pi 5) | `192.168.0.10` | PQC TLS server attached to gNB2 | `/home/ue1/` |
| UE2 (Raspberry Pi 5) | `192.168.0.20` | PQC TLS client attached to gNB1 | `/home/ue2/era7h/` |

ZMQ radio links are not OTA RF. UE2 IP within its 5G namespace was `10.45.1.3`, UE1 `10.45.1.2` in this topology.

### Required tools/components

- Correct versions of VMware guests, OCUDU/srsRAN gNB and srsUE, Open5GS core, Near-RT RIC with dual gNB E2/KPM xApp, GNU Radio/ZMQ broker
- Python 3, OpenSSH, `iperf3`, `tshark`, `tcpdump`, `tmux`, Docker and Docker Compose as required by the source scripts
- BoringSSL/liboqs builds with ML-KEM-768/1024 and Falcon-512/ML-DSA-44 endpoints
- Test-only TLS certificate material regenerated locally: do **not** use hard-coded or published private keys
- Review `env_info.json`/`env_frozen.json` from the **private** master archive for version fingerprints and script hashes before attempting byte-identical reproduction

### Saved setup and configuration

The private archive preserves:

- VM1: `era7h/`, `era_crypto_7h_campaign_FINAL/`, `decision.py`, `policy_envelope.json`, `era_set_mode.sh`, `era7h_golden_restart.sh`, `start_feed_dual.sh`, `kpm_to_csv.py`, `gnb1_direct_ue2_ric.yaml`, calibration `final_rates.env`, RIC xApp code when found
- VM2: `gnb2_direct_ue1.yaml`, optional `era7h` helpers
- UE1: `ue1_servers.sh`, `server_battery_agent.sh`, `set_battery.py`, `ue1_gnb2.conf`, primitive benchmark evidence
- UE2: `era7h/` worker/scripts, `agent.sh`, `battery.py`, `set_battery.py`, `ue2_gnb1.conf`

Real UE `.conf` files may hold subscriber K/OPc, IMSI or other sensitive values. They are **not automatically placed in the GitHub candidate**. Create sanitized templates with placeholders (e.g. `IMSI_REPLACE_ME`, `OPC_REPLACE_ME`, `K_REPLACE_ME`), then verify these are not real subscriber values. Also review network addresses and other local configuration.

## Setup outline (do not execute blindly on a live experiment)

1. Create a separate backup/snapshot and restore the compatible VM1 and VM2 images **locally**; do not upload them to GitHub.
2. Confirm gNB1 and gNB2 YAML configuration with corresponding two ZMQ-emulated radio links and Open5GS routing; VM2 previously used `sudo ip route replace 10.53.1.0/24 via 192.168.0.4 dev ens37` (verify interface/IP before use).
3. Start the software-defined core, RIC, E2/KPM feed and gNBs, then attach UE1 and UE2 through the configured namespace and radio interfaces.
4. Start UE1 Falcon-512 server on `4433` and ML-DSA-44 server on `4434`, receiver-side iperf service, UE2 battery/ERA agent and UE2 root worker in its own persistent tmux session.
5. Start the VM1 decision controller with the policy envelope and E2/KPM feed. Use the recorded `era_set_mode.sh` and controller scripts, checking that the battery and path signals map to the intended profiles.
6. On VM1 run `~/era7h/era7h_preflight.sh` and require `[READY] ERA7H FINAL preflight passed.`
7. Verify the original frozen environment hashes. If software differs, treat it as a **new reproduction**, not as identical source state.
8. Launch a new E2 campaign into an **empty new root**. Never write into the frozen 2026-10-18 source root.

### Recorded E2 command (VM1; new empty root)

The recorded final command used 40 measured and five warm-up connections per run (unlike an earlier planning runbook with 50).

```bash
NEWROOT="$HOME/results/era7h_reproduction_$(date +%Y%m%d_%H%M%S)"
python3 ~/era7h/era7h_driver.py \
  --experiment E2 --root "$NEWROOT" \
  --blocks 10 --measured 40 --warmup 5 \
  --contexts C00,CB0,C0F,CBF \
  --conditions static_low,static_high,battery_only,ran_only,era_dual \
  --seed 20261017 --sleep 0.7 \
  --load-rate 0.712M --max-attempts 2
```

**Verify against the captured `campaign_config.json` and schedule before running.** The command above reconstructs the reported experimental design; original setup paths and external services must also match. Use the original runbook only after checking it against the actual accepted campaign.

### Verification and expected evidence

Check 200 independent valid runs across 20 context-policy cells (10 each), with 40 measured and 5 warm-up TLS connections per accepted run, 8000 and 1000 totals. Every run should have both `VALID.ok` and `COMPLETE.ok`, with the correct negotiated KEM/signature pair, both dual-gNB KPM sources, context gates, and PCAP/iperf/host-state evidence. Failed/retried attempts must be reported from `meta/attempts.csv`; do not silently discard them. Do not interpret a nonsignificant latency difference as proof of equivalent latency.
