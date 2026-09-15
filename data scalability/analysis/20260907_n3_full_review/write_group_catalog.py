"""Generate N=3 navigation after verified moves; never write measured run files.

Read run_index.csv, both statistics tables, and the relocated original summaries.
Only FULL/N=3/200Hz/README.md and the four combination README files are written.
"""
from collections import Counter
import csv
import json
import math
import os
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data'
COMBINATIONS = {'M0_M1_M2', 'M0_M1_M3', 'M0_M2_M3', 'M1_M2_M3'}
LOW_RATE_RUN = '20260907_001505_375008'


def read_csv(name):
    with (HERE / name).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def eligible(row):
    assert row['main_eligible'] in ('True', 'False')
    return row['main_eligible'] == 'True'


def link(start, target, label):
    return f"[{label}]({os.path.relpath(target, start).replace(chr(92), '/')})"


def estimate(row, key, digits=6):
    mean, sd = row[key + '_mean'], row[key + '_sample_sd']
    if mean == '':
        return '未估计'
    if sd == '':
        return f'{float(mean):.{digits}f}（SD 未估计）'
    return f'{float(mean):.{digits}f} ± {float(sd):.{digits}f}'


def validate_stats(stat, selected, group):
    assert int(stat['temporal_repeat_n']) == len(selected)
    assert int(stat['recorded_repeat_n']) == len(group)
    assert int(stat['eligible_repeat_n']) == sum(eligible(r) for r in group)
    assert int(stat['review_required_n']) == sum(not eligible(r) for r in group)
    assert set(filter(None, stat['statistic_run_ids'].split(';'))) == {r['run_id'] for r in selected}
    for source_key, stat_key in [('main_rate_Hz', 'rate_Hz'),
                                 ('main_packet_Mbit_s', 'packet_Mbit_s'),
                                 ('main_raw_arrival_Mbit_s', 'raw_arrival_Mbit_s'),
                                 ('main_Lmean_B', 'Lmean_B')]:
        values = [float(r[source_key]) for r in selected]
        expected_mean = statistics.mean(values) if values else None
        expected_sd = statistics.stdev(values) if len(values) > 1 else None
        for suffix, expected in [('mean', expected_mean), ('sample_sd', expected_sd)]:
            recorded = stat[stat_key + '_' + suffix]
            assert (recorded == '') if expected is None else math.isclose(float(recorded), expected, rel_tol=1e-10, abs_tol=1e-12)


def build_catalogs(runs, stats, diagnostics, summaries):
    assert len(runs) == 12 and len({r['run_id'] for r in runs}) == 12
    assert len(stats) == len(diagnostics) == 4
    assert {r['modules'] for r in runs} == COMBINATIONS
    assert {r['modules'] for r in stats} == {r['modules'] for r in diagnostics} == COMBINATIONS
    assert len({r['batch_id'] for r in runs}) == 4
    stats_by_group = {r['modules']: r for r in stats}
    diagnostic_by_group = {r['modules']: r for r in diagnostics}
    base = DATA / 'FULL/N=3/200Hz'
    for row in runs:
        s = summaries[row['run_id']]
        assert s['run_id'] == row['run_id'] and s['schema_version'] == 2
        assert s['metadata']['N'] == 3 and s['metadata']['M'] == 4
        assert s['metadata']['target_mode'] == row['mode'] == 'FULL'
        assert s['metadata']['condition'] == row['condition'] == 'zero_load'
        assert s['metadata']['batch_id'] == row['batch_id']
        assert str(s['metadata']['repeat']) == row['repeat']
        assert s['scopes']['main']['status'] == row['main_status']
        assert s['scopes']['full_run']['status'] == row['full_status']
        assert eligible(row) == (s['scopes']['main']['status'] == 'PASS')
        assert s['scopes']['main']['Lmean_valid_packet_B'] == 3172
    low_rate = next(r for r in runs if r['run_id'] == LOW_RATE_RUN)
    assert eligible(low_rate), 'The low-rate PASS run must remain in performance statistics'
    main_statuses = Counter(s['scopes']['main']['status'] for s in summaries.values())
    full_statuses = Counter(s['scopes']['full_run']['status'] for s in summaries.values())
    status_text = (f"主窗口 {main_statuses['PASS']} 条 PASS、{main_statuses['CHECK REQUIRED']} 条 CHECK REQUIRED；"
                   f"全程 {full_statuses['PASS']} 条 PASS、{full_statuses['CHECK REQUIRED']} 条 CHECK REQUIRED。")
    links = ' · '.join(link(base, HERE / filename, label) for filename, label in [
        ('run_index.csv', '逐条索引'), ('group_statistics.csv', '有效性能统计'),
        ('all_runs_diagnostic_statistics.csv', '全部记录诊断统计'),
        ('ANALYSIS_CN.md', '独立 raw 审计'), ('TIMING_NOTE_CN.md', '时间诊断'),
        ('path_map.csv', '路径与 SHA256 映射')])
    text = ['# FULL / N=3 / 200 Hz / Zero load', '',
            '四个槽位任取三个，共四种组合；每个组合一个 batch、三个连续时间窗口。每段约 40 s，前 10 s 保留，以下性能统计采用其后约 30 s 主窗口。', '',
            status_text, '',
            '## 有效主窗口性能', '',
            '性能均值仅纳入完整性 PASS 的主窗口；以各段统计值计算均值和样本 SD（分母 n−1），不以帧率高低筛选。M012 Repeat 1 因主窗口 CRC/序号错误不计入此表，原 raw 和日志仍保留并用于可靠性评估。M013 Repeat 3 虽有末段停顿和较低帧率，仍保留在主统计中。', '',
            '三次 Repeat 是同一 setup 内的时间重复，不是三次独立重建或重新加载。表中同时给出有效 n 和已录 n。', '',
            '| 组合 | 有效 n / 已录 n | batch 数 | MUL1 包率 / Hz | USB 完整包数据率 / Mbit/s | 平均包长 / B |',
            '|---|---:|---:|---:|---:|---:|']
    for module in sorted(COMBINATIONS):
        group = sorted((r for r in runs if r['modules'] == module), key=lambda r: int(r['repeat']))
        assert {int(r['repeat']) for r in group} == {1, 2, 3}
        assert len({r['batch_id'] for r in group}) == len({r['block'] for r in group}) == 1
        stat, diag = stats_by_group[module], diagnostic_by_group[module]
        validate_stats(stat, [r for r in group if eligible(r)], group)
        validate_stats(diag, group, group)
        text.append(f"| [{module}]({module}/README.md) | {stat['eligible_repeat_n']} / {stat['recorded_repeat_n']} | {stat['batch_n']} | {estimate(stat, 'rate_Hz')} | {estimate(stat, 'packet_Mbit_s')} | {estimate(stat, 'Lmean_B', 0)} |")
    text += ['', '完整 FULL 包长为 3172 B = (24 + 4M) + 1044N，其中配置槽位数 M=4、有效模块数 N=3；200 Hz 时完整包字节流量理论值为 5.0752 Mbit/s。实测按各段实际包率计算。这里 USB 数据率指主窗口完整 MUL1 字节/时长，不含 USB 总线事务开销；raw 块到达字节率另列于 CSV，两者边界口径不同。', '',
             '## 全部记录诊断统计', '',
             '以下包含 CHECK 主窗口，仅用于诊断与可靠性追溯，不替代上方性能统计。不得将异常记录从原始数据集删除。', '',
             '| 组合 | 全部 n | MUL1 包率 / Hz | USB 完整包数据率 / Mbit/s |',
             '|---|---:|---:|---:|']
    for module in sorted(COMBINATIONS):
        diag = diagnostic_by_group[module]
        text.append(f"| {module} | {diag['temporal_repeat_n']} | {estimate(diag, 'rate_Hz')} | {estimate(diag, 'packet_Mbit_s')} |")
    text += ['', '## 逐次记录', '',
             '| 组合 | Repeat | 原始 run_id | 主窗口包数 | 包率 / Hz | 主窗口状态 | 纳入性能均值 |',
             '|---|---:|---|---:|---:|---|---|']
    for row in sorted(runs, key=lambda r: (r['modules'], int(r['repeat']))):
        use = '是；时间波动另注' if row['run_id'] == LOW_RATE_RUN else ('是' if eligible(row) else '否；保留作可靠性评估')
        text.append(f"| {row['modules']} | [{row['repeat']}]({row['modules']}/Repeat_{row['repeat']}/experiment_log.md) | {row['run_id']} | {row['main_packets']} | {float(row['main_rate_Hz']):.6f} | {row['main_status']} | {use} |")
    low_summary = summaries[LOW_RATE_RUN]
    low_tail = low_summary['scopes']['full_run']['counts'].get('trailing_unassigned_raw_bytes', 0)
    text += ['', '## 检查与追溯', '',
             'M012 Repeat 1 的主窗口含 1 次 outer CRC 错误、1 次有效序列间断及 2 个未解析成功序号，另有 2148 B 内部未归属 raw。不能把这些运行时计数直接解释为两个原始包或两个物理扫描均丢失；raw 恢复证据见独立审计。', '',
             f"M013 Repeat 3 主窗口包率为 {float(low_rate['main_rate_Hz']):.6f} Hz，桥端入队时间存在 123 ms 间隔，PC 完成观察时间最大间隔为 301.3735 ms，MUL1 和三个模块序号保持连续。其全程末尾片段为 {low_tail} B，需保留时间诊断；不因较低帧率剔除该 PASS 主窗口。不能将停顿归因于 SPI 饱和或具体设备层故障。", '',
             '各条尾部片段长度和完整性状态按原 summary 保留；全程 CHECK 不统一解释为 1 B 尾片段。原 summary.files 的旧时间戳路径作为采集来源保留，实际文件位置通过 path_map 追踪。', '',
             '200 Hz 为 GUI 配置目标，10 MHz 来源于本地固件配置，均非设备读回。M0–M3 是通信槽位而非唯一板卡身份；加载层数 unspecified、deployment_confirmed=false 的原值保留。', '',
             links, '', link(base, DATA / 'README.md', '返回活动数据总览'), '']
    outputs = {base / 'README.md': '\n'.join(text)}
    for module in sorted(COMBINATIONS):
        directory = base / module
        stat, diag = stats_by_group[module], diagnostic_by_group[module]
        group = sorted((r for r in runs if r['modules'] == module), key=lambda r: int(r['repeat']))
        lines = [f'# {module} / FULL / Zero load / N=3 / 200 Hz', '',
                 f"Batch: {stat['batch_id']}。Block: {group[0]['block']}。已录 {len(group)} 段，均为同一 setup 内的连续时间窗口；每次约 40 s，前段 10 s 预留。", '',
                 f"主性能有效 n={stat['eligible_repeat_n']}：包率 {estimate(stat, 'rate_Hz')} Hz，USB 完整包数据率 {estimate(stat, 'packet_Mbit_s')} Mbit/s（段间样本 SD）。全部记录诊断 n={diag['temporal_repeat_n']}：{estimate(diag, 'rate_Hz')} Hz、{estimate(diag, 'packet_Mbit_s')} Mbit/s。", '',
                 '| Repeat | 开始时间（英国当地 +01:00） | 原始 run_id | 主窗口包率 / Hz | 主窗口 | 全程 | 纳入性能均值 | 尾部片段 / B |',
                 '|---:|---|---|---:|---|---|---|---:|']
        for row in group:
            s = summaries[row['run_id']]
            tail = s['scopes']['full_run']['counts'].get('trailing_unassigned_raw_bytes', 0)
            lines.append(f"| [{row['repeat']}](Repeat_{row['repeat']}/experiment_log.md) | {row['started_at']} | {row['run_id']} | {float(row['main_rate_Hz']):.6f} | {row['main_status']} | {row['full_status']} | {'是' if eligible(row) else '否'} | {tail} |")
        for row in group:
            if not eligible(row):
                lines += ['', f"Repeat {row['repeat']} 不纳入性能均值，原始六文件仍全部保留用于可靠性分析。原主窗口复核原因：{row['main_review_reasons']}。"]
            if row['run_id'] == LOW_RATE_RUN:
                lines += ['', f"Repeat {row['repeat']} 完整性 PASS，较低帧率仍纳入主性能均值；末段桥端间隔 123 ms、PC 最大完成间隔 301.3735 ms，序号连续，尾部片段 {summaries[row['run_id']]['scopes']['full_run']['counts'].get('trailing_unassigned_raw_bytes', 0)} B。见时间诊断，不把低率直接解释为丢包。"]
        lines += ['', '完整包长 3172 B = (24 + 4×4) + 1044×3。每个 Repeat 保留原六文件、run_id、batch_id 和状态；另一批次不可覆盖本目录或重编号现有 Repeat。', '',
                  ' · '.join(link(directory, target, label) for target, label in [
                      (base / 'README.md', '返回组统计和定义'), (HERE / 'run_index.csv', '逐条索引'),
                      (HERE / 'ANALYSIS_CN.md', '独立 raw 审计'), (HERE / 'TIMING_NOTE_CN.md', '时间诊断'),
                      (HERE / 'path_map.csv', '路径与 SHA256 映射')]), '']
        outputs[directory / 'README.md'] = '\n'.join(lines)
    return outputs


def main():
    verification = json.loads((HERE / 'organization_verification.json').read_text(encoding='utf-8-sig'))
    assert verification['status'] == 'completed'
    assert verification['verified_runs'] == 12 and verification['verified_files'] == 72
    assert verification['original_contents_changed'] is False
    runs = read_csv('run_index.csv')
    summaries = {}
    for row in runs:
        path = (DATA / row['new_relative_path'] / 'summary.json').resolve()
        assert path.is_relative_to(DATA.resolve())
        summaries[row['run_id']] = json.loads(path.read_text(encoding='utf-8-sig'))
    outputs = build_catalogs(runs, read_csv('group_statistics.csv'),
                             read_csv('all_runs_diagnostic_statistics.csv'), summaries)
    assert len(outputs) == 5
    for path, content in outputs.items():
        path.write_text(content, encoding='utf-8')
    print('Wrote N=3 group catalog and four combination catalogs; measured files unchanged.')


if __name__ == '__main__':
    main()
