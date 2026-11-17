# Source-to-destination map

All original paths are the final campaign paths from the saved experiment logs. Missing optional items are logged instead of guessed.

| Original machine and path | Local private destination |
|---|---|
| VM1 `/home/srsran/era_crypto_7h_campaign_FINAL/` | `machines/vm1/final_source_pack/` |
| VM1 `/home/srsran/era7h/` | `machines/vm1/runtime/` |
| VM1 `/home/srsran/decision.py`, `era_set_mode.sh`, `era7h_golden_restart.sh`, `start_feed_dual.sh`, etc. | `machines/vm1/controller/` |
| VM1 `/home/srsran/configs/gnb1_direct_ue2_ric.yaml` | `machines/vm1/configs/` |
| VM1 `/home/srsran/results/calibration/final_kpm/final_rates.env` | `machines/vm1/calibration/` (private only) |
| VM1 `/home/srsran/oran-sc-ric/.../kpm_mon_xapp_dual.py` and compose files if present | `machines/vm1/ric/` |
| VM2 `/home/srsran/configs/gnb2_direct_ue1.yaml` | `machines/vm2/configs/` |
| UE1 `/home/ue1/ue1_servers.sh`, `server_battery_agent.sh`, `set_battery.py`, `ue1_gnb2.conf` | `machines/ue1/scripts/`, `configs/` |
| UE2 `/home/ue2/era7h/`, `agent.sh`, `battery.py`, `set_battery.py`, `ue2_gnb1.conf` | `machines/ue2/runtime/`, `scripts/`, `configs/` |
| VM1 final `meta/`, `processed/`, `paper_results/` | `results/meta/`, `processed/`, `paper_results/` |
| VM1 final `raw/<run>/ue2/crypto_measured.pcap` + matched CSV and run summary | `results/pcap_samples/<run>/` |

Nothing is deleted from any experiment machine; the script copies read-only. It excludes private key files, VM disks, general raw PCAP trees, and other high-risk material from bulk directory copies.
