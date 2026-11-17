#!/usr/bin/env python3

import sys
import csv
import time
import re
import os

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/ran_log.csv")

FIELDS = [
    "ts_epoch",
    "node",
    "collect_time",
    "DRB.UEThpDl",
    "DRB.UEThpUl",
]

node_re = re.compile(r"RIC Indication Received from (\S+)")
time_re = re.compile(r"ColletStartTime:\s*(.+)")
metric_re = re.compile(r"--Metric:\s*(\S+),\s*Value:\s*\[([^\]]*)\]")

header_written = os.path.exists(OUT) and os.path.getsize(OUT) > 0
cur = None


def flush(rec):
    global header_written

    if not rec or not rec.get("metrics"):
        return

    row = {
        "ts_epoch": f"{time.time():.3f}",
        "node": rec.get("node", ""),
        "collect_time": rec.get("collect_time", ""),
        "DRB.UEThpDl": rec["metrics"].get("DRB.UEThpDl", 0.0),
        "DRB.UEThpUl": rec["metrics"].get("DRB.UEThpUl", 0.0),
    }

    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)

        if not header_written:
            w.writeheader()
            header_written = True

        w.writerow(row)

    print(f"[csv] {row}", flush=True)


for line in sys.stdin:
    line = line.rstrip("\n")

    m = node_re.search(line)

    if m:
        flush(cur)
        cur = {
            "node": m.group(1),
            "metrics": {}
        }
        continue

    if cur is None:
        continue

    m = time_re.search(line)

    if m:
        cur["collect_time"] = m.group(1).strip()
        continue

    m = metric_re.search(line)

    if m:
        vals = [
            v.strip()
            for v in m.group(2).split(",")
            if v.strip()
        ]

        try:
            val = (
                sum(float(v) for v in vals) / len(vals)
                if vals else 0.0
            )
        except ValueError:
            val = 0.0

        cur["metrics"][m.group(1)] = val

flush(cur)
