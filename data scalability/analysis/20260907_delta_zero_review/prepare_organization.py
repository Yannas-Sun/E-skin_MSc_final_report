"""Freeze the 45 completed DELTA zero-load captures; never edit measured files."""
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path
import csv
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data'
FIRST, LAST = '20260907_013132_404213', '20260907_020930_401399'
REQUIRED = {'events.jsonl', 'experiment_log.md', 'module_log.csv',
            'mul1_raw.bin', 'packet_log.csv', 'summary.json'}

def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def main():
    paths = sorted(p for p in DATA.iterdir() if p.is_dir() and FIRST <= p.name <= LAST)
    assert len(paths) == 45
    assert not (HERE / 'organization_plan.json').exists(), 'Snapshot already exists; do not replace it'
    groups, files, runs, index = defaultdict(list), [], [], []
    targets = set()
    for source in paths:
        run_id = source.name
        summary = json.loads((source / 'summary.json').read_text(encoding='utf-8-sig'))
        meta, main = summary['metadata'], summary['scopes']['main']
        assert summary['schema_version'] == 2 and summary['run_id'] == run_id
        assert summary['completed_requested_duration'] and summary['reason'] == 'capture duration reached'
        assert meta['target_mode'] == 'DELTA' and meta['condition'] == 'zero_load'
        assert meta['target_hz'] == 200 and meta['N'] == len(meta['target_modules']) and meta['M'] == 4
        assert summary['settle_seconds'] == 10 and summary['requested_duration_seconds'] == 40
        assert {p.name for p in source.iterdir()} == REQUIRED
        repeat = int(meta['repeat'])
        assert repeat in (1, 2, 3) and repeat == meta['batch_repeat_index']
        assert meta['batch_repeat_count'] == 3
        module = '_'.join(f'M{i}' for i in sorted(meta['target_modules']))
        target_rel = f'DELTA/Zero_load/N={meta["N"]}/200Hz/{module}/Repeat_{repeat}'
        target = DATA / target_rel
        assert target_rel not in targets and not target.exists()
        targets.add(target_rel)
        eligible = main['status'] == 'PASS' and not main['review_reasons']
        row = dict(run_id=run_id, started_at=summary['started_at'], mode='DELTA',
                   condition='zero_load', N=meta['N'], target_hz=200, modules=module,
                   block=meta['block'], batch_id=meta['batch_id'], repeat=repeat,
                   old_relative_path=run_id, new_relative_path=target_rel,
                   duration_s=summary['duration_seconds'], main_duration_s=main['actual_duration_seconds'],
                   main_packets=main['counts']['valid_outer_packets'], main_status=main['status'],
                   full_status=summary['scopes']['full_run']['status'],
                   full_review_reasons=';'.join(summary['scopes']['full_run']['review_reasons']),
                   main_rate_Hz=main['valid_outer_packet_rate_Hz'],
                   main_Lmean_B=main['Lmean_valid_packet_B'],
                   main_packet_Mbit_s=main['packet_completion_Mbit_per_s'],
                   main_raw_arrival_Mbit_s=main['raw_arrival_Mbit_per_s'],
                   main_K_ESKD_mean=main['K_ESKD_pooled']['mean'],
                   main_q_ESKF=main['q_ESKF'],
                   main_ESKF_count=main['counts'].get('ESKF', 0),
                   main_ESKD_count=main['counts'].get('ESKD', 0),
                   source_local_firmware=meta['local_provenance']['firmware_variant'],
                   deployment_confirmed=meta['deployment_confirmed'],
                   main_eligible=eligible, main_review_reasons=';'.join(main['review_reasons']),
                   main_outer_crc_errors=main['counts'].get('outer_crc_error', 0),
                   main_outer_missing_sequence_numbers=main['counts'].get('outer_missing_sequence_numbers', 0),
                   main_missing_valid_expected_updates=main['counts'].get('missing_valid_expected_updates', 0),
                   main_interior_unassigned_raw_bytes=main['counts'].get('interior_unassigned_raw_bytes', 0),
                   source_review=HERE.name, timing_note='', replacement_batch_id='',
                   primary_matrix_selected=eligible,
                   selection_reason='original_complete_three_window_batch' if eligible else 'CHECK_retained_for_diagnostic_review')
        index.append(row); groups[(meta['N'], module)].append(row)
        run_files = []
        for p in sorted(source.iterdir()):
            assert p.is_file() and not p.is_symlink()
            before = p.stat()
            with p.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            after = p.stat()
            assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
            entry = dict(run_id=run_id, file_name=p.name, old_path=str(p.resolve()),
                         new_path=str((target / p.name).resolve()), old_relative_path=f'{run_id}/{p.name}',
                         new_relative_path=f'{target_rel}/{p.name}', bytes=p.stat().st_size, sha256=digest,
                         source_review=HERE.name)
            files.append(entry); run_files.append(entry)
        raw = next(f for f in run_files if f['file_name'] == 'mul1_raw.bin')
        assert raw['sha256'] == summary['raw_sha256'] and raw['bytes'] == summary['recorded_bytes']
        runs.append(dict(run_id=run_id, source=str(source.resolve()), destination=str(target.resolve()), files=run_files))
    expected = {(n, '_'.join(f'M{i}' for i in slots)) for n in range(1, 5) for slots in combinations(range(4), n)}
    assert set(groups) == expected
    assert len({r['batch_id'] for r in index}) == 15
    for rows in groups.values():
        assert len(rows) == 3 and {r['repeat'] for r in rows} == {1, 2, 3}
        assert len({r['batch_id'] for r in rows}) == 1
    backup = HERE / 'before_catalog'
    backup.mkdir(exist_ok=True)
    for p in DATA.iterdir():
        if p.is_file() and p.suffix.lower() in ('.csv', '.md'):
            assert not (backup / p.name).exists()
            shutil.copy2(p, backup / p.name)
    plan = dict(prepared_at=datetime.now().astimezone().isoformat(), data_root=str(DATA.resolve()),
                status='planned', rule='DELTA/Zero_load/N=<N>/200Hz/<slots>/Repeat_<within-batch-repeat>',
                collision_policy='abort; never overwrite or renumber another batch',
                original_file_content_policy='preserve every byte, timestamped identifiers, and embedded old paths',
                runs=runs, total_runs=len(runs), total_files=len(files), total_bytes=sum(f['bytes'] for f in files))
    (HERE / 'organization_plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (HERE / 'snapshot.json').write_text(json.dumps({
        'run_ids': [r['run_id'] for r in index], 'first_run': FIRST, 'last_run': LAST,
        'raw_bytes': sum(f['bytes'] for f in files if f['file_name'] == 'mul1_raw.bin'),
        'run_count': len(runs), 'combination_count': len(groups), 'batch_count': 15,
        'analysis_window': '10 s to actual completed duration, approximately 30 s',
        'unit': 'three consecutive time windows under one setup per module combination; no independent setup replication',
        'schema': {'K_ESKD': 'mask population over ordinary ESKD only, 0..480',
                   'q_ESKF': 'ESKF/(ESKF+ESKD) among valid module frames, cause unknown',
                   'Lmean_B': 'valid outer packet bytes / valid outer packets',
                   'rate_Hz': 'valid outer packets / actual main-window duration',
                   'Mbit_s': '8*valid outer packet bytes/main duration/1e6'},
        'scope': 'All 45 completed DELTA zero-load captures; later incoming captures excluded.'
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write_csv(HERE / 'path_map.csv', files)
    write_csv(HERE / 'run_index.csv', index)
    print(json.dumps({k: plan[k] for k in ['status', 'total_runs', 'total_files', 'total_bytes']}))

if __name__ == '__main__':
    main()
