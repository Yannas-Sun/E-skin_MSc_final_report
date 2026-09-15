"""Independent post-organization filesystem, provenance, and document checks."""
from pathlib import Path
import csv,hashlib,json,re

HERE=Path(__file__).resolve().parent
DATA=HERE.parents[1]/'data'
def table(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))
def sha(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()
index=table(DATA/'run_index.csv')
assert len(index)==111 and len({r['run_id'] for r in index})==111
assert not [p for p in DATA.iterdir() if p.is_dir() and re.fullmatch(r'\d{8}_\d{6}_\d{6}',p.name)]
lookup={r['run_id']:r for r in index}
for row in index:
    directory=(DATA/row['new_relative_path']).resolve()
    assert directory.is_relative_to(DATA.resolve()) and directory.is_dir()
    summary=json.loads((directory/'summary.json').read_text(encoding='utf-8-sig'))
    assert summary['run_id']==row['run_id']
    assert str(summary['metadata']['repeat'])==row['repeat']
    assert len(summary['metadata']['target_modules'])==int(row['N'])
    assert summary['scopes']['main']['status']==row['main_status']
paths=table(DATA/'path_map.csv')
assert len(paths)==666 and len({(r['run_id'],r['file_name']) for r in paths})==666
for entry in paths:
    path=Path(entry['new_path'])
    assert path.resolve().is_relative_to(DATA.resolve())
    assert path.parent.resolve()==(DATA/lookup[entry['run_id']]['new_relative_path']).resolve()
    assert path.stat().st_size==int(entry['bytes'])
    assert sha(path)==entry['sha256'],path
current_move=table(HERE/'path_map.csv')
assert len(current_move)==140
for entry in current_move:assert sha(Path(entry['new_path']))==entry['sha256']
for entry in json.loads((HERE/'protected_views.json').read_text()):assert sha(Path(entry['path']))==entry['sha256']
baseline=table(DATA/'primary_matrix.csv');dynamic=table(DATA/'dynamic_analysis_selected.csv');selected=table(DATA/'analysis_selected.csv')
assert len(baseline)==90 and len(dynamic)==12 and len(selected)==102
assert {r['run_id'] for r in selected}=={r['run_id'] for r in baseline+dynamic}
assert all(r['condition']=='zero_load' for r in baseline)
assert all(r['source_review']!='20260907_n4_full_coverage_review' for r in selected)
for folder,n in [(DATA,111),(DATA/'DELTA',63),(DATA/'DELTA/Dynamic_load',18)]:
    assert len(table(folder/'run_index.csv'))==n
for filename in ['all_runs_diagnostic_statistics.csv','all_pass_group_statistics.csv','batch_statistics.csv']:
    root=table(DATA/filename)
    delta=table(DATA/'DELTA'/filename)
    dyn=table(DATA/'DELTA/Dynamic_load'/filename)
    assert delta==[r for r in root if r['mode']=='DELTA']
    assert dyn==[r for r in delta if r['condition']!='zero_load']
documents=[HERE/'FINAL_SUMMARY_CN.md',DATA/'README.md',DATA/'DELTA/README.md',DATA/'DELTA/Dynamic_load/README.md',
    DATA/'DELTA/Dynamic_load/N=1/200Hz/M1/Large_area/README.md',HERE.parent/'20260907_n4_full_coverage_review/REVIEW_CN.md']
plan=json.loads((HERE/'organization_plan.json').read_text(encoding='utf-8'))
documents+=sorted({Path(run['destination']).parent/'README.md' for run in plan['runs']})
links=0
for path in documents:
    text=path.read_text(encoding='utf-8')
    assert '\ufffd' not in text
    for target in re.findall(r'\]\(([^)]+)\)',text):
        target=target.strip('<>').split('#')[0]
        if not target or '://' in target:continue
        assert (path.parent/target).resolve().exists(),(path,target)
        links+=1
result=dict(status='PASS',run_count=111,original_measurement_files_sha256_checked=len(paths),
    original_measurement_bytes=sum(int(r['bytes']) for r in paths),current_move_files_sha256_checked=140,
    zero_load_primary=90,dynamic_complete_batch_selected=12,analysis_selected=102,
    root_DELTA_dynamic_aggregation_consistent=True,documents_checked=len(documents),local_links_checked=links,
    source_summary_identity_and_original_GUI_status_preserved=True,no_unclassified_run_directories=True)
(HERE/'final_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
