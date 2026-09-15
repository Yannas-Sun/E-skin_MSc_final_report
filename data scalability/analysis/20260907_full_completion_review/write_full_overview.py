"""Publish the completed FULL catalog from the explicit primary selection."""
from pathlib import Path
import csv
import json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
DATA=ROOT/'data'
selection=json.loads((HERE/'primary_selection.json').read_text(encoding='utf-8'))
assert selection['primary_count']==45 and selection['recorded_count']==48
with (DATA/'group_statistics.csv').open(encoding='utf-8-sig',newline='') as stream:
    stats=list(csv.DictReader(stream))
assert len(stats)==15 and all(r['temporal_repeat_n']=='3' and r['batch_n']=='1' for r in stats)

overview='''# 当前 Data 实验数据

**FULL 零载 N=1～4 主矩阵已齐：15 种组合，每组一个完整批次、三次连续记录，共 45 条主窗口 PASS。** 每段约 40 s，前 10 s 保留，主分析使用其后约 30 s 的 `summary.scopes.main`。

全部原始数据为 48 条，其中 47 条主窗口 PASS、1 条 CHECK。补测成功不会消除先前的失败；完整性与主矩阵选择在索引中分别记录。

## 完成情况

| 配置 | 组合数 | 全部记录 | 主窗口 PASS / CHECK | 主矩阵记录 | 组结果 |
|---|---:|---:|---:|---:|---|
| N=1 FULL 零载 | 4 | 12 | 12 / 0 | 12 | [四个槽位](FULL/N=1/200Hz/README.md) |
| N=2 FULL 零载 | 6 | 18 | 18 / 0 | 18 | [六种组合](FULL/N=2/200Hz/README.md) |
| N=3 FULL 零载 | 4 | 15 | 14 / 1 | 12 | [四种组合和补测](FULL/N=3/200Hz/README.md) |
| N=4 FULL 零载 | 1 | 3 | 3 / 0 | 3 | [四模块结果](FULL/N=4/200Hz/README.md) |
| 合计 | 15 | 48 | 47 / 1 | 45 | [FULL 主矩阵总表](FULL/README.md) |

每组的三次是同一 setup 内的时间重复，不是三次独立装配。该完成状态仅指 FULL 零载主矩阵，不能代替 DELTA 零载/动态实验，也不能说明所有已采记录都无错误。

## M0_M1_M2 补测如何使用

新补测 batch `BATCH_6b6313d281364eaa891ce82942b3d531` 的 Repeat 1/2/3 全部 PASS，整体作为该组合的主矩阵批次，不按帧率挑选单条记录。

- 原批次三段仍在 `FULL/N=3/200Hz/M0_M1_M2/Repeat_1..3/`：Repeat_1 为失败证据，Repeat_2/3 为合格补充数据。它们没有被覆盖、改号或改为 PASS。
- 新补测在 `FULL/N=3/200Hz/M0_M1_M2/Batch_20260907_004948_668301/Repeat_1..3/`，保留原 run_id、batch_id 与采集时间。
- 该组合主矩阵 n=3、batch_n=1；全部 PASS 辅助统计 n=5、batch_n=2；全部记录诊断 n=6、batch_n=2。三种口径分别保存，不混成同一批次的六次重复。

其余组合使用原来的完整三次批次。原 M0_M1_M3 第三条较低帧率但 PASS，仍在主矩阵中，没有因为吞吐较低而剔除。

## 数据索引与统计口径

- [run_index.csv](run_index.csv)：全部 48 条，分别保存 `main_eligible`、`primary_matrix_selected`、`selection_reason` 与 `replacement_batch_id`。
- [primary_matrix.csv](primary_matrix.csv)：明确选定的 45 条主分析记录；用它确定报告图表的输入。
- [group_statistics.csv](group_statistics.csv)：15 个主矩阵配置，每组 n=3、batch_n=1，均值 ± 段间样本 SD。`recorded_repeat_n`/`eligible_repeat_n`仍说明该配置全部原记录数量。
- [all_pass_group_statistics.csv](all_pass_group_statistics.csv)：全部 47 个 PASS 窗口的辅助统计，M012 跨两个批次，不能解释为五次独立装配。
- [all_runs_diagnostic_statistics.csv](all_runs_diagnostic_statistics.csv)：包含所有 48 条记录及失败窗口，作为诊断和可靠性追溯输入。
- [batch_statistics.csv](batch_statistics.csv)：16 个实际批次各自的 PASS 统计，保留已录数量与失败数量。
- [主矩阵选择清单](../analysis/20260907_full_completion_review/primary_selection.json)：完整列出选择原则、45 个 run_id 和三个未选入主矩阵但仍保留的旧记录。

无错误性能子集不能用来宣称整个系统从未出错。评估可靠性时必须纳入全部采集记录、失败事件和实验暴露时间。样本 SD 是段间描述统计，不把每一帧当作独立重复。

## 协议与时间

正常 FULL 包长为 `(24+4M)+1044N` B，当前固定槽位数 M=4；N=1/2/3/4 分别为 1084/2128/3172/4216 B。USB 完整包数据率按有效包字节和实际主窗口时长计算；raw 到达字节率另列，两者均不包括 USB 总线事务开销。目标 200 Hz 不能替代实际包率。

原 M012 Repeat_1 在约19.47 s出现CRC错误和相对帧布局的1024 B短缺；第二个被跳过序号的完整有效包仍能从raw找到。原 Session 缺号2不能写成两个原始包都物理丢失，具体发生在哪一层尚未定位，日志不作恢复回填。

原 M013 Repeat_3 有123 ms桥端入队间隔及另一次301.3735 ms PC完成间隔，仍作为实际性能波动保留。补测M012 Repeat_3有278.7935 ms PC观察间隔，但对应桥端只隔5 ms，六条新增记录桥端相邻间隔最大6 ms、序号连续。PC批量接收、桥端入队时刻和物理扫描时间不可混为一谈。

## 文件与追溯

每次记录的六个文件保持原样：`mul1_raw.bin`、`packet_log.csv`、`module_log.csv`、`events.jsonl`、`summary.json`、`experiment_log.md`。原始字节、状态、Repeat、run_id、batch_id 和嵌入旧路径不修改。

- [288 个原文件旧路径 → 新路径及 SHA256](path_map.csv)。四批分类均核验搬迁前后哈希；原 `summary.files` 的绝对路径保留为来源，当前读取使用路径映射或本目录。
- [N=1 审计](../analysis/20260906_current_data_review/ANALYSIS_CN.md)
- [N=2 审计](../analysis/20260906_n2_full_review/ANALYSIS_CN.md)
- [原 N=3 审计及失败证据](../analysis/20260907_n3_full_review/ANALYSIS_CN.md) / [原时间诊断](../analysis/20260907_n3_full_review/TIMING_NOTE_CN.md)
- [补测与 N=4 审计](../analysis/20260907_full_completion_review/ANALYSIS_CN.md) / [本次时间诊断](../analysis/20260907_full_completion_review/TIMING_NOTE_CN.md) / [36 文件搬迁验证](../analysis/20260907_full_completion_review/organization_verification.json)

GUI 后续新录制仍先写时间戳目录；未完成或本轮固定快照之外的数据不自动选入本矩阵。另一批次不得覆盖现有 Repeat 目录。历史旧固件数据仍单独存于 `../history/pre_variable_spi_20260906/data`。

旧绘图脚本多针对schema 1，本批为schema 2；新图应显式读取primary_matrix并使用main窗口。本次整理数据与汇总文档，没有替换论文图表。M0–M3是槽位而非唯一板卡身份；本地固件provenance不是设备flash读回，保留原确认字段，不补造部署事实。
'''
(DATA/'README.md').write_text(overview,encoding='utf-8')

full=DATA/'FULL/README.md'
if full.exists() and not (HERE/'before_catalog/FULL_README.md').exists():
    (HERE/'before_catalog/FULL_README.md').write_bytes(full.read_bytes())
lines=['# FULL 零载主矩阵：N=1～4','',
       '15种槽位组合，每组选择一个完整三次批次，共45个主窗口PASS。每段前10 s保留，以下使用其后约30 s主窗口；均值±样本SD按三个时间窗口计算。M012使用整个补测批次，原失败和两条PASS仍保留，全部48条的可靠性历史不被替换。','',
       '| N | 组合 | 时间重复 n | 批次数 | MUL1 包率 / Hz | USB 完整包 / Mbit/s | 平均包长 / B |',
       '|---:|---|---:|---:|---:|---:|---:|']
for row in stats:
    directory=f"N={row['N']}/200Hz/{row['modules']}/README.md"
    lines.append(f"| {row['N']} | [{row['modules']}]({directory}) | 3 | 1 | {float(row['rate_Hz_mean']):.6f} ± {float(row['rate_Hz_sample_sd']):.6f} | {float(row['packet_Mbit_s_mean']):.6f} ± {float(row['packet_Mbit_s_sample_sd']):.6f} | {float(row['Lmean_B_mean']):.0f} ± {float(row['Lmean_B_sample_sd']):.0f} |")
lines+=['','包长模型为(24+4M)+1044N，M=4。USB指标是MUL1有效字节，非USB事务总开销；实际包率决定每秒流量。三次为时间重复，不是独立装配。原M013低率PASS继续纳入，主矩阵选择不使用帧率阈值。','',
        '[45条主矩阵](../primary_matrix.csv) · [主统计CSV](../group_statistics.csv) · [全部48条及选择标记](../run_index.csv) · [总体说明与失败历史](../README.md)','']
full.write_text('\n'.join(lines),encoding='utf-8')
print('Wrote completed FULL overview and 15-configuration primary results table.')
