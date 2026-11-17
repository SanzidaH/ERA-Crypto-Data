#!/usr/bin/env python3
"""Small root worker for ERA7H (v2). Start once with sudo INSIDE tmux on UE2; accepts only whitelisted experiment actions."""
import os,socket,json,subprocess,signal,sys,re,shutil,pwd,grp,hashlib
SOCK='/tmp/era7h_worker.sock'; ROOTBIN='/root/era7h_worker_scripts'; SRC='/home/ue2/era7h'
SCRIPTS=['pqc_bench_v2.sh','era7h_prepare.sh','era7h_warmup.sh','era7h_measure.sh','era7h_finish.sh','era7h_cleanup.sh','era7h_dynamic_load_start.sh','era7h_dynamic_load_stop.sh']
RUN_RE=re.compile(r'^[A-Za-z0-9_.-]{1,120}$'); RATE_RE=re.compile(r'^[0-9.]+[KMG]?$')
CTX={'C00','CB0','C0F','CBF','E1L0'}; COND={'static_low','static_high','battery_only','ran_only','era_dual','M1','M2','M3','M4'}

def fail(msg): return {'rc':2,'stdout':'','stderr':msg}
def sha256_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def snapshot_report():
    src={n:sha256_file(os.path.join(SRC,n)) for n in SCRIPTS if os.path.isfile(os.path.join(SRC,n))}
    root={n:sha256_file(os.path.join(ROOTBIN,n)) for n in SCRIPTS if os.path.isfile(os.path.join(ROOTBIN,n))}
    return {'source':src,'root':root,'match':src==root,'scripts':SCRIPTS}

def validate_run(x): return bool(RUN_RE.fullmatch(str(x)))
def setup():
    if os.geteuid()!=0: raise SystemExit('must run as root: sudo /home/ue2/era7h/era7h_worker_daemon.py (inside tmux)')
    os.makedirs(ROOTBIN,exist_ok=True)
    for n in SCRIPTS:
        src=os.path.join(SRC,n); dst=os.path.join(ROOTBIN,n)
        if not os.path.isfile(src): raise SystemExit(f'missing {src}')
        shutil.copy2(src,dst); os.chmod(dst,0o700)
    if os.path.exists(SOCK): os.unlink(SOCK)

def execute(req):
    action=req.get('action'); args=req.get('args') or []
    if action=='ping': return {'rc':0,'stdout':'PONG\n','stderr':''}
    if action=='snapshot':
        rep=snapshot_report(); return {'rc':0 if rep['match'] else 5,'stdout':json.dumps(rep,sort_keys=True)+'\n','stderr':'' if rep['match'] else 'worker root snapshot differs from /home/ue2/era7h; restart the worker'}
    if action=='netcheck':
        checks=[['ip','netns','exec','ue2','ping','-c','2','-W','3','10.45.1.2'],
                ['ip','netns','exec','ue2','bash','-lc','timeout 3 bash -c "</dev/tcp/10.45.1.2/4433"'],
                ['ip','netns','exec','ue2','bash','-lc','timeout 3 bash -c "</dev/tcp/10.45.1.2/4434"']]
        outs=[]
        for q in checks:
            r=subprocess.run(q,text=True,capture_output=True); outs.append(r.stdout+r.stderr)
            if r.returncode: return {'rc':r.returncode,'stdout':'\n'.join(outs),'stderr':'netcheck failed'}
        return {'rc':0,'stdout':'[PASS] 5G ping and TLS ports 4433/4434 reachable\n','stderr':''}
    if action=='iperfcheck':
        # v2: short, normally-terminating UDP test so preflight can prove the UE1 server log is written and matchable.
        r=subprocess.run(['ip','netns','exec','ue2','iperf3','-c','10.45.1.2','-u','-b','0.1M','-t','3','-J'],text=True,capture_output=True,timeout=60)
        try:
            j=json.loads(r.stdout); cookie=(j.get('start') or {}).get('cookie'); err=j.get('error')
            rx=((j.get('end') or {}).get('sum_received') or {}).get('bits_per_second')
        except Exception as e:
            return {'rc':3,'stdout':r.stdout[-2000:],'stderr':f'iperfcheck: unparseable client JSON: {e!r} {r.stderr[-2000:]}'}
        if r.returncode or err or not cookie:
            return {'rc':3,'stdout':r.stdout[-2000:],'stderr':f'iperfcheck failed rc={r.returncode} err={err!r}'}
        return {'rc':0,'stdout':json.dumps({'cookie':cookie,'client_reported_rx_mbps':(rx or 0)/1e6})+'\n','stderr':''}
    if action=='cleanup': cmd=[os.path.join(ROOTBIN,'era7h_cleanup.sh')]
    elif action=='prepare':
        if len(args)!=4 or not validate_run(args[0]) or args[1] not in CTX or args[2] not in COND or not RATE_RE.fullmatch(str(args[3])): return fail('invalid prepare args')
        cmd=[os.path.join(ROOTBIN,'era7h_prepare.sh'),*map(str,args)]
    elif action=='warmup':
        if len(args)!=4 or not validate_run(args[0]) or args[2] not in COND: return fail('invalid warmup args')
        try: n=int(args[1]); sl=float(args[3]); assert 1<=n<=50 and 0<=sl<=5
        except: return fail('invalid warmup numeric args')
        cmd=[os.path.join(ROOTBIN,'era7h_warmup.sh'),str(args[0]),str(n),str(args[2]),str(sl)]
    elif action=='measure':
        if len(args)!=4 or not validate_run(args[0]) or args[2] not in COND: return fail('invalid measure args')
        try: n=int(args[1]); sl=float(args[3]); assert 1<=n<=500 and 0<=sl<=5
        except: return fail('invalid measure numeric args')
        cmd=[os.path.join(ROOTBIN,'era7h_measure.sh'),str(args[0]),str(n),str(args[2]),str(sl)]
    elif action=='finish':
        if len(args)!=2 or not validate_run(args[0]) or args[1] not in CTX: return fail('invalid finish args')
        cmd=[os.path.join(ROOTBIN,'era7h_finish.sh'),*map(str,args)]
    elif action=='dynamic_load_start':
        if len(args)!=2 or not validate_run(args[0]) or not RATE_RE.fullmatch(str(args[1])): return fail('invalid dynamic_load_start args')
        cmd=[os.path.join(ROOTBIN,'era7h_dynamic_load_start.sh'),str(args[0]),str(args[1])]
    elif action=='dynamic_load_stop':
        if len(args)!=1 or not validate_run(args[0]): return fail('invalid dynamic_load_stop args')
        cmd=[os.path.join(ROOTBIN,'era7h_dynamic_load_stop.sh'),str(args[0])]
    else: return fail('unknown action')
    env=os.environ.copy(); env['ERA7H_BIN']=ROOTBIN
    try:
        r=subprocess.run(cmd,text=True,capture_output=True,env=env,timeout=1200)
        return {'rc':r.returncode,'stdout':r.stdout[-50000:],'stderr':r.stderr[-50000:]}
    except subprocess.TimeoutExpired as e:
        return {'rc':124,'stdout':(e.stdout or '')[-50000:] if isinstance(e.stdout,str) else '','stderr':'worker action timeout'}

def cleanup(*_):
    try: os.unlink(SOCK)
    except FileNotFoundError: pass
    raise SystemExit(0)

def main():
    setup(); signal.signal(signal.SIGINT,cleanup); signal.signal(signal.SIGTERM,cleanup)
    s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.bind(SOCK)
    u=pwd.getpwnam('ue2'); os.chown(SOCK,u.pw_uid,u.pw_gid); os.chmod(SOCK,0o600); s.listen(5)
    print(f'[READY] ERA7H root worker listening {SOCK}; root-owned script snapshot {ROOTBIN}',flush=True)
    while True:
        c,_=s.accept()
        with c:
            data=b''
            while not data.endswith(b'\n') and len(data)<65536:
                x=c.recv(4096)
                if not x: break
                data+=x
            try: req=json.loads(data.decode()); out=execute(req)
            except Exception as e: out={'rc':99,'stdout':'','stderr':repr(e)}
            c.sendall((json.dumps(out)+'\n').encode())
if __name__=='__main__': main()
