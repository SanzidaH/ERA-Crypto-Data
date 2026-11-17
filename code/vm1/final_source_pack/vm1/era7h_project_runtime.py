#!/usr/bin/env python3
"""Project final-campaign runtime from a representative full-size smoke root.
Uses valid-attempt wall-clock durations from meta/attempts.csv. The smoke should use the same measured/warmup/sleep as final.
"""
import argparse,csv,os,statistics,math,json
ap=argparse.ArgumentParser(); ap.add_argument('smoke_root'); ap.add_argument('--target-runs',type=int,default=200); ap.add_argument('--hours-limit',type=float,default=7.5); ap.add_argument('--retry-margin',type=float,default=0.10)
a=ap.parse_args(); root=os.path.abspath(os.path.expanduser(a.smoke_root)); p=os.path.join(root,'meta','attempts.csv')
if not os.path.exists(p): raise SystemExit(f'[FAIL] missing {p}')
rows=list(csv.DictReader(open(p))); valid=[r for r in rows if r.get('outcome')=='valid']
if len(valid)<4: raise SystemExit(f'[FAIL] need >=4 valid representative smoke runs, found {len(valid)}')
d=[float(r['end_epoch'])-float(r['start_epoch']) for r in valid]
# Verify representative smoke config if present
cp=os.path.join(root,'meta','campaign_config.json')
if os.path.exists(cp):
    c=json.load(open(cp))
    if int(c.get('measured',0))!=50 or int(c.get('warmup',0))!=5:
        print(f"[WARN] smoke measured/warmup={c.get('measured')}/{c.get('warmup')} rather than final 50/5; projection is not representative")
mean=statistics.mean(d); med=statistics.median(d); mx=max(d); base=mean*a.target_runs/3600; conservative=base*(1+a.retry_margin)
print(f'[SMOKE] valid runs={len(d)} durations_s={[round(x,1) for x in d]}')
print(f'[SMOKE] mean={mean:.1f}s median={med:.1f}s max={mx:.1f}s')
print(f'[PROJECT] {a.target_runs} runs: base={base:.2f} h; +{a.retry_margin*100:.0f}% retry/debug margin={conservative:.2f} h; limit={a.hours_limit:.2f} h')
if conservative<=a.hours_limit:
    print('[PASS] projected campaign fits the requested time budget with configured margin')
    raise SystemExit(0)
print('[WARN] projected campaign exceeds the time budget. Reduce measured handshakes per run only if necessary; preserve independent blocks first.')
raise SystemExit(3)
