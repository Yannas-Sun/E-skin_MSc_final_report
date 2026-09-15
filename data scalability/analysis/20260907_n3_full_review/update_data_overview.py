"""Publish a status-aware N=1..3 catalog after verified organization.

Measured files remain untouched. CHECK runs stay in the index and all-run
diagnostics, but do not enter the clean-performance means.
"""
from pathlib import Path
import csv
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT/'data'
REVIEWS = ['20260906_current_data_review', '20260906_n2_full_review', '20260907_n3_full_review']
all_runs, all_stats, all_files, all_diagnostics = [], [], [], []

def read_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))

def write_rows(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

for review in REVIEWS:
    folder = ROOT/'analysis'/review
    verified = json.loads((folder/'organization_verification.json').read_text(encoding='utf-8-sig'))
    assert verified['status'] == 'completed'
    runs = read_rows(folder/'run_index.csv')
    for row in runs:
        summary = json.loads((DATA/row['new_relative_path']/'summary.json').read_text(encoding='utf-8-sig'))
        assert summary['run_id'] == row['run_id']
        window = summary['scopes']['main']
        assert window['status'] == row['main_status']
        row['main_eligible'] = window['status'] == 'PASS' and not window['review_reasons']
        row['main_review_reasons'] = ';'.join(window['review_reasons'])
        row['main_outer_crc_errors'] = window['counts'].get('outer_crc_error', 0)
        row['main_outer_missing_sequence_numbers'] = window['counts'].get('outer_missing_sequence_numbers', 0)
        row['main_interior_unassigned_raw_bytes'] = window['counts'].get('interior_unassigned_raw_bytes', 0)
        row['timing_note'] = ('Main PASS; bridge enqueue gap 123 ms and PC completion gap 301.3735 ms; retained in performance statistics'
                             if row['run_id'] == '20260907_001505_375008' else '')
        row['source_review'] = review
        all_runs.append(row)
    for row in read_rows(folder/'group_statistics.csv'):
        selected = [r for r in runs if r['modules'] == row['modules']]
        eligible = [r for r in selected if r['main_eligible']]
        assert len(eligible) == int(row['temporal_repeat_n'])
        row.update(recorded_repeat_n=len(selected), eligible_repeat_n=len(eligible),
                   review_required_n=len(selected)-len(eligible),
                   statistics_basis='PASS main windows only; integrity filter, no frame-rate filter',
                   statistic_run_ids=';'.join(r['run_id'] for r in eligible),
                   review_required_run_ids=';'.join(r['run_id'] for r in selected if not r['main_eligible']),
                   source_review=review)
        all_stats.append(row)
    diagnostic = folder/'all_runs_diagnostic_statistics.csv'
    for row in read_rows(diagnostic if diagnostic.exists() else folder/'group_statistics.csv'):
        selected = [r for r in runs if r['modules'] == row['modules']]
        row.update(recorded_repeat_n=len(selected), eligible_repeat_n=sum(r['main_eligible'] for r in selected),
                   review_required_n=sum(not r['main_eligible'] for r in selected),
                   statistics_basis='all recorded windows including CHECK; diagnostic only',
                   statistic_run_ids=';'.join(r['run_id'] for r in selected), source_review=review)
        all_diagnostics.append(row)
    for row in read_rows(folder/'path_map.csv'):
        assert (DATA/row['new_relative_path']).is_file()
        row['source_review'] = review
        all_files.append(row)

assert len(all_runs) == 42 and len({r['run_id'] for r in all_runs}) == 42
assert len(all_stats) == len(all_diagnostics) == 14 and len(all_files) == 252
assert sum(r['main_eligible'] for r in all_runs) == 41
assert [r['run_id'] for r in all_runs if not r['main_eligible']] == ['20260907_000133_670681']
for name in ['README.md', 'run_index.csv', 'group_statistics.csv', 'path_map.csv']:
    backup = HERE/('data_'+name.replace('.', '_before.'))
    if not backup.exists():
        backup.write_bytes((DATA/name).read_bytes())
for name, rows in [('run_index.csv', all_runs), ('group_statistics.csv', all_stats),
                   ('all_runs_diagnostic_statistics.csv', all_diagnostics), ('path_map.csv', all_files)]:
    write_rows(DATA/name, rows)

text = '''# 当前 Data 实验数据

当前已整理 FULL、zero_load、目标 200 Hz 的 N=1～3 数据，共 42 条记录。41 条主窗口 PASS；N=3 的 M0_M1_M2 第一次记录有实际完整性错误，原样保留并标为需要补测。每段约 40 s，前 10 s 保留，主结果使用约 30 s 的 `summary.scopes.main`。

## 采集与可用数量

| 配置 | 组合数 | 已录段数 | 主窗口 PASS | 主窗口 CHECK | 结果 |
|---|---:|---:|---:|---:|---|
| N=1 FULL 零载 | 4 | 12 | 12 | 0 | [四个槽位](FULL/N=1/200Hz/README.md) |
| N=2 FULL 零载 | 6 | 18 | 18 | 0 | [六种组合](FULL/N=2/200Hz/README.md) |
| N=3 FULL 零载 | 4 | 12 | 11 | 1 | [四种组合及异常说明](FULL/N=3/200Hz/README.md) |

每组已录三次，均为同一 setup、一个 batch 的连续时间窗口，不是三个独立装配 Block。按每组合三条合格窗口的 FULL 零载主矩阵，已采集 42/45 段、现有合格 41/45 段；还需 N=4 三段，以及补齐 M0_M1_M2 的一条合格窗口。GUI Record x3 会再产生一个三段批次，后续需保留新的 batch 身份，不覆盖或抹去本次失败记录。

## N=3 需要保留的两个发现

1. **M0_M1_M2 / Repeat_1：主窗口 CHECK，暂不进入无完整性错误的性能均值。** 约 19.472339 s 时出现一个外 CRC 错误；包头 seq1675977 到 seq1675978 的间隔为 2148 B，而标准包长为 3172 B，存在 1024 B 差额。seq1675978 的完整包仍在 raw 中且内外 CRC 有效，被实时解析器越过，因此会话缺号 2 不能直接写成两个原始包都消失。不能仅凭 raw 定位字节缺口的设备/USB/PC成因。原始文件、summary 和错误计数全部保留，没有进行恢复回填。
2. **M0_M1_M3 / Repeat_3：主窗口 PASS，但帧率降至约 199.124 Hz，仍纳入性能统计。** 末段出现桥端相邻包入队时间间隔 123 ms，PC 端另有最大 301.3735 ms 的完成时间间隔。序号连续、无 CRC 错误；这说明有时间停顿和接收批量化影响，但不能单凭它定位 SPI 带宽不足或物理扫描丢失。不因帧率较低而删掉这条记录。

[N=3 完整审计](../analysis/20260907_n3_full_review/ANALYSIS_CN.md) · [时间间隔说明](../analysis/20260907_n3_full_review/TIMING_NOTE_CN.md)

## 命名和文件保留

沿用原 FULL 层级，例如：

```text
data/FULL/N=1/200Hz/M0/Repeat_1/
data/FULL/N=2/200Hz/M0_M1/Repeat_1/
data/FULL/N=3/200Hz/M0_M1_M2/Repeat_1/
```

每个 Repeat 原样保留六文件：`mul1_raw.bin`、`packet_log.csv`、`module_log.csv`、`events.jsonl`、`summary.json`、`experiment_log.md`。保留原 run_id、实验时间、batch_id、Repeat、检查状态和所有字节。异常记录仍在对应 Repeat_1 中，通过索引明确标记；不同条件或另一 batch 不覆盖旧目录，也不擅自改原 Repeat 编号。

GUI 后续新录制仍先保存时间戳目录；未完成或本次快照之外的记录不自动算入本索引。历史数据独立存于 `../history/pre_variable_spi_20260906/data`。

## 两种统计口径

- [run_index.csv](run_index.csv)：全部 42 条，含 `main_eligible`、主窗口错误理由和时间停顿备注。性能分析必须检查 eligible，不可把所有路径都当作合格窗口。
- [group_statistics.csv](group_statistics.csv)：仅主窗口 PASS 的性能统计，注明已录 n、有效 n、CHECK 数量、均值 ± 段间样本 SD 和采用的 run_id。M0_M1_M2 当前有效 n=2，其余配置 n=3。
- [all_runs_diagnostic_statistics.csv](all_runs_diagnostic_statistics.csv)：包含所有原记录的诊断统计，每组已录 n=3；异常记录没有从数据集或可靠性评估中消失。
- [path_map.csv](path_map.csv)：252 个原文件的旧路径 → 新路径及 SHA256。原 summary 内的时间戳绝对路径保留为采集来源，实际读取使用映射或当前目录。

完整性过滤只用于无错误窗口的性能均值，不可据此宣称所有采集都无错误。可靠性描述必须包含已发现的失败记录及其暴露时间。样本 SD 在每段指标之间计算；不把每一帧当作独立实验，不把三段时间重复当作三个独立 setup。

正常 FULL 包长为 `(24+4M)+1044N` B，当前固定槽位数 M=4，所以 N=1/2/3 分别为 1084/2128/3172 B。USB 完整包流量按有效完整包字节和实际主窗口时长计算；raw 到达字节率另列，均不含 USB 总线事务开销。目标 200 Hz 不能替代实际包率。

全程文件边界状态与主窗口独立：N=1 的 12 条、N=2 的 16 条全程 CHECK 均仅有 1 B 尾片段；N=3 全程 4 PASS/8 CHECK，其中一条有上述实际主窗口错误，其他是文件尾片段（包含 M0_M1_M3 第三条的 1020 B 尾部半包）。保留全部原状态，不统一改成 PASS。

## 追溯与适用范围

- [N=1 审计](../analysis/20260906_current_data_review/ANALYSIS_CN.md) / [搬迁验证](../analysis/20260906_current_data_review/organization_verification.json)
- [N=2 审计](../analysis/20260906_n2_full_review/ANALYSIS_CN.md) / [搬迁验证](../analysis/20260906_n2_full_review/organization_verification.json)
- [N=3 审计](../analysis/20260907_n3_full_review/ANALYSIS_CN.md) / [搬迁验证](../analysis/20260907_n3_full_review/organization_verification.json)

三批原始文件均分别完成搬迁前后哈希验证。M0–M3 是通信槽位，不是板卡唯一身份；本地固件 provenance 不是设备 flash 读回。保持原 deployment_confirmed 和未知板卡映射，不补造事实。

旧绘图/审计脚本多数针对 schema 1；本批为 schema 2，分析应明确选 run_id、main 窗口和完整性状态。`plot_delta_mul_length.py` 不自动排除前 10 s。本次只更新数据目录与汇总文档，没有替换论文图表。DELTA 与动态条件另行采集，FULL 数据不提供普通 ESKD 的 K 或压缩收益。
'''
(DATA/'README.md').write_text(text, encoding='utf-8')
print('Updated 42-run / 14-configuration / 252-file indexes: 41 eligible, one CHECK preserved.')
