"""Build a transparent FULL zero-load primary matrix without changing measurements.

Use the whole M012 retest batch for the three-window primary comparison. Keep
the earlier two PASS windows as supplemental and the failed window as evidence.
"""
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path
import csv
import json
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT/'data'
REVIEWS = ['20260906_current_data_review', '20260906_n2_full_review',
           '20260907_n3_full_review', '20260907_full_completion_review']
RETEST_BATCH = 'BATCH_6b6313d281364eaa891ce82942b3d531'
FAILED_RUN = '20260907_000133_670681'
SLOW_PASS_RUN = '20260907_001505_375008'

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))

def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def summarize(group, selected, scope):
    batches = sorted({r['batch_id'] for r in selected})
    eligible = [r for r in group if r['main_eligible']]
    item = dict(modules=group[0]['modules'], N=int(group[0]['N']), target_hz=200,
                condition='zero_load', temporal_repeat_n=len(selected),
                recorded_repeat_n=len(group), eligible_repeat_n=len(eligible),
                review_required_n=len(group)-len(eligible), batch_n=len(batches),
                recorded_batch_n=len({r['batch_id'] for r in group}),
                batch_id=';'.join(batches), statistics_scope=scope,
                statistics_basis='sample mean and SD across recorded windows; selection by batch/integrity, never rate',
                primary_matrix_selected_n=sum(r['primary_matrix_selected'] for r in group),
                statistic_run_ids=';'.join(r['run_id'] for r in selected),
                review_required_run_ids=';'.join(r['run_id'] for r in group if not r['main_eligible']),
                repeat_interpretation='temporal windows; not independent setup blocks')
    for field, key in [('main_rate_Hz','rate_Hz'), ('main_packet_Mbit_s','packet_Mbit_s'),
                       ('main_raw_arrival_Mbit_s','raw_arrival_Mbit_s'), ('main_Lmean_B','Lmean_B')]:
        values = [float(r[field]) for r in selected]
        item[key+'_mean'] = statistics.mean(values) if values else None
        item[key+'_sample_sd'] = statistics.stdev(values) if len(values)>1 else None
    item['main_packets_total'] = sum(int(r['main_packets']) for r in selected)
    item['main_window_seconds_total'] = sum(float(r['main_duration_s']) for r in selected)
    return item

all_runs, all_files = [], []
for review in REVIEWS:
    folder = ROOT/'analysis'/review
    verified = json.loads((folder/'organization_verification.json').read_text(encoding='utf-8-sig'))
    assert verified['status'] == 'completed'
    for row in read_csv(folder/'run_index.csv'):
        summary = json.loads((DATA/row['new_relative_path']/'summary.json').read_text(encoding='utf-8-sig'))
        meta, window = summary['metadata'], summary['scopes']['main']
        assert summary['run_id'] == row['run_id'] and meta['batch_id'] == row['batch_id']
        assert str(meta['repeat']) == row['repeat'] and window['status'] == row['main_status']
        assert meta['target_mode'] == 'FULL' and meta['condition'] == 'zero_load' and meta['target_hz'] == 200
        assert summary['completed_requested_duration']
        row['main_eligible'] = window['status']=='PASS' and not window['review_reasons']
        row['main_review_reasons'] = ';'.join(window['review_reasons'])
        row['main_outer_crc_errors'] = window['counts'].get('outer_crc_error',0)
        row['main_outer_missing_sequence_numbers'] = window['counts'].get('outer_missing_sequence_numbers',0)
        row['main_interior_unassigned_raw_bytes'] = window['counts'].get('interior_unassigned_raw_bytes',0)
        row['source_review'] = review
        row['timing_note'] = ('Bridge enqueue gap 123 ms and separate PC completion gap 301.3735 ms; PASS retained'
                             if row['run_id']==SLOW_PASS_RUN else
                             'PC completion gap 278.7935 ms, corresponding bridge interval 5 ms; PASS retained'
                             if row['run_id']=='20260907_005108_797842' else '')
        row['replacement_batch_id'] = RETEST_BATCH if row['modules']=='M0_M1_M2' else ''
        if row['modules']=='M0_M1_M2':
            row['primary_matrix_selected'] = row['batch_id']==RETEST_BATCH
            row['selection_reason'] = ('complete_retest_batch_selected_as_one_unit' if row['primary_matrix_selected'] else
                                       'earlier_PASS_retained_as_supplemental_not_primary' if row['main_eligible'] else
                                       'integrity_failure_retained_for_reliability_not_primary')
        else:
            row['primary_matrix_selected'] = True
            row['selection_reason'] = 'original_complete_three_window_batch'
        if row['primary_matrix_selected']:
            assert row['main_eligible']
        all_runs.append(row)
    for row in read_csv(folder/'path_map.csv'):
        assert (DATA/row['new_relative_path']).is_file()
        row['source_review'] = review
        all_files.append(row)

all_runs.sort(key=lambda r:(int(r['N']),r['modules'],r['started_at']))
assert len(all_runs)==48 and len({r['run_id'] for r in all_runs})==48 and len(all_files)==288
assert [r['run_id'] for r in all_runs if not r['main_eligible']]==[FAILED_RUN]
assert sum(r['main_eligible'] for r in all_runs)==47
primary = [r for r in all_runs if r['primary_matrix_selected']]
assert len(primary)==45 and next(r for r in all_runs if r['run_id']==SLOW_PASS_RUN)['primary_matrix_selected']
groups, batches = defaultdict(list), defaultdict(list)
for row in all_runs:
    key=(int(row['N']), row['modules'])
    groups[key].append(row)
    batches[key+(row['batch_id'],)].append(row)
expected={(n,'_'.join('M'+str(m) for m in members)) for n in range(1,5) for members in combinations(range(4),n)}
assert set(groups)==expected and len(batches)==16
primary_stats, pass_stats, diagnostics, batch_stats = [], [], [], []
for key, group in sorted(groups.items()):
    selected=[r for r in group if r['primary_matrix_selected']]
    assert len(selected)==3 and len({r['batch_id'] for r in selected})==1
    assert {r['repeat'] for r in selected}=={'1','2','3'}
    primary_stats.append(summarize(group, selected, 'primary_matrix_complete_batches'))
    pass_stats.append(summarize(group, [r for r in group if r['main_eligible']], 'all_PASS_supplemental_across_batches'))
    diagnostics.append(summarize(group, group, 'all_recorded_including_CHECK_diagnostic_only'))
for key, group in sorted(batches.items()):
    assert len(group)==3 and {r['repeat'] for r in group}=={'1','2','3'}
    batch_stats.append(summarize(group,[r for r in group if r['main_eligible']], 'per_batch_PASS_with_recorded_and_failed_counts'))

backup=HERE/'before_catalog';backup.mkdir(exist_ok=True)
for name in ['README.md','run_index.csv','group_statistics.csv','all_runs_diagnostic_statistics.csv','path_map.csv']:
    if (DATA/name).exists() and not (backup/name).exists():
        (backup/name).write_bytes((DATA/name).read_bytes())
for name,rows in [('run_index.csv',all_runs),('primary_matrix.csv',primary),
                  ('group_statistics.csv',primary_stats),('all_pass_group_statistics.csv',pass_stats),
                  ('all_runs_diagnostic_statistics.csv',diagnostics),('batch_statistics.csv',batch_stats),
                  ('path_map.csv',all_files)]:
    write_csv(DATA/name,rows)
manifest=dict(created_at=datetime.now().astimezone().isoformat(),
              rule='one complete batch of Repeat 1/2/3 per configuration; use entire M012 retest batch; no rate-based choice',
              retest_batch_id=RETEST_BATCH, primary_count=45, recorded_count=48, main_PASS_count=47,
              retained_main_CHECK_count=1, selected_run_ids=[r['run_id'] for r in primary],
              retained_nonprimary=[{k:r[k] for k in ['run_id','batch_id','main_eligible','selection_reason']} for r in all_runs if not r['primary_matrix_selected']],
              limitation='Clean performance subset does not establish zero failures across all recordings; repeats are temporal, not independent rebuilt setups')
(HERE/'primary_selection.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Built primary matrix: 45 PASS runs, 15 configurations; all 48 retained (47 PASS + 1 CHECK), 16 batches, 288 original files.')
