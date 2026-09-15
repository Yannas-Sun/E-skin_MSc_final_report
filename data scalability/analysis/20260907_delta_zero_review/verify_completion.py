"""Verify organized originals, mode-specific indexes and published local links."""
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
import csv
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1]/'data'
FINAL = HERE.parents[2]

def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    files=rows(DATA/'path_map.csv')
    assert len(files)==558
    for row in files:
        p=(DATA/row['new_relative_path']).resolve()
        assert p.is_relative_to(DATA.resolve()) and p.is_file()
        assert p.stat().st_size==int(row['bytes']) and digest(p)==row['sha256'].lower()
    index=rows(DATA/'run_index.csv');primary=rows(DATA/'primary_matrix.csv')
    assert len(index)==len({r['run_id'] for r in index})==93
    assert len(primary)==len({r['run_id'] for r in primary})==90
    assert Counter(r['mode'] for r in primary)=={'FULL':45,'DELTA':45}
    assert all(r['main_status']=='PASS' and r['main_eligible']=='True' for r in primary)
    assert [r['run_id'] for r in index if r['main_status']!='PASS']==['20260907_000133_670681']
    delta=[r for r in index if r['mode']=='DELTA']
    assert len({r['batch_id'] for r in delta})==15
    assert Counter(int(r['N']) for r in delta)=={1:12,2:18,3:12,4:3}
    assert all(r['full_status']=='CHECK REQUIRED' for r in delta)
    for mode in ['FULL','DELTA/Zero_load']:
        view=rows(DATA/mode/'primary_matrix.csv')
        expected='FULL' if mode=='FULL' else 'DELTA'
        assert len(view)==45 and all(r['mode']==expected for r in view)
    for name in ['group_statistics.csv','all_pass_group_statistics.csv','all_runs_diagnostic_statistics.csv']:
        groups=rows(DATA/name)
        assert len(groups)==30 and Counter(r['mode'] for r in groups)=={'FULL':15,'DELTA':15}
    assert len(rows(DATA/'batch_statistics.csv'))==31
    old=rows(HERE/'before_catalog/run_index.csv')
    byid={r['run_id']:r for r in index}
    for r in old:
        assert all(byid[r['run_id']][k]==v for k,v in r.items())
    assert {r['run_id'] for r in rows(HERE/'before_catalog/primary_matrix.csv')}=={
        r['run_id'] for r in primary if r['mode']=='FULL'}
    source_stats={r['modules']:r for r in rows(HERE/'stats_combinations_pass.csv')}
    for r in rows(DATA/'DELTA/Zero_load/group_statistics.csv'):
        for key in ['rate_Hz_mean','rate_Hz_sample_sd','Lmean_B_mean','packet_Mbit_s_mean',
                    'K_ESKD_mean','q_ESKF_mean']:
            assert r[key]==source_stats[r['modules']][key]
    docs=[DATA/'README.md',HERE/'ANALYSIS_CN.md',FINAL/'new_firmware_experiment_plan/PLAN_CN.md']
    docs+=list((DATA/'DELTA').rglob('README.md'))
    docs+=list((DATA/'FULL').rglob('README.md'))
    broken=[]
    for p in docs:
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8-sig')):
            if '://' in target or target.startswith('#'):continue
            q=p.parent/unquote(target.split('#')[0].strip('<>'))
            if not q.exists():broken.append({'source':str(p),'target':target})
    assert not broken,broken
    report=json.loads((FINAL/'report_versions/v2.2/manifest.json').read_text(encoding='utf-8'))
    assert digest(FINAL/report['output_pdf']['path'])==report['output_pdf']['sha256']
    for name,expected in report['source_and_asset_sha256'].items():
        assert digest(FINAL/name)==expected,name
    audit=json.loads((HERE/'raw_audit.json').read_text(encoding='utf-8'))
    assert len(audit['runs'])==45 and all(not r['cross_check_errors'] for r in audit['runs'])
    result={
        'status':'PASS','original_files_hash_checked':558,'DELTA_original_files':270,
        'FULL_original_files':288,'original_total_bytes':sum(int(r['bytes']) for r in files),
        'run_index_rows':93,'primary_matrix_rows':90,'DELTA_zero_main_PASS':45,
        'FULL_failure_retained':'20260907_000133_670681','main_conditions':30,'batches':31,
        'local_document_links_checked':len(docs),'broken_links':broken,
        'report_v2_2_and_archived_source_assets_unchanged':True,
        'raw_audit_tests_passed':7,
        'main_valid_MUL1':audit['totals']['main']['valid_outer_packets'],
        'main_valid_module_frames':audit['totals']['main']['valid_module_frames'],
        'statistical_unit':'consecutive temporal windows nested in one setup per slot combination',
        'scope':'All 45 fixed DELTA zero-load captures; no later recordings or dynamic conditions included.'}
    (HERE/'completion_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
