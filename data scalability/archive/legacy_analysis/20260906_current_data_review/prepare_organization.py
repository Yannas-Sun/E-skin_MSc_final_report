"""Prepare a reversible, hash-checked plan for the 12 completed FULL captures.

This snapshot script never moves or changes a measured file. Apply the reviewed
plan with apply_organization.ps1. Existing target directories are rejected.
"""
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import csv
import hashlib
import json
import statistics

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data'
RUN_IDS = '''20260906_225934_745706 20260906_230014_784220 20260906_230054_835519
20260906_230200_451593 20260906_230240_486802 20260906_230320_515930
20260906_230445_150722 20260906_230525_193234 20260906_230605_248880
20260906_230909_089519 20260906_230949_124162 20260906_231029_180830'''.split()
REQUIRED = {'events.jsonl', 'experiment_log.md', 'module_log.csv',
            'mul1_raw.bin', 'packet_log.csv', 'summary.json'}


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    runs, files, index = [], [], []
    groups = defaultdict(list)
    destinations = set()
    for run_id in RUN_IDS:
        source = DATA / run_id
        summary = json.loads((source/'summary.json').read_text(encoding='utf-8-sig'))
        meta = summary['metadata']
        window = summary['scopes']['main']
        assert summary['run_id'] == run_id and summary['schema_version'] == 2
        assert summary['completed_requested_duration'] and summary['reason'] == 'capture duration reached'
        assert meta['target_mode'] == 'FULL' and meta['condition'] == 'zero_load'
        assert meta['target_hz'] == 200 and meta['N'] == 1 and len(meta['target_modules']) == 1
        assert window['status'] == 'PASS' and not window['review_reasons']
        assert meta['live_parser_continuous_across_recordings']
        assert {p.name for p in source.iterdir()} == REQUIRED
        module = 'M' + str(meta['target_modules'][0])
        repeat = int(meta['repeat'])
        assert repeat in (1, 2, 3) and repeat == meta['batch_repeat_index']
        target_rel = f'FULL/N=1/200Hz/{module}/Repeat_{repeat}'
        target = DATA / target_rel
        assert target_rel not in destinations and not target.exists(), target
        destinations.add(target_rel)
        row = dict(run_id=run_id, started_at=summary['started_at'],
                   mode='FULL', condition='zero_load', N=1, target_hz=200,
                   modules=module, block=meta['block'], batch_id=meta['batch_id'],
                   repeat=repeat, old_relative_path=run_id, new_relative_path=target_rel,
                   duration_s=summary['duration_seconds'],
                   main_duration_s=window['actual_duration_seconds'],
                   main_packets=window['counts']['valid_outer_packets'],
                   main_status=window['status'], full_status=summary['scopes']['full_run']['status'],
                   full_review_reasons=';'.join(summary['scopes']['full_run']['review_reasons']),
                   main_rate_Hz=window['valid_outer_packet_rate_Hz'],
                   main_Lmean_B=window['Lmean_valid_packet_B'],
                   main_packet_Mbit_s=window['packet_completion_Mbit_per_s'],
                   main_raw_arrival_Mbit_s=window['raw_arrival_Mbit_per_s'],
                   source_local_firmware=meta['local_provenance']['firmware_variant'],
                   deployment_confirmed=meta['deployment_confirmed'])
        index.append(row)
        groups[module].append(row)
        run_files = []
        for path in sorted(source.iterdir()):
            assert path.is_file() and not path.is_symlink()
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            entry = dict(run_id=run_id, file_name=path.name,
                         old_path=str(path.resolve()), new_path=str((target/path.name).resolve()),
                         old_relative_path=f'{run_id}/{path.name}',
                         new_relative_path=f'{target_rel}/{path.name}',
                         bytes=path.stat().st_size,
                         sha256=digest)
            files.append(entry)
            run_files.append(entry)
        runs.append(dict(run_id=run_id, source=str(source.resolve()),
                         destination=str(target.resolve()), files=run_files))
    stats = []
    for module, rows in sorted(groups.items()):
        assert len(rows) == 3 and {r['repeat'] for r in rows} == {1, 2, 3}
        assert len({r['batch_id'] for r in rows}) == 1
        item = dict(modules=module, N=1, target_hz=200, condition='zero_load',
                    temporal_repeat_n=3, batch_n=1, batch_id=rows[0]['batch_id'])
        for source_key, name in [('main_rate_Hz', 'rate_Hz'),
                                 ('main_packet_Mbit_s', 'packet_Mbit_s'),
                                 ('main_raw_arrival_Mbit_s', 'raw_arrival_Mbit_s'),
                                 ('main_Lmean_B', 'Lmean_B')]:
            values = [r[source_key] for r in rows]
            item[name+'_mean'] = statistics.mean(values)
            item[name+'_sample_sd'] = statistics.stdev(values)
        stats.append(item)
    plan = dict(prepared_at=datetime.now().astimezone().isoformat(),
                data_root=str(DATA.resolve()), status='planned',
                rule='FULL/N=1/200Hz/M<slot>/Repeat_<within-batch-repeat>',
                collision_policy='abort; never overwrite or renumber another batch',
                original_file_content_policy='preserve every byte including embedded old paths',
                runs=runs, total_runs=len(runs), total_files=len(files),
                total_bytes=sum(f['bytes'] for f in files))
    (HERE/'organization_plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    write_csv(HERE/'path_map.csv', files)
    write_csv(HERE/'run_index.csv', index)
    write_csv(HERE/'group_statistics.csv', stats)
    print(json.dumps({k: plan[k] for k in ('status','total_runs','total_files','total_bytes')}, indent=2))
    for item in stats:
        print(item['modules'], item['rate_Hz_mean'], item['rate_Hz_sample_sd'])


if __name__ == '__main__':
    main()
