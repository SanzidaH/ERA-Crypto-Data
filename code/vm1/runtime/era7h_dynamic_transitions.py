#!/usr/bin/env python3
"""Optional five-phase live-adaptation demonstration/experiment.
Phases (30 s default): P1 high+inactive, P2 high+active, P3 low+active, P4 low+inactive, P5 high+inactive.
The first --settle seconds of each phase are excluded from switching-accuracy summaries.
"""
import argparse,csv,json,os,subprocess,time,shlex,statistics
from pathlib import Path
HOME=Path.home(); ENVF=HOME/'era7h/era7h.env'; SCRIPT=HOME/'era7h'
if ENVF.exists():
    for ln in ENVF.read_text().splitlines():
        if ln.strip() and not ln.lstrip().startswith('#') and '=' in ln:
            k,v=ln.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"\''))
UE1=os.environ.get('UE1_SSH'); UE2=os.environ.get('UE2_SSH')
def run(q,check=True,capture=False):
    print('+',q if isinstance(q,str) else ' '.join(q),flush=True); return subprocess.run(q,shell=isinstance(q,str),check=check,text=True,capture_output=capture)
def ssh(host,cmd,check=True,capture=False): return run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',host,cmd],check,capture)
def worker(action,*args,check=True,capture=False): return ssh(UE2,shlex.join(['python3','/home/ue2/era7h/era7h_worker_client.py',action,*map(str,args)]),check,capture)
def pull(runid,dest):
    dest.mkdir(parents=True,exist_ok=True); remote=f'tar -C /home/ue2/era7h_runs/{runid} -cf - .'
    p1=subprocess.Popen(['ssh','-o','BatchMode=yes',UE2,remote],stdout=subprocess.PIPE); p2=subprocess.run(['tar','-C',str(dest),'-xf','-'],stdin=p1.stdout)
    if p1.stdout:p1.stdout.close(); rc=p1.wait()
    if rc or p2.returncode: raise RuntimeError('artifact pull failed')
def add_event(ev,phase,state,batt,expected): ev.append({'phase':phase,'start_epoch':time.time(),'path_state':state,'ue2_batt':batt,'expected_kem':expected[0],'expected_sig':expected[1]})
def analyze(outdir,events,settle):
    cr=list(csv.DictReader(open(outdir/'ue2/crypto_log_measured.csv'))); au=[]
    ap=outdir/'era_audit_measured.jsonl'
    if ap.exists():
        for line in open(ap):
            try: au.append(json.loads(line))
            except: pass
    final_end=max(float(x['end_epoch']) for x in cr) if cr else time.time()
    rows=[]
    for i,e in enumerate(events):
        st=e['start_epoch']; en=events[i+1]['start_epoch'] if i+1<len(events) else final_end; lo=st+settle
        rr=[x for x in cr if lo<=float(x['start_epoch'])<en]
        ok=[x for x in rr if x.get('result')=='ok']; right=[x for x in ok if (x.get('req_kem'),x.get('req_sig'))==(e['expected_kem'],e['expected_sig'])]
        lat=[float(x['client_elapsed_ms']) for x in ok]
        aa=[x for x in au if lo<=float(x.get('ts_epoch',0))<en and str(x.get('ue','ue2'))=='ue2']; dv=[float((x.get('ran_context') or {}).get('decision_value')) for x in aa if isinstance((x.get('ran_context') or {}).get('decision_value'),(int,float))]
        rows.append({**e,'analysis_start_epoch':lo,'end_epoch':en,'handshakes':len(ok),'expected_matches':len(right),'selection_accuracy_pct':100*len(right)/len(ok) if ok else None,'latency_median_ms':statistics.median(lat) if lat else None,'decision_value_median':statistics.median(dv) if dv else None})
    with open(outdir/'dynamic_phase_summary.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    json.dump(rows,open(outdir/'dynamic_phase_summary.json','w'),indent=2)
    print('[PASS] dynamic summary')
    for r in rows: print(r)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',required=True); ap.add_argument('--phase-seconds',type=float,default=30); ap.add_argument('--settle',type=float,default=10); ap.add_argument('--load-rate',default='0.712M'); ap.add_argument('--handshakes',type=int,default=220); ap.add_argument('--sleep',type=float,default=0.2); a=ap.parse_args()
    if not UE1 or not UE2: raise SystemExit('[FAIL] UE1_SSH/UE2_SSH missing; install FINAL pack first')
    root=Path(os.path.expanduser(a.root)).resolve(); out=root/'dynamic'; out.mkdir(parents=True,exist_ok=True); runid='E6_'+root.name
    run([str(HOME/'era_set_mode.sh'),'dual']); worker('cleanup',check=False); worker('snapshot')
    ssh(UE1,'python3 ~/set_battery.py 90'); ssh(UE2,'python3 ~/set_battery.py 90'); time.sleep(5)
    worker('prepare',runid,'C00','era_dual',a.load_rate); worker('warmup',runid,3,'era_dual',a.sleep)
    cmd=['ssh','-o','BatchMode=yes',UE2,shlex.join(['python3','/home/ue2/era7h/era7h_worker_client.py','measure',runid,str(a.handshakes),'era_dual',str(a.sleep)])]
    print('+',' '.join(cmd),flush=True); mp=subprocess.Popen(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    time.sleep(3); events=[]; add_event(events,'P1','inactive',90,('mlkem1024','mldsa44'))
    def sleep_phase():
        end=time.time()+a.phase_seconds
        while time.time()<end:
            if mp.poll() is not None: raise RuntimeError('dynamic measured benchmark ended before phase schedule completed')
            time.sleep(min(2,end-time.time()))
    sleep_phase(); worker('dynamic_load_start',runid,a.load_rate); add_event(events,'P2','active',90,('mlkem768','mldsa44'))
    sleep_phase(); ssh(UE2,'python3 ~/set_battery.py 15'); add_event(events,'P3','active',15,('mlkem768','falcon512'))
    sleep_phase(); worker('dynamic_load_stop',runid); add_event(events,'P4','inactive',15,('mlkem1024','falcon512'))
    sleep_phase(); ssh(UE2,'python3 ~/set_battery.py 90'); add_event(events,'P5','inactive',90,('mlkem1024','mldsa44'))
    sleep_phase(); print('[INFO] phase schedule complete; waiting for benchmark to finish')
    try: stdout,_=mp.communicate(timeout=300)
    except subprocess.TimeoutExpired: mp.terminate(); stdout,_=mp.communicate(timeout=20); raise RuntimeError('dynamic benchmark did not finish within 5 min after phases')
    print(stdout[-5000:]);
    if mp.returncode: raise RuntimeError(f'dynamic benchmark failed rc={mp.returncode}')
    worker('finish',runid,'C00'); pull(runid,out/'ue2')
    bm=json.load(open(out/'ue2/bench_measured_meta.json')); t0=bm['run_start_epoch']; t1=bm['run_end_epoch']
    run(['python3',str(SCRIPT/'era7h_slice_logs.py'),'--start',str(t0),'--end',str(t1),'--outdir',str(out)])
    run(['python3',str(SCRIPT/'era7h_pcap_metrics.py'),'--pcap',str(out/'ue2/crypto_measured.pcap'),'--crypto-csv',str(out/'ue2/crypto_log_measured.csv'),'--outdir',str(out)])
    with open(out/'phase_events.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(events[0].keys())); w.writeheader(); w.writerows(events)
    analyze(out,events,a.settle); print('[DONE] dynamic experiment:',out)
if __name__=='__main__': raise SystemExit(main())
