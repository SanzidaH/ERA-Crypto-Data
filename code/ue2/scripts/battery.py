#!/usr/bin/env python3
# Virtual battery: real PMIC power draw, simulated capacity. Prints % remaining.
import os, re, subprocess, time, json
STATE="/tmp/vbattery.json"; CAP_MAH=3000.0; NOM_V=5.0; ACCEL=1.0
CAP_J=CAP_MAH/1000.0*NOM_V*3600.0
def watts():
    try:
        t=subprocess.check_output(["vcgencmd","pmic_read_adc"],text=True)
        a=dict(re.findall(r"(\S+)_A\s+current\(\d+\)=([0-9.]+)A",t))
        v=dict(re.findall(r"(\S+)_V\s+volt\(\d+\)=([0-9.]+)V",t))
        return sum(float(x)*float(a[k]) for k,x in v.items() if k in a)
    except Exception:
        return 3.0
now=time.time()
if os.path.exists(STATE):
    s=json.load(open(STATE)); r=s["remaining_j"]; last=s["t"]
else:
    r=CAP_J; last=now
r=max(0.0, r-watts()*(now-last)*ACCEL)
json.dump({"remaining_j":r,"t":now},open(STATE,"w"))
print(round(100.0*r/CAP_J,1))
