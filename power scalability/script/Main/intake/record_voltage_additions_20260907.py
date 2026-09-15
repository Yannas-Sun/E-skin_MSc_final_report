"""Record two three-module ZERO voltage configurations and a separate M0 retest.

All numbers were visually transcribed from the supplied photographs. The user
identified the old contact issue as a supply wire/connector fault, not a probe
measurement fault. Existing raw records and photographs are never overwritten.
"""
from pathlib import Path
from decimal import Decimal
import csv
import io
import json
import yaml
from record_voltage_additions_20260906 import sha, write_new_or_identical

ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if parent.name == "power scalability" and (parent / "DATA").is_dir()
)
PARENT = ROOT/'DATA/raw/canonical/power_experiment_records/transmission/n=3'
OUTPUT = ROOT/'DATA/raw/intake/voltage_additions_20260907'
EVENT_PATH = ROOT/'DATA/raw/canonical/power_experiment_records/quality_events/supply_contact_M0_20260907.json'
OLD_RUN = 'PS01_N3_F200_ZERO_M0-M1-M2_USB_RX_R1'
RETEST_RUN = 'PS01_N3_F200_ZERO_M0-M1-M2_USB_RX_VOLTAGE_RETEST_R1'
READINGS = {
    'M0-M1-M3': [('000539','3.277','3.277','3.277'), ('001239','3.241','3.241','3.241'),
                 ('001305','3.248','3.247','3.248'), ('001324','3.249','3.249','3.249')],
    'M0-M2-M3': [('002056','3.276','3.276','3.277'), ('002247','3.241','3.241','3.241'),
                 ('002315','3.242','3.242','3.242'), ('002343','3.244','3.244','3.244')],
}

def base_record(run_id, modules, measured):
    record = {
        'run_id': run_id, 'measurement_scope': 'VOLTAGE_ONLY',
        'record_status': 'MEASURED', 'data_quality': 'INCOMPLETE',
        'date': None, 'measurement_start_time': None, 'operator': None,
        'module_count': len(modules), 'module_ids': ','.join('Module'+m[1:] for m in modules),
        'measured_module_ids': ','.join('Module'+m[1:] for m in measured),
        'frequency_hz': 200, 'protocol_mode': 'FULL', 'load': 'ZERO',
        'load_mass_g': 0, 'load_application': 'NONE',
        'host_usb_polling_state': 'CONTINUOUS_USB_READ',
        'operating_condition_basis': 'Existing FULL/200 Hz continuous-read ZERO voltage supplement series and folder; not independently visible in meter photos.',
        'instrument_model': 'FNIRSI 2C53P', 'DMM_voltage_mode': 'DC',
        'measurement_duration_s': None, 'warmup_duration_s': None,
        'reading_semantics': 'avg fields preserve main display readings for schema compatibility; not verified time averages',
        'reset_count': None, 'current_limit_count': None, 'brownout_count': None,
        'data_stop_count': None, 'data_gap_count': None,
        'T_regulator_C': None, 'T_teensy_C': None,
    }
    for field in ('avg_V','min_V','max_V'):
        record['V_source_'+field] = None
    for module in modules:
        for field in ('avg_V','min_V','max_V'):
            record['V_module'+module[1:]+'_'+field] = None
        for field in ('avg_mA','min_mA','max_mA'):
            record['I_module'+module[1:]+'_'+field] = None
        record['T_module'+module[1:]+'_stm32_C'] = None
    return record

def main():
    protected_paths = [ROOT/'DATA/raw/canonical/power_raw.csv', *sorted((ROOT/'DATA/raw/canonical/power_experiment_records').rglob('*.yaml'))]
    protected = {str(p): sha(p) for p in protected_paths}
    planned, rows, records, photos = [], [], [], []

    def add_point(record, role, photo, main_v, min_v, max_v, source_main=None):
        assert photo.is_file(), photo
        assert Decimal(min_v) <= Decimal(main_v) <= Decimal(max_v)
        prefix = 'V_source' if role == 'SOURCE' else 'V_module'+role[1:]
        for field, value in [('avg_V',main_v),('min_V',min_v),('max_V',max_v)]:
            record[prefix+'_'+field] = float(value)
        photos.append({'path': photo.relative_to(ROOT).as_posix(), 'sha256': sha(photo)})
        rows.append({'run_id': record['run_id'], 'combo': record['module_ids'].replace('Module','M').replace(',','+'),
                     'load': 'ZERO', 'point': role, 'V_main_V': main_v, 'V_min_V': min_v, 'V_max_V': max_v,
                     'source_to_module_drop_mV': '' if role == 'SOURCE' or source_main is None else str((Decimal(source_main)-Decimal(main_v))*1000),
                     'photo': photo.relative_to(ROOT).as_posix(), 'n_run': 1})
        return {'role': role, 'file': photo.name if photo.parent.name == 'zero_load' else '../'+photo.name, 'sha256': sha(photo)}

    def stage(path, record):
        encoded = ('# Original photographs and earlier raw records are retained unchanged.\n'+yaml.safe_dump(record, sort_keys=False, allow_unicode=True)).encode('utf-8')
        planned.append((path, encoded))
        import hashlib
        records.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(encoded).hexdigest()})

    for combo, readings in READINGS.items():
        modules = combo.split('-')
        run_id = f'PS01_N3_F200_ZERO_{combo}_USB_RX_VOLTAGE_R1'
        record = base_record(run_id, modules, modules)
        record.update({'record_kind': 'COMBINATION_VOLTAGE', 'photo_filename_date': '2026-09-07',
                       'measurement_order': ['SOURCE', *modules],
                       'module_order_basis': 'Ascending module order retained from user instruction for the voltage supplement series.',
                       'source_order_basis': 'First photograph assigned to source following established capture sequence; probe endpoint is not identifiable.',
                       'source_order_independently_verified': False})
        evidence = []
        for role, (time, main_v, min_v, max_v) in zip(['SOURCE', *modules], readings):
            evidence.append(add_point(record, role, PARENT/combo/f'IMG_20260907_{time}.jpg', main_v, min_v, max_v, readings[0][1]))
        record['voltage_photo_evidence'] = evidence
        record['observation'] = 'ZERO voltage-only supplement; all three connected modules measured in ascending order. No current, temperature, fault or elapsed-time observations supplied.'
        stage(PARENT/combo/'zero_load'/f'{run_id}.yaml', record)

    record = base_record(RETEST_RUN, ['M0','M1','M2'], ['M0'])
    record.update({'record_kind': 'MODULE_VOLTAGE_RETEST', 'photo_filename_date': None,
                   'measurement_order': ['M0'], 'retest_of_run_id': OLD_RUN,
                   'connection_condition': 'AFTER_USER_REPORTED_SUPPLY_CONTACT_REPAIR',
                   'quality_event_id': 'SUPPLY_CONTACT_M0_N3_ZERO_20260907',
                   'independent_repeat_of_original_condition': False,
                   'observation': 'User identified the earlier anomalous reading as caused by a supply wire or connector contact issue. M0_new.jpg records M0 after correcting contact. No source, M1 or M2 voltage was supplied for this retest. Do not merge old source/current readings into a fictitious simultaneous repaired run.'})
    photo = PARENT/'M0-M1-M2/zero_load/M0_new.jpg'
    record['voltage_photo_evidence'] = [add_point(record, 'M0', photo, '3.241', '3.241', '3.241')]
    stage(PARENT/'M0-M1-M2/zero_load'/f'{RETEST_RUN}.yaml', record)

    old_path = PARENT/'M0-M1-M2/zero_load'/f'{OLD_RUN}.yaml'
    old_record = yaml.safe_load(old_path.read_text(encoding='utf-8-sig'))
    assert [old_record['V_module0_'+f] for f in ('avg_V','min_V','max_V')] == [3.224,3.224,3.225]
    event = {
        'event_id': 'SUPPLY_CONTACT_M0_N3_ZERO_20260907', 'reported_date': '2026-09-07',
        'event_type': 'USER_CONFIRMED_SUPPLY_WIRE_OR_CONNECTOR_CONTACT_FAULT',
        'evidence_basis': 'User clarification: 供电线或供电接头接触不良',
        'affected_run_id': OLD_RUN, 'affected_record_path': old_path.relative_to(ROOT).as_posix(),
        'affected_record_sha256': sha(old_path), 'affected_module': 'M0',
        'original_M0_voltage_V': {'main': 3.224, 'min': 3.224, 'max': 3.225},
        'interpretation': 'Retain as an actual supply-connection fault condition; do not describe it as a voltmeter/probe measurement error.',
        'normal_connection_analysis_action': 'Exclude the original fault-condition run from normal-connection summaries; preserve it in fault-condition/history outputs.',
        'other_fields_action': 'Preserve original currents, source/M1/M2 voltages and temperatures as measurements in the original run; they are not revalidated after repair.',
        'replacement_run_id': RETEST_RUN,
        'replacement_scope': 'M0 voltage only, after contact correction; no simultaneous replacement source voltage supplied.',
        'replacement_M0_voltage_V': {'main': 3.241, 'min': 3.241, 'max': 3.241},
        'drop_recalculation_allowed_with_old_source': False,
        'repeatability_pooling_allowed': False,
        'report_2_1_implications': ['3.224 V and 89 mV describe a contact-fault condition, not the normal-connection minimum.',
                                   'The associated voltage-drop result and the original N3 current/prediction point require a fault-condition label or separate analysis.',
                                   'Do not claim fault-free operation; default zero counters do not override this known contact fault.'],
        'published_report_updated': False,
    }
    encoded_event = (json.dumps(event, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    # A later user clarification refines scope without altering the original
    # photo transcription. Preserve that clarification when reproducing intake.
    if EVENT_PATH.exists():
        current_event = json.loads(EVENT_PATH.read_text(encoding='utf-8'))
        if current_event.get('event_revision', 1) >= 2:
            for key in ('event_id', 'affected_run_id', 'affected_record_sha256', 'replacement_run_id'):
                assert current_event[key] == event[key], key
            event = current_event
            encoded_event = EVENT_PATH.read_bytes()
    planned.append((EVENT_PATH, encoded_event))
    for path, encoded in planned:
        if path.exists() and path.read_bytes() != encoded:
            raise ValueError(f'Refusing to overwrite a different record: {path}')
    for path, encoded in planned:
        write_new_or_identical(path, encoded)
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    write_new_or_identical(OUTPUT/'voltage_readings.csv', ('\ufeff'+stream.getvalue()).encode('utf-8'))
    assert protected == {str(p): sha(p) for p in protected_paths}
    assert all(sha(ROOT/p['path']) == p['sha256'] for p in photos)
    manifest = {'batch': '20260907', 'combination_records': 2, 'partial_retest_records': 1,
                'source_voltage_points': 2, 'module_voltage_points': 7,
                'records': records, 'photographs': photos,
                'quality_event': {'path': EVENT_PATH.relative_to(ROOT).as_posix(), 'sha256': sha(EVENT_PATH)},
                'existing_raw_files_unchanged': True, 'photographs_unchanged': True,
                'published_report_updated': False, 'report_2_1_outputs_overwritten': False}
    if event.get('event_revision', 1) >= 2:
        manifest['quality_event_revision'] = event['event_revision']
        manifest['prior_scope_manifest'] = 'history/before_M0_only_scope_clarification/DATA/raw/intake/voltage_additions_20260907/source_manifest.json'
    write_new_or_identical(OUTPUT/'source_manifest.json', (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'combination_records': 2, 'M0_retest_V': 3.241, 'voltage_points': 9, 'quality_event': str(EVENT_PATH), 'old_readings_preserved': True}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
