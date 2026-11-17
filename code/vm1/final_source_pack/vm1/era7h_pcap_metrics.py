#!/usr/bin/env python3
import argparse,subprocess,csv,json,statistics,os,sys
ap=argparse.ArgumentParser(); ap.add_argument('--pcap',required=True); ap.add_argument('--crypto-csv',required=True); ap.add_argument('--outdir',required=True); a=ap.parse_args()
os.makedirs(a.outdir,exist_ok=True)
cmd=['tshark','-r',a.pcap,'-Y','tcp','-T','fields','-E','separator=/t','-E','occurrence=f',
     '-e','frame.time_epoch','-e','frame.len','-e','ip.src','-e','ip.dst','-e','tcp.stream','-e','tcp.flags.syn','-e','tcp.flags.ack','-e','tcp.analysis.retransmission']
r=subprocess.run(cmd,text=True,capture_output=True)
if r.returncode: print(r.stderr,file=sys.stderr); raise SystemExit(r.returncode)
streams={}
# v2: tshark >= 4.x prints boolean fields as True/False, 3.x as 1/0. Accept both.
TRUE={'1','true','True','TRUE'}
def is_true(x): return x.strip() in TRUE
def is_flag(x):  # FT_NONE analysis flags: present (any non-false text) vs empty
    x=x.strip(); return bool(x) and x not in ('0','False','false','FALSE')
for line in r.stdout.splitlines():
    p=line.split('\t'); p += ['']*(8-len(p))
    ts_s,l_s,src,dst,st,syn,ack,retr=p[:8]
    if not st or not ts_s or not l_s: continue
    try: ts=float(ts_s); ln=int(float(l_s)); st=int(st)
    except Exception: continue
    d=streams.setdefault(st,{'times':[],'bytes':0,'packets':0,'retrans':0,'syn':None,'synack':None})
    d['times'].append(ts); d['bytes']+=ln; d['packets']+=1
    if is_flag(retr): d['retrans']+=1
    if is_true(syn) and not is_true(ack) and src=='10.45.1.3' and d['syn'] is None: d['syn']=ts
    if is_true(syn) and is_true(ack) and src=='10.45.1.2' and d['synack'] is None: d['synack']=ts
crypto=[x for x in csv.DictReader(open(a.crypto_csv)) if x.get('result')=='ok']
sids=sorted(streams)
if len(sids)!=len(crypto):
    print(f'[FAIL] tcp_streams={len(sids)} successful_crypto_rows={len(crypto)}',file=sys.stderr); raise SystemExit(3)
rows=[]
for i,(sid,c) in enumerate(zip(sids,crypto),1):
    d=streams[sid]; dur=(max(d['times'])-min(d['times']))*1000 if d['times'] else 0
    rtt=(d['synack']-d['syn'])*1000 if d['syn'] is not None and d['synack'] is not None else None
    rows.append({'index':i,'tcp_stream':sid,'req_kem':c['req_kem'],'req_sig':c['req_sig'],
                 'capture_bytes':d['bytes'],'packet_count':d['packets'],'flow_duration_ms':round(dur,3),
                 'tcp_syn_rtt_ms':round(rtt,3) if rtt is not None else '', 'tcp_retransmissions':d['retrans']})
outcsv=os.path.join(a.outdir,'pcap_stream_metrics.csv')
with open(outcsv,'w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=rows[0].keys() if rows else []); w.writeheader(); w.writerows(rows)
def med(k):
    v=[float(x[k]) for x in rows if x[k] not in ('',None)]; return statistics.median(v) if v else None
summary={'streams':len(rows),'total_capture_bytes':sum(x['capture_bytes'] for x in rows),'total_packets':sum(x['packet_count'] for x in rows),
         'bytes_per_handshake_mean':statistics.mean([x['capture_bytes'] for x in rows]) if rows else None,
         'packets_per_handshake_mean':statistics.mean([x['packet_count'] for x in rows]) if rows else None,
         'flow_duration_ms_median':med('flow_duration_ms'),'tcp_syn_rtt_ms_median':med('tcp_syn_rtt_ms'),
         'tcp_retransmissions_total':sum(x['tcp_retransmissions'] for x in rows)}
missing=[x['index'] for x in rows if x['tcp_syn_rtt_ms'] in ('',None)]
summary['tcp_syn_rtt_missing']=len(missing)
json.dump(summary,open(os.path.join(a.outdir,'pcap_summary.json'),'w'),indent=2,sort_keys=True)
if missing:
    print(f'[FAIL] TCP SYN/SYN-ACK not found for handshakes {missing[:10]} (n={len(missing)}); refusing a silent null RTT',file=sys.stderr); raise SystemExit(4)
print('[PASS]',json.dumps(summary,sort_keys=True))
