#!/usr/bin/env python3
# usage: python3 set_battery.py 15   -> force battery to 15%
import sys, json, time
CAP_MAH=3000.0; NOM_V=5.0
CAP_J=CAP_MAH/1000.0*NOM_V*3600.0
pct=float(sys.argv[1]) if len(sys.argv)>1 else 100.0
json.dump({"remaining_j":CAP_J*pct/100.0,"t":time.time()},open("/tmp/vbattery.json","w"))
print(f"battery set to {pct}%")
