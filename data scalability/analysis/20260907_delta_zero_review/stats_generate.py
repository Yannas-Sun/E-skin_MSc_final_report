"""Summarize the fixed DELTA zero-load snapshot; writes derived statistics only.

Default: read exactly the 45 plan entries, resolving their source/destination,
and freeze the input statistics. --from-snapshot rebuilds outputs without any
access to measured files or the current FULL index.
"""
from collections import Counter, defaultdict
from datetime import datetime
import argparse
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data'
METRICS = {'rate_Hz': 'main_rate_Hz', 'Lmean_B': 'main_Lmean_B',
           'packet_Mbit_s': 'main_packet_Mbit_s', 'raw_arrival_Mbit_s': 'main_raw_arrival_Mbit_s',
           'K_ESKD': 'main_K_ESKD_mean', 'q_ESKF': 'main_q_ESKF',
           'q_ESKF_pct': 'main_q_ESKF_pct', 'K_effective': 'main_K_effective'}
ERRORS = ('outer_crc_errors', 'inner_crc_errors', 'sequence_gap_events', 'lost_frames',
          'duplicate_frames', 'out_of_order_frames', 'format_errors', 'delta_base_mismatches')


def csv_read(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def csv_write(name, rows):
    assert rows
    with (HERE / name).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def moments(values):
    known = [float(v) for v in values if v is not None]
    assert all(math.isfinite(v) for v in known)
    return (statistics.mean(known) if known else None,
            statistics.stdev(known) if len(known) > 1 else None, len(known))


def add_metrics(row, selected, metrics=METRICS):
    for label, source in metrics.items():
        mean, sd, n = moments(r[source] for r in selected)
        row.update({label + '_mean': mean, label + '_sample_sd': sd, label + '_known_n': n})


def close(actual, expected):
    return math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9)


def collect_inputs():
    plan_path = HERE / 'organization_plan.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8-sig'))
    assert len(plan['runs']) == 45 and len({r['run_id'] for r in plan['runs']}) == 45
    records, module_rows, issues = [], [], []
    for entry in plan['runs']:
        candidates = [Path(entry[k]).resolve() for k in ('source', 'destination')]
        assert all(p.is_relative_to(DATA.resolve()) for p in candidates)
        present = [p for p in candidates if (p / 'summary.json').is_file()]
        assert len(present) == 1, (entry['run_id'], present)
        path = present[0] / 'summary.json'
        blob = path.read_bytes()
        s = json.loads(blob.decode('utf-8-sig'))
        m, w, full = s['metadata'], s['scopes']['main'], s['scopes']['full_run']
        counts = w['counts']
        assert s['run_id'] == entry['run_id'] and s['schema_version'] == 2
        assert m['target_mode'] == 'DELTA' and m['condition'] == 'zero_load'
        assert s['completed_requested_duration'] and s['requested_duration_seconds'] == 40
        assert s['settle_seconds'] == w['start_elapsed_s'] == 10
        assert m['target_hz'] == 200 and m['M'] == 4 and m['delta_threshold'] == 8
        assert len(set(m['target_modules'])) == m['N']
        assert int(m['repeat']) == m['batch_repeat_index'] and m['batch_repeat_count'] == 3
        name = '_'.join(f'M{v}' for v in sorted(m['target_modules']))
        nF, nD = counts.get('ESKF', 0), counts.get('ESKD', 0)
        q = nF / (nF + nD) if nF + nD else None
        if q is not None and not close(q, w['q_ESKF']): issues.append([s['run_id'], 'q_count_mismatch'])
        ksum, dsum, frame_bytes = 0, 0, 0
        for slot in m['target_modules']:
            mod = w['modules'][f'M{slot}']; c = mod['counts']; k = mod['K']
            assert mod['expected']
            hist = {int(key): int(value) for key, value in mod['K_histogram'].items()}
            h_n, h_sum = sum(hist.values()), sum(key * value for key, value in hist.items())
            if h_n != k['n'] or h_n != c.get('ESKD', 0): issues.append([s['run_id'], f'M{slot}_K_denominator'])
            if h_n and not close(h_sum / h_n, k['mean']): issues.append([s['run_id'], f'M{slot}_K_histogram_mean'])
            ksum += h_sum; dsum += h_n
            encoded = 1044 * c.get('ESKF', 0) + 84 * c.get('ESKD', 0) + 2 * h_sum
            frame_bytes += encoded
            if encoded != c['payload_bytes']: issues.append([s['run_id'], f'M{slot}_byte_identity'])
            module_rows.append(dict(run_id=s['run_id'], N=m['N'], modules=name, slot=f'M{slot}',
                batch_id=m['batch_id'], repeat=int(m['repeat']), main_status=w['status'],
                ESKF_count=c.get('ESKF', 0), ESKD_count=c.get('ESKD', 0),
                K_ESKD=k['mean'], K1_ESKD=mod['K1']['mean'], K2_ESKD=mod['K2']['mean'],
                K_zero_fraction=k['zero_fraction'], K_max=k['max'], q_ESKF=mod['q_ESKF'],
                valid_update_rate_Hz=mod['valid_update_rate_Hz'],
                ESKF_PC_interval_mean_s=mod['ESKF_interval_mean_s'],
                ESKF_trigger_reason=mod['ESKF_trigger_reason']))
        kD = ksum / dsum if dsum else None
        if dsum != nD or (dsum and not close(kD, w['K_ESKD_pooled']['mean'])):
            issues.append([s['run_id'], 'pooled_K_mismatch'])
        P = counts['valid_outer_packets']
        coverage = counts['valid_expected_module_frames'] / (P * m['N']) if P else None
        packet_bytes = 40 * P + frame_bytes + counts.get('diagnostic_payload_bytes', 0)
        if packet_bytes != w['valid_outer_packet_bytes']: issues.append([s['run_id'], 'USB_byte_identity'])
        keff = (1-q) * kD + 480*q if q is not None and kD is not None else None
        row = dict(run_id=s['run_id'], started_at=s['started_at'], mode='DELTA', condition='zero_load',
            N=m['N'], M=m['M'], modules=name, batch_id=m['batch_id'], block=m['block'], repeat=int(m['repeat']),
            target_hz=m['target_hz'], delta_threshold=m['delta_threshold'], main_status=w['status'],
            full_status=full['status'], main_eligible=w['status']=='PASS',
            main_review_reasons=';'.join(w['review_reasons']), full_review_reasons=';'.join(full['review_reasons']),
            main_duration_s=w['actual_duration_seconds'], main_packets=P, main_ESKF_count=nF,
            main_ESKD_count=nD, main_valid_module_frames=counts['valid_module_frames'],
            main_rate_Hz=w['valid_outer_packet_rate_Hz'], main_Lmean_B=w['Lmean_valid_packet_B'],
            main_packet_Mbit_s=w['packet_completion_Mbit_per_s'], main_raw_arrival_Mbit_s=w['raw_arrival_Mbit_per_s'],
            main_K_ESKD_mean=kD, main_q_ESKF=q, main_q_ESKF_pct=100*q if q is not None else None,
            main_K_effective=keff, main_expected_update_coverage=coverage,
            main_ESKF_byte_increment_vs_ordinary_mean_B=2*m['N']*q*(480-kD) if kD is not None else None,
            main_missing_valid_expected_updates=counts.get('missing_valid_expected_updates', 0),
            main_diagnostic_payload_bytes=counts.get('diagnostic_payload_bytes', 0),
            main_trailing_raw_bytes=counts.get('trailing_unassigned_raw_bytes', 0),
            full_initial_prefix_unknown='initial_delta_prefix_cache_not_verifiable_from_file' in full['review_reasons'],
            full_trailing_raw_bytes=full['counts'].get('trailing_unassigned_raw_bytes', 0),
            summary_sha256=hashlib.sha256(blob).hexdigest(),
            new_relative_path=Path(entry['destination']).resolve().relative_to(DATA.resolve()).as_posix(),
            identity_source=m.get('module_identity_source', ''), load_layers=m.get('load_layers'),
            deployment_confirmed=m.get('deployment_confirmed'))
        row['main_error_deltas'] = {key: w['session_counter_delta_at_packet_observation'].get(key, 0) for key in ERRORS}
        row['full_counts'] = full['counts']
        row['full_error_deltas'] = {key: s['session_counters']['delta'].get(key, 0) for key in ERRORS}
        records.append(row)
    full_index = DATA / 'primary_matrix.csv'
    full_rows = [r for r in csv_read(full_index) if r['mode'] == 'FULL']
    assert len(full_rows) == 45 and all(r['main_status'] == 'PASS' for r in full_rows)
    return dict(collected_at=datetime.now().astimezone().isoformat(),
        plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        full_primary_index_sha256=hashlib.sha256(full_index.read_bytes()).hexdigest(),
        records=records, module_rows=module_rows, full_reference_rows=full_rows,
        summary_consistency_issues=issues)


def combo_statistics(records, pass_only=False):
    groups = defaultdict(list)
    for row in records: groups[(row['N'], row['modules'])].append(row)
    expected = {'_'.join(f'M{x}' for x in combo) for n in range(1, 5) for combo in itertools.combinations(range(4), n)}
    assert {key[1] for key in groups} == expected
    output = []
    for (N, name), group in sorted(groups.items()):
        assert len(group) == 3 and {r['repeat'] for r in group} == {1,2,3}
        assert len({r['batch_id'] for r in group}) == len({r['block'] for r in group}) == 1
        selected = [r for r in group if r['main_eligible']] if pass_only else group
        row = dict(N=N, modules=name, mode='DELTA', condition='zero_load', target_hz=200,
            temporal_repeat_n=len(selected), recorded_repeat_n=len(group),
            eligible_repeat_n=sum(r['main_eligible'] for r in group), batch_n=len({r['batch_id'] for r in selected}),
            batch_id=group[0]['batch_id'], statistics_scope='PASS_only' if pass_only else 'all_recorded',
            statistic_run_ids=';'.join(r['run_id'] for r in selected))
        add_metrics(row, selected)
        output.append(row)
    return output


def balanced_n(records, combos):
    output = []
    for N in range(1,5):
        cs = [r for r in combos if r['N']==N]; rs = [r for r in records if r['N']==N]
        row = dict(N=N, combination_n=len(cs), temporal_window_n=len(rs), batch_n=len({r['batch_id'] for r in rs}),
                   weighting='equal combination means; between-combination SD is undefined for one combination')
        for metric, source in METRICS.items():
            mean, sd, n = moments(c[metric+'_mean'] for c in cs)
            row.update({metric+'_mean':mean, metric+'_between_combination_sample_sd':sd,
                        metric+'_across_run_sample_sd':moments(r[source] for r in rs)[1]})
        output.append(row)
    return output


def slot_statistics(modules):
    result = []
    metrics = {'K_ESKD':'K_ESKD','K1_ESKD':'K1_ESKD','K2_ESKD':'K2_ESKD','q_ESKF':'q_ESKF'}
    for slot in ['M0','M1','M2','M3']:
        for N in range(1,5):
            rs = [r for r in modules if r['slot']==slot and r['N']==N]
            groups = defaultdict(list)
            for r in rs: groups[r['modules']].append(r)
            assert all(len(g)==3 for g in groups.values())
            row = dict(slot=slot,N=N,temporal_window_n=len(rs),combination_n=len(groups),
                       batch_n=len({r['batch_id'] for r in rs}),comparison_scope='same CS slot; physical board identity unverified')
            add_metrics(row,rs,metrics)
            for metric, source in metrics.items():
                means = [moments(r[source] for r in group)[0] for group in groups.values()]
                row[metric+'_between_combination_sample_sd']=moments(means)[1]
            result.append(row)
    return result


def compare_full(records, full_rows):
    result=[]
    for N, name in sorted({(r['N'],r['modules']) for r in records}):
        delta=[r for r in records if r['modules']==name]; full=[r for r in full_rows if r['modules']==name]
        assert len(delta)==len(full)==3 and len({r['batch_id'] for r in full})==1
        fL=moments(float(r['main_Lmean_B']) for r in full)[0]
        assert close(fL,40+1044*N) and all(float(r['main_Lmean_B'])==fL for r in full)
        fR=moments(float(r['main_raw_arrival_Mbit_s']) for r in full)[0]
        usb_reduction=[100*(1-r['main_Lmean_B']/fL) for r in delta]
        payload_reduction=[100*(1-(r['main_Lmean_B']-40)/(fL-40)) for r in delta]
        row=dict(N=N,modules=name,delta_temporal_repeat_n=3,full_temporal_repeat_n=3,
            delta_batch_id=delta[0]['batch_id'],full_batch_id=full[0]['batch_id'],
            delta_run_ids=';'.join(r['run_id'] for r in delta),full_run_ids=';'.join(r['run_id'] for r in full),
            full_Lmean_B=fL,full_raw_rate_Mbit_s_mean=fR,
            full_raw_rate_Mbit_s_sample_sd=moments(float(r['main_raw_arrival_Mbit_s']) for r in full)[1],
            full_rate_Hz_mean=moments(float(r['main_rate_Hz']) for r in full)[0],
            equal_rate_USB_reduction_pct_mean=moments(usb_reduction)[0],
            equal_rate_USB_reduction_pct_sample_sd=moments(usb_reduction)[1],
            equal_rate_module_payload_reduction_pct_mean=moments(payload_reduction)[0],
            equal_rate_module_payload_reduction_pct_sample_sd=moments(payload_reduction)[1],
            observed_raw_rate_reduction_pct=100*(1-moments(r['main_raw_arrival_Mbit_s'] for r in delta)[0]/fR),
            comparison_basis='USB-byte reduction at equal actual f uses L; raw-rate comparison uses each campaign actual rate; runs are not paired')
        result.append(row)
    return result


def fmt(value,d=6):
    return '未定义' if value is None else f'{value:.{d}f}'


def add_derived_raw_corroboration(inputs):
    path=HERE/'raw_audit.json'
    raw=json.loads(path.read_text(encoding='utf-8'))
    assert set(raw['snapshot_run_ids'])=={r['run_id'] for r in inputs['records']}
    totals=raw['totals']['main']
    for source,key in [('main_packets','valid_outer_packets'),('main_ESKF_count','ESKF'),
                       ('main_ESKD_count','ESKD'),('main_valid_module_frames','valid_module_frames')]:
        assert sum(r[source] for r in inputs['records'])==totals[key]
    gaps=[dict(run_id=r['run_id'],**gap) for r in raw['runs'] for gap in r['main_largest_pc_gaps']]
    gaps.sort(key=lambda r:r['pc_completion_gap_ms'],reverse=True)
    inputs['independent_raw_corroboration']=dict(
        file='raw_audit.json',sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        audit_time=raw['audit_time'],totals=raw['totals'],largest_PC_gaps=gaps[:5],
        cross_check_problem_runs=[r['run_id'] for r in raw['runs'] if r['cross_check_errors']])


def write_note(inputs, combos, balanced, slots, comparison):
    records=inputs['records']; comp={r['modules']:r for r in comparison}
    text=['# DELTA 零载45条：主窗口统计与FULL匹配比较','',
          '固定读取 organization_plan.json 的45个run_id；每条40 s、前10 s预留，统计使用 scopes.main 的实际约30 s窗口。所有原记录保留，完整性PASS子集另表，不按帧率或K筛选。', '',
          '15种非空槽位组合各3段、每组合1个batch。均为DELTA、zero_load、目标200 Hz、threshold=8、M=4。三段是同一setup内的时间重复；没有重新搭建的独立重复证明。', '',
          f"主窗口状态：{dict(Counter(r['main_status'] for r in records))}；全程状态：{dict(Counter(r['full_status'] for r in records))}。全部45条full_run的初始DELTA前缀无法仅从文件建立cache，另30条有尾部1 B；这些全程状态不能改写为PASS。主窗口在10 s之后，所有valid_expected_update覆盖率为1，summary错误计数为0。独立raw验证由同目录其他审计负责。", '',
          f"主窗口共{sum(r['main_packets'] for r in records):,}个完整MUL1、{sum(r['main_valid_module_frames'] for r in records):,}个有效内帧，其中ESKD={sum(r['main_ESKD_count'] for r in records):,}、ESKF={sum(r['main_ESKF_count'] for r in records):,}。", '',
          '## 每组合：均值 ± 样本SD，n=3，batch=1','',
          '| 组合 | Hz | 平均MUL1 / B | USB完整包 / Mbit/s | 普通ESKD K | 总ESKF q / % | 等帧率USB字节减少 / % |',
          '|---|---:|---:|---:|---:|---:|---:|']
    for r in combos:
        cells=[f"{fmt(r[k+'_mean'])} ± {fmt(r[k+'_sample_sd'])}" for k in ['rate_Hz','Lmean_B','packet_Mbit_s','K_ESKD','q_ESKF_pct']]
        text.append('| '+r['modules']+' | '+' | '.join(cells)+' | '+fmt(comp[r['modules']]['equal_rate_USB_reduction_pct_mean'],3)+' |')
    text+=['','SD以每段统计值为样本，分母n−1；ESKD K从有效ESKD mask histogram加权重算，与summary均值核对。ESKF没有普通变化计数，不能当成K=480的物理变化；K_effective=(1−q)K_D+480q仅是字节等效值。q分母是有效ESKF+ESKD模块内帧，不是含完整帧的USB包数。','',
           f"总q逐段范围为{100*min(r['main_q_ESKF'] for r in records):.6f}%–{100*max(r['main_q_ESKF'] for r in records):.6f}%，接近0.5%的周期参考，但协议没有trigger code，不能把记录中的全部ESKF都归因于周期同步或据间隔推断触发原因。",'',
           '## 按N平衡描述','',
           '对同一N下每种组合先取三段均值，再等权平均组合。下表SD是组合均值之间的样本SD；N=4只有一个组合，因此该SD未定义。CSV另列所有run均值的描述性SD，不能与组合间SD混用。','',
           '| N | 组合数 / 时间窗口数 | USB均值 / Mbit/s | 组合间SD | 普通K均值 | 总q均值 / % |','|---:|---:|---:|---:|---:|---:|']
    for r in balanced:text.append(f"| {r['N']} | {r['combination_n']} / {r['temporal_window_n']} | {fmt(r['packet_Mbit_s_mean'])} | {fmt(r['packet_Mbit_s_between_combination_sample_sd'])} | {fmt(r['K_ESKD_mean'])} | {fmt(r['q_ESKF_pct_mean'])} |")
    text+=['','## 同一CS槽位的活动差异','',
           '| 槽位 | N=1 K | N=2 K | N=3 K | N=4 K |','|---|---:|---:|---:|---:|']
    for slot in ['M0','M1','M2','M3']:
        rs=sorted((r for r in slots if r['slot']==slot),key=lambda r:r['N'])
        text.append('| '+slot+' | '+' | '.join(fmt(r['K_ESKD_mean'],3) for r in rs)+' |')
    text+=['','每个槽位在N=1/2/3/4中分别有3/9/9/3段，来自1/3/3/1个组合批次，均衡平均不改变槽位权重。M2的普通mask活动较高，主要来自FSR1通道；M3在本次按N分组中描述性增加，其他槽位并非一致单调。因此不能由总体K随N的变化推断统一噪声增长机制。CS槽位不是物理板卡UID，采集时间、搭接/装配、负载确认和实体映射未被控制；不能归因于某块板、供电、SPI时钟或模块数本身。','',
           '## FULL对照与字节口径','',
           '每个DELTA组合匹配 data/primary_matrix.csv 中同组合最新完整FULL批次的三条主窗口，不把两个不同批次的Repeat编号当作成对实验。FULL参考包长来自测量，均符合40+1044N。等实际帧率USB减少=1−L_DELTA/L_FULL；这比较整个MUL1包。去掉共同40 B包装后另算模块载荷减少，两个百分数不混称。','',
           'stats_full_comparison.csv另列各批实际raw到达字节率的比值，该比值包含实际包率和读块边界影响。它不是等频率字节减少，也不是USB总线物理带宽占用；没有把FULL组均值的变化传播成配对置信区间。','',
           '完整性PASS不保证严格200 Hz或每轮截止时间。保留M1_M3等较高/波动包率和所有较低包率记录；这里不依据统计差异推断时钟故障。原始模块扫描是否全部送达及具体时间停顿原因需额外证据。','']
    raw=inputs.get('independent_raw_corroboration')
    if raw:
        text+=['## 独立raw审计与时间边界','',
               f"[独立raw审计](raw_audit_CN.md)核对的主窗口MUL1/ESKD/ESKF总数与本统计一致；交叉校验问题run为{raw['cross_check_problem_runs']}。全窗口有{raw['totals']['full_run'].get('initial_unanchored_delta',0):,}个录制起点后的无锚点ESKD，全部位于前10 s；主窗口无此前缀。它们解释文件独立重放的初始状态限制，不能直接当作传输丢包。",'',
               'PC包完成时间受到缓冲和调度影响。独立审计记录的最大间隔如下；对应MUL1序号仍连续，桥端时间相邻仅5 ms。保持原PASS、原时长和原字节率，不自动删除、校正时间戳或推断硬件停顿。','',
               '| run_id | PC间隔 / s | 桥端间隔 / ms | 到达序号 |','|---|---:|---:|---:|']
        for gap in raw['largest_PC_gaps'][:3]:
            text.append(f"| {gap['run_id']} | {gap['pc_completion_gap_ms']/1000:.7f} | {gap['bridge_host_gap_ms']} | {gap['sequence']} |")
        text+=['','因此跨采集批次的raw到达速率差异还可能包含主窗口边界积压影响；等帧率的包长比较减少这类速率差异的混入，但不代表测得物理扫描截止时间。','']
    text+=['## 输出与复现','',
           'stats_generate.py默认只读固定plan的source/destination位置；完成快照后可用 --from-snapshot 从本目录JSON重建，完全不再访问原记录。输入summary SHA256和FULL索引SHA256保存在 zero_load_stats_summary.json。所有一致性问题会列入JSON；不会据问题自动删除某条记录。','',
           '[每条主统计](stats_runs.csv) · [全部组合](stats_combinations.csv) · [PASS组合](stats_combinations_pass.csv) · [平衡N描述](stats_by_n_balanced.csv) · [FULL匹配](stats_full_comparison.csv) · [模块逐次](module_activity_runs.csv) · [同槽位按N](module_activity_by_slot_n.csv) · [机器可读汇总](zero_load_stats_summary.json)','']
    (HERE/'statistical_note.md').write_text('\n'.join(text),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--from-snapshot',action='store_true')
    parser.add_argument('--refresh-derived-audit',action='store_true',help='Read only sibling raw_audit.json, never measured files')
    args=parser.parse_args()
    target=HERE/'zero_load_stats_summary.json'
    inputs=json.loads(target.read_text(encoding='utf-8'))['inputs'] if args.from_snapshot else collect_inputs()
    if args.refresh_derived_audit: add_derived_raw_corroboration(inputs)
    records=inputs['records'];modules=inputs['module_rows']
    combos=combo_statistics(records);passes=combo_statistics(records,True)
    balanced=balanced_n(records,combos);slots=slot_statistics(modules);comparison=compare_full(records,inputs['full_reference_rows'])
    run_export=[{k:v for k,v in r.items() if k not in ('full_counts','main_error_deltas','full_error_deltas')} for r in records]
    csv_write('stats_runs.csv',run_export);csv_write('stats_combinations.csv',combos)
    csv_write('stats_combinations_pass.csv',passes);csv_write('stats_by_n_balanced.csv',balanced)
    csv_write('stats_full_comparison.csv',comparison);csv_write('module_activity_runs.csv',modules)
    csv_write('module_activity_by_slot_n.csv',slots)
    result=dict(schema_version=1,inputs=inputs,statistics_scope='main windows; all records retained; no performance-based exclusion',
                main_status_counts=dict(Counter(r['main_status'] for r in records)),
                full_status_counts=dict(Counter(r['full_status'] for r in records)),
                combinations_all=combos,combinations_PASS=passes,by_N_balanced=balanced,
                module_activity_by_slot_N=slots,FULL_comparisons=comparison)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write_note(inputs,combos,balanced,slots,comparison)
    print(json.dumps({'runs':len(records),'module_runs':len(modules),'combinations':len(combos),
                      'summary_consistency_issues':inputs['summary_consistency_issues'],
                      'source_reads':not args.from_snapshot},ensure_ascii=False))


if __name__=='__main__':main()
