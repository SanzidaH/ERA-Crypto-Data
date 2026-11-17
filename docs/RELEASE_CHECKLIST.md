# GitHub release checklist — mandatory review

The collector produces **02_GITHUB_REVIEW**, not a verified public artifact. It does not run `git init`, `git add` or `git push`.

## Completeness and provenance

1. Read `03_REPORTS/missing_or_failed.txt`, `collection.log` and `collection_summary.json`.
2. Confirm `01_PRIVATE_MASTER/results/meta/campaign_config.json` shows the intended E2 settings. Verify `env_frozen.json` and `valid200` manifests without editing them.
3. Review `02_GITHUB_REVIEW/integrity/sample_manifest.tsv`: exactly which PCAPs were included, their SHA256 hashes, and whether any exceeded the configured max size.
4. Compare published scripts against the frozen hashes. If different, disclose that fact instead of labeling them an exact snapshot.
5. Execute the sample reanalysis and compare output to original summaries.

## Secrets/privacy

Check filenames in public candidate:

```bash
cd ~/ERA-Crypto-Research-2026/02_GITHUB_REVIEW
find . -type f \( -name '*.key' -o -name '*.pem' -o -name '.env*' -o -name 'id_ed25519*' -o -name 'id_rsa*' -o -name '*.vmdk' \)
```

Check text for potential secrets and other identifiers (manually inspect hits):

```bash
grep -RInE --exclude='*.pcap' --exclude-dir=.git \
 'BEGIN .*PRIVATE KEY|Authorization:|Bearer |password[[:space:]]*[:=]|api[_-]?key[[:space:]]*[:=]|secret[[:space:]]*[:=]|@.*\.edu|/home/' . || true
```

**Critical:** UE `.conf` files can include IMSI, K and OPc, not only generic subscriber configuration. The collector deliberately keeps real `.conf` and `.yaml` in the PRIVATE_MASTER rather than publishing them automatically. Review other source files and controller logic for hard-coded values; `gitignore` is not a secret scrubber.

For each sample PCAP, use `capinfos` and `tshark` and inspect for **only** test TLS port 4433/4434 traffic, plus potential unexpected contents. A complete packet capture can include data that name-based scanners miss; obtain appropriate release approval.

```bash
for p in data/pcap_samples/*/ue2/crypto_measured.pcap; do
  [ -f "$p" ] || continue
  capinfos "$p" | head -15
  tshark -r "$p" -q -z conv,tcp | head -35
done
```

If anonymization for double-blind review is required, handle Git author identity, source comments, paths and metadata, not only README authorship.

## Push using Git (only after approval)

Clone the existing GitHub repository first; do not force-push and do not overwrite unrelated work. From a clean clone of your existing `Era-Crypto_Files` repository:

```bash
# Example path: ~/Era-Crypto_Files is an EXISTING clone
cd ~/Era-Crypto_Files
git status --short
# After manually copying reviewed files from 02_GITHUB_REVIEW into this clone:
git add README.md .gitignore code configs analysis docs data integrity
git diff --cached --stat
git diff --cached
git status
# Only after the diff and content are approved:
git commit -m 'Add ERA-Crypto reproducibility artifact'
git push
```

Use the existing clone's remote. Never run `git add .` on the private archive or raw results. Normal Git hosting rejects files of 100 MiB or more; use a release archive, Zenodo or Git LFS with reviewed files if necessary. Never truncate a PCAP and claim its original metrics are reproducible.

If secrets were previously committed and pushed, rotating/revoking credentials matters; deleting a file in the newest commit does not remove historical copies.
