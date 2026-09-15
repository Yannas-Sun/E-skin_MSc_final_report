# Power scalability

> **M0空载电流复测已登记（2026-09-07）：** M0＋M1＋M2、ZERO 的M0电流为18.051 mA（MIN18.00、MAX18.08），用户确认模块电压仍3.241 V。[原值与复测对照](DATA/analysis/retest_reviews/m0_zero_retest_20260907/README_CN.md)。照片与用户确认来源分别保存，新的电压极值未提供；作为单模块补充记录保留，原矩阵、图表和报告未替换。

> **M3定向复测已登记（2026-09-07）：** M1＋M2＋M3、MAX 的M3复测电压3.243 V、电流19.263 mA，照片和MIN/MAX已独立保存。[原值与复测对照](DATA/analysis/retest_reviews/m3_max_retest_20260907/README_CN.md)。复测前已确认重新插入M3 connector；已澄清3.243 V为M3模块端、SOURCE尚未重测，加载一致性未确认，新压降留空；原44 mV、完整矩阵和报告2.3暂保持原记录。

> **2026-09-07报告2.3发布：** [当前报告](../main%202.3.pdf) 已纳入全部15组合的ZERO/MAX数据，更新7张Power图、方法、结果、讨论、附录、摘要和结论，共61页。[版本存档与校验](../report_versions/v2.3/manifest.json) 保留2.2基线和本轮来源。同一Word清单已更新，P05仍为部分完成。以下阶段性条目保留各自当时的状态，不再表示当前报告待合入；最新图表目录为 DATA/reference/report_v2_3_figures/。

本目录用于保存 Power Scalability 的实验设计、原始数据、分析脚本、派生结果和实验照片。

**最新完整汇总：[N=1–4全部空载／满负载结果](DATA/analysis/current/all_power_review_20260907/README_CN.md)。** 2026-09-07新增M0-M1-M3和M0-M2-M3的14张MAX电压/电流照片及10个温度点。两组电流合计58.631、58.279 mA；源端均3.275 V，输出侧功率估计192.016525、190.863725 mW。当前持续USB接收、FULL、配置200 Hz系列已覆盖15种非空组合×2种负载，即**30个配置条件、64条模块支路记录**。每个配置条件仍只有一组记录，没有新增同条件独立重复。全部配置的主读数、MIN/MAX、温度及来源保存在新汇总；主读数齐全不代表加载定义、故障监测、重复性或动态验证齐全。

| N | 每种负载组合数 | ZERO电流 / mA | MAX电流 / mA | ZERO输出侧功率估计 / mW | MAX输出侧功率估计 / mW |
|---|---:|---:|---:|---:|---:|
| 1 | 4 | 18.325 ± 0.111 | 20.009 ± 0.280 | 60.115 ± 0.370 | 65.644 ± 0.910 |
| 2 | 6 | 36.263 ± 0.265 | 39.629 ± 0.315 | 118.907 ± 0.848 | 129.891 ± 1.020 |
| 3 | 4 | 54.405 ± 0.337 | 58.964 ± 0.616 | 178.245 ± 1.091 | 193.136 ± 2.051 |
| 4 | 1 | 72.513 | 78.720 | 237.408 | 257.651 |

±为不同组合之间的样本SD，不是同条件重复SD；N=1为四个不同模块，N=4仅一个组合不能计算SD。功率为顺序支路读数之和乘顺序源端电压的估计，不含Teensy USB功耗和稳压器损耗。各组合MAX比ZERO电流高7.665%–10.973%，仅作描述性对照；新6组MAX的质量/接触面积/负载分配未给出，不能将差异全部归因于负载。原阻塞待机记录独立保留，本次没有补测阻塞状态。旧main 2.1不含这些补充数据；当前main 2.3已纳入。

双模块满负载子表：[N=2 MAX六组合电压、电流和温度](DATA/analysis/current/n2_max_review_20260907/README_CN.md)。四组新增电流合计分别39.357、39.335、39.719、40.016 mA；六组合合计电流39.629±0.315 mA（组合间样本SD），空载与满负载均覆盖6/6。

最新整体空载数据：[N=1–4 全部15组合统计](DATA/analysis/current/zero_power_review_20260907/README_CN.md)。2026-09-07补入M0-M1-M3与M0-M2-M3的三条支路电流和五个温度，ZERO电压、电流主读数、温度记录现覆盖15/15组合。N=3四组合合计电流54.405±0.337 mA（组合间样本SD）；各组合仍只有一组电流记录。主读数齐全不等于重复性、动态或热稳态验证完成。

最新补充统计：[N=2 ZERO六组合电流、功率估计和温度](DATA/analysis/current/n2_zero_review_20260907/README_CN.md)。2026-09-07新增四组合的电流/温度，原电压记录按组合关联；每组合一组电流记录，均值±SD描述组合间差异。这批数据已纳入当前main 2.3；旧2.1保留。

四个新增N=2组合及两个新增N=3组合的旧ZERO照片已移入各自`zero_load`目录，共34张，当前分析已按原SHA256核验并修复引用。原始转录保留当时路径，迁移映射及旧派生文件见[路径迁移记录](DATA/analysis/provenance/path_relocation_20260907/README_CN.md)。MAX新增照片和ZERO来源分别关联，原始读数及已发布main 2.1保持不变。

入口：[评估报告](Power_Scalability_Measurement_Plan_CN.md) · [全部图表及矢量版](DATA/analysis/figures/README.md) · [变更日志](CHANGELOG.md)。

## 目录结构

```text
power scalability/
├─ Power_Scalability_Measurement_Plan_CN.md
├─ Power_Scalability_Experiment_Log_CN.md
├─ CHANGELOG.md
├─ DATA/
│  ├─ power_raw.csv                      原始测量数据；分析脚本不会修改
│  ├─ power_experiment_records/          transmission/no_transmission 测试填写模板
│  └─ analysis/
│     ├─ figures/                        7 张图的 PNG/PDF/SVG、目录及校验清单
│     ├─ power_summary.csv               逐 run 派生指标
│     ├─ power_scaling.csv               按模块数汇总及拟合
│     ├─ branch_summary.csv              各模块支路电流、功耗和压降
│     ├─ thermal_summary.csv             温度汇总
│     ├─ anomaly_summary.csv             异常值与数据限制
│     └─ analysis_summary.json           完整机器可读分析结果
├─ script/
│  ├─ Main/
│  │  ├─ analyze_power_scalability.py    分析入口
│  │  ├─ power_figures.py                绘图与多格式导出
│  │  ├─ power_report.mplstyle           统一报告样式
│  │  └─ validate_power_figures.py       文件、尺寸、字体与来源校验
│  ├─ requirements.txt
│  └─ requirements-qa.txt
└─ photos/
   └─ n=1|n=2|n=3|n=4/                  各模块数量的实验照片
```

## 最新补充数据的复现

在本目录依次执行：

```powershell
python -B script/Main/summarize_voltage_review.py
python -B script/Main/summarize_n2_zero_20260907.py
python -B script/Main/summarize_zero_power_20260907.py
python -B script/Main/summarize_n2_max_20260907.py
python -B script/Main/summarize_all_power_20260907.py
```

这些入口生成日期命名的补充统计，不修改报告2.1的冻结分析。每份统计附有原始记录/照片哈希与已知限制。

## 历史分析的复现

在本目录执行：

```powershell
python -m pip install -r script/requirements.txt
python script/Main/analyze_power_scalability.py
```

以下旧入口只分析历史 `power_raw.csv` 中的 `200 Hz / FULL / ZERO` 数据，不包含顶部新增记录。`N=1` 使用四个模块的独立参考值，
`N=2` 现在汇总 M0+M1 与 M2+M3 两种组合；`N=3` 汇总 M0+M1+M2 与新增的 M1+M2+M3 两种组合；`N=4` 使用当前已有的多模块 run。所有派生结果覆盖写入 `DATA/analysis/`，
[DATA/raw/canonical/power_raw.csv](DATA/raw/canonical/power_raw.csv) 始终保持不变。

`DATA/rawdata/` 已按要求删除。当前分析仅使用 `DATA/raw/canonical/power_raw.csv`；
旧版 N=4 记录、M3 诊断记录和 M1+M2+M3 填写模板均不再保留。
其中 `host_usb_polling_state` 标记主机是否持续读取 USB；现有记录均为
`BLOCKED_STANDBY_NO_CONTINUOUS_USB_READ`，后续通路状态实验应标记为
`CONTINUOUS_USB_READ`。

新的 Power 实验填写文件统一保存在
`DATA/raw/canonical/power_experiment_records/`，按主机通信状态、模块数量、模块组合和负载分类。

图表统一宽 180 mm，输出 300 dpi 白底 PNG、嵌入字体的 PDF 和可编辑文本的 SVG；
放入报告或 PPT 时优先使用 PDF/SVG。图中的文字均为英文。

当前工作区已配置 `.venv-power-plots`，从项目根目录可直接运行：

```powershell
& .\.venv-power-plots\Scripts\python.exe 'docs/Final/power scalability/script/Main/analyze_power_scalability.py'
```

文件校验在本目录执行：

```powershell
python -m pip install -r script/requirements-qa.txt
python script/Main/validate_power_figures.py
```

绘图环境版本和源文件 SHA-256 保存在 [figure_manifest.json](DATA/analysis/figures/figure_manifest.json)，
检查结果保存在 [figure_validation.json](DATA/analysis/figures/figure_validation.json)。
