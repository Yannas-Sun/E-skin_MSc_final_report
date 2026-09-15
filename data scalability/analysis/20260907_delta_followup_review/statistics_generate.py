"""Describe nine fixed summary files without modifying data or applying exclusions.

Default freezes their inputs in statistics.json. --from-snapshot needs no source
data. --refresh-raw-audit optionally reads only the sibling derived raw audit.
The three new runs' actual large-area condition was confirmed by the operator;
their recorded zero-load labels are retained as provenance.
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
NEW_IDS = ['20260907_050453_154588', '20260907_050533_183636', '20260907_050613_222506']
SOURCES = {
    'new_large_area_user_confirmed': NEW_IDS,
    'previous_large_area': [f'DELTA/Dynamic_load/N=1/200Hz/M1/Large_area/Repeat_{i}' for i in range(1, 4)],
    'previous_zero_load': [f'DELTA/Zero_load/N=1/200Hz/M1/Repeat_{i}' for i in range(1, 4)],
}
LABELS = {'new_large_area_user_confirmed': '新Large_area（用户确认）',
          'previous_large_area': '旧Large_area（both层）', 'previous_zero_load': '旧zero_load（层未指定）'}
ERRORS = ['outer_crc_errors', 'inner_crc_errors', 'sequence_gap_events', 'lost_frames',
          'duplicate_frames', 'out_of_order_frames', 'format_errors', 'delta_base_mismatches']
METRICS = ['duration_s', 'rate_Hz', 'Lmean_B', 'valid_USB_Mbit_s', 'raw_arrival_Mbit_s',
           'K_ESKD_mean', 'K_ESKD_median', 'K_ESKD_IQR', 'ESKF_count', 'q_ESKF_pct']


def hist_stats(hist):
    hist = {int(k): int(v) for k, v in hist.items() if v}
    n = sum(hist.values())
    if not n:
        return dict(n=0, mean=None, median=None, p25=None, p75=None, IQR=None)
    ordered = sorted(hist.items())
    def at(index):
        acc = 0
        for k, count in ordered:
            acc += count
            if index < acc:
                return k
        raise AssertionError('histogram index')
    def quantile(p):
        rank = (n - 1) * p
        lo, hi = math.floor(rank), math.ceil(rank)
        return at(lo) + (at(hi) - at(lo)) * (rank - lo)
    p25, p75 = quantile(.25), quantile(.75)
    return dict(n=n, mean=sum(k*v for k, v in hist.items()) / n,
                median=quantile(.5), p25=p25, p75=p75, IQR=p75-p25)


def collect():
    out = []
    for group, directories in SOURCES.items():
        for directory in directories:
            path = DATA / directory / 'summary.json'
            blob = path.read_bytes()
            s = json.loads(blob.decode('utf-8-sig'))
            assert s['schema_version'] == 2
            m = s['metadata']
            assert m['target_modules'] == [1] and m['N'] == 1 and m['M'] == 4
            assert m['target_mode'] == 'DELTA' and m['target_hz'] == 200
            assert m['delta_threshold'] == 8 and m['spi_setting_hz'] == 10000000
            assert s['requested_duration_seconds'] == 40 and s['settle_seconds'] == 10
            assert m['batch_repeat_count'] == 3 and int(m['repeat']) == m['batch_repeat_index']
            assert m['condition'] == ('large_area' if group == 'previous_large_area' else 'zero_load')
            out.append(dict(group=group, run_id=s['run_id'], summary_path=path.relative_to(DATA).as_posix(),
                            summary_sha256=hashlib.sha256(blob).hexdigest(), metadata=m,
                            started_at=s['started_at'], result=s['result'],
                            completed_requested_duration=s['completed_requested_duration'],
                            capture_start_boundary_packets=s['capture_start_boundary_packets'],
                            raw_sha256=s['raw_sha256'], scopes=s['scopes']))
    assert len(out) == 9 and len({r['run_id'] for r in out}) == 9
    for group in SOURCES:
        rs = [r for r in out if r['group'] == group]
        assert {r['metadata']['repeat'] for r in rs} == {'1', '2', '3'}
        assert len({r['metadata']['batch_id'] for r in rs}) == 1
    correction_path = HERE / 'condition_correction.json'
    correction = json.loads(correction_path.read_text(encoding='utf-8-sig'))
    assert set(correction['run_ids']) == set(NEW_IDS) and correction['actual_condition'] == 'large_area'
    previous_path = HERE.parent / '20260907_delta_large_area_review' / 'raw_audit.json'
    previous = json.loads(previous_path.read_text(encoding='utf-8-sig'))
    return {'records': out, 'actual_new_condition': 'large_area',
            'actual_new_condition_source': 'User confirmed large-area dynamic loading, the same as the preceding batch',
            'condition_correction': {'path': correction_path.name, 'sha256': hashlib.sha256(correction_path.read_bytes()).hexdigest(), 'record': correction},
            'previous_large_area_audit': {'path': '../20260907_delta_large_area_review/raw_audit.json',
                'sha256': hashlib.sha256(previous_path.read_bytes()).hexdigest(),
                'inner_sequence_discontinuity_counts': {r['run_id']: len(r['inner_sequence_discontinuities']) for r in previous['runs']},
                'independent_disposition': previous.get('independent_disposition')}}


def row_for(record, scope_name, issues):
    w = record['scopes'][scope_name]
    m, c = record['metadata'], w['counts']
    mod = w['modules']['M1']
    hist = {int(k): int(v) for k, v in mod['K_histogram'].items()}
    h = hist_stats(hist)
    P, nF, nD = c['valid_outer_packets'], c.get('ESKF', 0), c.get('ESKD', 0)
    duration = w['actual_duration_seconds']
    byte_count = c['valid_outer_packet_bytes']
    q = nF / (nF + nD)
    expected_bytes = 40 * P + 1044 * nF + 84 * nD + 2 * sum(k*v for k, v in hist.items()) + c.get('diagnostic_payload_bytes', 0)
    checks = {'histogram_count': h['n'] == nD, 'valid_inner_count': nF + nD == c['valid_module_frames'],
              'actual_USB_byte_identity': byte_count == expected_bytes,
              'rate': math.isclose(P/duration, w['valid_outer_packet_rate_Hz']),
              'length': math.isclose(byte_count/P, w['Lmean_valid_packet_B']),
              'throughput': math.isclose(8*byte_count/duration/1e6, w['packet_completion_Mbit_per_s']),
              'q': math.isclose(q, w['q_ESKF'])}
    for field in ['mean', 'median', 'p25', 'p75']:
        checks['K_' + field] = math.isclose(h[field], w['K_ESKD_pooled'][field])
    for key, passed in checks.items():
        if not passed:
            issues.append({'run_id': record['run_id'], 'scope': scope_name, 'check': key})
    errors = {k: w.get('session_counter_delta_at_packet_observation', {}).get(k, 0) for k in ERRORS}
    row = dict(group=record['group'], run_id=record['run_id'], scope=scope_name,
               metadata_condition=m['condition'], actual_condition=('large_area' if record['run_id'] in NEW_IDS else m['condition']),
               actual_condition_source=('user_confirmation_2026_09_07' if record['run_id'] in NEW_IDS else 'original_metadata_not_reverified'),
               slots='M1', N=1, M=4, target_hz=m['target_hz'], threshold=m['delta_threshold'],
               load_layers=m['load_layers'], batch_id=m['batch_id'], repeat=m['repeat'], block=m['block'],
               temporal_repeat_n_in_batch=3, independent_setup_n='not_established',
               summary_status=w['status'], summary_review_reasons=w['review_reasons'],
               duration_s=duration, rate_Hz=P/duration, valid_outer_packets=P,
               valid_USB_bytes=byte_count, Lmean_B=byte_count/P, valid_USB_Mbit_s=8*byte_count/duration/1e6,
               raw_arrival_Mbit_s=w['raw_arrival_Mbit_per_s'], ESKD_count=nD, ESKF_count=nF,
               q_ESKF=q, q_ESKF_pct=100*q, K_ESKD_mean=h['mean'], K_ESKD_median=h['median'],
               K_ESKD_p25=h['p25'], K_ESKD_p75=h['p75'], K_ESKD_IQR=h['IQR'],
               K1_ESKD_mean=mod['K1']['mean'], K2_ESKD_mean=mod['K2']['mean'],
               missing_valid_expected_updates=c.get('missing_valid_expected_updates', 0),
               initial_unanchored_delta=c.get('initial_unanchored_delta', 0),
               known_start_boundary_bytes=w.get('known_start_boundary_bytes', 0),
               unassigned_raw_bytes=w.get('unassigned_raw_bytes', 0),
               summary_observed_errors=errors, ESKF_trigger_reason=mod['ESKF_trigger_reason'],
               independent_raw_qualification='pending' if record['run_id'] in NEW_IDS else 'reference_only_not_reaudited_here')
    return row


def refresh_audit(inputs):
    path = HERE / 'raw_audit.json'
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    inputs['independent_raw_audit'] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'report': raw}


def qualify(inputs, rows):
    audit = inputs.get('independent_raw_audit')
    previous = inputs['previous_large_area_audit']['inner_sequence_discontinuity_counts']
    for row in rows:
        if row['run_id'] in previous:
            row['independent_raw_qualification'] = 'CHECK REQUIRED: prior inner sequence discontinuities'
        elif row['run_id'] in NEW_IDS and audit:
            r = next(r for r in audit['report']['runs'] if r['run_id'] == row['run_id'])
            for key in ['anomalies', 'cross_check_errors', 'outer_sequence_discontinuities', 'inner_sequence_discontinuities', 'observed_base_discontinuities']:
                assert not r[key], (row['run_id'], key)
            counts = r['scopes'][row['scope']]['counts']
            for raw_field, stats_field in [('valid_outer_packets', 'valid_outer_packets'), ('valid_outer_packet_bytes', 'valid_USB_bytes'), ('ESKF', 'ESKF_count'), ('ESKD', 'ESKD_count')]:
                assert counts[raw_field] == row[stats_field]
            row['independent_raw_qualification'] = ('PASS: audited main window' if row['scope'] == 'main'
                                                   else 'CHECK REQUIRED: initial unanchored prefix and trailing partial byte retained')


def groups_for(records, rows):
    groups = []
    for group in SOURCES:
        for scope in ['main', 'full_run']:
            selected = [r for r in rows if r['group'] == group and r['scope'] == scope]
            histogram = Counter()
            for record in records:
                if record['group'] == group:
                    histogram.update({int(k): int(v) for k, v in record['scopes'][scope]['modules']['M1']['K_histogram'].items()})
            g = dict(group=group, scope=scope, temporal_repeat_n=len(selected), batch_n=len({r['batch_id'] for r in selected}),
                     independent_setup_n='not_established', run_ids=[r['run_id'] for r in selected],
                     status_counts=dict(Counter(r['summary_status'] for r in selected)),
                     all_runs_retained=True, ordinary_ESKD_pooled_histogram_statistics=hist_stats(histogram),
                     ESKF_count_total=sum(r['ESKF_count'] for r in selected), ESKD_count_total=sum(r['ESKD_count'] for r in selected))
            g['q_ESKF_pooled'] = g['ESKF_count_total'] / (g['ESKF_count_total'] + g['ESKD_count_total'])
            for field in METRICS:
                v = [r[field] for r in selected]
                g[field + '_mean'] = st.mean(v)
                g[field + '_sample_sd'] = st.stdev(v)
            groups.append(g)
    return groups


def write_note(inputs, rows, groups, comparisons, issues):
    lines = ['# M1 后续三条：统计审查', '',
             '**用户已确认实际为大面积动态加载，与上一批相同。** 三条metadata仍保留`zero_load`原标签；派生分析使用`recorded_condition=zero_load / actual_condition=large_area`，纠正依据见[condition_correction.json](condition_correction.json)。这不是由曲线推断出的条件，也不是零载噪声补测。', '',
             '新批run_id为20260907_050453_154588、20260907_050533_183636、20260907_050613_222506；同一batch、Block 1、Repeat 1/2/3。每条约40 s，主窗从10 s开始约30 s。三次均完整保留；n=3是同一setup的连续时间窗口，不是独立装配、独立板卡或独立加载重复。', '',
             '全部对照均为CS槽位M1、N=1、M=4、DELTA、目标200 Hz、阈值8、本地SPI配置10 MHz。旧Large_area记录load_layers=both；新批原metadata为unspecified，用户确认按同一大面积加载条件操作，具体力、接触面积和节奏未量化。旧零载仅作为不同加载条件的基线。槽位不提供实体板卡UID，本地配置也不是烧录读回证明。', '',
             '## 每批主窗与全程：均值 ± 样本SD', '',
             '| 记录批次 | 窗口 | Hz | 有效包均长/B | 有效USB/Mbit/s | 普通ESKD K | 总ESKF q/% |',
             '|---|---|---:|---:|---:|---:|---:|']
    for g in groups:
        vals=[f"{g[k+'_mean']:.6f} ± {g[k+'_sample_sd']:.6f}" for k in ['rate_Hz','Lmean_B','valid_USB_Mbit_s','K_ESKD_mean','q_ESKF_pct']]
        lines.append('| '+LABELS[g['group']]+' | '+g['scope']+' | '+' | '.join(vals)+' |')
    lines += ['', '各行n=3、batch=1；SD的分母为n−1。均值是三条run均值等权平均；没有把数千帧当作独立实验重复。三个不同批次分别列出，不按Repeat编号配对，也不混成n=9。', '',
              '## 新批逐条结果', '',
              '| Repeat | 窗口 | Hz | 均长/B | USB/Mbit/s | K均值 | K中位数 [Q1,Q3] | ESKF / ESKD | q/% | 原summary状态 |',
              '|---:|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:
        if r['run_id'] in NEW_IDS:
            lines.append(f"| {r['repeat']} | {r['scope']} | {r['rate_Hz']:.6f} | {r['Lmean_B']:.6f} | {r['valid_USB_Mbit_s']:.6f} | {r['K_ESKD_mean']:.6f} | {r['K_ESKD_median']:g} [{r['K_ESKD_p25']:g},{r['K_ESKD_p75']:g}] | {r['ESKF_count']} / {r['ESKD_count']} | {r['q_ESKF_pct']:.6f} | {r['summary_status']} |")
    lines += ['', 'K由普通有效ESKD的histogram重算。中位数和四分位数用排序后(n−1)p位置线性插值，IQR=Q3−Q1；不为ESKF虚构物理K。JSON还提供各批合并ESKD histogram的描述性分位数，其样本单位是帧，不能代替run级不确定度。', '',
              '## 有效字节与完整性口径', '',
              '有效USB吞吐率=有效完整MUL1字节×8/该窗实际秒数；包率=完整有效MUL1数/实际秒数；Lmean=有效完整字节/完整包数。raw_arrival吞吐单独保留，涉及读取块和截断边界，不冒充有效完整包字节或USB物理总线占用。', '',
              '本次N=1、M=4：ESKD完整MUL1=124+2K B；ESKF完整MUL1=1084 B。逐窗核验B_valid=40P+84 n_D+2ΣK+1044 n_F（另含任何诊断字节），所有ESKF都计入实际吞吐。q=n_F/(n_F+n_D)。ESKF触发原因没有线上字段，q不能拆成周期/高K/命令等原因。', '',
              f'内部summary/histogram/字节恒等式检查问题：{issues}。新三条GUI summary主窗PASS、全程CHECK REQUIRED均原样保留；全程初始无锚点ESKD和尾部字节不等同物理传输丢包。详细计数和错误字段在CSV/JSON。', '',
              '独立raw审计资格：' + ('[新批raw审计](raw_audit.md)核验三条主窗共18,009个完整MUL1=17,903 ESKD+106 ESKF，与本统计一致；CRC、格式、K、base、外层序号以及跨全部ESKD/ESKF的内层序号异常均为0。因此仅新批主窗标记独立PASS。全程201个初始无锚点ESKD及每条尾部1 B仍保留CHECK REQUIRED；不称所有完整capture无误。' if 'independent_raw_audit' in inputs else '**待独立raw审计完成**；此处尚不标记独立PASS或qualified。'), '',
              f"旧Large_area三条[独立审计](../20260907_delta_large_area_review/raw_audit.json)内层序号不连续事件分别为{list(inputs['previous_large_area_audit']['inner_sequence_discontinuity_counts'].values())}，均保持CHECK REQUIRED；表中数值仅为含原异常窗口的描述性对照。新三条没有复现这些异常，但不能据一次批次推断原因已修复。两批不合并为n=6，也不覆盖旧异常记录。", '',
              '## 描述性对照', '']
    for c in comparisons:
        lines.append(f"- 新批相对{LABELS[c['reference_group']]}：主窗平均有效包长差{c['Lmean_B_difference']:.6f} B（{c['Lmean_relative_difference_pct']:.3f}%），有效USB率差{c['valid_USB_Mbit_s_difference']:.6f} Mbit/s，普通K均值差{c['K_ESKD_mean_difference']:.6f}。条件关系：{c['condition_comparability']}。")
    lines += ['', '新批与旧Large_area按用户确认的相同名义加载条件作批次描述比较，但加载力、面积与节奏并未测定；不据均值差认定改进、退化或某ESKF触发原因。与旧零载的差异不能称为噪声增加。全部窗口均保留，未以高低速率筛选。', '',
              '## 复现', '',
              '运行`statistics_generate.py`读取固定9个summary；运行`statistics_generate.py --from-snapshot`仅用statistics.json内冻结输入。`--refresh-raw-audit`只额外读取同目录派生raw_audit.json。输入SHA256、原metadata与两种scope保存在JSON；不改原记录、索引或图。', '',
              '[逐run逐窗CSV](statistics.csv) · [输入快照与全部结果](statistics.json) · [生成脚本](statistics_generate.py)', '']
    (HERE/'statistics.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--from-snapshot', action='store_true')
    ap.add_argument('--refresh-raw-audit', action='store_true')
    args=ap.parse_args()
    path=HERE/'statistics.json'
    inputs=json.loads(path.read_text(encoding='utf-8'))['inputs'] if args.from_snapshot else collect()
    if args.refresh_raw_audit:
        refresh_audit(inputs)
    issues=[]
    rows=[row_for(r,s,issues) for r in inputs['records'] for s in ['main','full_run']]
    qualify(inputs, rows)
    groups=groups_for(inputs['records'], rows)
    new=next(g for g in groups if g['group']=='new_large_area_user_confirmed' and g['scope']=='main')
    comparisons=[]
    for ref in ['previous_large_area','previous_zero_load']:
        old=next(g for g in groups if g['group']==ref and g['scope']=='main')
        comparisons.append(dict(reference_group=ref, condition_comparability=('same_nominal_large_area_user_confirmed_not_quantitatively_matched' if ref=='previous_large_area' else 'different_load_condition_baseline_only'),
                                Lmean_B_difference=new['Lmean_B_mean']-old['Lmean_B_mean'],
                                Lmean_relative_difference_pct=100*(new['Lmean_B_mean']/old['Lmean_B_mean']-1),
                                valid_USB_Mbit_s_difference=new['valid_USB_Mbit_s_mean']-old['valid_USB_Mbit_s_mean'],
                                K_ESKD_mean_difference=new['K_ESKD_mean_mean']-old['K_ESKD_mean_mean']))
    result=dict(schema_version=1, inputs=inputs, rows=rows, groups=groups, comparisons=comparisons,
                consistency_issues=issues, no_exclusion=True, independent_audit_status='pending' if 'independent_raw_audit' not in inputs else 'new_main_PASS_full_CHECK_prior_large_area_CHECK_retained')
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    with (HERE/'statistics.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer=csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()} for row in rows)
    write_note(inputs,rows,groups,comparisons,issues)
    print(json.dumps(dict(records=len(inputs['records']), run_scope_rows=len(rows), batch_scope_groups=len(groups),
                          consistency_issues=issues, source_reads=not args.from_snapshot),ensure_ascii=False))


if __name__ == '__main__':
    main()
