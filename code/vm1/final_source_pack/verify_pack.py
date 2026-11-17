#!/usr/bin/env python3
"""Offline integrity/syntax self-test for the extracted FINAL pack."""
from pathlib import Path
import subprocess,sys,hashlib
root=Path(__file__).resolve().parent
fails=[]
sha=root/'PACK_SHA256.txt'
if sha.exists():
    for ln in sha.read_text().splitlines():
        if not ln.strip(): continue
        h,rel=ln.split(None,1); rel=rel.strip().lstrip('*')
        p=root/rel
        if not p.exists(): fails.append(f'missing checksum target {rel}'); continue
        got=hashlib.sha256(p.read_bytes()).hexdigest()
        if got!=h: fails.append(f'checksum mismatch {rel}')
for p in root.rglob('*.sh'):
    r=subprocess.run(['bash','-n',str(p)],capture_output=True,text=True)
    if r.returncode: fails.append(f'bash syntax {p.relative_to(root)}: {r.stderr.strip()}')
for p in root.rglob('*.py'):
    if p.name=='verify_pack.py': continue
    r=subprocess.run([sys.executable,'-m','py_compile',str(p)],capture_output=True,text=True)
    if r.returncode: fails.append(f'python syntax {p.relative_to(root)}: {r.stderr.strip()}')
# Policy matrix shape / single source of truth.
sys.path.insert(0,str(root/'vm1'))
try:
    from era7h_validate_run import EXPECTED
    if len(EXPECTED)!=4 or any(len(x)!=5 for x in EXPECTED.values()): fails.append('expected-policy matrix is not 4 contexts x 5 policies')
except Exception as e: fails.append(f'cannot import expected-policy matrix: {e!r}')
if fails:
    print('[FAIL] FINAL pack self-test')
    for x in fails: print(' -',x)
    raise SystemExit(2)
print('[PASS] checksums, shell syntax, Python syntax, and 4x5 policy matrix verified')
