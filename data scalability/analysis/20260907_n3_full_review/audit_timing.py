"""Read-only timing audit of the indexed N=3 snapshot; writes only timing_audit.json."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data'


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def locate(row):
    candidates = [DATA / row['new_relative_path'], DATA / row['old_relative_path']]
    found = [p for p in candidates if (p / 'summary.json').is_file()]
    if len(found) != 1:
        raise ValueError(f"Expected one current location for {row['run_id']}: {found}")
    return found[0]


def packet_view(row):
    return {key: row[key] for key in ('csv_line', 'packet_sequence', 'elapsed_s', 'host_ms')}


def audit(row):
    directory = locate(row)
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8-sig'))
    assert summary['run_id'] == row['run_id']
    log = directory / 'packet_log.csv'
    packets = read_csv(log)
    for line, packet in enumerate(packets, 2):
        packet['csv_line'] = line
    main = [p for p in packets if p['main_window'] == 'True'
            and p['outer_crc_ok'] == 'True' and p['parse_ok'] == 'True']
    gaps = []
    for previous, current in zip(main, main[1:]):
        gaps.append({
            'pc_completion_gap_s': float(current['elapsed_s']) - float(previous['elapsed_s']),
            'bridge_enqueue_gap_ms': (int(current['host_ms']) - int(previous['host_ms'])) % (2**32),
            'mul1_sequence_step': (int(current['packet_sequence']) - int(previous['packet_sequence'])) % (2**32),
            'previous': packet_view(previous), 'current': packet_view(current),
        })
    window = summary['scopes']['main']
    assert len(main) == window['counts']['valid_outer_packets']
    bins = [{'start_s': start, 'end_s': start + 5,
             'valid_packets': sum(start <= float(p['elapsed_s']) < start + 5 for p in main)}
            for start in range(10, 40, 5)]
    over_40 = sum(float(p['elapsed_s']) >= 40 for p in main)
    assert sum(b['valid_packets'] for b in bins) + over_40 == len(main)
    bridge_max = max(gaps, key=lambda g: g['bridge_enqueue_gap_ms'])
    adjacent_sequences = {bridge_max[side]['packet_sequence'] for side in ('previous', 'current')}
    modules = [p for p in read_csv(directory / 'module_log.csv')
               if p['packet_sequence'] in adjacent_sequences and p['valid'] == 'True']
    module_steps = {}
    for module in summary['metadata']['target_modules']:
        selected = [p for p in modules if int(p['module_id']) == module]
        assert len(selected) == 2
        module_steps[f'M{module}'] = {
            'sequences': [int(p['sequence']) for p in selected],
            'step': (int(selected[1]['sequence']) - int(selected[0]['sequence'])) % (2**32),
        }
    return {
        'run_id': row['run_id'], 'modules': row['modules'], 'repeat': int(row['repeat']),
        'new_relative_path': row['new_relative_path'],
        'packet_log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
        'main_status': window['status'], 'main_eligible': row['main_eligible'] == 'True',
        'main_duration_s': window['actual_duration_seconds'], 'main_valid_packets': len(main),
        'main_packet_rate_Hz': window['valid_outer_packet_rate_Hz'],
        'main_packet_Mbit_s': window['packet_completion_Mbit_per_s'],
        'main_review_reasons': window['review_reasons'],
        'main_session_error_deltas': {key: value for key, value in window['session_counter_delta_at_packet_observation'].items()
                                      if key not in ('candidate_packets', 'valid_packets')},
        'main_trailing_raw_bytes': window['counts'].get('trailing_unassigned_raw_bytes', 0),
        'first': packet_view(main[0]), 'last': packet_view(main[-1]),
        'pc_5s_bins': bins, 'main_packets_at_or_after_40_s': over_40,
        'pc_1s_counts_10_to_40': [sum(start <= float(p['elapsed_s']) < start + 1 for p in main)
                                 for start in range(10, 40)],
        'max_pc_gap': max(gaps, key=lambda g: g['pc_completion_gap_s']),
        'max_bridge_gap': bridge_max,
        'module_sequence_steps_at_max_bridge_gap': module_steps,
        'zero_pc_gap_count': sum(g['pc_completion_gap_s'] == 0 for g in gaps),
        'bridge_gap_ms_histogram': dict(sorted(Counter(g['bridge_enqueue_gap_ms'] for g in gaps).items())),
        'nonconsecutive_valid_mul1_steps': [g for g in gaps if g['mul1_sequence_step'] != 1],
    }


def main():
    rows = read_csv(HERE / 'run_index.csv')
    assert len(rows) == 12 and len({r['run_id'] for r in rows}) == 12
    result = {
        'schema_version': 1,
        'scope': 'Fixed indexed N=3 campaign; packet_log and summary timing, not independent raw CRC verification',
        'bridge_timestamp_definition': 'MUL1 host_ms: Teensy millis() when enqueueMultiPacket writes offset 16; not a physical scan timestamp',
        'pc_timestamp_definition': 'Packet completion observation; multiple packets can share a buffered-read timestamp',
        'eligibility_policy': 'Main integrity PASS only; no packet-rate filter; low-rate PASS remains included',
        'runs': [audit(row) for row in rows],
    }
    (HERE / 'timing_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Wrote timing_audit.json for {len(rows)} runs; measured files unchanged.")


if __name__ == '__main__':
    main()
