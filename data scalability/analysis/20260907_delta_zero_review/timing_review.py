"""Read-only metadata and packet-timing audit of the 45 DELTA zero-load runs."""
from pathlib import Path
import csv
import itertools
import json
from collections import Counter, defaultdict
from datetime import datetime
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DATA = ROOT / 'data'

def metrics(values):
    a = np.asarray(values, dtype=float)
    if not a.size:
        return {'n': 0}
    return {'n': int(a.size), 'mean': float(a.mean()),
            'sd_population': float(a.std()), 'min': float(a.min()),
            'p50': float(np.percentile(a, 50)), 'p95': float(np.percentile(a, 95)),
            'p99': float(np.percentile(a, 99)), 'max': float(a.max())}

def main():
    # Freeze this cohort by run ID; recursive discovery survives later folder organisation.
    paths = sorted((p for p in DATA.rglob('20260907_*') if p.is_dir()
                    and '20260907_013132_404213' <= p.name <= '20260907_020930_401399'),
                   key=lambda p:p.name)
    snapshot = {str(p): (p.stat().st_size, p.stat().st_mtime_ns)
                for d in paths for p in d.iterdir() if p.is_file()}
    rows, timing, pending, mismatches = [], [], [], []
    combos, batches = defaultdict(list), defaultdict(list)
    all_main_counts, all_full_counts = Counter(), Counter()
    all_main_errors, all_full_errors = Counter(), Counter()
    all_pc, all_host, joint_extremes = [], [], []
    main_status, full_status, main_reasons, full_reasons = Counter(), Counter(), Counter(), Counter()
    provenance = defaultdict(Counter)
    error_names = ['outer_crc_errors', 'sequence_gap_events', 'lost_frames',
                   'duplicate_frames', 'out_of_order_frames', 'format_errors',
                   'inner_crc_errors', 'delta_base_mismatches']
    for d in paths:
        if not (d/'summary.json').is_file():
            pending.append({'run_id':d.name,'reason':'summary_missing'}); continue
        s = json.loads((d/'summary.json').read_text(encoding='utf-8'))
        md, ma, fu = s['metadata'], s['scopes']['main'], s['scopes']['full_run']
        combo = '+'.join(f'M{i}' for i in md['target_modules'])
        seq_index = len(rows) + 1
        combos[combo].append(d.name)
        batches[md.get('batch_id', '')].append(d.name)
        if not s.get('completed_requested_duration'):
            pending.append({'run_id':d.name,'reason':s.get('reason')})
        main_status[ma['status']] += 1; full_status[fu['status']] += 1
        main_reasons.update(ma['review_reasons']); full_reasons.update(fu['review_reasons'])
        all_main_counts.update(ma['counts']); all_full_counts.update(fu['counts'])
        for scope, total in [(ma, all_main_errors), (fu, all_full_errors)]:
            for name in error_names:
                total[name] += scope['session_counter_delta_at_packet_observation'].get(name, 0)
        files = md.get('local_provenance', {}).get('files', {})
        for name, info in files.items(): provenance[name][info.get('sha256','MISSING')] += 1
        row = {'run_id':d.name, 'started_at':s['started_at'], 'chronological_order':seq_index,
               'combination':combo,'N':len(md['target_modules']), 'mode':md['target_mode'],
               'condition':md['condition'],'target_hz':md['target_hz'],
               'spi_setting_hz':md['spi_setting_hz'],'delta_threshold':md['delta_threshold'],
               'observed_mode_at_record':md.get('observed_mode_at_record'),
               'block':md.get('block'),'repeat':md.get('repeat'),
               'batch_id':md.get('batch_id'),'batch_repeat_index':md.get('batch_repeat_index'),
               'batch_repeat_count':md.get('batch_repeat_count'),
               'batch_recording_method':md.get('batch_recording_method'),
               'duration_seconds':s['duration_seconds'],'main_duration_seconds':ma['actual_duration_seconds'],
               'requested_duration_seconds':s['requested_duration_seconds'], 'settle_seconds':s['settle_seconds'],
               'completed':s['completed_requested_duration'], 'main_status':ma['status'], 'full_status':fu['status'],
               'deployment_confirmed':md.get('deployment_confirmed'),
               'board_identity_handling':md.get('board_identity_handling'),
               'physical_modules_to_slots':md.get('physical_modules_to_slots'),
               'metadata_warnings':s.get('metadata_warnings'),
               'main_packet_rate_Hz':ma['valid_outer_packet_rate_Hz'],
               'main_raw_boundary_warnings':ma.get('raw_boundary_warnings'),
               'main_missing_valid_expected_updates':ma['counts'].get('missing_valid_expected_updates',0)}
        rows.append(row)
        with (d/'packet_log.csv').open(encoding='utf-8-sig',newline='') as f:
            packets = [p for p in csv.DictReader(f) if p['main_window']=='True'
                       and p['outer_crc_ok']=='True']
        if len(packets) != ma['counts']['valid_outer_packets']:
            mismatches.append({'run_id':d.name,'packet_count':len(packets),
                               'summary_count':ma['counts']['valid_outer_packets']})
        pc=np.array([float(p['elapsed_s'])*1000 for p in packets])
        host=np.array([int(p['host_ms']) for p in packets],dtype=np.int64)
        seq=np.array([int(p['packet_sequence']) for p in packets],dtype=np.int64)
        dp=np.diff(pc); dh=np.diff(host)&0xFFFFFFFF; ds=np.diff(seq)&0xFFFFFFFF
        all_pc.extend(dp); all_host.extend(dh)
        ti={'run_id':d.name,'combination':combo,'N':row['N'],'packets':len(packets),
            'pc_completion_dt_ms':metrics(dp),'host_enqueue_dt_ms':metrics(dh),
            'pc_dt_zero_count':int(np.count_nonzero(dp==0)),
            'pc_dt_negative_count':int(np.count_nonzero(dp<0)),
            'pc_dt_gt_20ms_count':int(np.count_nonzero(dp>20)),
            'pc_dt_gt_100ms_count':int(np.count_nonzero(dp>100)),
            'host_dt_gt_20ms_count':int(np.count_nonzero(dh>20)),
            'host_dt_gt_100ms_count':int(np.count_nonzero(dh>100)),
            'sequence_step_not_one_count':int(np.count_nonzero(ds!=1)),
            'observed_pc_span_ms':float(pc[-1]-pc[0]),
            'observed_host_span_ms':int((host[-1]-host[0])&0xFFFFFFFF),
            'pc_packet_span_rate_Hz':float((len(pc)-1)*1000/(pc[-1]-pc[0])),
            'host_packet_span_rate_Hz':float((len(host)-1)*1000/((host[-1]-host[0])&0xFFFFFFFF))}
        for j in np.argsort(dp)[-3:]:
            joint_extremes.append({'run_id':d.name,'packet_sequence':int(seq[j+1]),
                                  'pc_dt_ms':float(dp[j]),'host_dt_ms':int(dh[j]),
                                  'outer_sequence_step':int(ds[j])})
        timing.append(ti)
    expected={'+'.join(f'M{i}' for i in c) for n in range(1,5) for c in itertools.combinations(range(4),n)}
    invalid_batch=[]
    by_id={r['run_id']:r for r in rows}
    for bid, ids in batches.items():
        rr=[by_id[i] for i in ids]
        if len(rr)!=3 or [r['batch_repeat_index'] for r in rr]!=[1,2,3] or len({r['combination'] for r in rr})!=1:
            invalid_batch.append(bid)
    summary={'created_at':datetime.now().astimezone().isoformat(),'input_root_at_audit':str(DATA),
             'selected_directory_count':len(paths),'completed_summary_count':len(rows),'pending_or_incomplete':pending,
             'expected_combinations':sorted(expected),'observed_combinations':dict(combos),
             'missing_combinations':sorted(expected-set(combos)),
             'unexpected_combinations':sorted(set(combos)-expected),
             'records_by_N':dict(Counter(r['N'] for r in rows)),
             'batch_count':len(batches),'invalid_batches':invalid_batch,
             'uniform_metadata':{k:dict(Counter(str(r[k]) for r in rows)) for k in
                 ['mode','condition','target_hz','spi_setting_hz','delta_threshold','observed_mode_at_record',
                  'block','repeat','batch_repeat_count','batch_recording_method',
                  'requested_duration_seconds','settle_seconds','deployment_confirmed','board_identity_handling']},
             'provenance_hash_counts':dict(provenance),
             'full_status_counts':dict(full_status),'main_status_counts':dict(main_status),
             'full_review_reason_counts':dict(full_reasons),'main_review_reason_counts':dict(main_reasons),
             'full_counts':dict(all_full_counts),'main_counts':dict(all_main_counts),
             'full_session_error_deltas':dict(all_full_errors),'main_session_error_deltas':dict(all_main_errors),
             'packet_count_mismatches':mismatches,'records':rows,
             'interpretation':[
                 'Three consecutive capture windows per unchanged setup are temporal repeats, not three independent reconnect/reassembly blocks.',
                 'Slot labels identify communicating CS/IRQ positions; no MCU board UID or physical-board mapping was recorded.',
                 'Local firmware/PC hashes identify local files only; all operator deployment confirmations are false.',
                 'SPI 10 MHz and threshold 8 are local configuration metadata, not hardware readback or measured timing.',
                 'PC completion times can repeat for buffered packets. host_ms is Teensy millis() when constructing/enqueuing MUL1, not SPI SCK or ADC scan timestamp.',
                 'Packet timing alone cannot establish unstable SPI clocks or physical-scan loss.']}
    pooled={'pc_completion_dt_ms':metrics(all_pc),'host_enqueue_dt_ms':metrics(all_host),
            'largest_pc_gaps':sorted(joint_extremes,key=lambda x:x['pc_dt_ms'],reverse=True)[:12],
            'total_pc_dt_zero_count':sum(t['pc_dt_zero_count'] for t in timing),
            'total_pc_dt_gt_100ms_count':sum(t['pc_dt_gt_100ms_count'] for t in timing),
            'total_host_dt_gt_100ms_count':sum(t['host_dt_gt_100ms_count'] for t in timing),
            'total_sequence_step_not_one_count':sum(t['sequence_step_not_one_count'] for t in timing),
            'per_run':timing}
    changed=[p for p,v in snapshot.items() if not Path(p).exists() or
             (Path(p).stat().st_size,Path(p).stat().st_mtime_ns)!=v]
    summary['input_files_changed_during_review']=changed
    if changed: raise RuntimeError('Input files changed during audit: '+repr(changed))
    OUT.mkdir(exist_ok=True)
    (OUT/'coverage_review.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    (OUT/'timing_summary.json').write_text(json.dumps(pooled,indent=2)+'\n',encoding='utf-8')
    flat=[]
    for t in timing:
        flat.append({k:v for k,v in t.items() if not isinstance(v,dict)} | {
            f'{kind}_{k}':v for kind in ['pc_completion_dt_ms','host_enqueue_dt_ms'] for k,v in t[kind].items()})
    with (OUT/'timing_per_run.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
    print(json.dumps({k:v for k,v in summary.items() if k not in ['records','provenance_hash_counts','observed_combinations']},indent=2))
    print(json.dumps({k:v for k,v in pooled.items() if k!='per_run'},indent=2))

if __name__=='__main__': main()
