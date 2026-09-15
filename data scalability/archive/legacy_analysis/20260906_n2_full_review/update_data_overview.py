"""Update the active data catalog after the N=2 snapshot is safely organized."""
from pathlib import Path
import csv
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT/'data'
REVIEWS = ['20260906_current_data_review', '20260906_n2_full_review']
all_runs, all_stats, all_files = [], [], []
for review in REVIEWS:
    folder = ROOT/'analysis'/review
    verified = json.loads((folder/'organization_verification.json').read_text(encoding='utf-8-sig'))
    assert verified['status'] == 'completed'
    for name, target in [('run_index.csv', all_runs), ('group_statistics.csv', all_stats), ('path_map.csv', all_files)]:
        with (folder/name).open(encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                row['source_review'] = review
                target.append(row)
assert len(all_runs) == 30 and len(all_stats) == 10 and len(all_files) == 180
assert len({r['run_id'] for r in all_runs}) == 30
for row in all_runs:
    source = DATA/row['new_relative_path']/'summary.json'
    summary = json.loads(source.read_text(encoding='utf-8-sig'))
    assert summary['run_id'] == row['run_id']
    assert summary['scopes']['main']['status'] == 'PASS'
for row in all_files:
    assert (DATA/row['new_relative_path']).is_file()
for name, rows in [('run_index.csv', all_runs), ('group_statistics.csv', all_stats), ('path_map.csv', all_files)]:
    with (DATA/name).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

old = DATA/'README.md'
backup = HERE/'data_README_before.md'
if not backup.exists():
    backup.write_bytes(old.read_bytes())
text = '''# 当前 Data 实验数据

已整理两批 FULL 零载数据：N=1 四种槽位配置、N=2 六种槽位组合，共 30 条记录，目标 200 Hz。每组一个 batch、三次连续时间重复；每段约 40 s，前 10 s 保留，主结果使用之后约 30 s 的 `summary.scopes.main`。30 个主窗口全部 PASS。

## 已完成范围

| 配置 | 组合数 | 每组合时间重复 n | 每组合 batch 数 | 完成记录数 | 结果与目录 |
|---|---:|---:|---:|---:|---|
| N=1 FULL 零载 | 4 | 3 | 1 | 12 | [四个槽位结果](FULL/N=1/200Hz/README.md) |
| N=2 FULL 零载 | 6 | 3 | 1 | 18 | [六种组合结果](FULL/N=2/200Hz/README.md) |

当前 FULL 零载的 N=1～4 主矩阵按每组合三段计算已完成 30/45 段；尚需 N=3 四种组合各三段及 N=4 一种组合三段。DELTA 和动态条件另行采集。此表仅表示实际已核验记录，不把三段时间重复视为完成三个独立装配 Block。

## 命名和分类

沿用原 FULL 目录层级：

```text
data/FULL/N=1/200Hz/M0/Repeat_1/
data/FULL/N=2/200Hz/M0_M1/Repeat_1/
```

N=1 包含 M0、M1、M2、M3；N=2 包含 M0_M1、M0_M2、M0_M3、M1_M2、M1_M3、M2_M3。每个组合下都有 Repeat_1、Repeat_2、Repeat_3。

每个 Repeat 原样保留六文件：`mul1_raw.bin`、`packet_log.csv`、`module_log.csv`、`events.jsonl`、`summary.json`、`experiment_log.md`。run_id、实验时间、batch_id、Repeat 和原始字节均不修改。当前均为 zero_load，故保留原 FULL 层级；后续不同条件或另一 batch 不得覆盖已有目录，也不得擅自重排原 Repeat 编号，应明确增加条件/Batch 层。

GUI 新录制仍先保存时间戳目录。未完成或本次快照之外的新记录不自动搬迁或算入本索引。

## 完整性和统计解释

两批均独立核对 raw 内外 CRC、完整包长度、序号、实际模块/模式、日志偏移和主窗口计数。N=1 的 12 条全程 CHECK、N=2 的 16 条全程 CHECK，均仅因文件截止时保留的 1 B 尾片段；N=2 另外 2 条全程 PASS。原始全程状态保留，主窗口全部 PASS，不需要仅因这些文件边界片段重录。

正常 FULL 包长为 `40 + 1044N` B：N=1 为 1084 B，N=2 为 2128 B。组表给出各段主窗口 MUL1 包率和 USB 完整包流量的均值 ± 段间样本 SD，并注明 n=3、batch_n=1；原始块到达流量另列在 group_statistics.csv。USB 流量指采集的 MUL1 有效字节，不含 USB 总线事务开销。200 Hz 是配置目标，不能用它替代实测包率。

三次 Repeat 是同一 setup 下的连续窗口，并非三次独立装配。M0–M3 是通信槽位，不是协议传输的板卡唯一身份。没有观察到包序号异常不能证明所有物理扫描均已送出，也不能单独证明 SPI 时钟稳定；FULL 数据不能提供普通 ESKD 的 K 或压缩收益。

## 汇总索引和原始路径追溯

- [全部 30 条记录及主窗口指标](run_index.csv)
- [10 个配置的均值、样本 SD 和 n](group_statistics.csv)
- [180 个原文件的旧路径 → 新路径及 SHA256](path_map.csv)
- [N=1 独立审计](../analysis/20260906_current_data_review/ANALYSIS_CN.md)；[搬迁验证](../analysis/20260906_current_data_review/organization_verification.json)
- [N=2 独立审计](../analysis/20260906_n2_full_review/ANALYSIS_CN.md)；[搬迁验证](../analysis/20260906_n2_full_review/organization_verification.json)

两批全部 180 个原文件分别完成搬迁前后 SHA256 校验。原 `summary.files` 中的时间戳绝对路径保留为采集来源；实际读取使用本目录或 path_map。历史数据仍独立存于 `../history/pre_variable_spi_20260906/data`。

旧绘图/审计脚本多数针对 schema 1；新记录为 schema 2，分析应明确选择 run_id 并使用 main 窗口。`plot_delta_mul_length.py` 默认读取整个时间序列，不自动去掉前 10 s。本次仅整理数据与汇总文档，没有替换报告图表。

本地 provenance 指向 four-module-variable-spi 及连续解析的 PC 修复版本；这是本地文件身份记录，不是设备 flash 读回。保留原 deployment_confirmed 和未知板卡映射，不通过目录整理补造确认信息。
'''
old.write_text(text, encoding='utf-8')
print('Updated active overview and combined 30-run / 10-group / 180-file indexes.')
