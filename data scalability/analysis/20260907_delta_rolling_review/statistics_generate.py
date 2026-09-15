"""Fixed three-run rolling statistics, with two frozen preceding-batch references.

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
NEW_IDS = ['20260907_053858_001637', '20260907_053938_027960', '20260907_054018_056649']
PRESS_IDS = ['20260907_051941_159689', '20260907_052021_196300', '20260907_052101_230925']
DYNAMIC_IDS = ['20260907_050453_154588', '20260907_050533_183636', '20260907_050613_222506']
GROUPS = ['rolling', 'previous_press_release_main_PASS', 'previous_large_area_main_PASS']
LABELS = {'rolling': '新批：rolling', 'previous_press_release_main_PASS': '前批：大面积反复按压、释放', 'previous_large_area_main_PASS': '前批：大面积动态加载'}
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
        records.append(dict(group='rolling', run_id=run_id, started_at=s['started_at'], metadata=m,
                            summary_path=path.relative_to(DATA).as_posix(), summary_sha256=sha,
                            raw_sha256=s['raw_sha256'], scopes=s['scopes']))
    path = HERE.parent / '20260907_delta_press_release_review' / 'statistics.json'
    previous, sha = read_json(path)
    references = [r for r in previous['inputs']['records'] if r['run_id'] in PRESS_IDS + DYNAMIC_IDS]
    assert len(references) == 6
    for r in references:
        r['group'] = 'previous_press_release_main_PASS' if r['run_id'] in PRESS_IDS else 'previous_large_area_main_PASS'
        records.append(r)
    for group in GROUPS:
        rs = [r for r in records if r['group'] == group]
        assert {r['metadata']['repeat'] for r in rs} == {'1', '2', '3'}
        assert len({r['metadata']['batch_id'] for r in rs}) == 1
    previous_audits = [previous['inputs']['new_raw_audit'], previous['inputs']['previous_raw_audit']]
    return dict(records=records, actual_condition='rolling', actual_load_protocol='rolling',
                actual_condition_source='User stated rolling in this conversation',
                quantitative_loading='Force, contact area, speed, route, duty cycle and loading layer are not specified',
                previous_statistics_source=dict(path='../20260907_delta_press_release_review/statistics.json', sha256=sha),
                previous_raw_audit=dict(source_audits=[dict(path=p,sha256=r['sha256']) for p,r in zip(
                                            ['../20260907_delta_press_release_review/raw_audit.json','../20260907_delta_followup_review/raw_audit.json'],previous_audits)],
                                        report=dict(runs=[run for r in previous_audits for run in r['report']['runs']])),
                original_large_area_diagnostic_groups=previous['inputs']['original_large_area_diagnostic_groups'],
                original_large_area_audit=previous['inputs']['original_large_area_audit'])


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
        assert correction['actual_condition'] == 'rolling'
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
                actual_condition='rolling' if record['run_id'] in NEW_IDS else 'large_area',actual_condition_source='user_confirmation',
                actual_load_protocol=('rolling' if record['run_id'] in NEW_IDS else 'repeated_press_release' if record['run_id'] in PRESS_IDS else 'large_area_dynamic_not_quantified'),
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


def write_note(inputs, rows, groups, issues):
    text=['# Rolling 三条：统计与前两批对照','',
          '用户说明实际条件为rolling。三条原metadata仍为zero_load，派生分析使用actual_condition=rolling；不改原文件，也不把这些记录当作零载。力、接触面积、滚动速度、路径、占空比及加载层未定量记录，不补填。','',
          '三条均为CS槽位M1、N=1、M=4、DELTA、目标200 Hz、阈值8、本地SPI配置10 MHz；同一batch、Block 1、Repeat 1/2/3。每条约40 s，固定主窗约10–40 s，包含静息与活动，不按曲线切片。n=3是同一setup内连续时间窗口，不是独立装配、独立板卡或独立加载实验。','',
          '## 每批每窗：均值 ± 样本SD（n=3、batch=1）','',
          '| 批次 | 窗口 | Hz | Lmean/B | 有效USB/Mbit/s | 普通ESKD K | 总ESKF q/% | 对FULL等包率节省/% |',
          '|---|---|---:|---:|---:|---:|---:|---:|']
    for g in groups:
        values=[f"{g[k+'_mean']:.6f} ± {g[k+'_sample_sd']:.6f}" for k in ['rate_Hz','Lmean_B','valid_USB_Mbit_s','K_ESKD_mean','q_ESKF_pct','equal_rate_FULL_USB_saving_pct']]
        text.append('| '+LABELS[g['group']]+' | '+g['scope']+' | '+' | '.join(values)+' |')
    text+=['','各批单独统计，SD分母n−1。前两批从既有冻结statistics.json获取，均主窗独立PASS；不同批次的Repeat编号不表示配对，不合并为n=9，也不把内帧数当独立重复数。','',
           '## 新批逐条','',
           '| Repeat | 窗口 | Hz | Lmean/B | USB/Mbit/s | K均值 | 中位数 [Q1,Q3] | IQR | 普通Kmax | ESKF / ESKD | q/% |',
           '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        if r['run_id'] in NEW_IDS:
            text.append(f"| {r['repeat']} | {r['scope']} | {r['rate_Hz']:.6f} | {r['Lmean_B']:.6f} | {r['valid_USB_Mbit_s']:.6f} | {r['K_ESKD_mean']:.6f} | {r['K_ESKD_median']:g} [{r['K_ESKD_p25']:g},{r['K_ESKD_p75']:g}] | {r['K_ESKD_IQR']:g} | {r['K_ESKD_max']} | {r['ESKF_count']} / {r['ESKD_count']} | {r['q_ESKF_pct']:.6f} |")
    text+=['','K由有效普通ESKD的histogram重算；分位数在(n−1)p位置线性插值，IQR=Q3−Q1。普通Kmax是ESKD中实际观察到的最大值，ESKF不赋予物理K=480。普通Kmax低于480不能排除某ESKF的高K触发，因为完整帧未携带该次普通变化计数。','',
           '## 实际混合字节与FULL参照','',
           'f=P/t，Lmean=B_valid/P，有效USB=8B_valid/t；t使用实际窗口时长，B_valid是有效完整MUL1字节。raw到达字节率另列，保留读取块与边界差异。全部ESKF都计入实际吞吐。','',
           'M=4、N=1时包装40 B，普通MUL1=124+2K B，ESKF MUL1=1084 B。逐窗核验B_valid=40P+84n_D+2ΣK+1044n_F+诊断字节；q=n_F/(n_F+n_D)。本数据每包一个有效模块且无诊断字节，亦满足Lmean=40+(1−q)(84+2K_D)+1044q。','',
           '同M/N的FULL参照为(24+4M)+1044N=1084 B/包；等实际包率节省=1−Lmean/1084，保持本批实际f不变。它是匹配协议字节模型的反事实FULL比较，不是新测FULL或不同批次raw速率比，也不代表USB物理总线全部开销。没有在线触发原因字段，不能把全部ESKF自动归因为周期刷新。','',
           f'统计与混合字节恒等式问题：{issues}。','',
           '## 独立完整性与解释限制','']
    if 'new_raw_audit' in inputs:
        text+=['[独立raw审计](raw_audit.json)与本统计一致：主窗18,033个MUL1=17,943 ESKD+90 ESKF；全程24,051=23,931 ESKD+120 ESKF。外内CRC、格式、K、base、缺模块更新、跨全部ESKD/ESKF内序号以及日志/summary差异均未发现异常，新三条只对主窗标独立PASS。','',
               '全程原CHECK REQUIRED保留：初始无锚点ESKD为195/182/162（合计539），尾片1/1/0 B，不能套用其他批次的边界数量。summary SHA与独立审计源文件清单一致，审计前后原文件SHA不变。','']
    else:
        text+=['独立raw资格待审计完成；GUI summary PASS没有自动升级为独立PASS。','']
    mains={g['group']:g for g in groups if g['scope']=='main'}
    new=mains['rolling']
    for ref in ['previous_press_release_main_PASS','previous_large_area_main_PASS']:
        old=mains[ref]
        text.append(f"- Rolling相对{LABELS[ref]}：主均长差{new['Lmean_B_mean']-old['Lmean_B_mean']:.6f} B（{100*(new['Lmean_B_mean']/old['Lmean_B_mean']-1):.3f}%），有效USB差{new['valid_USB_Mbit_s_mean']-old['valid_USB_Mbit_s_mean']:.6f} Mbit/s，普通K均值差{new['K_ESKD_mean_mean']-old['K_ESKD_mean_mean']:.6f}。")
    text+=['','这是不同加载方式/批次的描述比较；滚动路径、力和节奏未匹配，不能把差异归因于算法改进、退化或统一噪声变化。加载事件没有同步标记，不精确识别单次滚动接触或释放。','']
    legacy=next(g for g in inputs['original_large_area_diagnostic_groups'] if g['scope']=='main')
    events=inputs['original_large_area_audit']['inner_sequence_discontinuity_counts']
    text+=[f"最初Large_area批次仍为诊断背景：主均长{legacy['Lmean_B_mean']:.6f}±{legacy['Lmean_B_sample_sd']:.6f} B，三条内序号事件{list(events.values())}，保留CHECK REQUIRED。该旧批未加入上述通过审计批次的统计，也未被新数据覆盖。",'',
           '## 复现','',
           'statistics_generate.py仅读固定三条新summary及前批派生统计快照；--from-snapshot仅从本目录statistics.json重建，--refresh-raw-audit额外读取同目录派生raw审计与条件说明。JSON冻结原metadata、scopes、源SHA与独立审计。原data、索引和图未改。','',
           '[逐run逐窗CSV](statistics.csv) · [输入与全部汇总JSON](statistics.json) · [生成脚本](statistics_generate.py)','']
    (HERE/'statistics.md').write_text('\n'.join(text),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--from-snapshot',action='store_true')
    parser.add_argument('--refresh-raw-audit',action='store_true')
    args=parser.parse_args()
    path=HERE/'statistics.json'
    inputs=read_json(path)[0]['inputs'] if args.from_snapshot else collect_inputs()
    for audit, source_path in zip(inputs['previous_raw_audit']['source_audits'],
                                  ['../20260907_delta_press_release_review/raw_audit.json','../20260907_delta_followup_review/raw_audit.json']):
        audit['path'] = source_path
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
