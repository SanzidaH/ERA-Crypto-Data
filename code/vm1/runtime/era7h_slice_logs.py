#!/usr/bin/env python3
import argparse,csv,json,os
ap=argparse.ArgumentParser(); ap.add_argument('--start',type=float,required=True); ap.add_argument('--end',type=float,required=True)
ap.add_argument('--audit',default=os.path.expanduser('~/era_audit.log')); ap.add_argument('--ran',default=os.path.expanduser('~/ran_log.csv')); ap.add_argument('--outdir',required=True)
a=ap.parse_args(); os.makedirs(a.outdir,exist_ok=True); lo=a.start-1.0; hi=a.end+1.0
# audit JSONL
n=0
with open(os.path.join(a.outdir,'era_audit_measured.jsonl'),'w') as out:
    if os.path.exists(a.audit):
        for line in open(a.audit):
            try: j=json.loads(line); ts=float(j.get('ts_epoch'))
            except Exception: continue
            if lo<=ts<=hi: out.write(json.dumps(j,sort_keys=True)+'\n'); n+=1
# RAN CSV
m=0
if os.path.exists(a.ran):
    with open(a.ran,newline='') as f, open(os.path.join(a.outdir,'ran_measured.csv'),'w',newline='') as o:
        r=csv.DictReader(f); w=csv.DictWriter(o,fieldnames=r.fieldnames); w.writeheader()
        for row in r:
            try: ts=float(row['ts_epoch'])
            except Exception: continue
            if lo<=ts<=hi: w.writerow(row); m+=1
print(f'[PASS] sliced audit_rows={n} ran_rows={m}')
