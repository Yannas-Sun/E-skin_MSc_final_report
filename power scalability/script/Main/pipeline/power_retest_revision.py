"""Version 2.4 selected-point view; preserves acquisitions and the 2.3 analysis.

Two partial branch retests are selected by the author's report-update request.
Configuration sums are compiled across records, never new complete trials.
"""
from pathlib import Path
from decimal import Decimal as D
import csv, json, hashlib, statistics, copy
import summarize_all_power_20260907 as base

ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if parent.name == "power scalability" and (parent / "DATA").is_dir()
)
INPUT = ROOT / 'DATA/analysis/current/all_power_review_20260907'
OUT = ROOT / 'DATA/reference/report_v2_4_analysis'
RET = ROOT / 'DATA/raw/canonical/power_experiment_records/targeted_retests'
TARGETS = [('M0-M1-M2','ZERO','M0'), ('M1-M2-M3','MAX','M3')]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rd(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def numeric(rows):
    for r in rows:
        for k,v in list(r.items()):
            if k == 'module_count': r[k] = int(v)
            elif k.startswith(('I_', 'V_', 'P_', 'T_', 'source_minus_')) and not k.endswith(('json','text_mA')):
                r[k] = D(v) if v else None
    return rows
def main():
    OUT.mkdir(exist_ok=True)
    protected = {p:sha(p) for directory in (INPUT, RET) for p in directory.rglob('*') if p.is_file()}
    sources = {ROOT/r['relative_path'] : r['sha256'] for r in rd(INPUT/'source_manifest.json')['sources']}
    for p,h in sources.items(): assert sha(p)==h, p
    sources.update(protected); sources[Path(__file__)]=sha(Path(__file__))
    configs=numeric(base.read_csv(INPUT/'configuration_summary.csv'))
    branches=numeric(base.read_csv(INPUT/'branch_readings.csv'))
    originals=copy.deepcopy(branches); comparisons=[]
    for b in branches:
        b['selected_targeted_retest']=False
        b['new_complete_configuration_repeat']=False
        b['retest_reported_date']=''
    for c in configs:
        c['assembled_with_targeted_retest']=False
        c['n_selected_entries_per_condition']=1
        c['additional_independent_complete_repeats']=0
        c['n_records_field_meaning']='one compiled configuration entry; not the number of per-point acquisitions'
    for combo,load,mid in TARGETS:
        rp=RET/f'20260907_{combo}_{load}_{mid}'/'record.json'; ret=rd(rp)
        assert ret['user_identified_condition']==dict(combo=combo,module_count=3,load=load,module_id=mid)
        for photo in ret['photos']: assert sha(ROOT/photo['saved_path'])==photo['sha256']
        b=next(b for b in branches if (b['combo'],b['load'],b['module_id'])==(combo,load,mid))
        before=copy.deepcopy(b)
        for stat in ('main','min','max'): b[f'I_{stat}_mA']=D(ret['readings']['current'][stat])
        b['I_main_display_text_mA']=ret['readings']['current']['main']
        if mid=='M3':
            assert ret['source_voltage']['old_source_confirmed_unchanged_for_retest']
            assert D(ret['source_voltage']['main_V'])==b['V_source_main_V']==D('3.276')
            for stat in ('main','min','max'): b[f'V_module_{stat}_V']=D(ret['readings']['voltage'][stat])
        else:
            assert D(ret['readings']['voltage']['main'])==b['V_module_main_V']==D('3.241')
            assert ret['readings']['voltage']['min'] is None
            b['retained_quality_note']='Historical original current below original MIN; retained in historical_quality_issues.csv. Selected current retest is within its displayed bounds.'
        b['source_minus_module_main_mV']=(b['V_source_main_V']-b['V_module_main_V'])*1000
        b['selected_targeted_retest']=True; b['retest_reported_date']=ret['reported_date']
        prov={'baseline_branch':before,'targeted_retest_path':rp.relative_to(ROOT).as_posix(),
              'targeted_retest_sha256':sha(rp),'selected_current_fields':'new retest main/min/max',
              'selected_voltage_fields': 'M3 retest main/min/max' if mid=='M3' else 'prior accepted voltage main/min/max; new user confirmation of main only',
              'source_voltage_fields':'retained prior source; no newly measured SOURCE extrema',
              'temperature_fields':'retained prior reading; not remeasured',
              'configuration_context':'other branches retained from prior records; no full configuration repeat',
              'new_retest_load_mass_area_distribution_verified':False}
        b['provenance_json']=json.dumps(prov,ensure_ascii=False,default=base.json_default)
        c=next(c for c in configs if (c['combo'],c['load'])==(combo,load))
        oldsum=c['I_sum_mA']; c['assembled_with_targeted_retest']=True
        c['provenance_json']=json.dumps({'baseline_configuration':json.loads(c['provenance_json']),
             'selected_branch_retest':prov,'new_simultaneous_sum':False,'new_full_configuration_run':False,
             'original_load_mass_field':'retained historical context; matching retest load not verified'},ensure_ascii=False,default=base.json_default)
        comparisons.append(dict(combo=combo,load=load,module_id=mid,original_current_mA=before['I_main_mA'],
            selected_current_mA=b['I_main_mA'],current_change_mA=b['I_main_mA']-before['I_main_mA'],
            prior_accepted_voltage_V=before['V_module_main_V'],selected_voltage_V=b['V_module_main_V'],
            retained_SOURCE_V=b['V_source_main_V'],prior_accepted_drop_mV=before['source_minus_module_main_mV'],
            selected_drop_mV=b['source_minus_module_main_mV'],original_configuration_sum_mA=oldsum,
            compiled_configuration_sum_mA=oldsum-before['I_main_mA']+b['I_main_mA'],
            new_full_configuration_repeat=False,retained_other_module_readings=True,
            source_basis=prov['source_voltage_fields'],retest_record=rp.relative_to(ROOT).as_posix()))
    for c in configs:
        bb=[b for b in branches if (b['combo'],b['load'])==(c['combo'],c['load'])]
        c['I_sum_mA']=sum(b['I_main_mA'] for b in bb)
        c['P_source_output_estimate_mW']=c['V_source_main_V']*c['I_sum_mA']
        for b in bb:
            c[f"I_{b['module_id']}_main_mA"]=b['I_main_mA']; c[f"V_{b['module_id']}_main_V"]=b['V_module_main_V']
    index={(c['load'],c['combo']):c for c in configs}; groups=[]; predictions=[]
    for load in ('ZERO','MAX'):
        for n in range(1,5):
            selected=[c for c in configs if c['load']==load and c['module_count']==n]
            for batch in ['ALL']+sorted({c['photo_filename_date_batch'] for c in selected}):
                sub=selected if batch=='ALL' else [c for c in selected if c['photo_filename_date_batch']==batch]
                for metric in base.METRICS:
                    groups.append(dict(load=load,module_count=n,photo_filename_date_batch=batch,metric=metric,
                        **base.describe(c[metric] for c in sub),SD_meaning='Across combinations, not independent repeatability; two entries compile partial retests',
                        batch_meaning='baseline photo filename batch only; targeted retest reported 2026-09-07 separately'))
        refs={mid:index[(load,mid)]['I_sum_mA'] for mid in base.MODULES}
        for c in configs:
            if c['load']!=load or c['module_count']==1:continue
            prediction=sum(refs[mid] for mid in c['combo'].split('-')); residual=c['I_sum_mA']-prediction
            predictions.append(dict(load=load,combo=c['combo'],module_count=c['module_count'],I_observed_sum_mA=c['I_sum_mA'],
                I_prediction_from_same_load_N1_physical_modules_mA=prediction,residual_mA=residual,
                residual_percent_of_prediction=residual/prediction*100,N1_references_mA_json=json.dumps(refs,default=base.json_default),
                additional_independent_same_condition_repeats=0,interpretation='descriptive compiled sum versus separate N1 references',
                assembled_with_targeted_retest=c['assembled_with_targeted_retest']))
    pairs=base.read_csv(INPUT/'load_pairs.csv')
    for p in pairs:
        z,m=(index[(load,p['combo'])] for load in ('ZERO','MAX')); delta=m['I_sum_mA']-z['I_sum_mA']
        p.update(I_ZERO_sum_mA=z['I_sum_mA'],I_MAX_sum_mA=m['I_sum_mA'],MAX_minus_ZERO_mA=delta,
            MAX_minus_ZERO_percent_of_ZERO=delta/z['I_sum_mA']*100,P_ZERO_estimate_mW=z['P_source_output_estimate_mW'],
            P_MAX_estimate_mW=m['P_source_output_estimate_mW'],MAX_minus_ZERO_power_estimate_mW=m['P_source_output_estimate_mW']-z['P_source_output_estimate_mW'],
            comparison_basis='compiled points; partial retests at two N3 entries; not repeated paired trials')
    issues=[]
    for b in branches:
        for prefix,unit in [('I','mA'),('V_module','V')]:
            if not b[f'{prefix}_min_{unit}']<=b[f'{prefix}_main_{unit}']<=b[f'{prefix}_max_{unit}']:
                issues.append(dict(load=b['load'],combo=b['combo'],module_id=b['module_id'],issue=f'{prefix}_MAIN_OUTSIDE_DISPLAY_MIN_MAX',action='retain selected original reading; no hardware-fault conclusion'))
    assert len(issues)==4
    ranges={}
    for load in ('ZERO','MAX'):
        bs=[b for b in branches if b['load']==load]; cs=[c for c in configs if c['load']==load]; ranges[load]={}
        for key,rr in [('V_module_main_V',bs),('V_module_min_V',bs),('V_module_max_V',bs),('T_stm32_C',bs),('source_minus_module_main_mV',bs),('V_source_main_V',cs),('T_teensy_C',cs),('T_regulator_C',cs)]:
            ranges[load][key]=[min(r[key] for r in rr),max(r[key] for r in rr)]
    summary=rd(INPUT/'summary.json')
    summary.update(version='2.4',configuration_entry_basis='30 compiled condition entries; two partial branch retests selected; no new complete trials',
        additional_targeted_branch_retests=2,new_complete_configuration_repeats=0,range_values=ranges,
        groups_ALL=[g for g in groups if g['photo_filename_date_batch']=='ALL'],numeric_display_consistency_issues=issues,
        retained_historical_numeric_display_consistency_issues=rd(INPUT/'summary.json')['numeric_display_consistency_issues'],
        N4_ZERO_MAX={load:index[(load,'M0-M1-M2-M3')] for load in ('ZERO','MAX')},
        descriptive_additivity_residual_percent={load:base.describe(p['residual_percent_of_prediction'] for p in predictions if p['load']==load) for load in ('ZERO','MAX')},
        descriptive_MAX_minus_ZERO_percent=base.describe(p['MAX_minus_ZERO_percent_of_ZERO'] for p in pairs),
        targeted_retest_comparisons=comparisons,
        date_definition='baseline filename date retained as a grouping label, not the date of the whole compiled entry; retests reported 2026-09-07',
        current_extrema_complete_branches=64,module_voltage_extrema_complete_branches=64,source_voltage_extrema_complete_configurations=30,
        extrema_provenance='Complete selected fields span prior and retest records: M0 voltage and all SOURCE extrema are retained prior observations; no new extrema inferred.')
    for filename,rr in [('configuration_summary.csv',configs),('branch_readings.csv',branches),('group_summary.csv',groups),('load_pairs.csv',pairs),('additivity_checks.csv',predictions),('quality_issues.csv',issues),('targeted_retest_comparison.csv',comparisons)]:base.write_csv(OUT/filename,rr)
    for filename in ('source_voltage_readings.csv','coverage.csv'):
        rows=base.read_csv(INPUT/filename)
        for r in rows:r['entry_basis']='compiled selected points; retained SOURCE and coverage labels are not new measurements'
        base.write_csv(OUT/filename,rows)
    base.write_csv(OUT/'historical_quality_issues.csv',base.read_csv(INPUT/'quality_issues.csv'))
    base.write_json(OUT/'summary.json',summary)
    base.write_json(OUT/'source_manifest.json',{'version':'2.4','sources':[{'relative_path':p.relative_to(ROOT).as_posix(),'sha256':h} for p,h in sorted(sources.items())],
        'baseline_directory':INPUT.relative_to(ROOT).as_posix(),'selection_authorization':'User: 现在对报告以及图标进行更改',
        'raw_record_handling':'Original intake status flags describe the intake stage; this derived view implements the later report update without editing raw records.'})
    lines=['# Power 2.4：逐点复测合并视图','','以旧30条件、64支路为基础，选择M0空载电流和M3满载电流/电压复测，其余测点沿用此前记录。两处是跨记录合并，不能称为整组新实验或独立重复。旧矩阵及原始文件保持不变。','',
        '| 组合/条件 | 电流：旧 → 选用 / mA | 合计：旧 → 合并 / mA | 压降：此前接受 → 选用 / mV |','|---|---:|---:|---:|']
    for c in comparisons:lines.append(f"| {c['combo']}/{c['load']}/{c['module_id']} | {c['original_current_mA']} → {c['selected_current_mA']} | {c['original_configuration_sum_mA']} → {c['compiled_configuration_sum_mA']} | {c['prior_accepted_drop_mV']} → {c['selected_drop_mV']} |")
    lines += ['','M0电压保留此前已接受的3.241 V，用户再次确认主读数；其MIN/MAX来自此前电压记录。原接头故障3.224 V仍存档。M3新电压3.243 V，SOURCE按用户确认沿用3.276 V，故压降估计33 mV；未添加新的SOURCE极值。温度与其他支路没有作为新测量记录。','',
        'M3重新插入connector后读数改变，但加载质量/位置/分配是否相同未知，不能单凭前后差异证明唯一故障原因或无故障。','',
        'N=1/2/3/4每种负载的组合数仍为4/6/4/1；表中SD为组合间样本SD，不是同条件重复性。MIN/MAX是仪表显示极值，不是SD或经验证瞬态峰值。原5项主读数/极值不一致全部保留历史表；当前选择视图剩4项，M0新电流在新极值范围内。','',
        '| N | 负载 | 合计电流 mean ± SD / mA | 功率估计 mean ± SD / mW |','|---:|---|---:|---:|']
    for n in range(1,5):
        for load in ('ZERO','MAX'):
            vals=[]
            for metric in ('I_sum_mA','P_source_output_estimate_mW'):
                g=next(g for g in groups if g['module_count']==n and g['load']==load and g['metric']==metric and g['photo_filename_date_batch']=='ALL')
                vals.append(f"{g['mean']:.3f} ± {g['sample_SD_across_configurations']:.3f}" if g['sample_SD_across_configurations'] is not None else f"{g['mean']:.3f} (SD不可估计)")
            lines.append(f'| {n} | {load} | {vals[0]} | {vals[1]} |')
    lines += ['','复现：python script/Main/pipeline/power_retest_revision.py。来源SHA256见source_manifest.json；逐字段来源见branch_readings.csv的provenance_json。SOURCE×顺序支路电流和只估计模块侧输出功率，不包含Teensy USB及稳压器损耗。独立重复、同步测量、加载定义、故障监测仍有限；启动峰值、纹波、负载切换与连续温升为未来工作。','']
    (OUT/'README_CN.md').write_text('\n'.join(lines),encoding='utf-8')
    for p,h in protected.items():assert sha(p)==h,p
    print(json.dumps({'output':str(OUT),'sources':len(sources),'current_QC':len(issues),'N3_groups':[g for g in groups if g['module_count']==3 and g['photo_filename_date_batch']=='ALL']},default=base.json_default,indent=2))
if __name__=='__main__':main()
