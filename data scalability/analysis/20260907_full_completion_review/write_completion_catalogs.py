"""Generate five completion catalogs from the verified 48-run/45-primary indexes.

Writes derived README files only. Original M012 Repeat_1..3 are never moved or
edited. The older 12-run N3 catalog remains an archived snapshot; this generator
is the current source for the five completion catalogs listed in BACKUP_PATHS.
"""
from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data'
OLD_REVIEW = HERE.parent / '20260907_n3_full_review'
OLD_BATCH = 'BATCH_5ccf81b3a4814c0a88241ef83d9e4bcf'
NEW_BATCH = 'BATCH_6b6313d281364eaa891ce82942b3d531'
N4_BATCH = 'BATCH_9fd1ea44282d4e30a57739ebb1856112'
NEW_BATCH_FOLDER = 'Batch_20260907_004948_668301'
BACKUP_PATHS = {
    'FULL/N=3/200Hz/README.md',
    'FULL/N=3/200Hz/M0_M1_M2/README.md',
    f'FULL/N=3/200Hz/M0_M1_M2/{NEW_BATCH_FOLDER}/README.md',
    'FULL/N=4/200Hz/README.md',
    'FULL/N=4/200Hz/M0_M1_M2_M3/README.md',
}


def read_csv(name):
    with (DATA / name).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def yes(value):
    assert value in ('True', 'False')
    return value == 'True'


def link(start, target, label):
    return f"[{label}]({os.path.relpath(target, start).replace(chr(92), '/')})"


def estimate(row, metric, digits=6):
    mean, sd = row[metric + '_mean'], row[metric + '_sample_sd']
    if mean == '':
        return '未估计'
    return f'{float(mean):.{digits}f} ± {float(sd):.{digits}f}' if sd else f'{float(mean):.{digits}f}（SD 未估计）'


def sources(start):
    return ' · '.join(link(start, target, label) for target, label in [
        (DATA / 'run_index.csv', '全部48条索引'), (DATA / 'primary_matrix.csv', '主矩阵45条'),
        (DATA / 'group_statistics.csv', '主矩阵分组统计'),
        (DATA / 'all_pass_group_statistics.csv', '全部PASS辅助统计'),
        (DATA / 'all_runs_diagnostic_statistics.csv', '全部记录诊断'),
        (DATA / 'batch_statistics.csv', '分批统计'),
        (HERE / 'primary_selection.json', '批次选择依据'),
        (HERE / 'ANALYSIS_CN.md', '本次raw审计'), (HERE / 'TIMING_NOTE_CN.md', '本次时间诊断'),
        (OLD_REVIEW / 'ANALYSIS_CN.md', '原N3异常审计'),
        (OLD_REVIEW / 'TIMING_NOTE_CN.md', '原N3时间诊断'),
    ])


def validate_statistics(stats, lookup):
    for stat in stats:
        ids = list(filter(None, stat['statistic_run_ids'].split(';')))
        assert len(ids) == len(set(ids)) == int(stat['temporal_repeat_n'])
        selected = [lookup[run_id] for run_id in ids]
        assert len({r['batch_id'] for r in selected}) == int(stat['batch_n'])
        for source, metric in [('main_rate_Hz', 'rate_Hz'), ('main_packet_Mbit_s', 'packet_Mbit_s'),
                               ('main_raw_arrival_Mbit_s', 'raw_arrival_Mbit_s'), ('main_Lmean_B', 'Lmean_B')]:
            values = [float(r[source]) for r in selected]
            expected = {'mean': statistics.mean(values) if values else None,
                        'sample_sd': statistics.stdev(values) if len(values) > 1 else None}
            for suffix, target in expected.items():
                value = stat[metric + '_' + suffix]
                if target is None:
                    assert value == ''
                else:
                    assert math.isclose(float(value), target, rel_tol=1e-10, abs_tol=1e-12)


def run_table(start, rows, summaries):
    lines = ['| Repeat | 原始 run_id / 日志 | 开始时间（英国当地 +01:00） | 主包率 / Hz | 主窗口 | 全程 | 主矩阵 | 尾片段 / B |',
             '|---:|---|---|---:|---|---|---|---:|']
    for row in sorted(rows, key=lambda r: int(r['repeat'])):
        s = summaries[row['run_id']]
        tail = s['scopes']['full_run']['counts'].get('trailing_unassigned_raw_bytes', 0)
        log = link(start, DATA / row['new_relative_path'] / 'experiment_log.md', row['run_id'])
        selected = '是' if yes(row['primary_matrix_selected']) else ('辅助PASS' if yes(row['main_eligible']) else '否；可靠性异常')
        lines.append(f"| {row['repeat']} | {log} | {row['started_at']} | {float(row['main_rate_Hz']):.6f} | {row['main_status']} | {row['full_status']} | {selected} | {tail} |")
    return lines


def batch_section(start, rows, stat, summaries, title):
    selected = sum(yes(r['primary_matrix_selected']) for r in rows)
    lines = [f'## {title}', '',
             f"Batch: {stat['batch_id']}。Block: {rows[0]['block']}。已录 {len(rows)} 段，完整性 PASS {stat['temporal_repeat_n']} 段，主矩阵纳入 {selected} 段。", '',
             f"本批 PASS 窗口：{estimate(stat, 'rate_Hz')} Hz，{estimate(stat, 'packet_Mbit_s')} Mbit/s；n={stat['temporal_repeat_n']}，batch=1（段间样本 SD）。", '']
    lines += run_table(start, rows, summaries)
    return lines


def main():
    verification = json.loads((HERE / 'organization_verification.json').read_text(encoding='utf-8-sig'))
    assert verification['status'] == 'completed' and verification['verified_runs'] == 6
    assert verification['verified_files'] == 36 and verification['original_contents_changed'] is False
    backup = json.loads((HERE / 'catalog_backups/manifest.json').read_text(encoding='utf-8'))
    assert {r['relative_path'] for r in backup['files']} == BACKUP_PATHS
    for row in backup['files']:
        if row['existed_before']:
            assert hashlib.sha256((HERE / row['backup_relative_path']).read_bytes()).hexdigest() == row['sha256']

    runs = read_csv('run_index.csv')
    matrix = read_csv('primary_matrix.csv')
    primary_stats = read_csv('group_statistics.csv')
    pass_stats = read_csv('all_pass_group_statistics.csv')
    all_stats = read_csv('all_runs_diagnostic_statistics.csv')
    batch_stats = read_csv('batch_statistics.csv')
    lookup = {r['run_id']: r for r in runs}
    assert len(runs) == len(lookup) == 48 and len(matrix) == 45
    selected_ids = {r['run_id'] for r in runs if yes(r['primary_matrix_selected'])}
    assert selected_ids == {r['run_id'] for r in matrix} and len(selected_ids) == 45
    assert sum(yes(r['main_eligible']) for r in runs) == 47
    assert all(yes(lookup[run_id]['main_eligible']) for run_id in selected_ids)
    assert len(primary_stats) == len(pass_stats) == len(all_stats) == 15 and len(batch_stats) == 16
    for table in (primary_stats, pass_stats, all_stats, batch_stats):
        validate_statistics(table, lookup)
    for stat in primary_stats:
        assert int(stat['temporal_repeat_n']) == 3 and int(stat['batch_n']) == 1
        assert set(stat['statistic_run_ids'].split(';')) <= selected_ids
    original = [r for r in runs if r['batch_id'] == OLD_BATCH]
    replacement = [r for r in runs if r['batch_id'] == NEW_BATCH]
    assert len(original) == len(replacement) == 3
    assert sum(yes(r['main_eligible']) for r in original) == 2
    assert all(not yes(r['primary_matrix_selected']) and r['replacement_batch_id'] == NEW_BATCH for r in original)
    assert all(yes(r['primary_matrix_selected']) for r in replacement)
    assert yes(lookup['20260907_001505_375008']['primary_matrix_selected']), 'Keep the original low-rate M013 PASS run'
    pstats = {r['modules']: r for r in primary_stats}
    astats = {r['modules']: r for r in all_stats}
    sstats = {r['modules']: r for r in pass_stats}
    bstats = {r['batch_id']: r for r in batch_stats}
    summaries = {}
    for row in runs:
        path = (DATA / row['new_relative_path'] / 'summary.json').resolve()
        assert path.is_relative_to(DATA.resolve())
        summary = json.loads(path.read_text(encoding='utf-8-sig'))
        assert summary['run_id'] == row['run_id']
        assert summary['scopes']['main']['status'] == row['main_status']
        assert summary['scopes']['full_run']['status'] == row['full_status']
        assert yes(row['main_eligible']) == (row['main_status'] == 'PASS')
        summaries[row['run_id']] = summary

    n3 = [r for r in runs if int(r['N']) == 3]
    n4 = [r for r in runs if int(r['N']) == 4]
    assert len(n3) == 15 and len(n4) == 3
    n3main = Counter(r['main_status'] for r in n3)
    n3full = Counter(r['full_status'] for r in n3)
    n4full = Counter(r['full_status'] for r in n4)
    base3, base4 = DATA / 'FULL/N=3/200Hz', DATA / 'FULL/N=4/200Hz'
    combo3, combo4 = base3 / 'M0_M1_M2', base4 / 'M0_M1_M2_M3'
    newdir = combo3 / NEW_BATCH_FOLDER
    policy = '主矩阵按完整三段批次选择，不按帧率选择单条。M012 后续完整补测 batch 整体用于该组合的主矩阵位置；原两条 PASS 保留作辅助分析，原一条 CHECK 持续用于可靠性评估。原目录、Repeat、batch_id 和原始文件不覆盖、不重编号。'
    interpretation = '每段约 40 s，前 10 s 保留，性能采用其后约 30 s 主窗口。均值与样本 SD 按段计算；这些是同一 setup 内的连续时间重复，不是独立重建或重新加载。'
    timing = 'M012 补测 Repeat 3 在 PC 完成观察中出现 278.7935 ms 间隔，对应桥端仅 5 ms；六条新记录桥端最大间隔均为 6 ms，MUL1 序号连续。保留补测全部三条，不因 PC 观察停顿或较低帧率删选。host_ms 是桥端入队时间，不能据此证明每次物理扫描均已送达或定位停顿责任。'
    length3 = '完整 FULL 包长为 3172 B = (24 + 4M) + 1044N，其中 M=4、N=3；200 Hz 时完整包字节流量理论值为 5.0752 Mbit/s。'
    length4 = '完整 FULL 包长为 4216 B = (24 + 4M) + 1044N，其中 M=4、N=4；200 Hz 时完整包字节流量理论值为 6.7456 Mbit/s。'
    byte_note = 'USB 指完整 MUL1 字节/主窗口时长，不含 USB 总线事务开销；raw 到达字节率另列于 CSV。200 Hz、10 MHz 为配置来源而非设备读回；槽位不是唯一板卡身份，原 deployment_confirmed=false 和 load_layers=unspecified 保留。'

    lines3 = ['# FULL / N=3 / 200 Hz / Zero load', '',
              f"主矩阵包含四组合各三段，共 {sum(yes(r['primary_matrix_selected']) for r in n3)} 条 PASS。全部 N=3 记录 {len(n3)} 条：{n3main['PASS']} 个主窗口 PASS、{n3main['CHECK REQUIRED']} 个 CHECK；全程 {n3full['PASS']} PASS、{n3full['CHECK REQUIRED']} CHECK。", '',
              policy, '', interpretation, '', '## 主矩阵性能', '',
              '| 组合 | 主矩阵 n / batch | 全部已录 / PASS | 主包率 / Hz | USB完整包 / Mbit/s | 包长 / B |',
              '|---|---:|---:|---:|---:|---:|']
    for modules in sorted({r['modules'] for r in n3}):
        stat = pstats[modules]
        lines3.append(f"| [{modules}]({modules}/README.md) | {stat['temporal_repeat_n']} / {stat['batch_n']} | {stat['recorded_repeat_n']} / {stat['eligible_repeat_n']} | {estimate(stat, 'rate_Hz')} | {estimate(stat, 'packet_Mbit_s')} | {estimate(stat, 'Lmean_B', 0)} |")
    lines3 += ['', length3, '', byte_note, '', '## 保留异常与辅助证据', '',
               'M012 原 Repeat 1 含 outer CRC 与重同步异常，不纳入主性能统计，原始数据和 raw 恢复证据仍保留。全记录诊断包含这条失败，不能用主矩阵全部 PASS 代替全部采集的可靠性结果。M012 两个 batch 的五条 PASS 可作辅助诊断，但不能标为一个 batch。', '',
               'M013 原 Repeat 3（20260907_001505_375008）约 199.123828 Hz，仍属于主矩阵；其 123 ms 桥端间隔、301.3735 ms PC 间隔及 1020 B 尾片段保持原说明，不能挑选另两条较快记录。', '',
               timing, '', sources(base3), '', link(base3, DATA / 'README.md', '返回活动数据总览'), '']

    special = ['# M0_M1_M2 / FULL / Zero load / N=3 / 200 Hz', '', policy, '', interpretation, '',
               '## 当前统计口径', '',
               '| 口径 | 时间窗口 n | batch 数 | 包率 / Hz | USB完整包 / Mbit/s |',
               '|---|---:|---:|---:|---:|']
    for label, stat in [('主矩阵：完整补测 batch', pstats['M0_M1_M2']),
                        ('辅助：两个 batch 的全部 PASS', sstats['M0_M1_M2']),
                        ('诊断：两个 batch 的全部记录，含 CHECK', astats['M0_M1_M2'])]:
        special.append(f"| {label} | {stat['temporal_repeat_n']} | {stat['batch_n']} | {estimate(stat, 'rate_Hz')} | {estimate(stat, 'packet_Mbit_s')} |")
    special += ['', link(combo3, newdir / 'README.md', '进入完整补测批次目录'), '']
    special += batch_section(combo3, original, bstats[OLD_BATCH], summaries, '原批次：原 Repeat_1..3 保持原位')
    special += ['', '原 Repeat 1 主窗口 CHECK 不纳入性能均值，原两条 PASS 仍保留完整性资格，作为辅助证据。原 CRC/重同步错误与可恢复 raw 包详见原 N3 审计，不把运行时 lost_frames=2 直接等同于两个物理扫描丢失。', '']
    special += batch_section(combo3, replacement, bstats[NEW_BATCH], summaries, '后续完整补测：主矩阵所用 batch')
    special += ['', timing, '', length3, '', sources(combo3), '', link(combo3, base3 / 'README.md', '返回N3组统计'), '']

    batchdoc = ['# M012 完整补测批次 / FULL / 200 Hz', '', policy, '', interpretation, '']
    batchdoc += batch_section(newdir, replacement, bstats[NEW_BATCH], summaries, '本批三条：全部纳入主矩阵')
    batchdoc += ['', timing, '', '本批全程为 1 PASS、2 CHECK；两条 CHECK 仅尾部 1 B。主窗口全部 PASS。开始边界包、尾片段和原始状态保持原值，不修改原 raw 或 CSV。', '',
                 length3, '', byte_note, '', sources(newdir), '', link(newdir, combo3 / 'README.md', '返回M012双批次说明'), '']

    stat4 = pstats['M0_M1_M2_M3']
    lines4 = ['# FULL / N=4 / 200 Hz / Zero load', '',
              f"四槽位同时参与，一个完整 batch 的三段记录全部纳入主矩阵。主窗口 {sum(r['main_status'] == 'PASS' for r in n4)} PASS；全程 {n4full['PASS']} PASS、{n4full['CHECK REQUIRED']} CHECK。", '',
              interpretation, '', '| 组合 | n / batch | 主包率 / Hz | USB完整包 / Mbit/s | 包长 / B |',
              '|---|---:|---:|---:|---:|',
              f"| [M0_M1_M2_M3](M0_M1_M2_M3/README.md) | {stat4['temporal_repeat_n']} / {stat4['batch_n']} | {estimate(stat4, 'rate_Hz')} | {estimate(stat4, 'packet_Mbit_s')} | {estimate(stat4, 'Lmean_B', 0)} |", '',
              length4, '', byte_note, '',
              '三条均无新增主窗口 CRC、序号间断或目标模块缺失。桥端相邻包最大间隔为 6 ms；PC 最大完成观察间隔分别为 32.0931、48.7044、18.4781 ms。Repeat 1 全程 CHECK 仅因尾部 1 B，Repeat 2/3 全程 PASS。', '',
              sources(base4), '', link(base4, DATA / 'README.md', '返回活动数据总览'), '']
    combodoc4 = ['# M0_M1_M2_M3 / FULL / Zero load / N=4 / 200 Hz', '', interpretation, '']
    combodoc4 += batch_section(combo4, n4, bstats[N4_BATCH], summaries, '完整三段批次：全部纳入主矩阵')
    combodoc4 += ['', length4, '', byte_note, '',
                  '三条主窗口完整性全部 PASS；桥端最大入队间隔为 6 ms。Repeat 1 末尾片段 1 B；Repeat 2/3 为 0 B。较长 PC 完成间隔对应缓冲观察，不直接当作物理扫描丢失。', '',
                  sources(combo4), '', link(combo4, base4 / 'README.md', '返回N4组统计'), '']
    outputs = {base3 / 'README.md': lines3, combo3 / 'README.md': special,
               newdir / 'README.md': batchdoc, base4 / 'README.md': lines4,
               combo4 / 'README.md': combodoc4}
    assert {p.relative_to(DATA).as_posix() for p in outputs} == BACKUP_PATHS
    for path, lines in outputs.items():
        assert path.parent.is_dir()
        path.write_text('\n'.join(lines), encoding='utf-8')
    print('Wrote 5 N3/N4 completion catalogs; original capture files and prior M012 Repeat directories unchanged.')


if __name__ == '__main__':
    main()
