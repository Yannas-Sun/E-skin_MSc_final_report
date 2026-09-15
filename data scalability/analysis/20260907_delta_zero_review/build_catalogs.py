"""Add the audited DELTA zero-load matrix, preserving all existing FULL selections."""
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import csv
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data'

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))

def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)

def truth(value):
    return str(value).lower() == 'true'

def main():
    verified = json.loads((HERE / 'organization_verification.json').read_text(encoding='utf-8-sig'))
    assert verified['status'] == 'completed' and verified['verified_files'] == 270
    baseline = HERE / 'before_catalog'
    old_index = read_csv(baseline / 'run_index.csv')
    old_primary = read_csv(baseline / 'primary_matrix.csv')
    assert len(old_index) == 48 and len(old_primary) == 45
    assert all(row['mode'] == 'FULL' for row in old_index)
    new_index = read_csv(HERE / 'run_index.csv')
    assert len(new_index) == 45 and all(truth(r['main_eligible']) for r in new_index)
    timing = {r['run_id']: r for r in read_csv(HERE / 'timing_per_run.csv')}
    stats_runs = {r['run_id']: r for r in read_csv(HERE / 'stats_runs.csv')}
    groups = defaultdict(list)
    for row in new_index:
        t = timing[row['run_id']]
        row['pc_max_completion_gap_ms'] = t['pc_completion_dt_ms_max']
        row['host_max_enqueue_gap_ms'] = t['host_enqueue_dt_ms_max']
        row['host_packet_span_rate_Hz'] = t['host_packet_span_rate_Hz']
        row['timing_note'] = ('PC completion timestamps are buffered; packet rate per PC window is not physical scan rate. '
                              f'Max PC gap {float(t["pc_completion_dt_ms_max"]):.4f} ms; '
                              f'max bridge gap {float(t["host_enqueue_dt_ms_max"]):.0f} ms; consecutive sequences.')
        row['independent_raw_audit'] = 'PASS_no_detected_internal_transport_or_cache_chain_errors'
        for field in ['main_rate_Hz','main_Lmean_B','main_packet_Mbit_s','main_raw_arrival_Mbit_s',
                      'main_K_ESKD_mean','main_q_ESKF']:
            assert abs(float(row[field]) - float(stats_runs[row['run_id']][field])) < 1e-9, field
        folder = DATA / row['new_relative_path']
        summary = json.loads((folder / 'summary.json').read_text(encoding='utf-8-sig'))
        assert summary['run_id'] == row['run_id'] and summary['scopes']['main']['status'] == row['main_status']
        groups[(int(row['N']), row['modules'])].append(row)
    assert len(groups) == 15
    for rows in groups.values():
        assert len(rows) == 3 and {r['repeat'] for r in rows} == {'1', '2', '3'}
        assert len({r['batch_id'] for r in rows}) == 1
    new_stats = read_csv(HERE / 'stats_combinations_pass.csv')
    new_all_stats = read_csv(HERE / 'stats_combinations.csv')
    assert len(new_stats) == len(new_all_stats) == 15
    for rows in [new_stats, new_all_stats]:
        for row in rows:
            row['mode'] = 'DELTA'
            row['target_hz'] = '200'
            row['condition'] = 'zero_load'
            row['primary_matrix_selected_n'] = 3
            row['repeat_interpretation'] = 'temporal windows; not independent setup blocks'
            row['recorded_batch_n'] = 1
            row['review_required_n'] = 0
            row['review_required_run_ids'] = ''
            members = groups[(int(row['N']), row['modules'])]
            row['main_packets_total'] = sum(int(r['main_packets']) for r in members)
            row['main_window_seconds_total'] = sum(float(r['main_duration_s']) for r in members)
            row['statistics_basis'] = 'sample mean and SD across recorded windows; no frame-rate or K selection'
    new_primary_stats = [dict(r, statistics_scope='primary_matrix_complete_batches') for r in new_stats]
    new_pass_stats = [dict(r, statistics_scope='all_PASS_supplemental_across_batches') for r in new_stats]
    new_diagnostic_stats = [dict(r, statistics_scope='all_recorded_including_CHECK_diagnostic_only') for r in new_all_stats]
    new_batch_stats = [dict(r, statistics_scope='per_batch_PASS_with_recorded_and_failed_counts') for r in new_stats]
    index = old_index + new_index
    index.sort(key=lambda r: (r['mode'], int(r['N']), r['modules'], r['started_at']))
    assert len(index) == len({r['run_id'] for r in index}) == 93
    primary = old_primary + new_index
    primary.sort(key=lambda r: (r['mode'], int(r['N']), r['modules'], r['started_at']))
    assert len(primary) == 90
    # Copy baseline field values exactly. Adding a mode column to old FULL
    # statistics avoids collisions with the new DELTA groups.
    outputs = {}
    for name, new_rows in [
        ('group_statistics.csv', new_primary_stats),
        ('all_pass_group_statistics.csv', new_pass_stats),
        ('all_runs_diagnostic_statistics.csv', new_diagnostic_stats),
        ('batch_statistics.csv', new_batch_stats),
    ]:
        old_rows = read_csv(baseline / name)
        for row in old_rows: row['mode'] = 'FULL'
        outputs[name] = old_rows + new_rows
    files = read_csv(baseline / 'path_map.csv') + read_csv(HERE / 'path_map.csv')
    assert len(files) == 558 and len({r['new_relative_path'] for r in files}) == 558
    for row in files:
        assert (DATA / row['new_relative_path']).is_file(), row['new_relative_path']
    outputs.update({'run_index.csv': index, 'primary_matrix.csv': primary, 'path_map.csv': files})
    for name, rows in outputs.items(): write_csv(DATA / name, rows)
    write_csv(HERE / 'run_index.csv', new_index)
    # Mode-specific indexes support current GUI schema without silently mixing
    # FULL and DELTA conditions in legacy downstream scripts.
    for folder in [DATA/'DELTA', DATA/'DELTA/Zero_load']:
        folder.mkdir(parents=True, exist_ok=True)
        write_csv(folder/'run_index.csv', new_index)
        write_csv(folder/'primary_matrix.csv', new_index)
        write_csv(folder/'group_statistics.csv', new_primary_stats)
        write_csv(folder/'path_map.csv', read_csv(HERE/'path_map.csv'))
    for name in ['stats_by_n_balanced.csv', 'stats_full_comparison.csv', 'module_activity_by_slot_n.csv']:
        shutil.copy2(HERE/name, DATA/'DELTA/Zero_load'/name)
    # Backward-compatible FULL-only convenience views retain the exact old
    # numerical contents and primary selection.
    for name in ['run_index.csv','primary_matrix.csv','group_statistics.csv',
                 'all_pass_group_statistics.csv','all_runs_diagnostic_statistics.csv',
                 'batch_statistics.csv','path_map.csv']:
        dest = DATA/'FULL'/name
        if dest.exists():
            protected = HERE/'before_catalog'/'FULL'
            protected.mkdir(exist_ok=True)
            if not (protected/name).exists(): shutil.copy2(dest, protected/name)
        shutil.copy2(baseline/name, dest)
    validation = dict(created_at=datetime.now().astimezone().isoformat(),
        all_recorded_runs=93, primary_runs=90, all_main_PASS=92, retained_FULL_main_CHECK=1,
        FULL_recorded=48, FULL_primary=45, DELTA_zero_recorded=45, DELTA_zero_primary=45,
        conditions=30, batches=31, original_files=558, delta_moved_files=270,
        unchanged_existing_FULL_run_ids=[r['run_id'] for r in old_index],
        preserved_FULL_primary_ids=[r['run_id'] for r in old_primary],
        note='No new measured files or raw content; total indexes include mode, and FULL failure remains retained.')
    # Confirm that every pre-existing FULL index field survived the merge.
    actual = {r['run_id']: r for r in read_csv(DATA/'run_index.csv')}
    for row in old_index:
        assert all(actual[row['run_id']][key] == value for key, value in row.items())
    (HERE/'catalog_validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in validation.items() if not isinstance(v,list)},ensure_ascii=False))

if __name__ == '__main__':
    main()
