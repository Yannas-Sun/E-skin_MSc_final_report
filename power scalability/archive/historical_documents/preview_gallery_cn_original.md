# 最新 M0 复测：Power 图表预览

本文件仅展示独立预览，尚未写入论文或覆盖报告原图。输入为报告 2.4 的编制数据，加上最新五组 M0 逐点复测。

**已确认：** N=1、M0、ZERO 的 3.252 V 照片归属和数值已由用户确认，对应压降 28 mV，已移除问号及待确认说明。星号仅表示该条目包含逐点复测，与其他复测条目含义相同。N=2、M0+M1、ZERO 的 M0 电压采用用户确认的 3.251 V（主读数/MIN/MAX 一致），不使用误放照片。

平均压降热力图已从本图册移除。逐组合图现为三幅并排热力图：空载、满载，以及满载减去空载的压降差值。前两幅共用根据实际数据生成的压降色标；第三幅使用以0为中心的独立色标，正负数显示增减方向。它是两个记录条件的差值，未新增测量或重复。

SOURCE、其他模块和温度沿用用户说明未变的记录。当前仍为 30 个组合/负载条目、64 条模块读数；逐点复测不增加完整配置的重复数。图中 SD 为不同组合间的样本 SD，不是重复实验误差。

| M0 条件 | 最新电流 / mA | 最新模块电压 / V | 采用的 SOURCE / V | 压降 / mV |
|---|---:|---:|---:|---:|
| N=1 ZERO | 18.018 | 3.252（用户确认） | 3.280 | 28 |
| N=1 MAX | 19.675 | 3.249 | 3.281 | 32 |
| N=2 M0+M1 ZERO | 17.941 | 3.251（用户确认） | 3.281 | 30 |
| N=2 M0+M2 ZERO | 17.969 | 3.251 | 3.279 | 28 |
| N=2 M0+M3 ZERO | 17.956 | 3.250 | 3.279 | 29 |

## 1. 电流与估计输出功率随 N 变化

采用最新 M0 电流；功率为保留的 SOURCE 电压乘以各支路电流之和，不含 Teensy USB 和稳压器损耗。

![电流与估计输出功率随 N 变化](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/current_power_scaling.png>)

[PNG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/current_power_scaling.png>) · [SVG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/current_power_scaling.svg>)

## 2. 源端与模块端电压

采用最新模块端电压，SOURCE 沿用已确认未变的记录；MIN–MAX 为仪表记录范围。

![源端与模块端电压](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/voltage_scaling.png>)

[PNG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/voltage_scaling.png>) · [SVG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/voltage_scaling.svg>)

## 3. 空载压降、满载压降及对应差值

第三幅热力图逐组合、逐模块显示满载压降减去空载压降：增加用正号，减少用负号，不变为0，未连接模块为空位。u 表示用户确认的 3.251 V，错误照片已排除。 色标自动范围为 25–40 mV，两负载面板共用。 差值面板独立采用 -10 至 +10 mV、以0为中心的色标。

![空载压降、满载压降及对应差值](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/module_voltage_drop.png>)

[PNG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/module_voltage_drop.png>) · [SVG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/module_voltage_drop.svg>)

## 4. N=1～4 的压降散点与均值

每个散点为一个组合；菱形为均值。仅 N=2、3 可计算组合间样本 SD。

![N=1～4 的压降散点与均值](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/module_drop_N1_N4.png>)

[PNG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/module_drop_N1_N4.png>) · [SVG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/module_drop_N1_N4.svg>)

## 5. 单模块不同状态的电流比较

连续传输状态下 M0 空载和满载采用最新电流；阻塞状态沿用原记录。

![单模块不同状态的电流比较](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/single_module_screening.png>)

[PNG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/single_module_screening.png>) · [SVG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/single_module_screening.svg>)

## 6. 各模块支路电流随 N 变化

M0 最新五组电流和此前两组逐点复测已纳入；其他支路读数保留。

![各模块支路电流随 N 变化](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/branch_current_balance.png>)

[PNG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/branch_current_balance.png>) · [SVG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/branch_current_balance.svg>)

## 7. 温度随 N 变化

温度测量未更新，本图沿用原数据；图形重新导出，不代表新增温度实验。

![温度随 N 变化](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/temperature_scaling.png>)

[PNG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/temperature_scaling.png>) · [SVG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/temperature_scaling.svg>)

## 8. 由 N=1 参考电流预测多模块电流

M0 的 N=1 参考值已更新，并重算所有组合的预测差值。

![由 N=1 参考电流预测多模块电流](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/independent_current_prediction.png>)

[PNG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/independent_current_prediction.png>) · [SVG](<../../DATA/archive/m0_n1_n2_preview_20260907/figures/independent_current_prediction.svg>)

## 数据与复现

预览数据保存在本目录 `data/`，图像保存在 `figures/`；来源及文件校验值分别在 `data/source_manifest.json`、`figures/base_figure_manifest.json`、`drop_figure_manifest.json` 与 `preview_manifest.json`。

差值明细保存在 `data/load_voltage_drop_changes.csv`，含32组模块配对与各负载的SOURCE、模块端电压和压降。撤下的平均压降热力图保存在 `archive/removed_mean_heatmap/`。

脚本位于 `power scalability/script/Main/`：先运行 `power_m0_preview_data_20260907.py`，再运行 `power_m0_preview_load_difference_20260907.py`，然后运行 `power_m0_preview_figures_20260907.py` 与 `power_m0_preview_drop_20260907.py`，最后运行 `power_m0_preview_gallery_20260907.py`。所有输出仅在独立预览目录，均不含复制到报告的选项。
