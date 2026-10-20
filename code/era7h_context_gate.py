#!/usr/bin/env python3
"""Mode-independent dual-gNB RAN gate using the same path-activity formula as ERA-Crypto."""
import argparse,csv,time,statistics,json,sys,os

def newest_pair(path):
    latest={}
    try:
        with open(path,newline='') as f:
            for r in csv.DictReader(f):
                node=(r.get('node') or '').lower()
                key='19b' if '19b' in node else ('19c' if '19c' in node else None)
                if not key: continue
                try: ts=float(r['ts_epoch'])
                except Exception: continue
                if key not in latest or ts>float(latest[key]['ts_epoch']): latest[key]=r
    except FileNotFoundError:
        return None
    if not {'19b','19c'} <= set(latest): return None
    a,b=latest['19b'],latest['19c']
    try:
        t1,t2=float(a['ts_epoch']),float(b['ts_epoch'])
        g1dl=float(a['DRB.UEThpDl']); g1ul=float(a['DRB.UEThpUl'])
        g2dl=float(b['DRB.UEThpDl']); g2ul=float(b['DRB.UEThpUl'])
    except Exception: return None
    now=time.time(); skew=abs(t1-t2); age=max(now-t1,now-t2)
    fwd=min(g1ul,g2dl); rev=min(g2ul,g1dl); path_activity=max(fwd,rev)
    return {'pair_key':(t1,t2),'g1dl':g1dl,'g1ul':g1ul,'g2dl':g2dl,'g2ul':g2ul,
            'forward_thp':fwd,'reverse_thp':rev,'path_activity':path_activity,'skew_s':skew,'age_s':age}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--state',choices=['idle','loaded'],required=True)
    ap.add_argument('--ran-log',default=os.path.expanduser('~/ran_log.csv'))
    ap.add_argument('--threshold',type=float,default=322.4)
    ap.add_argument('--timeout',type=float,default=60)
    ap.add_argument('--max-skew',type=float,default=5)
    ap.add_argument('--max-age',type=float,default=15)
    args=ap.parse_args()
    hist=[]; last=None; deadline=time.time()+args.timeout; last_sample=None
    while time.time()<deadline:
        s=newest_pair(args.ran_log)
        if s and s['skew_s']<=args.max_skew and s['age_s']<=args.max_age:
            last_sample=s
            if tuple(s['pair_key'])!=last:
                hist.append(s['path_activity']); hist=hist[-3:]; last=tuple(s['pair_key'])
                if len(hist)==3:
                    med=statistics.median(hist)
                    good=(med < args.threshold) if args.state=='idle' else (med >= args.threshold)
                    if good:
                        out={'status':'PASS','expected_state':args.state,'decision_value':med,
                             'threshold':args.threshold,'filter_samples':hist,'latest':s}
                        print(json.dumps(out,sort_keys=True)); return 0
        time.sleep(1)
    out={'status':'FAIL','expected_state':args.state,'threshold':args.threshold,'filter_samples':hist,'latest':last_sample}
    print(json.dumps(out,sort_keys=True)); return 2
if __name__=='__main__': raise SystemExit(main())
