"""Audit six completion-run CSV timelines; only timing_audit.json is written."""
import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data'
RUN_IDS = {
    '20260907_004948_668301', '20260907_005028_724004', '20260907_005108_797842',
    '20260907_005250_875035', '20260907_005330_930696', '20260907_005410_996854',
}


def main():
    # Reuse the previous, read-only CSV timing calculations without invoking its
    # 12-run main function. The helper hash records the exact implementation.
    helper = HERE.parent / '20260907_n3_full_review' / 'audit_timing.py'
    namespace = {'__name__': 'completion_timing_helpers', '__file__': str(helper)}
    exec(compile(helper.read_text(encoding='utf-8'), str(helper), 'exec'), namespace)
    namespace.update(HERE=HERE, DATA=DATA)
    with (HERE / 'run_index.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 6 and {r['run_id'] for r in rows} == RUN_IDS
    records = [namespace['audit'](row) for row in rows]
    result = {
        'schema_version': 1,
        'scope': 'Six completion captures only; summary/CSV timing, independent raw integrity audit is separate',
        'helper_relative_path': '../20260907_n3_full_review/audit_timing.py',
        'helper_sha256': hashlib.sha256(helper.read_bytes()).hexdigest(),
        'bridge_timestamp_definition': 'MUL1 host_ms is Teensy millis() at enqueueMultiPacket; not physical scan or USB transaction time',
        'pc_timestamp_definition': 'Packet-completion observation; buffered packets can share a timestamp',
        'selection_policy': 'All three runs in each new batch retained, including the 278.7935 ms PC-observation interval run',
        'runs': records,
    }
    (HERE / 'timing_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Wrote timing_audit.json for six completion runs; measured files unchanged.')


if __name__ == '__main__':
    main()
