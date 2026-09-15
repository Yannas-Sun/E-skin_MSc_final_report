"""Fixed 15-run organization and catalog extension; original file bytes preserved.

prepare snapshots completed runs and catalogs. PowerShell performs guarded moves.
finish consumes independent audits, validates hashes, and extends derived views.
"""
from pathlib import Path
import csv, hashlib, json, shutil, statistics, sys
from datetime import datetime

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
DATA = BASE / 'data'
MEASUREMENT = {'mul1_raw.bin','packet_log.csv','module_log.csv','events.jsonl','summary.json','experiment_log.md'}
BATCHES = [
    ('20260907_delta_followup_review', ['20260907_050453_154588','20260907_050533_183636','20260907_050613_222506'], 'N=1/200Hz/M1/Large_area/Batch_20260907_050453_154588', 'large_area_dynamic'),
    ('20260907_delta_press_release_review', ['20260907_051941_159689','20260907_052021_196300','20260907_052101_230925'], 'N=1/200Hz/M1/Large_area_press_release', 'repeated_press_release'),
    ('20260907_delta_rolling_review', ['20260907_053858_001637','20260907_053938_027960','20260907_054018_056649'], 'N=1/200Hz/M1/Rolling', 'rolling'),
    ('20260907_n2_large_area_review', ['20260907_054752_155421','20260907_054832_183609','20260907_054912_204552'], 'N=2/200Hz/M1_M3/Large_area_simultaneous', 'large_area_coverage'),
    ('20260907_n4_full_coverage_review', ['20260907_060147_020562','20260907_060227_053987','20260907_060307_083182'], 'N=4/200Hz/M0_M1_M2_M3/Full_coverage_all_modules', 'full_coverage_all_modules'),
]

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def read_csv(path):
    if not path.exists(): return []
    with path.open(encoding='utf-8-sig', newline='') as stream: return list(csv.DictReader(stream))

def write_csv(path, rows, fields=None):
    columns = list(fields or [])
    for row in rows:
        for key in row:
            if key not in columns: columns.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer=csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader(); writer.writerows(rows)

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): digest.update(block)
    return digest.hexdigest()

def prepare():
    assert not (HERE/'organization_plan.json').exists(), 'Do not overwrite an existing move snapshot'
    runs=[]; files=[]; snapshots={}
    for review, ids, group, protocol in BATCHES:
        for rid in ids:
            source=DATA/rid
            summary=read_json(source/'summary.json')
            assert summary['run_id']==rid and summary['completed_requested_duration']
            assert summary['reason']=='capture duration reached'
            assert set(summary['metadata']['target_modules']) in ({1},{1,3},{0,1,2,3})
            repeat=str(summary['metadata']['repeat'])
            destination=DATA/'DELTA/Dynamic_load'/group/f'Repeat_{repeat}'
            assert not destination.exists(), destination
            assert not source.is_symlink() and source.resolve().parent==DATA.resolve()
            runfiles=[]
            for path in sorted(source.iterdir()):
                assert path.is_file() and not path.is_symlink(), path
                item=dict(run_id=rid,file_name=path.name,old_path=str(path.resolve()),new_path=str((destination/path.name).resolve()),
                    old_relative_path=path.relative_to(DATA).as_posix(),new_relative_path=(destination/path.name).relative_to(DATA).as_posix(),
                    bytes=path.stat().st_size,sha256=sha(path),source_review=review,
                    file_kind='original_measurement' if path.name in MEASUREMENT else 'existing_derived')
                files.append(item);runfiles.append(item)
            assert MEASUREMENT.issubset({f['file_name'] for f in runfiles})
            runs.append(dict(run_id=rid,source=str(source.resolve()),destination=str(destination.resolve()),
                group=group,source_review=review,actual_load_protocol=protocol,files=runfiles))
            snapshots[rid]=summary
    assert len(runs)==15 and len(snapshots)==15
    assert {p.name for p in DATA.iterdir() if p.is_dir() and p.name[:8].isdigit()}==set(snapshots), 'Unreviewed top-level captures present'
    catalog_dirs=[DATA,DATA/'DELTA',DATA/'DELTA/Dynamic_load',DATA/'DELTA/Dynamic_load/N=1/200Hz/M1/Large_area']
    backups=[]
    for folder in catalog_dirs:
        for path in folder.iterdir():
            if path.is_file() and path.suffix in ('.csv','.md'):
                destination=HERE/'before_catalog'/path.relative_to(DATA)
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,destination)
                backups.append(dict(path=str(path.resolve()),backup=str(destination.resolve()),sha256=sha(path)))
    protected=[]
    for folder in [DATA/'FULL',DATA/'DELTA/Zero_load']:
        for path in folder.rglob('*'):
            if path.is_file() and path.suffix in ('.csv','.md','.json') and path.name not in MEASUREMENT:
                protected.append(dict(path=str(path.resolve()),sha256=sha(path)))
    write_json(HERE/'summary_snapshot.json',snapshots)
    write_json(HERE/'protected_views.json',protected)
    write_json(HERE/'catalog_backups.json',backups)
    plan=dict(prepared_at=datetime.now().astimezone().isoformat(),data_root=str(DATA.resolve()),runs=runs,
        total_runs=len(runs),total_files=len(files),total_bytes=sum(f['bytes'] for f in files),
        original_files=sum(f['file_kind']=='original_measurement' for f in files),
        policy='Preserve every existing file, original metadata/status/plot labels and embedded historical paths. Never overwrite a Repeat directory.')
    write_json(HERE/'organization_plan.json',plan); write_csv(HERE/'path_map.csv',files)
    print(json.dumps({k:plan[k] for k in ['total_runs','total_files','total_bytes','original_files']}))

def get_timing(review,rid):
    path=HERE.parent/review/'timing_review.json'
    if not path.exists(): return {}
    record=next(r for r in read_json(path)['records'] if r['run_id']==rid)
    return record['timing']['main']

def qualify(review,rid,a):
    qpath=HERE.parent/review/'qualification.json'
    if qpath.exists():
        source=read_json(qpath)
        if isinstance(source,dict): source=source.get('runs',source.get('records',source))
        if isinstance(source,list): return next(r for r in source if r['run_id']==rid)
        if rid in source: return source[rid]
    s=a['scopes']['main']; c=s['counts']
    reasons=[]
    events=s.get('inner_sequence_discontinuity_count',0)
    if events: reasons.append('inner_sequence_discontinuity')
    if c.get('missing_valid_expected_updates',0): reasons.append('missing_valid_expected_updates')
    for field in ['outer_crc_error','inner_crc_error','outer_missing_sequence_numbers','delta_base_mismatch','interior_unassigned_raw_bytes']:
        if c.get(field,0): reasons.append(field)
    if a.get('cross_check_errors'): reasons.append('raw_log_cross_check_errors')
    if a.get('independent_protocol_findings') != 'NO DETECTED PROTOCOL ANOMALY':
        raise AssertionError(f'Explicit qualification required for {rid}')
    assert not reasons
    return dict(independent_main_status='PASS',main_review_reasons=[],main_inner_sequence_events=events)

def summarize(rows, scope, all_records=None):
    all_records=all_records or rows
    first=all_records[0]
    result={k:first.get(k,'') for k in ['mode','condition','actual_load_protocol','loading_relationship_between_modules','modules','N','target_hz','batch_id','load_layers']}
    result.update(temporal_repeat_n=len(rows),recorded_repeat_n=len(all_records),eligible_repeat_n=sum(r['main_eligible']=='True' for r in all_records),
        review_required_n=sum(r['main_eligible']!='True' for r in all_records),batch_n=len({r['batch_id'] for r in rows}),recorded_batch_n=1,
        statistics_scope=scope,statistics_basis='sample mean and SD across fixed main windows; CHECK retained in diagnostic statistics',
        primary_matrix_selected_n=0,dynamic_analysis_selected_n=sum(r.get('dynamic_analysis_selected')=='True' for r in rows),
        statistic_run_ids=';'.join(r['run_id'] for r in rows),review_required_run_ids=';'.join(r['run_id'] for r in all_records if r['main_eligible']!='True'),
        repeat_interpretation='consecutive temporal windows in one setup; not independent assemblies',
        main_packets_total=sum(int(r['main_packets']) for r in rows),main_window_seconds_total=sum(float(r['main_duration_s']) for r in rows))
    for short,long in [('rate_Hz','main_rate_Hz'),('packet_Mbit_s','main_packet_Mbit_s'),('raw_arrival_Mbit_s','main_raw_arrival_Mbit_s'),
        ('Lmean_B','main_Lmean_B'),('K_ESKD','main_K_ESKD_mean'),('q_ESKF','main_q_ESKF'),('q_ESKF_pct','main_q_ESKF_pct'),
        ('equal_rate_FULL_saving_pct','main_equal_rate_FULL_saving_pct')]:
        values=[float(r[long]) for r in rows if r.get(long,'')!='']
        result[short+'_mean']=statistics.mean(values) if values else ''
        result[short+'_sample_sd']=statistics.stdev(values) if len(values)>1 else ''
        result[short+'_known_n']=len(values)
    return result

def finish():
    plan=read_json(HERE/'organization_plan.json'); verification=read_json(HERE/'organization_verification.json')
    assert verification['status']=='completed' and verification['verified_runs']==15
    for item in read_csv(HERE/'path_map.csv'): assert sha(Path(item['new_path']))==item['sha256']
    snapshots=read_json(HERE/'summary_snapshot.json'); new=[]
    for run in plan['runs']:
        rid=run['run_id']; s=snapshots[rid]; m=s['metadata']; p=s['scopes']['main']; c=p['counts']; full=s['scopes']['full_run']
        review=run['source_review']; audit=read_json(HERE.parent/review/'raw_audit.json')
        a=next(r for r in audit['runs'] if r['run_id']==rid)
        assert not audit['changed_original_files']
        assert a['raw_sha256']==s['raw_sha256']
        q=qualify(review,rid,a)
        condition=read_json(HERE.parent/review/'condition_correction.json')
        timing=get_timing(review,rid)
        if not timing:
            timing=dict(pc_completion_dt_ms={'max':max((v['pc_completion_gap_ms'] for v in a['main_largest_pc_gaps']),default='')},
                host_enqueue_dt_ms={'max':max((v['bridge_host_gap_ms'] for v in a['main_largest_bridge_gaps']),default='')})
        passed=q['independent_main_status']=='PASS' and p['status']=='PASS'
        reasons=q.get('main_review_reasons',[])
        if isinstance(reasons,str): reasons=[reasons]
        modules='_'.join(f'M{i}' for i in m['target_modules']); n=len(m['target_modules'])
        row=dict(run_id=rid,started_at=s['started_at'],mode=m['target_mode'],condition=condition['actual_condition'],N=n,target_hz=m['target_hz'],modules=modules,
            block=m['block'],batch_id=m['batch_id'],repeat=m['repeat'],old_relative_path=rid,new_relative_path=Path(run['destination']).relative_to(DATA).as_posix(),
            duration_s=s['duration_seconds'],main_duration_s=p['actual_duration_seconds'],main_packets=c.get('valid_outer_packets',0),main_status=p['status'],
            full_status=full['status'],full_review_reasons=';'.join(full['review_reasons']),main_rate_Hz=p['valid_outer_packet_rate_Hz'],main_Lmean_B=p['Lmean_valid_packet_B'],
            main_packet_Mbit_s=p['packet_completion_Mbit_per_s'],main_raw_arrival_Mbit_s=p['raw_arrival_Mbit_per_s'],
            main_K_ESKD_mean=a['scopes']['main']['K_ESKD']['mean'],main_q_ESKF=p['q_ESKF'],main_q_ESKF_pct=100*p['q_ESKF'],
            main_ESKF_count=c.get('ESKF',0),main_ESKD_count=c.get('ESKD',0),
            source_local_firmware=m['local_provenance']['firmware_variant'],deployment_confirmed=str(m['deployment_confirmed']),
            main_eligible=str(passed),main_review_reasons=';'.join(p['review_reasons']),main_outer_crc_errors=q.get('main_outer_crc_errors',c.get('outer_crc_error',0)),
            main_outer_missing_sequence_numbers=q.get('main_outer_missing_sequence_numbers',c.get('outer_missing_sequence_numbers',0)),
            main_missing_valid_expected_updates=c.get('missing_valid_expected_updates',0),main_interior_unassigned_raw_bytes=c.get('interior_unassigned_raw_bytes',0),
            source_review=review,timing_note='PC completion rate is not physical scan rate; see independent audit and timing evidence.',replacement_batch_id='',
            primary_matrix_selected='False',selection_reason='dynamic condition; kept separate from the 90-run zero-load matrix',
            pc_max_completion_gap_ms=timing.get('pc_completion_dt_ms',{}).get('max',''),host_max_enqueue_gap_ms=timing.get('host_enqueue_dt_ms',{}).get('max',''),
            host_packet_span_rate_Hz=timing.get('host_packet_span_rate_Hz',''),independent_raw_audit=q['independent_main_status'],
            load_layers=m.get('load_layers','unspecified'),load_description=condition.get('actual_condition_description',''),
            independent_review_reasons=';'.join(reasons),main_inner_sequence_events=q.get('main_inner_sequence_events',a['scopes']['main'].get('inner_sequence_discontinuity_count',0)),
            recorded_condition=m['condition'],actual_load_protocol=run['actual_load_protocol'],loading_relationship_between_modules=condition.get('loading_relationship_between_modules',''),
            independent_main_status=q['independent_main_status'],dataset_role='dynamic_load',main_equal_rate_FULL_saving_pct=100*(1-p['Lmean_valid_packet_B']/(40+1044*n)))
        new.append(row)
    diagnostic=[]; selected_groups=[]; supplemental=[]; batch_stats=[]
    for review,ids,group,protocol in BATCHES:
        rows=[r for r in new if r['run_id'] in ids]; assert len(rows)==3
        complete=all(r['main_eligible']=='True' for r in rows)
        for r in rows:
            r['dynamic_batch_eligible']=str(complete); r['dynamic_analysis_selected']=str(complete)
            r['dynamic_selection_reason']='complete_three_window_batch_passed' if complete else 'whole_batch_retained_as_diagnostic_due_to_integrity_CHECK'
        diagnostic.append(summarize(rows,'all_recorded_dynamic_including_CHECK'))
        good=[r for r in rows if r['main_eligible']=='True']
        batch_stats.append(summarize(good,'per_batch_eligible_with_recorded_and_CHECK_counts',rows))
        if complete: selected_groups.append(summarize(rows,'complete_three_window_dynamic_batch'))
        if good: supplemental.append(summarize(good,'eligible_windows_supplemental_not_complete_batch',rows))
    before=HERE/'before_catalog'; old=read_csv(before/'run_index.csv')
    assert len(old)==96 and not {r['run_id'] for r in old}&{r['run_id'] for r in new}
    for r in old:
        r['recorded_condition']=r['condition']
        r['dataset_role']='zero_load' if r['condition']=='zero_load' else 'dynamic_load'
        r['dynamic_analysis_selected']='False'
    all_rows=old+new
    old_dynamic=[r for r in old if r['dataset_role']=='dynamic_load']
    dynamic=old_dynamic+new
    original_files=[{k:v for k,v in f.items() if k!='file_kind'} for f in read_csv(HERE/'path_map.csv') if f['file_kind']=='original_measurement']
    derived_files=[f for f in read_csv(HERE/'path_map.csv') if f['file_kind']!='original_measurement']
    for folder, prefix, rows in [(DATA,Path('.'),all_rows),(DATA/'DELTA',Path('DELTA'),[r for r in all_rows if r['mode']=='DELTA']),
        (DATA/'DELTA/Dynamic_load',Path('DELTA/Dynamic_load'),dynamic)]:
        backup=before/prefix
        write_csv(folder/'run_index.csv',rows)
        write_csv(folder/'path_map.csv',read_csv(backup/'path_map.csv')+original_files)
        write_csv(folder/'derived_path_map.csv',read_csv(backup/'derived_path_map.csv')+derived_files)
        write_csv(folder/'dynamic_analysis_selected.csv',[r for r in rows if r.get('dynamic_analysis_selected')=='True'])
        write_csv(folder/'dynamic_group_statistics.csv',selected_groups)
        write_csv(folder/'dynamic_diagnostic_statistics.csv',read_csv(before/'DELTA/Dynamic_load/all_runs_diagnostic_statistics.csv')+diagnostic)
        for filename, additions in [('all_runs_diagnostic_statistics.csv',diagnostic),('all_pass_group_statistics.csv',supplemental),('batch_statistics.csv',batch_stats)]:
            if folder==DATA:
                aggregate=read_csv(backup/filename)+additions
            else:
                aggregate=[r for r in read_csv(DATA/filename) if r.get('mode')=='DELTA']
                if folder==DATA/'DELTA/Dynamic_load':
                    aggregate=[r for r in aggregate if r.get('condition')!='zero_load']
            write_csv(folder/filename,aggregate)
    # The old CHECK batch remains at Large_area/Repeat_*; the later batch gets its own subdirectory.
    for review,ids,group,protocol in BATCHES:
        rows=[r for r in new if r['run_id'] in ids]; folder=DATA/'DELTA/Dynamic_load'/group
        write_csv(folder/'run_index.csv',rows)
        write_csv(folder/'path_map.csv',[f for f in original_files if f['run_id'] in ids])
        write_csv(folder/'derived_path_map.csv',[f for f in derived_files if f['run_id'] in ids])
        write_csv(folder/'group_statistics.csv',[r for r in selected_groups if r['batch_id']==rows[0]['batch_id']],fields=list(diagnostic[0]))
        write_csv(folder/'all_runs_diagnostic_statistics.csv',[r for r in diagnostic if r['batch_id']==rows[0]['batch_id']])
        relative_review=Path(__import__('os').path.relpath(HERE.parent/review,folder)).as_posix()
        body=f'# {group}\n\n'+rows[0]['load_description']+'。原始记录内标签保留，索引使用用户确认的条件。\n\n'
        body+='每条约40 s，主窗口10–40 s；三条是同一设置的连续时间重复。\n\n'
        body+='| Repeat | run_id | GUI主状态 | 独立主状态 | 有效USB Mbit/s |\n|---|---|---|---|---:|\n'
        for r in rows: body+=f"| {r['repeat']} | {r['run_id']} | {r['main_status']} | {r['independent_main_status']} | {r['main_packet_Mbit_s']:.6f} |\n"
        body+=f'\n[统计报告]({relative_review}/statistics.md) / [独立raw检查]({relative_review}/raw_audit.md)。\n'
        body+='\n全部原始文件、图、状态及嵌入历史路径保持原样；当前路径见path_map.csv。含CHECK的完整批次只用于诊断统计，不选单条包装为无错误三次重复。\n'
        (folder/'README.md').write_text(body,encoding='utf-8')
    large=DATA/'DELTA/Dynamic_load/N=1/200Hz/M1/Large_area'
    followup=[r for r in new if r['source_review']=='20260907_delta_followup_review']
    write_csv(large/'run_index.csv',old_dynamic+followup)
    write_csv(large/'path_map.csv',read_csv(before/'DELTA/Dynamic_load/N=1/200Hz/M1/Large_area/path_map.csv')+[f for f in original_files if f['run_id'] in {r['run_id'] for r in followup}])
    followup_ids={r['run_id'] for r in followup}
    write_csv(large/'derived_path_map.csv',read_csv(before/'DELTA/Dynamic_load/N=1/200Hz/M1/Large_area/derived_path_map.csv')+[f for f in derived_files if f['run_id'] in followup_ids])
    write_csv(large/'dynamic_analysis_selected.csv',followup)
    write_csv(large/'group_statistics.csv',[r for r in selected_groups if r['batch_id']==followup[0]['batch_id']])
    write_csv(large/'all_runs_diagnostic_statistics.csv',read_csv(before/'DELTA/Dynamic_load/N=1/200Hz/M1/Large_area/all_runs_diagnostic_statistics.csv')+[r for r in diagnostic if r['batch_id']==followup[0]['batch_id']])
    selected=[r for r in new if r['dynamic_analysis_selected']=='True']
    primary=read_csv(before/'primary_matrix.csv')
    write_csv(DATA/'analysis_selected.csv',primary+selected)
    write_csv(HERE/'new_run_index.csv',new); write_csv(HERE/'dynamic_diagnostic_statistics.csv',diagnostic)
    for item in read_json(HERE/'protected_views.json'): assert sha(Path(item['path']))==item['sha256']
    for filename in ['primary_matrix.csv','group_statistics.csv']:
        assert sha(DATA/filename)==sha(before/filename)
    for prior in read_csv(before/'run_index.csv'):
        current=next(r for r in all_rows if r['run_id']==prior['run_id'])
        assert all(str(current[k])==v for k,v in prior.items()), prior['run_id']
    assert len(all_rows)==111 and len({r['run_id'] for r in all_rows})==111
    assert len(read_csv(DATA/'path_map.csv'))==666
    validation=dict(status='PASS',all_runs=111,FULL_runs=48,DELTA_zero_runs=45,DELTA_dynamic_runs=18,newly_organized_runs=15,
        zero_load_primary_runs=len(primary),dynamic_selected_runs=len(selected),analysis_selected_runs=len(primary)+len(selected),
        new_main_independent_counts={k:sum(r['independent_main_status']==k for r in new) for k in sorted({r['independent_main_status'] for r in new})},
        original_path_entries=666,moved_files=plan['total_files'],moved_bytes=plan['total_bytes'],old_rows_preserved=True,protected_views_unchanged=True,
        unclassified_top_level_runs=[p.name for p in DATA.iterdir() if p.is_dir() and p.name[:8].isdigit()])
    assert not validation['unclassified_top_level_runs']
    write_json(HERE/'catalog_validation.json',validation)
    print(json.dumps(validation))

if __name__=='__main__':
    {'prepare':prepare,'finish':finish}[sys.argv[1]]()
