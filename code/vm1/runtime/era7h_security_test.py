#!/usr/bin/env python3
"""Controller-level policy-envelope rejection test on frozen config.
Sends forced classical choices to /decide. This validates controller policy enforcement, not complete wire-level downgrade resistance.
"""
import argparse,json,os,time,urllib.request,csv
ap=argparse.ArgumentParser(); ap.add_argument('--outdir',default=os.path.expanduser('~/results/era7h_security')); ap.add_argument('--n',type=int,default=40); ap.add_argument('--url',default='http://127.0.0.1:8080/decide')
a=ap.parse_args(); os.makedirs(a.outdir,exist_ok=True)
rows=[]
def post(payload):
    b=json.dumps(payload).encode(); req=urllib.request.Request(a.url,data=b,headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=5) as r: return json.loads(r.read().decode())
for kind,field,bad in [('kem','force_group','X25519'),('sig','force_sig','ecdsa')]:
    for i in range(1,a.n+1):
        payload={'ue':'ue2','battery_pct':90,field:bad}
        ts=time.time()
        try: resp=post(payload); err=''
        except Exception as e: resp={}; err=repr(e)
        reason=resp.get('kem_reason') if kind=='kem' else resp.get('sig_reason')
        selected=resp.get('kem') if kind=='kem' else resp.get('sig')
        ok=(not err and selected and selected.lower()!=bad.lower() and isinstance(reason,str) and ('reject' in reason.lower() or 'outside-envelope' in reason.lower()))
        rows.append({'ts_epoch':ts,'kind':kind,'attempt':i,'forced':bad,'selected':selected,'reason':reason,'ok':ok,'error':err})
out=os.path.join(a.outdir,'policy_rejection_attempts.csv')
with open(out,'w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
summary={k:{'attempts':sum(r['kind']==k for r in rows),'rejected_ok':sum(r['kind']==k and r['ok'] for r in rows)} for k in ('kem','sig')}
summary['all_pass']=all(r['ok'] for r in rows); summary['scope']='controller-level policy-envelope enforcement only'
json.dump(summary,open(os.path.join(a.outdir,'policy_rejection_summary.json'),'w'),indent=2,sort_keys=True)
print(json.dumps(summary,indent=2,sort_keys=True)); print('[FILE]',out)
raise SystemExit(0 if summary['all_pass'] else 2)
