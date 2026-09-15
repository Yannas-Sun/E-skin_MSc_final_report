# 当前 Data 实验数据

本轮已核验并整理 2026-09-06 英国当地时间 22:59:34 至 23:11:09 的 12 条完成记录：FULL、zero_load、N=1、目标 200 Hz，M0–M3 各三次。原始文件内容、run_id、实验时间、batch_id 和 Repeat 元数据保持不变。

## 分类规则

沿用历史 FULL 的层级，在每个槽位下增加三次重复目录：

```text
data/
└── FULL/
    └── N=1/
        └── 200Hz/
            ├── M0/Repeat_1, Repeat_2, Repeat_3
            ├── M1/Repeat_1, Repeat_2, Repeat_3
            ├── M2/Repeat_1, Repeat_2, Repeat_3
            └── M3/Repeat_1, Repeat_2, Repeat_3
```

每个 Repeat 保留原来的六个文件：`mul1_raw.bin`、`packet_log.csv`、`module_log.csv`、`events.jsonl`、`summary.json`、`experiment_log.md`。

本轮全部为 zero_load，故沿用原 FULL 路径，不额外插入负载层。以后不同条件或同一条件的另一批次不可覆盖这些目录，也不可将批次内 Repeat 擅自改成全局编号；整理时需明确分出条件或 Batch 层。GUI 后续新录制仍先保存时间戳目录，只有完成记录才参与整理。

## 结果及统计口径

12 条主窗口均 PASS。每条约 40 s，前 10 s 作为稳定前段保留，主结果使用 `summary.scopes.main` 的约 30 s。已独立核验全部 96,193 个完整包（主窗口 72,096 个）：内外 CRC、序号、模块模式、日志偏移及数量均一致。

| 槽位 | 主窗口帧率 / Hz，均值 ± 样本 SD | 时间重复 n | 独立批次数 |
|---|---:|---:|---:|
| M0 | 200.100 ± 0.024 | 3 | 1 |
| M1 | 200.374 ± 0.053 | 3 | 1 |
| M2 | 200.197 ± 0.019 | 3 | 1 |
| M3 | 200.331 ± 0.050 | 3 | 1 |

三次是同一接线条件下的连续时间窗口，不代表三次独立装配。M0–M3 表示 CS/IRQ 槽位；物理板卡身份没有由协议传输。200 Hz 是配置目标，实际 MUL1 包率另行统计。

全窗口 CHECK 的唯一原因均为文件截止时保存的 1 B 尾片段。启动跨界包及其 1083 B 后缀已正确单列；未发现新增会话跳号或 CRC 错误。保留原检查状态，不改写为 PASS。这些边界片段不要求重录本组数据。

这批数据适用于 N=1 的 FULL 零载基线。N=2/3/4 的 FULL、DELTA 对照及动态加载仍需另外采集。不能用本批 FULL 数据估计 ESKD 的 K 或压缩收益，也不能仅由包序号连续推断所有物理扫描均已送出或 SPI 时钟稳定。

## 索引和追溯

- [分组与逐次结果](FULL/N=1/200Hz/README.md)
- [独立数据审计](../analysis/20260906_current_data_review/ANALYSIS_CN.md)
- [run_id → 当前目录及逐次指标](../analysis/20260906_current_data_review/run_index.csv)
- [每组均值、样本 SD 和 n](../analysis/20260906_current_data_review/group_statistics.csv)
- [逐文件旧路径 → 新路径及 SHA256](../analysis/20260906_current_data_review/path_map.csv)
- [搬迁后哈希验证](../analysis/20260906_current_data_review/organization_verification.json)

全部 72 个原始文件、159,181,044 B 搬迁前后 SHA256 一致。原 `summary.files` 中的时间戳绝对路径作为采集来源记录保留；查找实际文件请使用本目录及 path_map，不要将旧绝对路径视为当前路径。

历史数据仍单独保存在 `../history/pre_variable_spi_20260906/data`。旧绘图/审计程序多为 schema 1，不能因目录相似便直接处理新版 schema 2；新结果应显式选择本批 run，并使用 main 窗口。`plot_delta_mul_length.py` 默认包含整个录制时间，不自动排除前 10 s。本次没有改写报告或重生成旧图。

本地 provenance 对应 four-module-variable-spi 及修复后的连续 PC parser；这不是设备 flash 读回。原 deployment_confirmed=false 及未知板卡映射保持原值，不能通过整理目录补造烧录或身份确认。
