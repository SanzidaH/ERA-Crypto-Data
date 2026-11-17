#!/usr/bin/env python3
import socket,json,sys
SOCK='/tmp/era7h_worker.sock'
if len(sys.argv)<2: raise SystemExit('usage: era7h_worker_client.py ACTION [ARGS...]')
req={'action':sys.argv[1],'args':sys.argv[2:]}
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
try: s.connect(SOCK)
except OSError as e: raise SystemExit(f'[FAIL] ERA7H root worker unavailable: {e}')
s.sendall((json.dumps(req)+'\n').encode()); data=b''
while not data.endswith(b'\n'):
    x=s.recv(65536)
    if not x: break
    data+=x
r=json.loads(data.decode());
if r.get('stdout'): print(r['stdout'],end='')
if r.get('stderr'): print(r['stderr'],end='',file=sys.stderr)
raise SystemExit(int(r.get('rc',99)))
