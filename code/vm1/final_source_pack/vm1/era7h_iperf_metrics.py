#!/usr/bin/env python3
"""ERA7H FINAL: receiver-side UDP metrics from the UE1 iperf3 server object (matched by cookie).

Two views are written to iperf_summary.json:
  whole_*  : the entire load period (prepare -> finish), from server end.sum_received
  window_* : only server 1-s intervals lying inside the measured-handshake window.
The window is located with UE2-clock offsets (measured run start/end minus load start), so no cross-host
clock synchronisation is assumed. The offset ignores iperf control-connection setup time (typically one or
two RTTs), which is negligible for a constant-rate load but is recorded as a caveat.
"""
import argparse, json, statistics, sys

ap = argparse.ArgumentParser()
ap.add_argument('--server-json', required=True)
ap.add_argument('--client-summary', required=True)
ap.add_argument('--load-start-epoch-file', required=True)
ap.add_argument('--bench-meta', required=True)
ap.add_argument('--out', required=True)
a = ap.parse_args()

srv = json.load(open(a.server_json))
cli = json.load(open(a.client_summary))
load_start = float(open(a.load_start_epoch_file).read().strip())
bm = json.load(open(a.bench_meta))
rel_lo = bm['run_start_epoch'] - load_start
rel_hi = bm['run_end_epoch'] - load_start

if (srv.get('start') or {}).get('cookie') != cli.get('cookie'):
    sys.exit('[FAIL] server/client cookie mismatch')
err = (srv.get('error') or '').strip()
if err not in ('', 'the client has terminated'):
    sys.exit(f'[FAIL] unexpected iperf server error: {err}')

ints = [x.get('sum') or {} for x in (srv.get('intervals') or [])]
win = [s for s in ints if s.get('start', -1) >= rel_lo and s.get('end', 1e18) <= rel_hi]
e = (srv.get('end') or {}).get('sum_received') or (srv.get('end') or {}).get('sum') or {}

def tot(rows, k):
    return sum((r.get(k) or 0) for r in rows)

w_secs = tot(win, 'seconds')
w_pk = tot(win, 'packets'); w_lost = tot(win, 'lost_packets')
w_jit = [r['jitter_ms'] for r in win if isinstance(r.get('jitter_ms'), (int, float))]
out = {
    'cookie': cli.get('cookie'),
    'server_error': err,
    'server_interval_count': len(ints),
    'sender_mbps': cli.get('sender_mbps'),
    'whole_receiver_mbps': (e.get('bits_per_second') or 0) / 1e6,
    'whole_lost_percent': e.get('lost_percent'),
    'whole_jitter_ms': e.get('jitter_ms'),
    'whole_packets': e.get('packets'),
    'whole_lost_packets': e.get('lost_packets'),
    'whole_seconds': e.get('seconds'),
    'window_rel_start_s': rel_lo,
    'window_rel_end_s': rel_hi,
    'window_interval_count': len(win),
    'window_receiver_mbps': (tot(win, 'bytes') * 8 / w_secs / 1e6) if w_secs > 0 else None,
    'window_lost_percent': (100.0 * w_lost / w_pk) if w_pk > 0 else None,
    'window_jitter_ms_median': statistics.median(w_jit) if w_jit else None,
    'window_packets': w_pk,
    'window_lost_packets': w_lost,
    'caveat': 'window located by UE2-clock offsets; iperf control setup delay not subtracted',
}
# Backward-compatible keys used by the v1 analyzer: receiver_* now = measured-window, server-side.
out['receiver_mbps'] = out['window_receiver_mbps']
out['lost_percent'] = out['window_lost_percent']
out['jitter_ms'] = out['window_jitter_ms_median']
out['interval_count'] = out['window_interval_count']
json.dump(out, open(a.out, 'w'), indent=2, sort_keys=True)
print('[PASS] iperf server-side summary', json.dumps({k: out[k] for k in ('window_interval_count', 'window_receiver_mbps', 'window_lost_percent', 'window_jitter_ms_median', 'whole_receiver_mbps')}))
