# ERA-Crypto Artifact

This repository contains the minimum code and processed data required to
inspect and reproduce the main results reported in the ERA-Crypto paper.

## Experimental design

- 4 contexts: C00, CB0, C0F, CBF
- 5 policies: Static-L, Static-H, Battery-only, RAN-only, ERA-Dual
- 10 randomized complete blocks
- 200 accepted independent runs
- 5 warm-up TLS connections per run
- 40 measured TLS connections per run
- 8,000 measured connections total
- randomization seed: 20261017

## Contexts

C00: high battery, inactive path
CB0: low battery, inactive path
C0F: high battery, active path
CBF: low battery, active path

## Adaptive policy

RAN context selects:
- inactive -> ML-KEM-1024
- active -> ML-KEM-768

Battery context selects:
- battery >= 30% -> ML-DSA-44
- battery < 30% -> Falcon-512

All choices are restricted to the configured PQC policy envelope.

## Main data

`data/run_summary.csv` contains one row per accepted experimental run.
Individual TLS connections are nested within runs and are not treated as
independent samples.

`data/primary_pairing_manifest.csv` gives the block-level pairing used for
ERA-Dual versus Static-H comparisons.

## Reproducing the main analysis

Run:

python3 code/era7h_paired_stats.py

The resulting ERA-Dual versus Static-H values should match
`data/table_primary_comparisons.csv`.
