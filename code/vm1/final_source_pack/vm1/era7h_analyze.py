#!/usr/bin/env python3
# ERA7H FINAL analyzer: run-level and cell-level summaries + attempt accounting. Paired within-block tests: era7h_paired_stats.py
import argparse,csv,json,glob,os,re,statistics,math

def pct(v,p):
    if not v:return None
    x=sorted(v); k=(len(x)-1)*p; lo=math.floor(k); hi=math.ceil(k)
    return x[lo] if lo==hi else x[lo]*(hi-k)+x[hi]*(k-lo)
def fmean(v): return statistics.mean(v) if v else None
def sd(v): return statistics.stdev(v) if len(v)>1 else 0.0
def med(v): return statistics.median(v) if v else None
def iqr(v): return (pct(v,.75)-pct(v,.25)) if v else None
# 95% t critical, df 1..30; normal beyond.
T95={1:12.706,2:4.303,3:3.182,4:2.776,5:2.571,6:2.447,7:2.365,8:2.306,9:2.262,10:2.228,11:2.201,12:2.179,13:2.160,14:2.145,15:2.131,16:2.120,17:2.110,18:2.101,19:2.093,20:2.086,21:2.080,22:2.074,23:2.069,24:2.064,25:2.060,26:2.056,27:2.052,28:2.048,29:2.045,30:2.042}
def ci95(v):
    if len(v)<2:return (None,None)
    m=fmean(v); se=sd(v)/math.sqrt(len(v)); t=T95.get(len(v)-1,1.96); return (m-t*se,m+t*se)
def num(x):
    try:return float(x)
    except:return None

def ping_metrics(path):
    if not os.path.exists(path): return (None,None,None)
    vals=[]
    for line in open(path,errors='ignore'):
        m=re.search(r'time[=<]([0-9.]+)\s*ms',line)
        if m: vals.append(float(m.group(1)))
    loss=None
    txt=open(path,errors='ignore').read()
    m=re.search(r'([0-9.]+)% packet loss',txt)
    if m: loss=float(m.group(1))
    return med(vals),fmean(vals),loss

def audit_metrics(path):
    vals=[]; skew=[]; age=[]
    if not os.path.exists(path):return (None,None,None)
    for line in open(path):
        try:j=json.loads(line); r=j.get('ran_context') or {}
        except:continue
        if isinstance(r.get('decision_value'),(int,float)): vals.append(float(r['decision_value']))
        if isinstance(r.get('kpm_pair_skew_s'),(int,float)): skew.append(float(r['kpm_pair_skew_s']))
        if isinstance(r.get('kpm_pair_age_s'),(int,float)): age.append(float(r['kpm_pair_age_s']))
    return med(vals),med(skew),med(age)

def audit_policy_metrics(path):
    rows=[]
    if not os.path.exists(path): return (None,'','','')
    for line in open(path):
        try:
            j=json.loads(line)
            if str(j.get('ue','ue2'))=='ue2': rows.append(j)
        except: pass
    if not rows: return (None,'','','')
    ok=[r for r in rows if r.get('kem_result')=='accepted' and r.get('sig_result')=='accepted']
    pct=100*len(ok)/len(rows)
    modes=';'.join(sorted({str(r.get('policy_mode','')) for r in rows if r.get('policy_mode') is not None}))
    kb=';'.join(sorted({str(r.get('kem_bound_by','')) for r in rows if r.get('kem_bound_by') is not None}))
    sb=';'.join(sorted({str(r.get('sig_bound_by','')) for r in rows if r.get('sig_bound_by') is not None}))
    return pct,modes,kb,sb

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('root'); a=ap.parse_args(); root=os.path.abspath(a.root); out=os.path.join(root,'processed'); os.makedirs(out,exist_ok=True)
    rows=[]
    for d in sorted(glob.glob(os.path.join(root,'raw','*'))):
        if not os.path.isfile(os.path.join(d,'VALID.ok')): continue
        m=json.load(open(os.path.join(d,'metadata.json'))); c=list(csv.DictReader(open(os.path.join(d,'ue2','crypto_log_measured.csv'))))
        ok=[x for x in c if x['result']=='ok']; lat=[float(x['client_elapsed_ms']) for x in ok]; u=[num(x['user_cpu_s']) for x in ok]; u=[x for x in u if x is not None]; sy=[num(x['sys_cpu_s']) for x in ok]; sy=[x for x in sy if x is not None]; rss=[num(x['max_rss_kb']) for x in ok]; rss=[x for x in rss if x is not None]
        ps=json.load(open(os.path.join(d,'pcap_summary.json'))) if os.path.exists(os.path.join(d,'pcap_summary.json')) else {}
        prtt,pmean,ploss=ping_metrics(os.path.join(d,'ue2','ping.txt'))
        iv={}
        ip=os.path.join(d,'iperf_summary.json')   # v2: server-side (UE1) receiver data
        if os.path.exists(ip): iv=json.load(open(ip))
        hs=json.load(open(os.path.join(d,'host_state.json'))) if os.path.exists(os.path.join(d,'host_state.json')) else {}
        def hget(k,f): return (hs.get(k) or {}).get(f)
        bm=json.load(open(os.path.join(d,'ue2','bench_measured_meta.json'))) if os.path.exists(os.path.join(d,'ue2','bench_measured_meta.json')) else {}
        gate=json.load(open(os.path.join(d,'context_gate_after.json')))
        audit_path=os.path.join(d,'era_audit_measured.jsonl')
        adv,sk,age=audit_metrics(audit_path); policy_pct,policy_mode,kem_bound,sig_bound=audit_policy_metrics(audit_path)
        rows.append({
          'run':os.path.basename(d),'experiment':m['experiment'],'block':m['block'],'context':m['context'],'condition':m['condition'],
          'independent_run_n':1,'handshakes':len(ok),'kem':ok[0]['req_kem'] if ok else '', 'sig':ok[0]['req_sig'] if ok else '',
          'conn_latency_median_ms':med(lat),'conn_latency_mean_ms':fmean(lat),'conn_latency_sd_ms':sd(lat),'conn_latency_p95_ms':pct(lat,.95),
          'cpu_user_s_mean':fmean(u),'cpu_sys_s_mean':fmean(sy),'max_rss_kb_median':med(rss),
          'capture_bytes_per_hs':ps.get('bytes_per_handshake_mean'),'packets_per_hs':ps.get('packets_per_handshake_mean'),
          'flow_duration_median_ms':ps.get('flow_duration_ms_median'),'tcp_syn_rtt_median_ms':ps.get('tcp_syn_rtt_ms_median'),'tcp_retrans_total':ps.get('tcp_retransmissions_total'),
          'ping_rtt_median_ms':prtt,'ping_rtt_mean_ms':pmean,'ping_loss_pct':ploss,
          'udp_receiver_mbps':iv.get('window_receiver_mbps'),'udp_sender_mbps':iv.get('sender_mbps'),'udp_loss_pct':iv.get('window_lost_percent'),'udp_jitter_ms':iv.get('window_jitter_ms_median'),
          'udp_window_intervals':iv.get('window_interval_count'),'udp_whole_receiver_mbps':iv.get('whole_receiver_mbps'),
          'tcpdump_dropped':bm.get('tcpdump_dropped_kernel'),'attempt':m.get('attempt',1),
          'ue2_temp_after_c':hget('ue2_after','temp_c'),'ue1_temp_after_c':hget('ue1_after','temp_c'),
          'ue2_throttled_now':any(bool(hget(k,'throttled_now')) for k in ('ue2_before','ue2_after')),
          'ue1_throttled_now':any(bool(hget(k,'throttled_now')) for k in ('ue1_before','ue1_after')),
          'ue2_governor':hget('ue2_after','governor'),'ue1_governor':hget('ue1_after','governor'),
          'ran_gate_decision_value':gate.get('decision_value'),'audit_decision_value_median':adv,'kpm_pair_skew_median_s':sk,'kpm_pair_age_median_s':age,
          'policy_accept_pct':policy_pct,'policy_mode_audit':policy_mode,'kem_bound_by_audit':kem_bound,'sig_bound_by_audit':sig_bound
        })
    if not rows: raise SystemExit('no VALID runs found')
    runf=os.path.join(out,'run_summary.csv')
    with open(runf,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    metrics=['conn_latency_median_ms','conn_latency_p95_ms','capture_bytes_per_hs','packets_per_hs','flow_duration_median_ms','tcp_syn_rtt_median_ms','ping_rtt_median_ms','udp_receiver_mbps','udp_loss_pct','udp_jitter_ms','cpu_user_s_mean','max_rss_kb_median','ran_gate_decision_value','ue2_temp_after_c']
    groups={}
    for r in rows: groups.setdefault((r['experiment'],r['context'],r['condition']),[]).append(r)
    cell=[]
    for key,rs in sorted(groups.items()):
        z={'experiment':key[0],'context':key[1],'condition':key[2],'n_runs':len(rs),'handshakes_total':sum(int(x['handshakes']) for x in rs)}
        for k in metrics:
            v=[num(x[k]) for x in rs]; v=[x for x in v if x is not None]
            lo,hi=ci95(v)
            z[k+'_mean']=fmean(v); z[k+'_sd']=sd(v) if v else None; z[k+'_median']=med(v); z[k+'_iqr']=iqr(v); z[k+'_ci95_lo']=lo; z[k+'_ci95_hi']=hi
        cell.append(z)
    cellf=os.path.join(out,'cell_summary.csv')
    fields=[]
    for z in cell:
        for k in z:
            if k not in fields: fields.append(k)
    with open(cellf,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(cell)
    # v2: attempt / quarantine accounting per cell (report this in the paper alongside n_runs)
    att=os.path.join(root,'meta','attempts.csv'); arows=list(csv.DictReader(open(att))) if os.path.exists(att) else []
    acc={}
    for r in arows:
        k=(r['context'],r['condition']); z=acc.setdefault(k,{'context':k[0],'condition':k[1],'valid':0,'failed_attempts':0,'interrupted':0,'reasons':[]})
        if r['outcome']=='valid': z['valid']+=1
        elif r['outcome']=='failed': z['failed_attempts']+=1; z['reasons'].append(r['reason'][:120])
        else: z['interrupted']+=1
    attf=os.path.join(out,'attempt_summary.csv')
    with open(attf,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['context','condition','valid','failed_attempts','interrupted','reasons']); w.writeheader()
        for k in sorted(acc): z=dict(acc[k]); z['reasons']=' | '.join(z['reasons']); w.writerow(z)
    tot_f=sum(z['failed_attempts'] for z in acc.values()); tot_v=sum(z['valid'] for z in acc.values())
    thr=sum(1 for r in rows if r['ue2_throttled_now'] or r['ue1_throttled_now'])
    print('[PASS] wrote',runf); print('[PASS] wrote',cellf); print('[PASS] wrote',attf)
    print(f'[NOTE] attempts: valid={tot_v} failed={tot_f}; runs with active Pi throttling={thr}/{len(rows)}')
    print('[NOTE] n_runs is the independent replicate count; handshakes_total is nested observations, not independent n.')
if __name__=='__main__': main()
