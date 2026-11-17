#!/usr/bin/env python3
"""Runs ON UE1 (piped over ssh stdin by the VM1 driver/preflight; nothing is installed on UE1).
Usage: python3 - COOKIE LOGFILE [WAIT_S]
Prints the single iperf3 server JSON test object whose start.cookie == COOKIE.
The persistent server must be started as:
  sudo ip netns exec ue1 iperf3 -s -J --logfile /home/ue1/era7h_iperf_server.json
"""
import json, os, sys, time
cookie, path = sys.argv[1], os.path.expanduser(sys.argv[2])
wait_s = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0
deadline = time.time() + wait_s
dec = json.JSONDecoder()
while True:
    try:
        txt = open(path, errors='replace').read()
    except FileNotFoundError:
        txt = ''
    pos = txt.find(cookie)
    if pos >= 0:
        # Decode objects sequentially; the server writes one pretty-printed object per test.
        i = 0; n = len(txt)
        while i < n:
            while i < n and txt[i].isspace():
                i += 1
            if i >= n:
                break
            try:
                obj, i = dec.raw_decode(txt, i)
            except ValueError:
                break  # object still being written; retry after a short wait
            if ((obj.get('start') or {}).get('cookie')) == cookie:
                sys.stdout.write(json.dumps(obj) + '\n')
                sys.exit(0)
    if time.time() > deadline:
        sys.stderr.write(f'[FAIL] cookie {cookie} not found in {path} within {wait_s}s\n')
        sys.exit(3)
    time.sleep(1.0)
