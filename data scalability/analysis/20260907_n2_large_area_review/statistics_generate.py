"""Fixed three-run N2 large-area statistics; per-slot and per-packet ESKF scopes stay distinct.

Writes only statistics.json/csv/md in this directory. --from-snapshot never reads
measured files. The user supplied actual loading; recorded metadata is preserved.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics as st

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data'
NEW_IDS = ['20260907_054752_155421', '20260907_054832_183609', '20260907_054912_204552']
SLOTS = [1, 3]
METRICS = ['duration_s','rate_Hz','Lmean_B','valid_USB_Mbit_s','raw_arrival_Mbit_s',
           'K_ESKD_pooled_inner_mean','q_ESKF_inner_pct','packet_any_ESKF_pct',
           'equal_rate_FULL_USB_saving_pct']


def read_json(path):
    blob = path.read_bytes()
    return json.loads(blob.decode('utf-8-sig')), hashlib.sha256(blob).hexdigest()


def histogram_statistics(hist):
    hist = {int(k): int(v) for k, v in hist.items() if v}
    n = sum(hist.values())
    assert n > 0
    ordered = sorted(hist.items())
    def at(i):
        total = 0
        for k, count in ordered:
            total += count
            if i < total:
                return k
        raise AssertionError('histogram index')
    def quantile(p):
        rank = (n - 1) * p
        a, b = math.floor(rank), math.ceil(rank)
        return at(a) + (at(b) - at(a)) * (rank - a)
    q1, q3 = quantile(.25), quantile(.75)
    return dict(n=n, mean=sum(k*v for k, v in hist.items())/n, median=quantile(.5),
                p25=q1, p75=q3, IQR=q3-q1, max=max(hist), min=min(hist))


def collect_inputs():
    records=[]
    for run_id in NEW_IDS:
        path=DATA/run_id/'summary.json'; summary,sha=read_json(path); m=summary['metadata']
        assert m['target_modules']==SLOTS and m['N']==2 and m['M']==4
        assert m['target_mode']=='DELTA' and m['condition']=='zero_load'
        assert m['target_hz']==200 and m['delta_threshold']==8 and m['spi_setting_hz']==10000000
        assert summary['requested_duration_seconds']==40 and summary['settle_seconds']==10 and summary['completed_requested_duration']
        assert int(m['repeat'])==m['batch_repeat_index'] and m['batch_repeat_count']==3
        log_path=path.parent/'packet_log.csv'; blob=log_path.read_bytes()
        mix={scope:Counter() for scope in ['main','full_run']}
        bytes_valid={scope:0 for scope in mix}; invalid=[]
        import io
        for row in csv.DictReader(io.StringIO(blob.decode('utf-8-sig'))):
            if row['outer_crc_ok']!='True' or row['parse_ok']!='True':
                invalid.append(dict(sequence=row['packet_sequence'],error=row['error']));continue
            algorithms=row['algorithms'].split(',')
            symbols={'DELTA':'D','DELTA_SYNC':'F'}
            code=''.join(symbols.get(algorithms[i],'?') for i in SLOTS)
            selected=['full_run']+(['main'] if row['main_window']=='True' else [])
            for scope in selected:
                mix[scope][code]+=1;bytes_valid[scope]+=int(row['received_bytes'])
        records.append(dict(run_id=run_id,started_at=summary['started_at'],metadata=m,scopes=summary['scopes'],
                            summary_path=path.relative_to(DATA).as_posix(),summary_sha256=sha,raw_sha256=summary['raw_sha256'],
                            packet_log_sha256=hashlib.sha256(blob).hexdigest(),packet_mix={k:dict(v) for k,v in mix.items()},
                            logged_valid_bytes=bytes_valid,invalid_packet_log_rows=invalid))
    assert {r['metadata']['repeat'] for r in records}=={'1','2','3'}
    assert len({r['metadata']['batch_id'] for r in records})==1
    n1_path=HERE.parent/'20260907_delta_press_release_review'/'statistics.json'
    n1,n1sha=read_json(n1_path)
    n1_ref=next(g for g in n1['groups'] if g['group']=='previous_large_area_main_PASS' and g['scope']=='main')
    zero_path=HERE.parent/'20260907_delta_zero_review'/'zero_load_stats_summary.json'
    zero,zero_sha=read_json(zero_path)
    zero_ref=next(g for g in zero['combinations_all'] if g['modules']=='M1_M3')
    return dict(records=records,actual_condition='large_area',actual_load_protocol='large_area_coverage',
                actual_condition_source='User confirmed simultaneously covering and loading M1 and M3 in this conversation',
                loading_relationship_between_modules='simultaneous_coverage_and_loading_of_both_modules',
                loading_equality='equal force or contact area not established',
                quantitative_loading='Per-slot force, contact area, loading rhythm and layers are not quantified',
                references=dict(N1_large_area_main_PASS=dict(path='../20260907_delta_press_release_review/statistics.json',sha256=n1sha,statistics=n1_ref),
                                N2_M1_M3_zero_load=dict(path='../20260907_delta_zero_review/zero_load_stats_summary.json',sha256=zero_sha,statistics=zero_ref)),
                original_large_area_audit=n1['inputs']['original_large_area_audit'])


def refresh_audit(inputs):
    path=HERE/'raw_audit.json'; raw,sha=read_json(path)
    assert set(raw['snapshot_run_ids'])==set(NEW_IDS) and not raw['changed_original_files']
    for record in inputs['records']:
        for name,key in [('summary.json','summary_sha256'),('packet_log.csv','packet_log_sha256')]:
            assert raw['original_files_before'][record['run_id']+'\\'+name]['sha256']==record[key]
    inputs['raw_audit']=dict(path=path.name,sha256=sha,report=raw)
    refresh_condition(inputs)


def refresh_condition(inputs):
    path=HERE/'condition_correction.json'
    if path.is_file():
        correction,sha=read_json(path);assert correction['actual_condition']=='large_area'
        assert correction['loading_relationship_between_modules']=='simultaneous_coverage_and_loading_of_both_modules'
        inputs['condition_correction']=dict(path=path.name,sha256=sha,record=correction)
        inputs['actual_condition_source']='User confirmed simultaneously covering and loading M1 and M3 in this conversation'
        inputs['loading_relationship_between_modules']=correction['loading_relationship_between_modules']
        inputs['loading_equality']='equal force or contact area not established'
        inputs['quantitative_loading']='Per-slot force, contact area, loading rhythm and layers are not quantified'


def make_row(record,scope,inputs,issues):
    w=record['scopes'][scope];c=w['counts'];m=record['metadata'];P=c['valid_outer_packets']
    t=w['actual_duration_seconds'];B=c['valid_outer_packet_bytes'];hist=Counter();module_rows=[]
    qsum_bytes=0
    for slot in SLOTS:
        mod=w['modules'][f'M{slot}'];mc=mod['counts'];h={int(k):int(v) for k,v in mod['K_histogram'].items()}
        hs=histogram_statistics(h);hist.update(h);nd=mc.get('ESKD',0);nf=mc.get('ESKF',0)
        encoded=84*nd+2*sum(k*v for k,v in h.items())+1044*nf
        checks={'hist_n':hs['n']==nd,'encoded_bytes':encoded==mc['payload_bytes'],
                'inner_count':nd+nf==mc['valid_frames'],
                'q':math.isclose(nf/(nd+nf),mod['q_ESKF'])}
        for key in ['mean','median','p25','p75','max']:checks['K_'+key]=math.isclose(hs[key],mod['K'][key])
        for key,ok in checks.items():
            if not ok:issues.append(dict(run_id=record['run_id'],scope=scope,slot=slot,check=key))
        module_rows.append(dict(run_id=record['run_id'],scope=scope,slot=f'M{slot}',repeat=m['repeat'],batch_id=m['batch_id'],
                                loading_relationship_between_modules=inputs['loading_relationship_between_modules'],
                                valid_updates=mc['valid_frames'],expected_opportunities=P,update_coverage=mc['valid_frames']/P,
                                ESKD_count=nd,ESKF_count=nf,q_ESKF=nf/(nd+nf),q_ESKF_pct=100*nf/(nd+nf),
                                K_ESKD_mean=hs['mean'],K_ESKD_median=hs['median'],K_ESKD_p25=hs['p25'],K_ESKD_p75=hs['p75'],
                                K_ESKD_IQR=hs['IQR'],K_ESKD_max=hs['max'],K1_ESKD_mean=mod['K1']['mean'],K2_ESKD_mean=mod['K2']['mean'],
                                initial_unanchored_delta=mc.get('initial_unanchored_delta',0),valid_payload_bytes=encoded))
        qsum_bytes += mod['q_ESKF']*1044+(1-mod['q_ESKF'])*(84+2*hs['mean'])
    hs=histogram_statistics(hist);nd=c.get('ESKD',0);nf=c.get('ESKF',0);q=nf/(nd+nf)
    mix={code:record['packet_mix'][scope].get(code,0) for code in ['DD','DF','FD','FF']}
    any_full=mix['DF']+mix['FD']+mix['FF'];both_full=mix['FF']
    checks={'hist_n':hs['n']==nd,'module_inner_count':nd+nf==c['valid_module_frames'],
            'byte_identity':B==40*P+84*nd+2*sum(k*v for k,v in hist.items())+1044*nf+c.get('diagnostic_payload_bytes',0),
            'packet_mix_count':sum(mix.values())==P,
            'packet_mix_F':nf==mix['DF']+mix['FD']+2*mix['FF'],
            'packet_mix_M1F':module_rows[0]['ESKF_count']==mix['FD']+mix['FF'],
            'packet_mix_M3F':module_rows[1]['ESKF_count']==mix['DF']+mix['FF'],
            'logged_bytes':record['logged_valid_bytes'][scope]==B,
            'Lmean_module_formula':math.isclose(40+qsum_bytes,B/P),
            'rate':math.isclose(P/t,w['valid_outer_packet_rate_Hz']),
            'q':math.isclose(q,w['q_ESKF']),
            'Kpooled':math.isclose(hs['mean'],w['K_ESKD_pooled']['mean'])}
    for key,ok in checks.items():
        if not ok:issues.append(dict(run_id=record['run_id'],scope=scope,check=key))
    qualification='pending_independent_raw_audit'
    if 'raw_audit' in inputs:
        audit=next(r for r in inputs['raw_audit']['report']['runs'] if r['run_id']==record['run_id'])
        for key in ['anomalies','cross_check_errors','outer_sequence_discontinuities','inner_sequence_discontinuities','observed_base_discontinuities']:
            assert not audit[key],(record['run_id'],key)
        ac=audit['scopes'][scope]['counts']
        assert (ac['valid_outer_packets'],ac['valid_module_frames'],ac['ESKD'],ac['ESKF'],ac['valid_outer_packet_bytes'])==(P,nd+nf,nd,nf,B)
        assert audit['packet_frame_type_slot_order']==SLOTS
        raw_mix=audit['packet_frame_type_combinations'][scope]
        assert all(raw_mix.get(code,0)==mix[code] for code in mix)
        for mr in module_rows:
            slot=mr['slot'][1:]
            raw_mod=audit['scopes'][scope]['modules'][slot]
            raw_counts=raw_mod['counts']
            assert (raw_counts['valid_frames'],raw_counts['ESKD'],raw_counts['ESKF'])==(mr['valid_updates'],mr['ESKD_count'],mr['ESKF_count'])
            assert {int(k):int(v) for k,v in raw_mod['K_histogram'].items()}=={int(k):int(v) for k,v in w['modules'][mr['slot']]['K_histogram'].items()}
        qualification='PASS: audited main window' if scope=='main' else 'CHECK REQUIRED: file start anchoring/boundary limits retained'
    for r in module_rows:r['independent_raw_status']=qualification
    row=dict(run_id=record['run_id'],scope=scope,batch_id=m['batch_id'],repeat=m['repeat'],block=m['block'],
             metadata_condition=m['condition'],actual_condition='large_area',actual_load_protocol='large_area_coverage',
             loading_relationship_between_modules=inputs['loading_relationship_between_modules'],
             slots='M1_M3',N=2,M=4,metadata_load_layers=m['load_layers'],independent_setup_n='not_established',
             summary_status=w['status'],summary_review_reasons=w['review_reasons'],independent_raw_status=qualification,
             duration_s=t,valid_outer_packets=P,valid_inner_updates=nd+nf,valid_USB_bytes=B,rate_Hz=P/t,Lmean_B=B/P,
             valid_USB_Mbit_s=8*B/t/1e6,raw_arrival_Mbit_s=w['raw_arrival_Mbit_per_s'],
             ESKD_count=nd,ESKF_count=nf,q_ESKF_inner=q,q_ESKF_inner_pct=100*q,
             packet_any_ESKF_count=any_full,packet_any_ESKF_fraction=any_full/P,packet_any_ESKF_pct=100*any_full/P,
             packet_DD=mix['DD'],packet_DF=mix['DF'],packet_FD=mix['FD'],packet_FF=both_full,
             K_ESKD_pooled_inner_mean=hs['mean'],K_ESKD_pooled_inner_median=hs['median'],K_ESKD_pooled_inner_IQR=hs['IQR'],
             K_ESKD_pooled_inner_max=hs['max'],valid_update_coverage=(nd+nf)/(2*P),
             missing_valid_expected_updates=c.get('missing_valid_expected_updates',0),
             matched_FULL_packet_B=2128,all_D_K0_packet_B=208,equal_rate_FULL_USB_saving_pct=100*(1-(B/P)/2128),
             FULL_USB_at_same_actual_rate_Mbit_s=8*2128*(P/t)/1e6,model_byte_identity_pass=checks['byte_identity'],
             initial_unanchored_delta=c.get('initial_unanchored_delta',0),known_start_boundary_bytes=w.get('known_start_boundary_bytes',0),
             unassigned_raw_bytes=w.get('unassigned_raw_bytes',0),session_observed_counters=w.get('session_counter_delta_at_packet_observation',{}))
    return row,module_rows


def aggregate(rows,module_rows):
    groups=[];module_groups=[]
    for scope in ['main','full_run']:
        selected=[r for r in rows if r['scope']==scope]
        result=dict(scope=scope,temporal_repeat_n=len(selected),batch_n=len({r['batch_id'] for r in selected}),
                    independent_setup_n='not_established',run_ids=[r['run_id'] for r in selected],
                    summary_status_counts=dict(Counter(r['summary_status'] for r in selected)),
                    independent_raw_status_counts=dict(Counter(r['independent_raw_status'] for r in selected)))
        for key in METRICS:
            values=[r[key] for r in selected];result[key+'_mean']=st.mean(values);result[key+'_sample_sd']=st.stdev(values)
        for key in ['ESKF_count','ESKD_count','valid_outer_packets','valid_inner_updates','packet_DD','packet_DF','packet_FD','packet_FF','packet_any_ESKF_count']:
            result[key+'_total']=sum(r[key] for r in selected)
        result['q_ESKF_inner_pooled']=result['ESKF_count_total']/result['valid_inner_updates_total']
        result['packet_any_ESKF_pooled_fraction']=result['packet_any_ESKF_count_total']/result['valid_outer_packets_total']
        groups.append(result)
        for slot in ['M1','M3']:
            chosen=[r for r in module_rows if r['scope']==scope and r['slot']==slot]
            mr=dict(scope=scope,slot=slot,temporal_repeat_n=3,batch_n=1,independent_setup_n='not_established',
                    valid_updates_total=sum(r['valid_updates'] for r in chosen),ESKD_count_total=sum(r['ESKD_count'] for r in chosen),
                    ESKF_count_total=sum(r['ESKF_count'] for r in chosen),K_ESKD_max_over_runs=max(r['K_ESKD_max'] for r in chosen))
            for key in ['K_ESKD_mean','K_ESKD_median','K_ESKD_IQR','q_ESKF_pct','update_coverage']:
                values=[r[key] for r in chosen];mr[key+'_mean']=st.mean(values);mr[key+'_sample_sd']=st.stdev(values)
            module_groups.append(mr)
    return groups,module_groups


def write_note(inputs,rows,module_rows,groups,module_groups,issues):
    text=['# N2 大面积覆盖：统计与模块/包级ESKF口径','',
          '用户确认“同时覆盖、加载两个模块（M1、M3）”。原metadata的zero_load保留；派生actual_condition=large_area、actual_load_protocol=large_area_coverage。两模块同时加载，但各自力、接触面积、节奏及层未量化，不能据此认定等力或等面积。条件依据见[condition_correction.json](condition_correction.json)。','',
          '配置为M1+M3、N=2、M=4、DELTA、目标200 Hz、阈值8、本地SPI配置10 MHz。同一batch、Block 1、Repeat 1/2/3；每条约40 s，固定主窗10–40 s，全部保留，不按波峰切片。n=3是同一setup内连续时间窗口，不是独立装配。','',
          '## 主窗和全程：均值 ± 样本SD（n=3，batch=1）','',
          '| 窗口 | Hz | Lmean/B | 有效USB/Mbit/s | 普通K pooled-inner | 内帧ESKF q/% | 含任一ESKF包/% | 对FULL等包率节省/% |',
          '|---|---:|---:|---:|---:|---:|---:|---:|']
    for g in groups:
        keys=['rate_Hz','Lmean_B','valid_USB_Mbit_s','K_ESKD_pooled_inner_mean','q_ESKF_inner_pct','packet_any_ESKF_pct','equal_rate_FULL_USB_saving_pct']
        text.append('| '+g['scope']+' | '+' | '.join(f"{g[k+'_mean']:.6f} ± {g[k+'_sample_sd']:.6f}" for k in keys)+' |')
    text+=['','SD分母n−1，以三个run统计值计算。pooled-inner K的单位是一个普通模块ESKD内帧；它不是每个MUL1包两模块变化数之和。模块帧数和包数均不能当作独立实验重复。','',
           '## 逐条包统计与异步完整帧','',
           '| Repeat | 窗口 | Hz | Lmean/B | USB/Mbit/s | ESKF / ESKD内帧 | DD | DF | FD | FF |',
           '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        text.append(f"| {r['repeat']} | {r['scope']} | {r['rate_Hz']:.6f} | {r['Lmean_B']:.6f} | {r['valid_USB_Mbit_s']:.6f} | {r['ESKF_count']} / {r['ESKD_count']} | {r['packet_DD']} | {r['packet_DF']} | {r['packet_FD']} | {r['packet_FF']} |")
    text+=['','顺序固定为M1、M3：D=ESKD，F=ESKF。例如DF仅M3发ESKF。q_inner=nF/(nD+nF)；packet_any=(DF+FD+FF)/P；nF=DF+FD+2FF。两模块可异步发ESKF，不假设一次完整刷新同时占据两个模块。','',
           '## 逐模块普通ESKD分布','',
           '| Repeat | 窗口 | 槽位 | 有效更新数 | 覆盖率 | K均值 | 中位数 [Q1,Q3] | IQR | Kmax | ESKF / ESKD | q_m/% |',
           '|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in module_rows:
        text.append(f"| {r['repeat']} | {r['scope']} | {r['slot']} | {r['valid_updates']} | {r['update_coverage']:.6f} | {r['K_ESKD_mean']:.6f} | {r['K_ESKD_median']:g} [{r['K_ESKD_p25']:g},{r['K_ESKD_p75']:g}] | {r['K_ESKD_IQR']:g} | {r['K_ESKD_max']} | {r['ESKF_count']} / {r['ESKD_count']} | {r['q_ESKF_pct']:.6f} |")
    text+=['','K从各模块histogram重算；分位数采用(n−1)p线性插值，IQR=Q3−Q1。普通K=480仍合法，对应1044 B模块帧；ESKF不伪造物理K。q_m的分母为该模块有效内更新数，两个q_m与包级含F比例不可混称。CSV/JSON另存逐模块均值±SD。','',
           '## 实际混合字节','',
           'M=4的包装为24+4M=40 B；N=2的FULL完整MUL1为40+2×1044=2128 B；双D且K1=K3=0时为40+2×84=208 B。逐窗核验B_valid=40P+84nD+2ΣK+1044nF+诊断字节。也按各模块核验Lmean=40+Σ_m[(1−q_m)(84+2K_D,m)+1044q_m]。全部ESKF计入实际字节，不能套用N1的1084 B分母。','',
           'f=P/t、Lmean=B_valid/P、有效USB=8B_valid/t，t采用实际窗口秒数。raw到达吞吐另列。FULL等实际包率节省=1−Lmean/2128，是同M/N且保持本批f不变的协议字节反事实，不是新测FULL或物理USB总开销。没有ESKF触发原因码，不自动拆成周期/高K/命令。','',
           f'统计、packet mix和字节恒等式检查问题：{issues}。','',
           '## 独立完整性与参照','']
    if 'raw_audit' in inputs:
        text+=['[独立raw审计](raw_audit.json)与本统计一致：主窗17,968个MUL1、35,936内更新=35,700 ESKD+236 ESKF；全程23,988个MUL1、47,976内更新=47,680 ESKD+296 ESKF。两个槽位在每个有效包都更新；外内CRC、格式、K、base、跨ESKD/ESKF内序号与日志差异未见异常。仅主窗标独立PASS，原全程CHECK REQUIRED保持。','']
        full=[r for r in rows if r['scope']=='full_run']
        text.append(f"本批初始无锚点ESKD分别{[r['initial_unanchored_delta'] for r in full]}，尾部未归属字节分别{[r['unassigned_raw_bytes'] for r in full]}；不套用其他批次。summary和packet_log的SHA与独立审计源清单一致。")
        text.append('')
    else:text+=['独立raw资格尚待审计；原GUI PASS不自动升级为独立PASS。','']
    n1=inputs['references']['N1_large_area_main_PASS']['statistics'];zero=inputs['references']['N2_M1_M3_zero_load']['statistics']
    text+=[f"- N1/M1大面积动态加载主PASS批次：L={n1['Lmean_B_mean']:.6f}±{n1['Lmean_B_sample_sd']:.6f} B，USB={n1['valid_USB_Mbit_s_mean']:.6f}±{n1['valid_USB_Mbit_s_sample_sd']:.6f} Mbit/s，仅作名义场景对照；不能假定本批两模块各自复现该N1负载或固定K线性扩展。",
           f"- N2/M1_M3旧零载批次：L={zero['Lmean_B_mean']:.6f}±{zero['Lmean_B_sample_sd']:.6f} B，USB={zero['packet_Mbit_s_mean']:.6f}±{zero['packet_Mbit_s_sample_sd']:.6f} Mbit/s，f={zero['rate_Hz_mean']:.6f}±{zero['rate_Hz_sample_sd']:.6f} Hz。槽位组合相同但加载条件不同，另批描述不合并。",'',
           '槽位不是实体板卡UID，各槽位受力、面积及节奏未定量匹配；以上差异不能推断算法退化、某模块噪声或单独的模块数效应。最初N1 Large_area的CHECK记录及内序号事件仍在参照审计中保留，不被后续PASS覆盖。独立raw审计保留当时的条件说明快照，本次用户确认不改写该历史审计。','',
           '## 复现','',
           '默认固定读取三条新summary和packet_log，以及两份既有派生统计。--from-snapshot仅从statistics.json重建；--refresh-condition仅读同目录条件说明，保留已冻结的历史raw审计；--refresh-raw-audit读取同目录派生raw审计及条件说明。源SHA、metadata、scopes、packet模式计数均冻结。原data、索引及图未修改。','',
           '[逐run逐窗CSV](statistics.csv) · [逐模块CSV](statistics.modules.csv) · [全部汇总JSON](statistics.json) · [脚本](statistics_generate.py)','']
    (HERE/'statistics.md').write_text('\n'.join(text),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--from-snapshot',action='store_true');parser.add_argument('--refresh-raw-audit',action='store_true')
    parser.add_argument('--refresh-condition',action='store_true')
    args=parser.parse_args();path=HERE/'statistics.json'
    inputs=read_json(path)[0]['inputs'] if args.from_snapshot else collect_inputs()
    if args.refresh_raw_audit:refresh_audit(inputs)
    elif args.refresh_condition:refresh_condition(inputs)
    issues=[];rows=[];module_rows=[]
    for record in inputs['records']:
        for scope in ['main','full_run']:
            row,mods=make_row(record,scope,inputs,issues);rows.append(row);module_rows.extend(mods)
    groups,module_groups=aggregate(rows,module_rows)
    result=dict(schema_version=1,inputs=inputs,rows=rows,module_rows=module_rows,groups=groups,module_groups=module_groups,
                consistency_issues=issues,all_windows_retained=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name,selected in [('statistics.csv',rows),('statistics.modules.csv',module_rows)]:
        with (HERE/name).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(selected[0]));writer.writeheader()
            writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in selected)
    write_note(inputs,rows,module_rows,groups,module_groups,issues)
    print(json.dumps(dict(records=len(inputs['records']),run_scope_rows=len(rows),module_scope_rows=len(module_rows),
                          consistency_issues=issues,source_reads=not args.from_snapshot),ensure_ascii=False))


if __name__=='__main__':main()
