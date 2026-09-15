"""Fixed three-run press/release statistics, with a frozen preceding-batch reference.

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
NEW_IDS = ['20260907_051941_159689', '20260907_052021_196300', '20260907_052101_230925']
PREVIOUS_IDS = ['20260907_050453_154588', '20260907_050533_183636', '20260907_050613_222506']
GROUPS = ['press_release', 'previous_large_area_main_PASS']
LABELS = {'press_release': '新批：大面积反复按压、释放', 'previous_large_area_main_PASS': '上一批：大面积动态加载'}
METRICS = ['duration_s', 'rate_Hz', 'Lmean_B', 'valid_USB_Mbit_s', 'raw_arrival_Mbit_s',
           'K_ESKD_mean', 'K_ESKD_median', 'K_ESKD_IQR', 'K_ESKD_max', 'ESKF_count',
           'q_ESKF_pct', 'equal_rate_FULL_USB_saving_pct', 'FULL_USB_at_same_actual_rate_Mbit_s']


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
    records = []
    for run_id in NEW_IDS:
        path = DATA / run_id / 'summary.json'
        s, sha = read_json(path)
        m = s['metadata']
        assert s['run_id'] == run_id and s['schema_version'] == 2
        assert m['target_modules'] == [1] and m['N'] == 1 and m['M'] == 4
        assert m['target_mode'] == 'DELTA' and m['condition'] == 'zero_load'
        assert m['target_hz'] == 200 and m['delta_threshold'] == 8 and m['spi_setting_hz'] == 10000000
        assert s['requested_duration_seconds'] == 40 and s['settle_seconds'] == 10
        assert s['completed_requested_duration']
        assert int(m['repeat']) == m['batch_repeat_index'] and m['batch_repeat_count'] == 3
        records.append(dict(group='press_release', run_id=run_id, started_at=s['started_at'], metadata=m,
                            summary_path=path.relative_to(DATA).as_posix(), summary_sha256=sha,
                            raw_sha256=s['raw_sha256'], scopes=s['scopes']))
    path = HERE.parent / '20260907_delta_followup_review' / 'statistics.json'
    previous, sha = read_json(path)
    references = [r for r in previous['inputs']['records'] if r['run_id'] in PREVIOUS_IDS]
    assert len(references) == 3
    for r in references:
        r['group'] = 'previous_large_area_main_PASS'
        records.append(r)
    for group in GROUPS:
        rs = [r for r in records if r['group'] == group]
        assert {r['metadata']['repeat'] for r in rs} == {'1', '2', '3'}
        assert len({r['metadata']['batch_id'] for r in rs}) == 1
    return dict(records=records, actual_condition='large_area', actual_load_protocol='repeated_press_release',
                actual_condition_source='User stated large-area repeated pressing and release in this conversation',
                quantitative_loading='Exact force, contact area, rate, duty cycle and loading layer are not specified',
                previous_statistics_source=dict(path='../20260907_delta_followup_review/statistics.json', sha256=sha),
                previous_raw_audit=previous['inputs']['independent_raw_audit'],
                original_large_area_diagnostic_groups=[g for g in previous['groups'] if g['group'] == 'previous_large_area'],
                original_large_area_audit=previous['inputs']['previous_large_area_audit'])


def refresh_audit(inputs):
    path = HERE / 'raw_audit.json'
    raw, sha = read_json(path)
    assert set(raw['snapshot_run_ids']) == set(NEW_IDS)
    assert not raw['changed_original_files']
    for record in inputs['records']:
        if record['run_id'] in NEW_IDS:
            key = record['run_id'] + '\\summary.json'
            assert raw['original_files_before'][key]['sha256'] == record['summary_sha256']
    inputs['new_raw_audit'] = dict(path='raw_audit.json', sha256=sha, report=raw)
    path = HERE / 'condition_correction.json'
    if path.is_file():
        correction, sha = read_json(path)
        assert correction['actual_condition'] == 'large_area'
        inputs['condition_correction'] = dict(path=path.name, sha256=sha, record=correction)


def make_row(record, scope, inputs, issues):
    m, w = record['metadata'], record['scopes'][scope]
    c = w['counts']; mod = w['modules']['M1']
    hist = {int(k): int(v) for k, v in mod['K_histogram'].items()}
    k = histogram_statistics(hist)
    P, nD, nF = c['valid_outer_packets'], c.get('ESKD', 0), c.get('ESKF', 0)
    B, duration = c['valid_outer_packet_bytes'], w['actual_duration_seconds']
    header = 24 + 4 * m['M']
    full_length = header + 1044 * m['N']
    q = nF / (nF + nD)
    checks = {'nD_histogram': nD == k['n'], 'valid_inner_count': nD+nF == c['valid_module_frames'],
              'mixed_byte_identity': B == header*P+84*nD+2*sum(a*b for a,b in hist.items())+1044*nF+c.get('diagnostic_payload_bytes',0),
              'q': math.isclose(q,w['q_ESKF']), 'rate': math.isclose(P/duration,w['valid_outer_packet_rate_Hz']),
              'Lmean': math.isclose(B/P,w['Lmean_valid_packet_B']),
              'USB_rate': math.isclose(8*B/duration/1e6,w['packet_completion_Mbit_per_s'])}
    for key in ['mean','median','p25','p75','max']:
        checks['K_'+key] = math.isclose(k[key],w['K_ESKD_pooled'][key])
    for key, ok in checks.items():
        if not ok:
            issues.append(dict(run_id=record['run_id'],scope=scope,check=key))
    audit_key = 'new_raw_audit' if record['run_id'] in NEW_IDS else 'previous_raw_audit'
    audit = inputs.get(audit_key)
    qualified = 'pending_independent_raw_audit'
    if audit:
        audited = next(r for r in audit['report']['runs'] if r['run_id'] == record['run_id'])
        for key in ['anomalies','cross_check_errors','outer_sequence_discontinuities','inner_sequence_discontinuities','observed_base_discontinuities']:
            assert not audited[key],(record['run_id'],key)
        ac = audited['scopes'][scope]['counts']
        assert (ac['valid_outer_packets'],ac['valid_outer_packet_bytes'],ac['ESKD'],ac['ESKF']) == (P,B,nD,nF)
        qualified = 'PASS: audited main window' if scope == 'main' else 'CHECK REQUIRED: initial file anchoring/boundary limits retained'
    return dict(group=record['group'],run_id=record['run_id'],scope=scope,metadata_condition=m['condition'],
                actual_condition='large_area',actual_condition_source='user_confirmation',
                actual_load_protocol='repeated_press_release' if record['run_id'] in NEW_IDS else 'large_area_dynamic_not_quantified',
                slots='M1',N=m['N'],M=m['M'],target_Hz=m['target_hz'],threshold=m['delta_threshold'],
                metadata_load_layers=m['load_layers'],batch_id=m['batch_id'],repeat=m['repeat'],block=m['block'],
                independent_setup_n='not_established',summary_status=w['status'],summary_review_reasons=w['review_reasons'],
                independent_raw_status=qualified,duration_s=duration,valid_outer_packets=P,valid_USB_bytes=B,
                rate_Hz=P/duration,Lmean_B=B/P,valid_USB_Mbit_s=8*B/duration/1e6,
                raw_arrival_Mbit_s=w['raw_arrival_Mbit_per_s'],ESKD_count=nD,ESKF_count=nF,q_ESKF=q,q_ESKF_pct=100*q,
                K_ESKD_mean=k['mean'],K_ESKD_median=k['median'],K_ESKD_p25=k['p25'],K_ESKD_p75=k['p75'],
                K_ESKD_IQR=k['IQR'],K_ESKD_max=k['max'],K1_ESKD_mean=mod['K1']['mean'],K2_ESKD_mean=mod['K2']['mean'],
                matched_FULL_packet_B=full_length,equal_rate_FULL_USB_saving_pct=100*(1-(B/P)/full_length),
                FULL_USB_at_same_actual_rate_Mbit_s=8*full_length*(P/duration)/1e6,
                model_byte_identity_pass=checks['mixed_byte_identity'],
                initial_unanchored_delta=c.get('initial_unanchored_delta',0),
                missing_valid_expected_updates=c.get('missing_valid_expected_updates',0),
                known_start_boundary_bytes=w.get('known_start_boundary_bytes',0),unassigned_raw_bytes=w.get('unassigned_raw_bytes',0),
                session_observed_counters=w.get('session_counter_delta_at_packet_observation',{}))


def aggregate(rows, records):
    output = []
    for group in GROUPS:
        for scope in ['main','full_run']:
            selected=[r for r in rows if r['group']==group and r['scope']==scope]
            histogram=Counter()
            for record in records:
                if record['group']==group:
                    histogram.update({int(k):int(v) for k,v in record['scopes'][scope]['modules']['M1']['K_histogram'].items()})
            result=dict(group=group,scope=scope,temporal_repeat_n=len(selected),batch_n=len({r['batch_id'] for r in selected}),
                        independent_setup_n='not_established',run_ids=[r['run_id'] for r in selected],
                        summary_status_counts=dict(Counter(r['summary_status'] for r in selected)),
                        independent_raw_status_counts=dict(Counter(r['independent_raw_status'] for r in selected)),
                        ESKF_count_total=sum(r['ESKF_count'] for r in selected),ESKD_count_total=sum(r['ESKD_count'] for r in selected),
                        K_ESKD_pooled=histogram_statistics(histogram),K_ESKD_max_over_all_runs=max(r['K_ESKD_max'] for r in selected))
            result['q_ESKF_pooled']=result['ESKF_count_total']/(result['ESKF_count_total']+result['ESKD_count_total'])
            for key in METRICS:
                values=[r[key] for r in selected]
                result[key+'_mean']=st.mean(values);result[key+'_sample_sd']=st.stdev(values)
            output.append(result)
    return output


def write_note(inputs,rows,groups,issues):
    text=['# 大面积反复按压、释放：三条统计与对照','',
          '用户说明实际加载为“大面积反复按压、释放”。三条原metadata仍是zero_load，派生分析标为actual_condition=large_area、actual_load_protocol=repeated_press_release；原文件未修改。实际面积、力、节奏、占空比及层未量化，不补填这些值。','',
          '新批为CS槽位M1，N=1、M=4、DELTA、目标200 Hz、阈值8、本地SPI配置10 MHz；三条同一batch、Block 1、Repeat 1/2/3，每条约40 s，主窗从10 s开始约30 s。n=3指同一setup的连续时间窗口，不是独立装配或独立受试板卡。所有窗口都保留。','',
          '主统计固定使用约10–40 s，包含该窗内的静息与活动，不按曲线切出较高或较低流量片段。原记录没有加载事件标记，不能精确把某个峰识别为按压或释放。','',
          '## 每批、每窗：均值 ± 样本SD（n=3，batch=1）','',
          '| 批次 | 窗口 | Hz | Lmean/B | 有效USB/Mbit/s | 普通K均值 | 总q/% | 对FULL等包率节省/% |',
          '|---|---|---:|---:|---:|---:|---:|---:|']
    for g in groups:
        values=[f"{g[k+'_mean']:.6f} ± {g[k+'_sample_sd']:.6f}" for k in ['rate_Hz','Lmean_B','valid_USB_Mbit_s','K_ESKD_mean','q_ESKF_pct','equal_rate_FULL_USB_saving_pct']]
        text.append('| '+LABELS[g['group']]+' | '+g['scope']+' | '+' | '.join(values)+' |')
    text+=['','SD使用三个run统计值、分母n−1；没有把帧数当作独立实验样本数。上一批只使用050453_154588、050533_183636、050613_222506三条，来自冻结统计快照；两批分开，不把Repeat编号当作配对实验。','',
           '## 新批逐条普通ESKD分布与完整帧','',
           '| Repeat | 窗口 | K均值 | 中位数 | Q1–Q3 | IQR | 普通K最大值 | ESKF / ESKD | q/% |',
           '|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        if r['run_id'] in NEW_IDS:
            text.append(f"| {r['repeat']} | {r['scope']} | {r['K_ESKD_mean']:.6f} | {r['K_ESKD_median']:g} | {r['K_ESKD_p25']:g}–{r['K_ESKD_p75']:g} | {r['K_ESKD_IQR']:g} | {r['K_ESKD_max']} | {r['ESKF_count']} / {r['ESKD_count']} | {r['q_ESKF_pct']:.6f} |")
    text+=['','K分布仅来自有效普通ESKD的histogram；分位数使用(n−1)p位置线性插值，IQR=Q3−Q1。JSON另列每批合并帧的描述性分布，不能代替run级SD。ESKF不赋予物理K=480。观察到的普通Kmax低于480也不能排除某ESKF由高K触发，因为该次普通K未在线上传输。','',
           '## 实际混合字节与FULL参照','',
           '使用完整有效MUL1字节与该窗实际秒数：f=P/t、Lmean=B_valid/P、USB_valid=8B_valid/t。raw到达吞吐单独输出，保留读取块和边界差异。ESKF全部计入实际字节，没有从DELTA吞吐中删去。','',
           'M=4、N=1时包装为24+4M=40 B，普通包为124+2K B，ESKF包为1084 B。逐窗核对B_valid=40P+84n_D+2ΣK+1044n_F+诊断字节；q=n_F/(n_F+n_D)。等价Lmean=40+(1−q)(84+2K_D)+1044q（本数据每包一个有效模块且无诊断载荷）。','',
           '匹配FULL参照为(24+4M)+1044N=1084 B/包。等实际包率节省=1−Lmean/1084，使用本批实际f不变的反事实FULL字节率；它不是两批实际速率之比，不是新测FULL，也不是USB物理总线总开销。协议未记录ESKF触发原因，因此不将q自动归因于周期或按压。','',
           f'统计与字节恒等式核验问题：{issues}。','',
           '## 完整性与比较边界','']
    if 'new_raw_audit' in inputs:
        text+=['[独立raw审计](raw_audit.json)与本统计计数一致：新主窗18,039个MUL1=17,948 ESKD+91 ESKF；全程24,059=23,938 ESKD+121 ESKF。外内CRC、格式、K、base、目标更新及跨ESKD/ESKF内序号连续性未发现异常，新三条仅主窗标记独立PASS。原全程CHECK REQUIRED保留：有367个初始无锚点ESKD，Repeat 1/2各有1 B尾片，Repeat 3没有尾片。输入summary的SHA与独立审计清单一致，审计前后原文件SHA未改变。','']
    else:
        text+=['独立raw审计尚待附入；GUI summary主窗PASS没有被自动转换成独立PASS。','']
    main={g['group']:g for g in groups if g['scope']=='main'}
    new,old=main['press_release'],main['previous_large_area_main_PASS']
    text += [f"新批相对上一批主窗均长差{new['Lmean_B_mean']-old['Lmean_B_mean']:.6f} B（{100*(new['Lmean_B_mean']/old['Lmean_B_mean']-1):.3f}%），有效USB差{new['valid_USB_Mbit_s_mean']-old['valid_USB_Mbit_s_mean']:.6f} Mbit/s，普通K均值差{new['K_ESKD_mean_mean']-old['K_ESKD_mean_mean']:.6f}。两批都为大面积加载，但反复按压/释放节奏和力没有定量匹配，不能据差值认定算法改进或退化。",'']
    legacy=next(g for g in inputs['original_large_area_diagnostic_groups'] if g['scope']=='main')
    events=inputs['original_large_area_audit']['inner_sequence_discontinuity_counts']
    text += [f"最初Large_area批次仅作诊断背景：主窗均长{legacy['Lmean_B_mean']:.6f}±{legacy['Lmean_B_sample_sd']:.6f} B，USB{legacy['valid_USB_Mbit_s_mean']:.6f}±{legacy['valid_USB_Mbit_s_sample_sd']:.6f} Mbit/s；三条已有内序号事件{list(events.values())}，保持CHECK REQUIRED，不进入本次通过审计批次的均值，也不被新记录覆盖。",'',
             '## 复现','',
             'statistics_generate.py默认仅读取固定三条新summary及上一轮派生统计快照。--from-snapshot只读取本目录statistics.json；--refresh-raw-audit额外读取同目录派生审计及条件纠正文档。JSON保留输入metadata、scopes和SHA，原data、索引及图未改。','',
             '[逐run逐窗CSV](statistics.csv) · [输入及汇总JSON](statistics.json) · [生成脚本](statistics_generate.py)','']
    (HERE/'statistics.md').write_text('\n'.join(text),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--from-snapshot',action='store_true')
    parser.add_argument('--refresh-raw-audit',action='store_true')
    args=parser.parse_args()
    path=HERE/'statistics.json'
    inputs=read_json(path)[0]['inputs'] if args.from_snapshot else collect_inputs()
    if args.refresh_raw_audit:
        refresh_audit(inputs)
    issues=[]
    rows=[make_row(r,scope,inputs,issues) for r in inputs['records'] for scope in ['main','full_run']]
    groups=aggregate(rows,inputs['records'])
    result=dict(schema_version=1,inputs=inputs,rows=rows,groups=groups,consistency_issues=issues,all_windows_retained=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (HERE/'statistics.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader()
        writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)
    write_note(inputs,rows,groups,issues)
    print(json.dumps(dict(records=len(inputs['records']),run_scope_rows=len(rows),batch_scope_groups=len(groups),consistency_issues=issues,source_reads=not args.from_snapshot),ensure_ascii=False))


if __name__=='__main__':
    main()
