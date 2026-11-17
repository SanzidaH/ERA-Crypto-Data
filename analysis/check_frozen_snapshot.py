#!/usr/bin/env python3
"""Compare copied scripts to recorded meta/env_frozen.json without changing evidence.
Usage: python3 check_frozen_snapshot.py PATH_TO_01_PRIVATE_MASTER
"""
import hashlib
import json
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Usage: check_frozen_snapshot.py PATH_TO_01_PRIVATE_MASTER")
base = Path(sys.argv[1])
envfile = base / "results/meta/env_frozen.json"
if not envfile.is_file():
    print("status\tmachine\toriginal_path\tlocal_copy\tshort_hashes")
    print(f"NO_ENV_FROZEN\tvm1\t{envfile}\t-\t-")
    raise SystemExit(0)
obj = json.loads(envfile.read_text())
print("status\tmachine\toriginal_path\tlocal_copy\tshort_hashes")
counts = {}


def local_for(section, remote_path):
    s = str(remote_path)
    if section == "vm1":
        roots = (
            ("/home/srsran/era7h/", "machines/vm1/runtime/"),
            ("/home/srsran/configs/", "machines/vm1/configs/"),
            ("/home/srsran/results/calibration/final_kpm/", "machines/vm1/calibration/"),
            ("/home/srsran/", "machines/vm1/controller/"),
        )
        for prefix, local in roots:
            if s.startswith(prefix):
                return base / (local + s[len(prefix):])
    elif section in ("ue1", "ue2"):
        if s.startswith(f"/home/{section}/"):
            s = s[len(f"/home/{section}/"):]
        if s.startswith("era7h/"):
            return base / f"machines/{section}/runtime" / s[len("era7h/"):]
        if section == "ue2" and s.startswith("era7h_"):
            return base / "machines/ue2/runtime" / s
        return base / f"machines/{section}/scripts" / s
    elif section == "ue2_root_worker_snapshot":
        s = s.removeprefix("/home/ue2/era7h/")
        return base / "machines/ue2/runtime" / s.removeprefix("era7h/")
    return None


for section in ("vm1", "ue1", "ue2", "ue2_root_worker_snapshot"):
    block = obj.get(section)
    if not isinstance(block, dict):
        continue
    for path, original_hash in sorted(block.items()):
        if not isinstance(original_hash, str) or len(original_hash) != 64:
            continue
        local = local_for(section, path)
        if local is None or not local.is_file():
            stat = "NOT_COLLECTED"
            pair = "-"
        else:
            current = hashlib.sha256(local.read_bytes()).hexdigest()
            stat = "MATCH" if current.lower() == original_hash.lower() else "MISMATCH"
            pair = f"{original_hash[:12]}/{current[:12]}"
        counts[stat] = counts.get(stat, 0) + 1
        print(f"{stat}\t{section}\t{path}\t{local if local else '-'}\t{pair}")
print(f"# Frozen comparison counts: {counts}", file=sys.stderr)
