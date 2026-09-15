"""Intake-only M0 retest summary. Does not edit the report or published analyses."""
from pathlib import Path
from decimal import Decimal as D
import csv, json, hashlib, statistics
from datetime import datetime, timezone

ROOT=next(parent for parent in Path(__file__).resolve().parents
          if parent.name == "power scalability" and (parent / "DATA").is_dir())
FINAL=ROOT.parent
BASE=ROOT/'DATA/reference/report_v2_4_analysis'
RAW=ROOT/'DATA/raw/canonical/power_experiment_records/transmission'
OUT=ROOT/'DATA/analysis/retest_reviews/m0_n1_n2_retest_20260907'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def readcsv(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def writecsv(p,rows):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def main():
    OUT.mkdir(exist_ok=True)
    report=FINAL/'Imperial College Individual Project Template_LaTeX'
    protected={p:sha(p) for directory in (report,BASE,ROOT/'DATA/raw/canonical/power_experiment_records') for p in directory.rglob('*')
               if p.is_file() and not {'build','tmp','__pycache__'}.intersection(p.relative_to(directory).parts)}
    protected.update({p:sha(p) for p in FINAL.glob('main *.pdf')})
    word=FINAL/'E_SKIN_Final_Report_修订待办清单.docx';protected[word]=sha(word)
    observations=[
        (1,'M0','ZERO','IMG_20260907_065244.jpg',('18.018','18.00','18.02'),'new_v.jpg',('3.252','3.252','3.252'),'FILENAME_ASSIGNMENT_PENDING_CONFIRMATION'),
        (1,'M0','MAX','new_I.jpg',('19.675','19.65','19.68'),'new_V.jpg',('3.249','3.249','3.250'),'PHOTO_TRANSCRIBED'),
        (2,'M0-M1','ZERO','new_I.jpg',('17.941','17.92','17.99'),None,('3.251','3.251','3.251'),'USER_CONFIRMED_CORRECTION'),
        (2,'M0-M2','ZERO','new_I.jpg',('17.969','17.94','17.98'),'new_V.jpg',('3.251','3.251','3.251'),'PHOTO_TRANSCRIBED'),
        (2,'M0-M3','ZERO','new_I (1).jpg',('17.956','17.94','17.99'),'new_V.jpg',('3.250','3.250','3.250'),'PHOTO_TRANSCRIBED')]
    # The optional filename-assignment answer can be added without changing any old data.
    clarification=OUT/'clarifications.json'
    cf=json.loads(clarification.read_text(encoding='utf-8')) if clarification.exists() else {}
    bb=readcsv(BASE/'branch_readings.csv');cc=readcsv(BASE/'configuration_summary.csv');comparisons=[];readings=[];sources={BASE/'branch_readings.csv',BASE/'configuration_summary.csv',Path(__file__)}
    for n,combo,load,ip,iv,vp,vv,status in observations:
        folder=RAW/f'n={n}'/combo/('zero_load' if load=='ZERO' else 'full_load')
        if n==1 and load=='ZERO' and cf.get('N1_M0_ZERO_voltage_assignment_confirmed') is True:status='PHOTO_ASSIGNMENT_USER_CONFIRMED'
        b=next(b for b in bb if (b['combo'],b['load'],b['module_id'])==(combo,load,'M0'))
        c=next(c for c in cc if (c['combo'],c['load'])==(combo,load));oldI=D(b['I_main_mA']);newI=D(iv[0]);oldV=D(b['V_module_main_V']);newV=D(vv[0]);vs=D(b['V_source_main_V'])
        source_note='No new reading supplied; retained original value under user instruction: 没新添加的代表和原来一样'
        for quantity,vals,file,unit in [('current',iv,ip,'mA'),('voltage',vv,vp,'V')]:
            photo=folder/file if file else None
            if photo:sources.add(photo)
            assert D(vals[1])<=D(vals[0])<=D(vals[2])
            readings.append(dict(module_count=n,combo=combo,load=load,module_id='M0',quantity=quantity,unit=unit,
                main=vals[0],minimum=vals[1],maximum=vals[2],photo_path=photo.relative_to(ROOT).as_posix() if photo else '',photo_sha256=sha(photo) if photo else '',
                value_basis='PHOTO_TRANSCRIBED' if photo else 'USER_CONFIRMED_3.251_MAIN_MIN_MAX',assignment_status=status if quantity=='voltage' else 'USER_SCOPE_AND_FOLDER',
                reported_date='2026-09-07',verified_measurement_time='',main_is_verified_time_average=False))
        total=D(c['I_sum_mA'])-oldI+newI
        comparisons.append(dict(module_count=n,combo=combo,load=load,module_id='M0',old_I_mA=oldI,new_I_mA=newI,delta_I_mA=newI-oldI,
            delta_I_percent=100*(newI-oldI)/oldI,old_V_V=oldV,new_V_V=newV,delta_V_mV=1000*(newV-oldV),retained_SOURCE_V=vs,
            old_drop_mV=D(b['source_minus_module_main_mV']),new_drop_mV=1000*(vs-newV),voltage_assignment_status=status,
            old_config_sum_mA=D(c['I_sum_mA']),compiled_config_sum_mA=total,source_output_estimate_mW=vs*total,
            retained_other_module_readings=n>1,source_basis=source_note,new_complete_configuration_repeat=False))
    # Current summaries are independent of voltage-photo provenance.
    revised=[]
    for c in cc:
        r=dict(c); found=[x for x in comparisons if (x['combo'],x['load'])==(c['combo'],c['load'])]
        r['I_sum_mA']=found[0]['compiled_config_sum_mA'] if found else D(c['I_sum_mA'])
        r['P_source_output_estimate_mW']=r['I_sum_mA']*D(c['V_source_main_V']);revised.append(r)
    groups=[];predictions=[]
    for load in ('ZERO','MAX'):
        for n in range(1,5):
            sel=[c for c in revised if c['load']==load and int(c['module_count'])==n]
            for metric in ('I_sum_mA','P_source_output_estimate_mW'):
                values=[c[metric] for c in sel]
                groups.append(dict(load=load,module_count=n,metric=metric,n_configurations=len(values),mean=statistics.mean(values),
                    sample_SD_across_configurations=statistics.stdev(values) if len(values)>1 else None,interpretation='Descriptive compiled values; not independent repeat SD'))
        refs={c['combo']:c['I_sum_mA'] for c in revised if c['load']==load and c['module_count']=='1'}
        for c in revised:
            if c['load']!=load or c['module_count']=='1':continue
            prediction=sum(refs[mid] for mid in c['combo'].split('-'))
            predictions.append(dict(load=load,combo=c['combo'],compiled_I_mA=c['I_sum_mA'],N1_reference_sum_mA=prediction,
                residual_percent=100*(c['I_sum_mA']-prediction)/prediction,interpretation='New M0 N1 reference; inherited others, no causal claim'))
    bad=RAW/'n=2/M0-M1/zero_load/new_V.jpg';dup=ROOT/'DATA/raw/canonical/power_experiment_records/targeted_retests/20260907_M1-M2-M3_MAX_M3/M3_voltage_retest.jpg'
    n1=RAW/'n=1/M0/zero_load/new_v.jpg';extra=RAW/'n=2/M0-M2/zero_load/IMG_20260907_064239.jpg'
    assert sha(bad)==sha(dup) and sha(n1)==sha(extra)
    sources.update([bad,dup,extra])
    if clarification.exists():sources.add(clarification)
    notes={'M0_M1_wrong_photo':{'excluded_file':bad.relative_to(ROOT).as_posix(),'duplicate_of':dup.relative_to(ROOT).as_posix(),
        'user_confirmed_wrong_photo':True,'user_initial_text':'放错照片，应该是2.251，max和min都是','user_final_confirmation':'是3.251 V，主读数/MIN/MAX均为3.251',
        'accepted_voltage_main_min_max_V':['3.251']*3,'replacement_photo_available':False},
        'N1_ZERO_duplicate':{'selected_by_filename':n1.relative_to(ROOT).as_posix(),'duplicate_extra_file':extra.relative_to(ROOT).as_posix(),
        'assignment_confirmed':cf.get('N1_M0_ZERO_voltage_assignment_confirmed',False),'handling':'Never counted as another measurement; N2 uses its distinct new_V=3.251 V.'}}
    writecsv(OUT/'readings.csv',readings);writecsv(OUT/'comparison_with_report_2_4.csv',comparisons)
    writecsv(OUT/'current_group_summary.csv',groups);writecsv(OUT/'current_prediction_checks.csv',predictions)
    dump(OUT/'intake_notes.json',notes)
    summary={'scope':'Intake/summary only; report and its graphs/checklist remain unchanged','reported_conditions':5,'new_current_observations':5,
        'new_voltage_values':5,'voltage_provenance':'four assigned photos, one user correction; N1ZERO assignment tracked separately',
        'retained_values_instruction':'没新添加的代表和原来一样','source_voltage_basis':'retained prior SOURCE values confirmed unchanged by that instruction',
        'no_same_session_or_complete_configuration_repeat_inferred':True,'report_modified':False,'paper_figures_modified':False,
        'differences':comparisons,'current_groups':groups,'additivity_range_percent':{load:[min(r['residual_percent'] for r in predictions if r['load']==load),max(r['residual_percent'] for r in predictions if r['load']==load)] for load in ('ZERO','MAX')},
        'M0_N2_ZERO_drop_mean_mV':statistics.mean(x['new_drop_mV'] for x in comparisons if x['module_count']==2),
        'M0_N2_ZERO_drop_sample_SD_mV':statistics.stdev(x['new_drop_mV'] for x in comparisons if x['module_count']==2)}
    dump(OUT/'summary.json',summary)
    lines=['# M0：N=1与N=2复测总结（2026-09-07）','','仅整理本轮数据，论文、PDF、论文图表、现有2.4分析与待办清单均未修改。SOURCE及未新增的模块/温度按用户说明保留原值，标注为沿用数据。','',
        '| N/组合/条件 | M0电流：原 → 新 / mA | M0电压：原 → 新 / V | SOURCE沿用 / V | 压降：原 → 新 / mV |','|---|---:|---:|---:|---:|']
    for x in comparisons:
        mark='†' if x['voltage_assignment_status']=='FILENAME_ASSIGNMENT_PENDING_CONFIRMATION' else ('*' if x['voltage_assignment_status']=='USER_CONFIRMED_CORRECTION' else '')
        lines.append(f"| {x['module_count']}/{x['combo']}/{x['load']} | {x['old_I_mA']:.3f} → {x['new_I_mA']:.3f} | {x['old_V_V']:.3f} → {x['new_V_V']:.3f}{mark} | {x['retained_SOURCE_V']:.3f} | {x['old_drop_mV']:.0f} → {x['new_drop_mV']:.0f}{mark} |")
    lines+=['','* M0-M1空载new_V.jpg经用户确认放错，排除其3.243 V读数；采用用户最终确认的3.251 V（主读数/MIN/MAX相同），保存最初2.251的输入及随后更正，不伪称照片转录。',
        ('N1空载new_v.jpg的归属和3.252 V数值已由用户确认，移除待确认标记。N2/M0-M2使用另一张new_V.jpg的3.251 V；重复文件不计新增观测。' if cf.get('N1_M0_ZERO_voltage_assignment_confirmed') else '† N1空载new_v.jpg与N2/M0-M2中的额外IMG_20260907_064239.jpg是相同文件；暂按文件名归入N1，等待归属确认。N2/M0-M2使用另一张new_V.jpg的3.251 V。相同照片不计新增观测。'),'',
        '所有新电流主读数均位于对应仪表MIN/MAX内；显示极值不等于重复性SD或经验证动态峰值。5组电流下降0.014–0.142 mA，仅凭变化不能归因于接头、负载或特定器件。',
        'N2三个M0空载压降为30、28、29 mV，均值29.00 mV、组合间样本SD 1.00 mV；此前为47、44、42 mV，均值44.33 mV。此比较使用保留SOURCE，不是同一时刻差分测量。','',
        '| 组合/条件 | 原电流合计 / mA | 新的逐点合计 / mA | SOURCE侧功率估计 / mW |','|---|---:|---:|---:|']
    for x in comparisons:lines.append(f"| {x['combo']}/{x['load']} | {x['old_config_sum_mA']:.3f} | {x['compiled_config_sum_mA']:.3f} | {x['source_output_estimate_mW']:.3f} |")
    lines+=['','上述合计只更新M0电流，其余支路保留。SOURCE电压×电流合计是模块供电侧估计，不含Teensy USB与稳压器损耗，也不是同步总功率。','',
        '后续论文若合入本轮，应联动更新N1/N2电流均值、M0压降图及使用M0单模块电流作参考的P-H1预测。更新N1参考后，ZERO残差范围为−1.483%至−0.256%，MAX为−2.726%至+0.460%；这些结果仍是描述性比较。N3/N4原配置电流本身不变。','',
        '文件：readings.csv保存主读数与MIN/MAX；comparison_with_report_2_4.csv为逐组对照；current_group_summary.csv和current_prediction_checks.csv为后续修订参考；intake_notes.json保存错图/重复文件处理及用户更正；intake_manifest.json保存SHA256和论文未修改核对。','']
    (OUT/'README_CN.md').write_text('\n'.join(lines),encoding='utf-8')
    for p,h in protected.items():assert sha(p)==h,p
    dump(OUT/'intake_manifest.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'sources':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for p in sorted(sources)],
        'protected_files':{p.relative_to(FINAL).as_posix():h for p,h in protected.items()},'protected_files_unchanged':len(protected),
        'report_and_published_figures_unchanged':True,'summary_only':True})
    print(json.dumps({'output':str(OUT),'conditions':5,'protected_unchanged':len(protected),'n2_M0_drop_mean_mV':summary['M0_N2_ZERO_drop_mean_mV'],'pending_N1_voltage_assignment':not cf.get('N1_M0_ZERO_voltage_assignment_confirmed',False)},default=str))
if __name__=='__main__':main()
