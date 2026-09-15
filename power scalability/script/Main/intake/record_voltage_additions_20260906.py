"""Transcribe the twelve visually reviewed ZERO-voltage photos; no raw overwrite.

The source-first assignment follows the established capture sequence and is
explicitly marked as an inference; the user confirmed ascending module order.
No current, temperature, timing, fault event or time average is inferred.
"""
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import csv
import hashlib
import json
import yaml

ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if parent.name == "power scalability" and (parent / "DATA").is_dir()
)
PARENT = ROOT / 'DATA/raw/canonical/power_experiment_records/transmission/n=2'
OUTPUT = ROOT / 'DATA/raw/intake/voltage_additions_20260906'
# Each entry is (photo suffix, main reading, displayed MIN, displayed MAX), V.
READINGS = {
    'M0-M2': [('231927','3.279','3.279','3.279'), ('232003','3.235','3.235','3.235'), ('232035','3.248','3.248','3.248')],
    'M0-M3': [('232855','3.279','3.278','3.279'), ('232921','3.237','3.236','3.237'), ('232941','3.241','3.241','3.242')],
    'M1-M2': [('233306','3.278','3.278','3.278'), ('233326','3.252','3.252','3.252'), ('233351','3.247','3.247','3.247')],
    'M1-M3': [('233839','3.278','3.278','3.279'), ('233906','3.248','3.247','3.248'), ('233928','3.245','3.245','3.245')],
}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_new_or_identical(path, content):
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f'Refusing to replace existing content: {path}')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

def main():
    original_files = [ROOT/'DATA/raw/canonical/power_raw.csv', *sorted((ROOT/'DATA/raw/canonical/power_experiment_records').rglob('*.yaml'))]
    protected = {str(p): sha(p) for p in original_files}
    rows, records, photo_hashes = [], [], []
    planned = []
    for combo, readings in READINGS.items():
        modules = combo.split('-')
        run_id = f'PS01_N2_F200_ZERO_{combo}_USB_RX_VOLTAGE_R1'
        record_path = PARENT/combo/'zero_load'/f'{run_id}.yaml'
        record = {
            'run_id': run_id, 'measurement_scope': 'VOLTAGE_ONLY',
            'record_status': 'MEASURED', 'data_quality': 'INCOMPLETE',
            'date': None, 'measurement_start_time': None, 'operator': None,
            'photo_filename_date': '2026-09-06',
            'module_count': 2, 'module_ids': ','.join('Module'+m[1:] for m in modules),
            'frequency_hz': 200, 'protocol_mode': 'FULL', 'load': 'ZERO',
            'load_mass_g': 0, 'load_application': 'NONE',
            'host_usb_polling_state': 'CONTINUOUS_USB_READ',
            'operating_condition_basis': 'Existing FULL/200 Hz continuous-read test series and transmission folder; not independently visible in meter photos.',
            'measurement_order': ['SOURCE', *modules],
            'module_order_basis': 'User confirmed measurements followed ascending module number.',
            'source_order_basis': 'First photograph assigned to source following established capture sequence; probe endpoint is not identifiable in these photos.',
            'source_order_independently_verified': False,
            'instrument_model': 'FNIRSI 2C53P', 'DMM_voltage_mode': 'DC',
            'measurement_duration_s': None, 'warmup_duration_s': None,
            'reading_semantics': 'avg fields preserve main display readings for schema compatibility; not verified time averages',
            'reset_count': None, 'current_limit_count': None, 'brownout_count': None,
            'data_stop_count': None, 'data_gap_count': None,
            'T_regulator_C': None, 'T_teensy_C': None,
        }
        source_main = Decimal(readings[0][1])
        evidence = []
        for role, (time, main_v, min_v, max_v) in zip(['SOURCE', *modules], readings):
            photo = PARENT/combo/f'IMG_20260906_{time}.jpg'
            if not photo.is_file():
                raise FileNotFoundError(photo)
            assert Decimal(min_v) <= Decimal(main_v) <= Decimal(max_v), photo
            entry = {'path': photo.relative_to(ROOT).as_posix(), 'sha256': sha(photo)}
            photo_hashes.append(entry)
            evidence.append({'role': role, 'file': '../'+photo.name, 'sha256': entry['sha256']})
            prefix = 'V_source' if role == 'SOURCE' else 'V_module'+role[1:]
            for field, value in [('avg_V', main_v), ('min_V', min_v), ('max_V', max_v)]:
                record[prefix+'_'+field] = float(value)
            if role != 'SOURCE':
                record['I_module'+role[1:]+'_avg_mA'] = None
                record['I_module'+role[1:]+'_min_mA'] = None
                record['I_module'+role[1:]+'_max_mA'] = None
                record['T_module'+role[1:]+'_stm32_C'] = None
            rows.append({'run_id': run_id, 'combo': combo, 'load': 'ZERO', 'point': role,
                         'V_main_V': main_v, 'V_min_V': min_v, 'V_max_V': max_v,
                         'source_to_module_drop_mV': '' if role == 'SOURCE' else str((source_main-Decimal(main_v))*1000),
                         'photo': photo.relative_to(ROOT).as_posix(),
                         'point_mapping_basis': 'source-first inference; module order confirmed by user',
                         'n_run': 1})
        record['voltage_photo_evidence'] = evidence
        record['observation'] = 'Voltage-only ZERO supplement. Currents, temperatures, timing and fault observations are unavailable. Photos retained unchanged.'
        encoded = ('# Transcribed from twelve reviewed photos; source-first assignment is documented below.\n'+yaml.safe_dump(record, sort_keys=False, allow_unicode=True)).encode('utf-8')
        planned.append((record_path, encoded))
        records.append({'path': record_path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(encoded).hexdigest()})
    # Check all destinations before performing any writes.
    for path, encoded in planned:
        if path.exists() and path.read_bytes() != encoded:
            raise ValueError(f'Record already exists with different content: {path}')
    for path, encoded in planned:
        write_new_or_identical(path, encoded)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    import io
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
    write_new_or_identical(OUTPUT/'voltage_readings.csv', ('\ufeff'+stream.getvalue()).encode('utf-8'))
    assert protected == {str(p): sha(p) for p in original_files}
    assert all(sha(ROOT/entry['path']) == entry['sha256'] for entry in photo_hashes)
    manifest = {'capture_filename_date': '2026-09-06', 'measurement_scope': 'VOLTAGE_ONLY',
                'records': records, 'photographs': photo_hashes, 'record_count': 4,
                'module_voltage_points': 8, 'source_voltage_points': 4,
                'preexisting_raw_files_unchanged': True, 'photos_unchanged': True,
                'source_first_mapping': 'inferred and explicitly documented',
                'module_order': 'ascending, confirmed by user',
                'published_report_updated': False, 'report_2_1_analysis_outputs_overwritten': False}
    write_new_or_identical(OUTPUT/'source_manifest.json', (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'records_added': 4, 'readings': 12, 'raw_and_photos_preserved': True, 'output': str(OUTPUT)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
