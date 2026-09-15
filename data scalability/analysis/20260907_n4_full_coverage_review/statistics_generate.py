"""Fixed N4 full-coverage statistics; failed windows, missing updates and independent audit results are retained.

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
NEW_IDS = ['20260907_060147_020562', '20260907_060227_053987', '20260907_060307_083182']
SLOTS = [0, 1, 2, 3]
METRICS = ['duration_s','rate_Hz','all_expected_updated_rate_Hz','Lmean_B','valid_USB_Mbit_s','raw_arrival_Mbit_s',
           'K_ESKD_pooled_inner_mean','q_ESKF_inner_pct','packet_any_ESKF_pct',
           'valid_update_coverage','equal_rate_FULL_USB_saving_pct']


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
    import io
    for run_id in NEW_IDS:
        path=DATA/run_id/'summary.json';summary,sha=read_json(path);m=summary['metadata']
        assert m['target_modules']==SLOTS and m['N']==4 and m['M']==4
        assert m['target_mode']=='DELTA' and m['condition']=='zero_load'
        assert m['target_hz']==200 and m['delta_threshold']==8 and m['spi_setting_hz']==10000000
        assert summary['requested_duration_seconds']==40 and summary['settle_seconds']==10 and summary['completed_requested_duration']
        assert int(m['repeat'])==m['batch_repeat_index'] and m['batch_repeat_count']==3
        log_path=path.parent/'packet_log.csv';blob=log_path.read_bytes()
        mix={scope:Counter() for scope in ['main','full_run']};bytes_valid={scope:0 for scope in mix};flagged=[]
        for row in csv.DictReader(io.StringIO(blob.decode('utf-8-sig'))):
            if row['outer_crc_ok']!='True':
                flagged.append(row);continue
            algorithms=row['algorithms'].split(',')
            symbols={'DELTA':'D','DELTA_SYNC':'F','NONE':'X'}
            code=''.join(symbols.get(algorithms[i],'?') for i in SLOTS)
            selected=['full_run']+(['main'] if row['main_window']=='True' else [])
            for scope in selected:
                mix[scope][code]+=1;bytes_valid[scope]+=int(row['received_bytes'])
            if row['parse_ok']!='True' or 'X' in code or '?' in code:flagged.append(row)
        records.append(dict(run_id=run_id,started_at=summary['started_at'],metadata=m,scopes=summary['scopes'],
                            summary_path=path.relative_to(DATA).as_posix(),summary_sha256=sha,raw_sha256=summary['raw_sha256'],
                            packet_log_sha256=hashlib.sha256(blob).hexdigest(),packet_mix={k:dict(v) for k,v in mix.items()},
                            logged_valid_bytes=bytes_valid,flagged_packet_log_rows=flagged))
    assert {r['metadata']['repeat'] for r in records}=={'1','2','3'}
    assert len({r['metadata']['batch_id'] for r in records})==1
    inputs=dict(records=records,actual_condition='large_area',actual_load_protocol='full_coverage_all_modules')
    refresh_condition(inputs)
    return inputs


def refresh_audit(inputs):
    path=HERE/'raw_audit.json'; raw,sha=read_json(path)
    assert set(raw['snapshot_run_ids'])==set(NEW_IDS) and not raw['changed_original_files']
    for record in inputs['records']:
        for name,key in [('summary.json','summary_sha256'),('packet_log.csv','packet_log_sha256')]:
            assert raw['original_files_before'][record['run_id']+'\\'+name]['sha256']==record[key]
    inputs['raw_audit']=dict(path=path.name,sha256=sha,report=raw)
    qualification_path=HERE/'qualification.json'
    qualification,qsha=read_json(qualification_path)
    assert qualification['raw_audit_sha256']==sha
    assert {r['run_id'] for r in qualification['runs']}==set(NEW_IDS)
    inputs['qualification']=dict(path=qualification_path.name,sha256=qsha,report=qualification)
    refresh_condition(inputs)


def refresh_condition(inputs):
    path=HERE/'condition_correction.json';correction,sha=read_json(path)
    assert correction['actual_condition']=='large_area' and correction['actual_load_protocol']=='full_coverage_all_modules'
    assert correction['loading_relationship_between_modules']=='simultaneous_coverage_and_loading_of_all_four_modules'
    inputs['condition_correction']=dict(path=path.name,sha256=sha,record=correction)
    inputs['actual_condition_source']=correction['confirmation_source']
    inputs['loading_relationship_between_modules']=correction['loading_relationship_between_modules']
    inputs['loading_equality']=correction['loading_equality']
    inputs['quantitative_loading']=correction['quantitative_loading']


def audit_disposition(record,scope,inputs,counts,byte_count):
    if 'raw_audit' not in inputs:return 'PENDING',{'independent_raw_audit':'not_attached'}
    audit=next(r for r in inputs['raw_audit']['report']['runs'] if r['run_id']==record['run_id'])
    ac=audit['scopes'][scope]['counts']
    for key in ['valid_outer_packets','valid_module_frames','ESKD','ESKF','valid_outer_packet_bytes']:
        assert ac.get(key,0)==counts.get(key,0),(record['run_id'],scope,key)
    reasons={}
    def within(event):
        if scope=='full_run':return True
        if isinstance(event,dict) and 'scope' in event:return event['scope']=='main'
        if isinstance(event,dict) and 'elapsed_s' in event:return float(event['elapsed_s'])>=10
        return True
    for key in ['anomalies','outer_sequence_discontinuities','inner_sequence_discontinuities','observed_base_discontinuities']:
        n=sum(within(e) for e in audit.get(key,[]))
        if n:reasons[key]=n
    if audit['cross_check_errors']:reasons['raw_summary_cross_check']=audit['cross_check_errors']
    if ac.get('missing_valid_expected_updates',0):reasons['missing_valid_expected_updates']=ac['missing_valid_expected_updates']
    if scope=='full_run':
        if ac.get('initial_unanchored_delta',0):reasons['initial_unanchored_delta']=ac['initial_unanchored_delta']
        tail=record['scopes'][scope].get('unassigned_raw_bytes',0)
        if tail:reasons['unassigned_raw_bytes']=tail
    status='CHECK REQUIRED' if reasons else 'PASS'
    if scope=='main':
        qualified=next(r for r in inputs['qualification']['report']['runs'] if r['run_id']==record['run_id'])
        assert status==qualified['independent_main_status']
    return status,reasons


def make_row(record,scope,inputs,issues):
    w=record['scopes'][scope];c=w['counts'];m=record['metadata'];P=c['valid_outer_packets']
    t=w['actual_duration_seconds'];B=c['valid_outer_packet_bytes'];hist=Counter();module_rows=[]
    weighted_payload_per_packet=0
    for slot in SLOTS:
        mod=w['modules'][f'M{slot}'];mc=mod['counts'];h={int(k):int(v) for k,v in mod['K_histogram'].items()}
        hs=histogram_statistics(h);hist.update(h);nd=mc.get('ESKD',0);nf=mc.get('ESKF',0);valid=mc['valid_frames']
        encoded=84*nd+2*sum(k*v for k,v in h.items())+1044*nf;coverage=valid/P
        checks={'hist_n':hs['n']==nd,'encoded_bytes':encoded==mc['payload_bytes'],
                'inner_count':nd+nf==valid,'q':math.isclose(nf/valid,mod['q_ESKF'])}
        for key in ['mean','median','p25','p75','max']:checks['K_'+key]=math.isclose(hs[key],mod['K'][key])
        for key,ok in checks.items():
            if not ok:issues.append(dict(run_id=record['run_id'],scope=scope,slot=slot,check=key))
        module_rows.append(dict(run_id=record['run_id'],scope=scope,slot=f'M{slot}',repeat=m['repeat'],batch_id=m['batch_id'],
                                loading_relationship_between_modules=inputs['loading_relationship_between_modules'],
                                valid_updates=valid,received_outer_opportunities=P,update_coverage=coverage,missing_valid_updates=P-valid,
                                ESKD_count=nd,ESKF_count=nf,q_ESKF=nf/valid,q_ESKF_pct=100*nf/valid,
                                K_ESKD_mean=hs['mean'],K_ESKD_median=hs['median'],K_ESKD_p25=hs['p25'],K_ESKD_p75=hs['p75'],
                                K_ESKD_IQR=hs['IQR'],K_ESKD_max=hs['max'],K1_ESKD_mean=mod['K1']['mean'],K2_ESKD_mean=mod['K2']['mean'],
                                initial_unanchored_delta=mc.get('initial_unanchored_delta',0),valid_payload_bytes=encoded,
                                status_counts=mod['status_counts']))
        weighted_payload_per_packet+=coverage*(mod['q_ESKF']*1044+(1-mod['q_ESKF'])*(84+2*hs['mean']))
    hs=histogram_statistics(hist);nd=c.get('ESKD',0);nf=c.get('ESKF',0);q=nf/(nd+nf)
    mix=record['packet_mix'][scope];f_hist={k:sum(v for code,v in mix.items() if code.count('F')==k) for k in range(5)}
    any_full=sum(f_hist[k] for k in range(1,5));partial=sum(v for code,v in mix.items() if 'X' in code or '?' in code)
    checks={'hist_n':hs['n']==nd,'module_inner_count':nd+nf==c['valid_module_frames'],
            'byte_identity':B==40*P+84*nd+2*sum(k*v for k,v in hist.items())+1044*nf+c.get('diagnostic_payload_bytes',0),
            'packet_mix_count':sum(mix.values())==P,'packet_mix_F':sum(k*v for k,v in f_hist.items())==nf,
            'packet_mix_D':sum(code.count('D')*n for code,n in mix.items())==nd,
            'logged_bytes':record['logged_valid_bytes'][scope]==B,
            'coverage_weighted_Lmean':math.isclose(40+weighted_payload_per_packet+c.get('diagnostic_payload_bytes',0)/P,B/P),
            'rate':math.isclose(P/t,w['valid_outer_packet_rate_Hz']),'q':math.isclose(q,w['q_ESKF']),
            'Kpooled':math.isclose(hs['mean'],w['K_ESKD_pooled']['mean'])}
    for key,ok in checks.items():
        if not ok:issues.append(dict(run_id=record['run_id'],scope=scope,check=key))
    qualification,reasons=audit_disposition(record,scope,inputs,c,B)
    if 'raw_audit' in inputs:
        audit=next(r for r in inputs['raw_audit']['report']['runs'] if r['run_id']==record['run_id'])
        assert audit['packet_frame_type_slot_order']==SLOTS
        assert audit['packet_frame_type_combinations'][scope]==mix
        for mr in module_rows:
            raw_mod=audit['scopes'][scope]['modules'][mr['slot'][1:]]
            assert raw_mod['counts']['valid_frames']==mr['valid_updates']
            assert {int(k):int(v) for k,v in raw_mod['K_histogram'].items()}=={int(k):int(v) for k,v in w['modules'][mr['slot']]['K_histogram'].items()}
    for r in module_rows:r['run_scope_independent_status']=qualification
    row=dict(run_id=record['run_id'],scope=scope,batch_id=m['batch_id'],repeat=m['repeat'],block=m['block'],
             metadata_condition=m['condition'],actual_condition='large_area',actual_load_protocol='full_coverage_all_modules',
             loading_relationship_between_modules=inputs['loading_relationship_between_modules'],
             slots='M0_M1_M2_M3',N=4,M=4,metadata_load_layers=m['load_layers'],independent_setup_n='not_established',
             summary_status=w['status'],summary_review_reasons=w['review_reasons'],independent_raw_status=qualification,
             independent_review_reasons=reasons,duration_s=t,valid_outer_packets=P,valid_inner_updates=nd+nf,valid_USB_bytes=B,
             rate_Hz=P/t,all_expected_updated_rate_Hz=c['all_expected_modules_updated_packets']/t,Lmean_B=B/P,
             valid_USB_Mbit_s=8*B/t/1e6,raw_arrival_Mbit_s=w['raw_arrival_Mbit_per_s'],
             ESKD_count=nd,ESKF_count=nf,q_ESKF_inner=q,q_ESKF_inner_pct=100*q,
             packet_any_ESKF_count=any_full,packet_any_ESKF_fraction=any_full/P,packet_any_ESKF_pct=100*any_full/P,
             packet_F0=f_hist[0],packet_F1=f_hist[1],packet_F2=f_hist[2],packet_F3=f_hist[3],packet_F4=f_hist[4],
             packet_all_ESKD=mix.get('DDDD',0),packet_incomplete_updates=partial,packet_pattern_counts=mix,
             K_ESKD_pooled_inner_mean=hs['mean'],K_ESKD_pooled_inner_median=hs['median'],K_ESKD_pooled_inner_IQR=hs['IQR'],
             K_ESKD_pooled_inner_max=hs['max'],valid_update_coverage=(nd+nf)/(4*P),
             missing_valid_expected_updates=c.get('missing_valid_expected_updates',0),
             outer_missing_sequence_numbers=c.get('outer_missing_sequence_numbers',0),
             matched_FULL_packet_B=4216,all_D_K0_packet_B=376,equal_rate_FULL_USB_saving_pct=100*(1-(B/P)/4216),
             FULL_USB_at_same_actual_rate_Mbit_s=8*4216*(P/t)/1e6,model_byte_identity_pass=checks['byte_identity'],
             diagnostic_payload_bytes=c.get('diagnostic_payload_bytes',0),
             initial_unanchored_delta=c.get('initial_unanchored_delta',0),known_start_boundary_bytes=w.get('known_start_boundary_bytes',0),
             unassigned_raw_bytes=w.get('unassigned_raw_bytes',0),session_observed_counters=w.get('session_counter_delta_at_packet_observation',{}))
    return row,module_rows


def aggregate(rows,module_rows,pass_only=False):
    groups=[];module_groups=[]
    for scope in ['main','full_run']:
        selected=[r for r in rows if r['scope']==scope and (not pass_only or r['independent_raw_status']=='PASS')]
        result=dict(scope=scope,selection='independent_PASS_only' if pass_only else 'all_recorded_windows_including_CHECK',
                    temporal_repeat_n=len(selected),batch_n=len({r['batch_id'] for r in selected}),
                    independent_setup_n='not_established',run_ids=[r['run_id'] for r in selected],
                    summary_status_counts=dict(Counter(r['summary_status'] for r in selected)),
                    independent_raw_status_counts=dict(Counter(r['independent_raw_status'] for r in selected)))
        for key in METRICS:
            values=[r[key] for r in selected]
            result[key+'_mean']=st.mean(values) if values else None
            result[key+'_sample_sd']=st.stdev(values) if len(values)>1 else None
        for key in ['ESKF_count','ESKD_count','valid_outer_packets','valid_inner_updates','packet_F0','packet_F1','packet_F2','packet_F3','packet_F4','packet_all_ESKD','packet_incomplete_updates','packet_any_ESKF_count','outer_missing_sequence_numbers','missing_valid_expected_updates']:
            result[key+'_total']=sum(r[key] for r in selected)
        result['q_ESKF_inner_pooled']=result['ESKF_count_total']/result['valid_inner_updates_total'] if selected else None
        result['packet_any_ESKF_pooled_fraction']=result['packet_any_ESKF_count_total']/result['valid_outer_packets_total'] if selected else None
        groups.append(result)
        for slot in [f'M{i}' for i in SLOTS]:
            chosen=[r for r in module_rows if r['scope']==scope and r['slot']==slot and r['run_id'] in result['run_ids']]
            mr=dict(scope=scope,slot=slot,selection=result['selection'],temporal_repeat_n=len(chosen),batch_n=result['batch_n'],
                    independent_setup_n='not_established',valid_updates_total=sum(r['valid_updates'] for r in chosen),
                    ESKD_count_total=sum(r['ESKD_count'] for r in chosen),ESKF_count_total=sum(r['ESKF_count'] for r in chosen),
                    K_ESKD_max_over_runs=max((r['K_ESKD_max'] for r in chosen),default=None))
            for key in ['K_ESKD_mean','K_ESKD_median','K_ESKD_IQR','q_ESKF_pct','update_coverage']:
                values=[r[key] for r in chosen]
                mr[key+'_mean']=st.mean(values) if values else None
                mr[key+'_sample_sd']=st.stdev(values) if len(values)>1 else None
            module_groups.append(mr)
    return groups,module_groups


def write_note(inputs,rows,module_rows,groups,module_groups,pass_groups,issues):
    text=['# N4 同时全覆盖按下：完整统计与异常保留','',
          '用户确认所有四个模块同时全覆盖按下。派生条件为large_area / full_coverage_all_modules，原metadata的zero_load不改；固件实际模式为DELTA。每模块力、接触面积、加载层及节奏未量化，不推断四模块等力或等面积。条件说明见[condition_correction.json](condition_correction.json)。','',
          '配置M0/M1/M2/M3、N=4、M=4、目标200 Hz、阈值8、本地SPI配置10 MHz。三条同一batch，Repeat 1/2/3是连续40 s时间窗口；主窗固定10–40 s，全部保留。没有将数千内帧视为独立实验，没有切除异常段或以速度选择记录。','',
          '## 全部三窗口描述：均值 ± 样本SD（包含CHECK）','',
          '| 窗口 | Hz | Lmean/B | 有效USB/Mbit/s | 普通K pooled-inner | 内帧q/% | 含任一ESKF包/% | 对FULL观察字节减少/% |',
          '|---|---:|---:|---:|---:|---:|---:|---:|']
    for g in groups:
        keys=['rate_Hz','Lmean_B','valid_USB_Mbit_s','K_ESKD_pooled_inner_mean','q_ESKF_inner_pct','packet_any_ESKF_pct','equal_rate_FULL_USB_saving_pct']
        text.append('| '+g['scope']+' | '+' | '.join(f"{g[k+'_mean']:.6f} ± {g[k+'_sample_sd']:.6f}" for k in keys)+' |')
    text+=['','以上n=3、batch=1是包含失败窗口的描述统计，不能作为三次全部通过的性能证明。SD使用run统计值、分母n−1。pooled-inner K是一个普通模块内帧的变化数，不是四个模块每包K之和。','',
           '## 逐条结果与完整性','',
           '| Repeat | 窗口 | Hz | Lmean/B | USB/Mbit/s | 原summary | 独立raw | 外层缺号 | 已收到包内缺更新 |',
           '|---:|---|---:|---:|---:|---|---|---:|---:|']
    for r in rows:text.append(f"| {r['repeat']} | {r['scope']} | {r['rate_Hz']:.6f} | {r['Lmean_B']:.6f} | {r['valid_USB_Mbit_s']:.6f} | {r['summary_status']} | {r['independent_raw_status']} | {r['outer_missing_sequence_numbers']} | {r['missing_valid_expected_updates']} |")
    text+=['','R2主窗有一个40 B状态包，四个模块都没有有效内更新，不能当成正常的DDDD/K=0包。R2、R3各缺4个外层序号，真实含义不能直接等同物理扫描损失数。已收到包内缺更新与外层缺号分别保留，不凭空补帧或补字节。','',
           '## 独立PASS子集（另列，原三条不删除）','',
           '| 窗口 | PASS窗口n | batch n | Hz | Lmean/B | USB/Mbit/s | run间SD |',
           '|---|---:|---:|---:|---:|---:|---|']
    for g in pass_groups:
        fmt=lambda v:'未定义' if v is None else f'{v:.6f}'
        text.append(f"| {g['scope']} | {g['temporal_repeat_n']} | {g['batch_n']} | {fmt(g['rate_Hz_mean'])} | {fmt(g['Lmean_B_mean'])} | {fmt(g['valid_USB_Mbit_s_mean'])} | {'未定义（n<2）' if g['temporal_repeat_n']<2 else fmt(g['valid_USB_Mbit_s_sample_sd'])} |")
    text+=['',('当前主窗仅R1独立通过，n=1的SD未定义；全程没有独立PASS窗口。R2/R3各有7次跨ESKF内序号前跳与一次外层缺号，仍保留CHECK，不能称三个重复通过。' if 'raw_audit' in inputs else '独立审计尚未附入，当前无qualified记录；n=1时SD未定义，不能补成0或称三个重复通过。'),'',
           '## 每包0–4个ESKF','',
           '| Repeat | 窗口 | 0F | 1F | 2F | 3F | 4F | 全DDDD | 含无更新槽包 | ESKF / ESKD内帧 |',
           '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:text.append(f"| {r['repeat']} | {r['scope']} | {r['packet_F0']} | {r['packet_F1']} | {r['packet_F2']} | {r['packet_F3']} | {r['packet_F4']} | {r['packet_all_ESKD']} | {r['packet_incomplete_updates']} | {r['ESKF_count']} / {r['ESKD_count']} |")
    text+=['','模式顺序M0/M1/M2/M3；D=ESKD，F=ESKF，X=无有效内更新。0F包含可能的XXXX状态包，故与DDDD分开。完整16种D/F模式及异常模式在JSON/CSV保留。packet_any=(1F+2F+3F+4F)/P；q_inner=nF/(nD+nF)，nF=Σ_k k×包数(kF)。不能把两种比例混为一谈，不能假设四模块同步发完整帧。','',
           '## 逐模块ESKD与更新覆盖','',
           '| Repeat | 窗口 | 槽位 | 有效更新 | 覆盖率 | K均值 | 中位数 [Q1,Q3] | IQR | Kmax | ESKF / ESKD | q_m/% |',
           '|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in module_rows:text.append(f"| {r['repeat']} | {r['scope']} | {r['slot']} | {r['valid_updates']} | {r['update_coverage']:.8f} | {r['K_ESKD_mean']:.6f} | {r['K_ESKD_median']:g} [{r['K_ESKD_p25']:g},{r['K_ESKD_p75']:g}] | {r['K_ESKD_IQR']:g} | {r['K_ESKD_max']} | {r['ESKF_count']} / {r['ESKD_count']} | {r['q_ESKF_pct']:.6f} |")
    text+=['','K从各slot有效ESKD histogram重算；分位数为(n−1)p线性插值，IQR=Q3−Q1。ESKF不赋予物理K=480。覆盖率c_m=已收到有效内更新数/P，只描述已收到有效外包的更新完整度，不能证明每次预期扫描都已传到PC。','',
           '## 准确字节账','',
           '包装24+4M=40 B；四模块FULL完整MUL1=40+4×1044=4216 B；四模块全D且各K=0为40+4×84=376 B。实际有效外包字节B_valid=40P+84nD+2ΣK+1044nF+诊断载荷字节，全部ESKF及40 B状态包均保留。','',
           '存在缺更新时必须带覆盖率：Lmean=40+Σ_m c_m[(1−q_m)(84+2K_D,m)+1044q_m]+诊断字节/P。R2的c_m<1，不能套用每包四个完整内更新的简化均值。f=P/t、有效USB=8B_valid/t，另存全模块更新包率和raw到达字节率。','',
           '1−Lmean/4216仅表示保持实际收到包率不变时相对FULL模型的观察字节减少。失败窗口缺帧、缺更新也影响观察流量，不能把它解释为可靠压缩收益或修复后的性能。没有补足丢失包的字节，更没有将低帧率筛掉。ESKF线上无触发原因码，不据短间隔诊断原因。','',
           f'统计/日志/混合字节恒等式检查问题：{issues}。这只表示计算一致，绝不表示协议完整性没有异常。','']
    if 'raw_audit' in inputs:
        text+=['[独立raw审计](raw_audit.json)及[资格判定](qualification.json)已附入并核对SHA，逐窗风险在JSON的independent_review_reasons保留。逐slot全部K histogram、有效更新数和每包D/F/X模式均与独立raw一致。原全程初始无锚点与尾部边界CHECK也保持；异常不会因CRC通过或统计一致而消失。','']
    text+=['## 复现','',
           '默认固定读取三条新summary、packet_log和本目录条件说明。--from-snapshot只读statistics.json；--refresh-raw-audit仅读同目录派生raw审计，按事件保留CHECK。原metadata、scopes、日志模式及SHA均冻结；源data与索引未改。','',
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
    pass_groups,pass_module_groups=aggregate(rows,module_rows,True)
    result=dict(schema_version=1,inputs=inputs,rows=rows,module_rows=module_rows,groups_all_recorded=groups,
                module_groups_all_recorded=module_groups,groups_independent_PASS=pass_groups,
                module_groups_independent_PASS=pass_module_groups,consistency_issues=issues,all_windows_retained=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name,selected in [('statistics.csv',rows),('statistics.modules.csv',module_rows)]:
        with (HERE/name).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(selected[0]));writer.writeheader()
            writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in selected)
    write_note(inputs,rows,module_rows,groups,module_groups,pass_groups,issues)
    print(json.dumps(dict(records=len(inputs['records']),run_scope_rows=len(rows),module_scope_rows=len(module_rows),
                          consistency_issues=issues,source_reads=not args.from_snapshot),ensure_ascii=False))


if __name__=='__main__':main()
