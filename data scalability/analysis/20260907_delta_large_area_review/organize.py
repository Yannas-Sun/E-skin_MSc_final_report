"""Organize exactly three completed large-area captures; preserve all file bytes."""
from collections import Counter
from datetime import datetime
from pathlib import Path
import csv
import hashlib
import json
import shutil
import statistics
import sys

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data'
IDS = ('20260907_040621_371357', '20260907_040701_400114', '20260907_040741_429011')
ORIGINAL = {'mul1_raw.bin','packet_log.csv','module_log.csv','events.jsonl','summary.json','experiment_log.md'}
GROUP = 'DELTA/Dynamic_load/N=1/200Hz/M1/Large_area'

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))

def write_csv(path, rows, fields=None):
    fields = fields or list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def prepare():
    assert not (HERE/'organization_plan.json').exists(), 'Keep the existing fixed snapshot'
    files, runs, index, summaries = [], [], [], []
    for run_id in IDS:
        source = DATA/run_id
        s = json.loads((source/'summary.json').read_text(encoding='utf-8'))
        m, p = s['metadata'], s['scopes']['main']; summaries.append(s)
        assert s['run_id']==run_id and s['schema_version']==2 and s['completed_requested_duration']
        assert m['target_mode']=='DELTA' and m['target_modules']==[1] and m['condition']=='large_area' and m['load_layers']=='both'
        assert m['target_hz']==200 and m['spi_setting_hz']==10000000 and m['delta_threshold']==8
        assert s['settle_seconds']==10 and s['requested_duration_seconds']==40
        relative=f'{GROUP}/Repeat_{m["repeat"]}'
        target=DATA/relative
        assert not target.exists()
        entries=[]
        for path in sorted(source.iterdir()):
            assert path.is_file() and not path.is_symlink()
            item=dict(run_id=run_id,file_name=path.name,old_path=str(path.resolve()),new_path=str((target/path.name).resolve()),
                old_relative_path=f'{run_id}/{path.name}',new_relative_path=f'{relative}/{path.name}',
                bytes=path.stat().st_size,sha256=sha(path),source_review=HERE.name,
                file_kind='original_measurement' if path.name in ORIGINAL else 'derived_plot')
            entries.append(item);files.append(item)
        assert ORIGINAL.issubset({e['file_name'] for e in entries})
        assert sha(source/'mul1_raw.bin')==s['raw_sha256']
        runs.append(dict(run_id=run_id,source=str(source.resolve()),destination=str(target.resolve()),files=entries))
        rows=[r for r in read_csv(source/'packet_log.csv') if r['main_window']=='True' and r['outer_crc_ok']=='True']
        pc=[(float(b['elapsed_s'])-float(a['elapsed_s']))*1000 for a,b in zip(rows,rows[1:])]
        host=[(int(b['host_ms'])-int(a['host_ms']))%(2**32) for a,b in zip(rows,rows[1:])]
        eligible=p['status']=='PASS' and not p['review_reasons']
        index.append(dict(run_id=run_id,started_at=s['started_at'],mode='DELTA',condition='large_area',N=1,target_hz=200,
            modules='M1',block=m['block'],batch_id=m['batch_id'],repeat=m['repeat'],old_relative_path=run_id,new_relative_path=relative,
            duration_s=s['duration_seconds'],main_duration_s=p['actual_duration_seconds'],main_packets=p['counts']['valid_outer_packets'],
            main_status=p['status'],full_status=s['scopes']['full_run']['status'],full_review_reasons=';'.join(s['scopes']['full_run']['review_reasons']),
            main_rate_Hz=p['valid_outer_packet_rate_Hz'],main_Lmean_B=p['Lmean_valid_packet_B'],main_packet_Mbit_s=p['packet_completion_Mbit_per_s'],
            main_raw_arrival_Mbit_s=p['raw_arrival_Mbit_per_s'],main_K_ESKD_mean=p['K_ESKD_pooled']['mean'],main_q_ESKF=p['q_ESKF'],
            main_ESKF_count=p['counts'].get('ESKF',0),main_ESKD_count=p['counts'].get('ESKD',0),
            source_local_firmware=m['local_provenance']['firmware_variant'],deployment_confirmed=m['deployment_confirmed'],
            main_eligible=eligible,main_review_reasons=';'.join(p['review_reasons']),
            main_outer_crc_errors=p['counts'].get('outer_crc_error',0),main_outer_missing_sequence_numbers=p['counts'].get('outer_missing_sequence_numbers',0),
            main_missing_valid_expected_updates=p['counts'].get('missing_valid_expected_updates',0),main_interior_unassigned_raw_bytes=p['counts'].get('interior_unassigned_raw_bytes',0),
            source_review=HERE.name,timing_note=f'PC maximum completion gap {max(pc):.4f} ms; bridge maximum enqueue gap {max(host)} ms. Do not infer physical scan loss or SCK instability.',
            replacement_batch_id='',primary_matrix_selected=eligible,selection_reason='original_complete_three_window_batch',
            pc_max_completion_gap_ms=max(pc),host_max_enqueue_gap_ms=max(host),host_packet_span_rate_Hz=(len(rows)-1)*1000/sum(host),
            independent_raw_audit='pending',load_layers=m['load_layers'],
            load_description='large_area; both layers; area/force/rhythm not recorded'))
    assert {r['repeat'] for r in index}=={'1','2','3'} and len({r['batch_id'] for r in index})==1
    for root in (DATA,DATA/'DELTA'):
        backup=HERE/'before_catalog'/('root' if root==DATA else 'DELTA');backup.mkdir(parents=True,exist_ok=True)
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in ('.csv','.md'): shutil.copy2(path,backup/path.name)
    # Keep FULL and zero-load-only views byte-identical during this extension.
    protected=[]
    for folder in (DATA/'FULL', DATA/'DELTA/Zero_load'):
        for path in folder.iterdir():
            if path.is_file() and path.suffix.lower() in ('.csv','.md'):
                protected.append({'path':str(path.resolve()),'sha256':sha(path)})
    (HERE/'protected_views.json').write_text(json.dumps(protected,indent=2),encoding='utf-8')
    plan=dict(prepared_at=datetime.now().astimezone().isoformat(),data_root=str(DATA.resolve()),runs=runs,total_runs=3,
              total_files=len(files),total_bytes=sum(f['bytes'] for f in files),original_files=sum(f['file_kind']=='original_measurement' for f in files),
              rule=GROUP+'/Repeat_<original repeat>',original_file_content_policy='preserve all bytes and embedded old paths')
    (HERE/'organization_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    (HERE/'summary_snapshot.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
    write_csv(HERE/'run_index.csv',index);write_csv(HERE/'path_map.csv',files)
    print(json.dumps({k:plan[k] for k in ('total_runs','total_files','total_bytes','original_files')}))

def finish():
    v=json.loads((HERE/'organization_verification.json').read_text(encoding='utf-8-sig'))
    assert v['status']=='completed' and v['verified_runs']==3
    index=read_csv(HERE/'run_index.csv')
    for number,r in enumerate(index):
        assert r['main_status']=='PASS'
        r['independent_raw_audit']='CHECK_inner_sequence_discontinuity'
        r['main_eligible']=False
        r['primary_matrix_selected']=False
        r['selection_reason']='excluded_pending_independent_inner_sequence_review; original recorder PASS preserved'
        r['independent_review_reasons']=('inner_sequence_reset_to_2_on_ESKF' if number<2 else 'inner_sequence_forward_gaps_on_ESKF')
        r['main_inner_sequence_events']=(1,11,2)[number]
    assert (HERE/'raw_audit.json').is_file(), 'Independent audit must finish first'
    stats={k:'' for k in read_csv(HERE/'before_catalog/root/group_statistics.csv')[0]}
    stats.update(mode='DELTA',condition='large_area',modules='M1',N=1,target_hz=200,
        temporal_repeat_n=3,recorded_repeat_n=3,eligible_repeat_n=0,review_required_n=3,batch_n=1,recorded_batch_n=1,
        batch_id=index[0]['batch_id'],primary_matrix_selected_n=0,statistic_run_ids=';'.join(IDS),review_required_run_ids=';'.join(IDS),
        repeat_interpretation='temporal windows; not independent setup blocks',
        statistics_basis='DIAGNOSTIC ONLY: three windows with independent inner-sequence CHECK; original recorder PASS preserved',
        main_packets_total=sum(int(r['main_packets']) for r in index),main_window_seconds_total=sum(float(r['main_duration_s']) for r in index),
        load_layers='both')
    for field,source in [('rate_Hz','main_rate_Hz'),('packet_Mbit_s','main_packet_Mbit_s'),('raw_arrival_Mbit_s','main_raw_arrival_Mbit_s'),
                         ('Lmean_B','main_Lmean_B'),('K_ESKD','main_K_ESKD_mean'),('q_ESKF','main_q_ESKF')]:
        values=[float(r[source]) for r in index]
        stats[field+'_mean']=statistics.mean(values); stats[field+'_sample_sd']=statistics.stdev(values);stats[field+'_known_n']=3
    stats['q_ESKF_pct_mean']=stats['q_ESKF_mean']*100;stats['q_ESKF_pct_sample_sd']=stats['q_ESKF_sample_sd']*100;stats['q_ESKF_pct_known_n']=3
    effective=[(float(r['main_Lmean_B'])-40-84)/2 for r in index]
    stats.update(K_effective_mean=statistics.mean(effective),K_effective_sample_sd=statistics.stdev(effective),K_effective_known_n=3)
    stat_scopes={'group_statistics.csv':'primary_matrix_complete_batches','all_pass_group_statistics.csv':'all_PASS_supplemental_across_batches',
        'all_runs_diagnostic_statistics.csv':'all_recorded_including_CHECK_diagnostic_only','batch_statistics.csv':'per_batch_PASS_with_recorded_and_failed_counts'}
    original=[{k:v for k,v in r.items() if k!='file_kind'} for r in read_csv(HERE/'path_map.csv') if r['file_kind']=='original_measurement']
    derived=[r for r in read_csv(HERE/'path_map.csv') if r['file_kind']!='original_measurement']
    for folder,base in ((DATA,HERE/'before_catalog/root'),(DATA/'DELTA',HERE/'before_catalog/DELTA')):
        for name in ('run_index.csv',):
            old=read_csv(base/name)
            assert not set(IDS)&{r['run_id'] for r in old}
            write_csv(folder/name,old+index)
        write_csv(folder/'path_map.csv',read_csv(base/'path_map.csv')+original)
        name='all_runs_diagnostic_statistics.csv'
        if (base/name).exists():
            write_csv(folder/name,read_csv(base/name)+[dict(stats,statistics_scope='all_recorded_independent_CHECK_diagnostic_only')])
        name='batch_statistics.csv'
        if (base/name).exists():
            empty=dict(stats,statistics_scope='per_batch_eligible_with_independent_review_counts',temporal_repeat_n=0,
                       statistic_run_ids='',main_packets_total=0,main_window_seconds_total=0)
            for key in empty:
                if key.endswith(('_mean','_sample_sd')): empty[key]=''
                if key.endswith('_known_n'): empty[key]=0
            write_csv(folder/name,read_csv(base/name)+[empty])
    for folder in (DATA/'DELTA/Dynamic_load',DATA/GROUP):
        folder.mkdir(parents=True,exist_ok=True)
        write_csv(folder/'run_index.csv',index);write_csv(folder/'primary_matrix.csv',[],fields=list(index[0]))
        write_csv(folder/'group_statistics.csv',[],fields=list(stats))
        write_csv(folder/'all_runs_diagnostic_statistics.csv',[dict(stats,statistics_scope='all_recorded_independent_CHECK_diagnostic_only')])
        write_csv(folder/'path_map.csv',original);write_csv(folder/'derived_path_map.csv',derived)
    write_csv(HERE/'run_index.csv',index);write_csv(HERE/'diagnostic_statistics.csv',[stats])
    # All old row values and protected single-mode/zero-load-only views survive.
    for folder,base in ((DATA,HERE/'before_catalog/root'),(DATA/'DELTA',HERE/'before_catalog/DELTA')):
        for name in ('run_index.csv','primary_matrix.csv','path_map.csv',*stat_scopes):
            if not (base/name).exists(): continue
            old=read_csv(base/name);now=read_csv(folder/name)
            assert all(all(now[i][k]==v for k,v in row.items()) for i,row in enumerate(old)), name
    for item in json.loads((HERE/'protected_views.json').read_text()): assert sha(Path(item['path']))==item['sha256']
    for item in read_csv(HERE/'path_map.csv'): assert sha(Path(item['new_path']))==item['sha256']
    counts=dict(all_runs=len(read_csv(DATA/'run_index.csv')),primary_runs=len(read_csv(DATA/'primary_matrix.csv')),
        DELTA_runs=len(read_csv(DATA/'DELTA/run_index.csv')),conditions=len(read_csv(DATA/'group_statistics.csv')),
        original_path_entries=len(read_csv(DATA/'path_map.csv')),all_moved_files=v['verified_files'],status='PASS')
    assert counts==dict(all_runs=96,primary_runs=90,DELTA_runs=48,conditions=30,original_path_entries=576,all_moved_files=27,status='PASS')
    (HERE/'catalog_validation.json').write_text(json.dumps(counts,indent=2),encoding='utf-8')
    print(json.dumps(counts))

if __name__=='__main__':
    {'prepare':prepare,'finish':finish}[sys.argv[1]]()
