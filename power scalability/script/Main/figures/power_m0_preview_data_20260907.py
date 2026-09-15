"""Build an isolated preview data view; never write the report or frozen analyses."""
from __future__ import annotations
import csv
import hashlib
import json
import statistics
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if parent.name == "power scalability" and (parent / "DATA").is_dir()
)
FINAL = ROOT.parent
BASE = ROOT / 'DATA/reference/report_v2_4_analysis'
INTAKE = ROOT / 'DATA/analysis/retest_reviews/m0_n1_n2_retest_20260907'
OUT = ROOT / 'DATA/archive/m0_n1_n2_preview_20260907'

def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def write(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def snapshot():
    report = FINAL / 'Imperial College Individual Project Template_LaTeX'
    paths = list(report.rglob('*.tex')) + list((report/'figures/power').glob('*'))
    paths += list(FINAL.glob('main*.pdf'))
    for folder in (BASE, INTAKE, ROOT/'DATA/reference/report_v2_4_figures', ROOT/'DATA/reference/voltage_drop_by_N_v2_4'):
        paths += list(folder.glob('*'))
    paths += [Path(__file__).with_name(name) for name in
              ('power_retest_figures.py', 'power_retest_drop_by_count.py', 'power_revision_figures.py')]
    return {str(p.relative_to(FINAL)): digest(p) for p in sorted(set(paths)) if p.is_file()}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = OUT/'data'
    data.mkdir(exist_ok=True)
    protected = snapshot()
    branches, configs = read(BASE/'branch_readings.csv'), read(BASE/'configuration_summary.csv')
    readings = read(INTAKE/'readings.csv')
    bm = {(b['combo'], b['load'], b['module_id']): b for b in branches}
    assert len(branches) == 64 and len(configs) == 30 and len(readings) == 10
    changed = set()
    for r in readings:
        k = (r['combo'], r['load'], r['module_id'])
        b = bm[k]
        changed.add(k)
        current = r['quantity'] == 'current'
        fields = ('I_main_mA', 'I_min_mA', 'I_max_mA') if current else ('V_module_main_V', 'V_module_min_V', 'V_module_max_V')
        for dest, src in zip(fields, ('main', 'minimum', 'maximum')):
            b[dest] = r[src]
        if current:
            b['I_main_display_text_mA'] = r['main']
        else:
            b['preview_voltage_assignment_status'] = r['assignment_status']
            b['preview_voltage_value_basis'] = r['value_basis']
        provenance = json.loads(b.get('preview_targeted_readings_json') or '{}')
        provenance[r['quantity']] = r
        b['preview_targeted_readings_json'] = json.dumps(provenance, ensure_ascii=False)
        b['selected_targeted_retest'] = 'True'
        b['retest_reported_date'] = '2026-09-07'
        b['new_complete_configuration_repeat'] = 'False'
        b['preview_updated_M0'] = 'True'
        b['preview_baseline_provenance_notice'] = 'provenance_json refers to retained 2.4 baseline; preview_targeted_readings_json supersedes selected current/voltage only'
        b['preview_source_basis'] = 'retained original SOURCE, user says values not newly supplied remain unchanged; not a new synchronous measurement'
    assert len(changed) == 5
    for b in branches:
        b['source_minus_module_main_mV'] = str(1000*(D(b['V_source_main_V'])-D(b['V_module_main_V'])))
    for c in configs:
        rows = [b for b in branches if (b['combo'], b['load']) == (c['combo'], c['load'])]
        total = sum((D(b['I_main_mA']) for b in rows), D(0))
        c['I_sum_mA'] = str(total)
        c['P_source_output_estimate_mW'] = str(total*D(c['V_source_main_V']))
        for b in rows:
            c[f"I_{b['module_id']}_main_mA"] = b['I_main_mA']
            c[f"V_{b['module_id']}_main_V"] = b['V_module_main_V']
        if any((b['combo'],b['load'],b['module_id']) in changed for b in rows):
            c['assembled_with_targeted_retest'] = 'True'
            c['preview_updated_M0'] = 'True'
            c['preview_retest_reported_date'] = '2026-09-07'
            c['preview_baseline_provenance_notice'] = 'provenance_json describes baseline; selected M0 current/voltage updated in branch preview_targeted_readings_json'
    assert sum(c['assembled_with_targeted_retest']=='True' for c in configs)==7
    groups = read(BASE/'group_summary.csv')
    for g in groups:
        rows = [c for c in configs if c['load']==g['load'] and c['module_count']==g['module_count']
                and (g['photo_filename_date_batch']=='ALL' or c['photo_filename_date_batch']==g['photo_filename_date_batch'])]
        vals = [D(c[g['metric']]) for c in rows]
        g.update(n_configurations=str(len(vals)), mean=str(statistics.mean(vals)),
                 sample_SD_across_configurations=str(statistics.stdev(vals)) if len(vals)>1 else '',
                 minimum=str(min(vals)), maximum=str(max(vals)),
                 SD_meaning='Across different combinations, not independent repeatability; seven entries include targeted current retests',
                 batch_meaning='Original record photo batch retained; targeted retest dates are separate, not assigned to baseline acquisition date')
    predictions=[]
    for load in ('ZERO','MAX'):
        refs = {b['module_id']:D(b['I_main_mA']) for b in branches if b['module_count']=='1' and b['load']==load}
        for c in configs:
            if c['load']!=load or c['module_count']=='1':
                continue
            expected = sum((refs[m] for m in c['combo'].split('-')),D(0))
            residual = D(c['I_sum_mA'])-expected
            predictions.append(dict(load=load, combo=c['combo'], module_count=c['module_count'],
                I_observed_sum_mA=c['I_sum_mA'], I_prediction_from_same_load_N1_physical_modules_mA=str(expected),
                residual_mA=str(residual), residual_percent_of_prediction=str(100*residual/expected),
                N1_references_mA_json=json.dumps({m:float(v) for m,v in refs.items()}),
                additional_independent_same_condition_repeats=0,
                interpretation='Descriptive compiled sum versus separate N1 references; M0 reference uses latest current retest',
                assembled_with_targeted_retest=c['assembled_with_targeted_retest']))
    # Compare an independently generated intake summary, including all updated references.
    checks=read(INTAKE/'current_prediction_checks.csv')
    for p in predictions:
        old, = [x for x in checks if x['combo']==p['combo'] and x['load']==p['load']]
        # Use common numeric fields only; intake also retains comparison columns.
        for field in ('I_observed_sum_mA','I_prediction_from_same_load_N1_physical_modules_mA','residual_mA','residual_percent_of_prediction'):
            if field in old:
                assert abs(D(p[field])-D(old[field]))<D('1e-20'), (field,p,old)
    for name, rows in [('branch_readings.csv',branches),('configuration_summary.csv',configs),('group_summary.csv',groups),('additivity_checks.csv',predictions)]:
        write(data/name, rows)
    pending = [b for b in branches if 'PENDING' in b.get('preview_voltage_assignment_status','')]
    assert not pending, 'Preview expects the latest user-confirmed voltage assignment'
    confirmed=bm[('M0','ZERO','M0')]
    assert confirmed['preview_voltage_assignment_status']=='PHOTO_ASSIGNMENT_USER_CONFIRMED'
    assert confirmed['source_minus_module_main_mV']=='28.000'
    source_paths=list(BASE.glob('*.csv'))+[BASE/'source_manifest.json',INTAKE/'readings.csv',INTAKE/'intake_notes.json',INTAKE/'comparison_with_report_2_4.csv',Path(__file__)]
    source_paths += [ROOT/r['photo_path'] for r in readings if r['photo_path']]
    source_paths += [INTAKE/'clarifications.json']
    sources=[dict(relative_path=str(p.relative_to(ROOT)),sha256=digest(p)) for p in sorted(set(source_paths))]
    for r in readings:
        if r['photo_path']:
            assert digest(ROOT/r['photo_path'])==r['photo_sha256']
    manifest=dict(created_at_utc=datetime.now(timezone.utc).isoformat(),sources=sources,
        configuration_entries=30,branch_entries=64,new_M0_targeted_entries=5,total_current_targeted_entries=7,
        full_configuration_repeats_added=0,pending_voltage_assignment=[],
        confirmed_voltage_assignment=dict(combo='M0',load='ZERO',module='M0',V='3.252',drop_mV=28,basis='User confirmation in clarifications.json; no extra measurement'),
        wrong_M0_M1_voltage_photo_excluded=True,M0_M1_voltage_basis='User correction: main/MIN/MAX 3.251 V',
        sources_and_temperatures='Retained under user instruction; no new synchronous source measurements',
        protection_scope='Report source, published PDFs, report power figures, frozen inputs and original plotting scripts',
        protected_files_before=protected, generated_csv_sha256={name:digest(data/name) for name in
            ('branch_readings.csv','configuration_summary.csv','group_summary.csv','additivity_checks.csv')})
    (data/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    after=snapshot()
    assert all(after.get(p)==h for p,h in protected.items()), 'Protected input/report changed during data generation'
    print(json.dumps(dict(output=str(data),configurations=len(configs),branches=len(branches),groups=len(groups),predictions=len(predictions),protected_files=len(protected),report_unchanged=True),indent=2))

if __name__=='__main__':
    main()
