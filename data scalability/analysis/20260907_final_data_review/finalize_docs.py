"""Publish the completed data inventory and evidence-bounded final summary."""
from pathlib import Path
import csv,json

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]
DATA=BASE/'data'

def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def doc(path,text):
    path.write_text(text.strip()+'\n',encoding='utf-8')
def number(value):return float(value)
def msd(row,field,digits=6):
    return f"{number(row[field+'_mean']):.{digits}f} ± {number(row[field+'_sample_sd']):.{digits}f}"

validation=json.loads((HERE/'catalog_validation.json').read_text())
assert validation['status']=='PASS' and validation['all_runs']==111 and validation['dynamic_selected_runs']==12
evidence=json.loads((HERE/'evidence_review.json').read_text(encoding='utf-8'))
index=rows(DATA/'run_index.csv')
dynamic=rows(DATA/'dynamic_diagnostic_statistics.csv')
n4=[r for r in index if r['source_review']=='20260907_n4_full_coverage_review']
assert len(n4)==3

zero_table='| N | 组合数 | 每模式时间窗 n | FULL 有效USB / Mbit/s | DELTA零载有效USB / Mbit/s |\n|---:|---:|---:|---:|---:|\n'
for group in evidence['zero_load_by_N']:
    vals=[]
    for mode in ['FULL','DELTA']:
        metric=group[mode]['metrics']['packet_Mbit_s']
        vals.append(f"{metric['equal_combination_mean']:.6f} ± {metric['across_window_sample_sd']:.6f}")
    zero_table+=f"| {group['N']} | {group['combination_n']} | {group['temporal_window_n_per_mode']} | {' | '.join(vals)} |\n"

labels=['最早M1大面积批次（诊断）','M1大面积后续批次','M1大面积反复按压/释放','M1 Rolling','M1＋M3同时大面积覆盖','M0～M3同时全覆盖（诊断）']
assert len(dynamic)==len(labels)
dynamic_table='| 动态场景 | 记录 n | 主窗 PASS / CHECK | 平均包长 / B | 有效USB / Mbit/s |\n|---|---:|---:|---:|---:|\n'
for label,r in zip(labels,dynamic):
    dynamic_table+=f"| {label} | {r['recorded_repeat_n']} | {r['eligible_repeat_n']} / {r['review_required_n']} | {msd(r,'Lmean_B',2)} | {msd(r,'packet_Mbit_s')} |\n"

n4_table='| Repeat | 独立主窗 | 包率 / Hz | 平均包长 / B | 有效USB / Mbit/s | 外层缺号 | 内序号事件 | 已收到包内缺模块更新 |\n|---:|---|---:|---:|---:|---:|---:|---:|\n'
for r in n4:
    n4_table+=f"| {r['repeat']} | {r['independent_main_status']} | {number(r['main_rate_Hz']):.3f} | {number(r['main_Lmean_B']):.2f} | {number(r['main_packet_Mbit_s']):.6f} | {r['main_outer_missing_sequence_numbers']} | {r['main_inner_sequence_events']} | {r['main_missing_valid_expected_updates']} |\n"

n4_section='''## 最后一批 N=4：一段通过，两段有记录缺口

用户确认M0、M1、M2、M3同时全覆盖按下，模式仍是DELTA。三段各40 s，主分析窗口固定为10–40 s。原文件中zero_load标签保留为来源，派生条件改记large_area / full_coverage_all_modules。没有按错误时段或帧率剪裁记录。

'''+n4_table+'''
R2在22.7522755 s出现760731→760736的外层缺号，桥端相邻包间隔522 ms；该760736包为40 B，CRC有效，但四槽均没有有效更新。22.8446298 s四槽有效ESKF到达；其模块内序号前跳，之后M0～M2又各发生一次前跳。R3在16.7725519 s出现767419→767424、桥端453 ms间隔和四槽ESKF前跳，之后M0～M2再次前跳。两段各7次内序号事件，共14次；外层共有8个未观测编号。

全部已解析候选的内外CRC、布局、K和base链检查正常；有效ESKF后建立了基线，随后收到的ESKD可应用，锚点后未应用ESKD为0。**这些事实不能填补未观测编号，不能说“只因PC缓冲、系统没有丢帧”，也不能确定是ESKF、高K或SCK导致。** 外层与模块内的编号缺口分别报告，不能直接相加为物理扫描丢失数。

三段全部保留的诊断均值±样本SD：包率196.749261±2.206474 Hz，包长1674.366648±55.065612 B，有效USB 2.634962±0.067917 Mbit/s，普通内帧K=160.576658±6.811278，ESKF内帧比例0.542338%±0.034258个百分点。相同已观测包率下，相对4216 B FULL的字节减少约60.29%；因为该组含缺号和空更新包，此数值不能当作无损压缩性能结论。

只有R1主窗口独立通过，n=1无法计算段间SD。R1仍可作为明确标注的单段实例；整个N4批次作为诊断资料保留，不加入完整三次通过的动态性能子集。全程的初始1308个无锚点ESKD和尾片1/1/1 B与主窗内部事件分开记录。

[N4独立审计](../20260907_n4_full_coverage_review/raw_audit.md) / [逐模块统计及字节模型](../20260907_n4_full_coverage_review/statistics.md)。
'''

summary='''# Data 最终实验总结与分类记录（2026-09-07）

**本轮数据已全部整理：111条记录，未分类时间戳目录为0。新版固件FULL与DELTA零载N=1～4主矩阵完整；最后N=4同时全覆盖动态批次有两段异常，需要在报告中如实保留。**

## 完成范围与统计资格

| 类别 | 全部记录 | 主窗符合现有完整性检查 | CHECK | 完整批次入选记录 |
|---|---:|---:|---:|---:|
| FULL零载 | 48 | 47 | 1 | 45 |
| DELTA零载 | 45 | 45 | 0 | 45 |
| DELTA动态 | 18 | 13 | 5 | 12 |
| 合计 | 111 | 105 | 6 | 102 |

以上均指主窗口，不把原始全程CHECK改为PASS，也不把105/111当作独立试验的总体可靠性估计。FULL原M012批次三条被完整补测批次替换，其中仅一条CHECK，另外两条PASS保留为补充。动态13条主窗PASS中，N4 R1只有单段通过，未凑入完整三次重复的性能子集。

零载每种模式均为15个模块组合×3个连续窗口，共45条。n=3是同一设置下的时间重复，未建立三次独立装配。正式零载primary_matrix.csv仍为90条；dynamic_analysis_selected.csv另列12条；analysis_selected.csv合并这两种明确筛选口径为102条，使用时仍须按模式、条件和批次筛选。

'''+n4_section+'''
## N=1～4 零载主结果

'''+zero_table+'''
各组合等权，每组合恰有三段。表中SD为同N下各时间窗口均值的样本SD，包含组合间差异及时间波动；并非独立板卡或装配的不确定度。每个具体组合的n=3统计仍保存在原group_statistics.csv。

FULL包长为1084/2128/3172/4216 B；DELTA零载平均包长约145.24/251.98/360.74/475.15 B。按相同实际包率比较，DELTA有效包字节减少约86.60%～88.73%，已经包含ESKF成本。USB指标是完整有效MUL1的字节速率，不含USB物理事务全部开销。

## 各动态场景

'''+dynamic_table+'''
每行保留一个实际三连录批次，均值±样本SD跨三个主窗口计算。含CHECK的行是诊断统计；后续PASS不覆盖最早的失败记录，不将不同动作合并成同一个重复组。同时加载不代表各模块受力、覆盖面积或K相等。

四个完整通过批次的同包率字节减少分别为73.95%、80.57%、67.00%、75.99%。Rolling平均K和流量较高，说明压缩效果还取决于活动持续时间，不能仅看一次峰值。N2两模块均出现合法K=480，且额外密集ESKF期间仍通过检查，故“大量变化或出现ESKF必然产生错误”不受数据支持。

## 协议模型如何使用这些数据

当前M=4是最大槽位数，N是实际模块数，固定外层开销24+4M=40 B。每个普通模块ESKD为84+2K B，ESKF为1044 B，等长交点K=480与N无关。对实际已观测包逐帧求和：

`B = 40P + 84n_D + 2ΣK_D + 1044n_F`（本批无额外诊断payload）。

该字节账包含全部ESKF；对N4 R2的40 B无更新包，内帧数为0，不能按正常四模块K=0包376 B计费。平均模型应逐模块用有效更新覆盖率c_m、其ESKF比例q_m和普通帧K：

`L_mean = 40 + Σ_m c_m[(1-q_m)(84+2K_mean,D,m) + 1044q_m]`。

q_m分母为该模块有效内帧数；含任一ESKF的外包比例另有分母，不能互换。没有原因编码的ESKF，不能精确分拆为定时、高K回退、手动或故障恢复。更新覆盖率只覆盖已观测包中的模块更新，不能隐藏外层缺号。

零载K跨N均值约8.26、8.64、9.10、10.04；固定K外推仍是条件假设。字节模型与吞吐比较应分开使用实测包长和实测包率；不能把目标200 Hz与实测完成包率的差异称作逐帧字节模型误差。

## 分类及原始数据保护

本次搬迁15条、140个已有文件，共144,509,120 B，其中90个为六类原始测量文件。搬迁前后所有文件SHA-256一致，现有图也随目录保留。原始summary、记录状态、错误证据、run_id、batch_id、Repeat及嵌入旧路径不改写。根path_map.csv现有666条原始测量文件映射；根和DELTA层derived_path_map.csv仅记录本轮15条的50个派生文件，不是全部历史绘图清单。

新增记录目的地均在DELTA/Dynamic_load下：

| 批次 | 相对路径 |
|---|---|
| M1大面积后续三条 | N=1/200Hz/M1/Large_area/Batch_20260907_050453_154588/Repeat_1～3 |
| M1反复按压/释放 | N=1/200Hz/M1/Large_area_press_release/Repeat_1～3 |
| M1 Rolling | N=1/200Hz/M1/Rolling/Repeat_1～3 |
| N2同时大面积覆盖 | N=2/200Hz/M1_M3/Large_area_simultaneous/Repeat_1～3 |
| N4同时全覆盖 | N=4/200Hz/M0_M1_M2_M3/Full_coverage_all_modules/Repeat_1～3 |

最早M1大面积CHECK三条仍留在Large_area/Repeat_1～3，与后续批次分开。旧固件history/pre_variable_spi_20260906未动。FULL与DELTA零载专用视图和原90条主矩阵哈希不变；旧96条总索引的已有字段原值保留。分类前的catalog已备份到本目录before_catalog。

原审计报告与脚本描述的是分类前的固定快照，因此其中时间戳路径属于来源证据。当前路径用run_index.csv或path_map.csv解析；支持from-snapshot的统计脚本可从派生快照复现。不要直接运行旧分类快照去覆盖当前111条索引。

## 论文可更新项与保留限制

- [x] FULL、DELTA零载N=1～4全部组合的新固件数据已齐，每组合三段重复。
- [x] 动态场景标签已按用户确认分类，未混入零载统计。
- [x] 各批次均值、样本SD、n及重复层级已记录；异常和补测批次保留。
- [x] 实际包长、实际完成包率、有效USB流量、普通K及全部ESKF分别统计。
- [x] 新增动态已检查跨ESKF的模块序号、CRC、base链和目标更新，失败批次独立列出。
- [ ] N4动态尚未获得完整三段无错误结果，异常机制仍未定位；如保留“四模块动态无错”声明，需要针对性排查后补测整批，不需要因此重做已通过的零载矩阵。
- [ ] 新固件没有N3动态或单独小面积动态记录；对应图只能展示已测场景，或明确区分历史数据，不能补点后称为实测。
- [ ] 定时与特殊ESKF原因的精确归类、物理丢扫数和线路SPI时钟波形未由本次USB日志证明。40 MHz仍为理论条件；本批日志的10 MHz字段为本地配置来源。
- [ ] K固定、各模块相同载荷、唯一板卡身份和独立装配重复不应写成已验证事实。

因此当前足以完成限定范围的Data章节：新版N=1～4零载扩展实测、已通过的动态案例，以及N4高活动输入下观察到的完整性限制。Power和Calibration不在本次重测范围。本文档是实验与数据总结，论文图表/PDF仍需按上述新索引更新。

[全部111条索引](../../data/run_index.csv) / [102条选定分析记录](../../data/analysis_selected.csv) / [所有动态批次诊断统计](../../data/dynamic_diagnostic_statistics.csv) / [搬迁核验](organization_verification.json) / [索引核验](catalog_validation.json) / [独立证据复核](evidence_review.md)。
'''
doc(HERE/'FINAL_SUMMARY_CN.md',summary)
doc(HERE.parent/'20260907_n4_full_coverage_review/REVIEW_CN.md','# N=4 同时全覆盖：最终检查结论\n\n'+n4_section.replace('## 最后一批 N=4：一段通过，两段有记录缺口','## 一段通过，两段有记录缺口')+'\n记录已分类至data/DELTA/Dynamic_load/N=4/200Hz/M0_M1_M2_M3/Full_coverage_all_modules/Repeat_1～3；原审计文件内时间戳路径为分类前来源。\n\n[全部实验最终总结](../20260907_final_data_review/FINAL_SUMMARY_CN.md)。')

doc(DATA/'README.md','''# 当前 Data 实验数据：最终整理

**全部111条已分类。新版FULL与DELTA零载N=1～4主矩阵齐全；N4同时全覆盖动态批次R1通过，R2/R3保留CHECK。**

| 类别 | 全部记录 | 主窗合格 / CHECK | 完整批次入选 |
|---|---:|---:|---:|
| FULL零载 | 48 | 47 / 1 | 45 |
| DELTA零载 | 45 | 45 / 0 | 45 |
| DELTA动态 | 18 | 13 / 5 | 12 |
| 合计 | 111 | 105 / 6 | 102 |

- [最终实验总结](../analysis/20260907_final_data_review/FINAL_SUMMARY_CN.md)
- [全部111条索引](run_index.csv)：保留原GUI状态，结合main_eligible、independent_raw_audit与动态批次选择字段使用。
- [零载主矩阵90条](primary_matrix.csv) / [零载30个组合统计](group_statistics.csv)：FULL和DELTA各15组合×3段，保持原选择与数值。
- [完整通过的动态12条](dynamic_analysis_selected.csv) / [动态4批次性能统计](dynamic_group_statistics.csv)。
- [两类合并102条](analysis_selected.csv)：仍须按模式、实际条件、组合和批次筛选，不是同一统计组。
- [动态全部6批次诊断统计](dynamic_diagnostic_statistics.csv)：包括最早M1异常三条及N4异常批次。
- [666个原始文件路径和哈希](path_map.csv) / [本次搬迁核验](../analysis/20260907_final_data_review/organization_verification.json)。
- [FULL说明](FULL/README.md) / [DELTA零载](DELTA/Zero_load/README.md) / [全部动态场景](DELTA/Dynamic_load/README.md)。

各组n=3是同一设置的连续时间窗口，不是独立装配重复。完整主窗通常为10–40 s；原全程CHECK和边界证据保留。原FULL M012旧批次三条中只有一条CHECK，其余两条为补充PASS；整个补测三连录入主矩阵。

动态记录原zero_load误选标签保持在summary及原图中，分类索引使用用户确认的condition、actual_load_protocol，recorded_condition另列。最早M1大面积3条虽原GUI主PASS，独立序号检查CHECK；N4只有R1主PASS，整批不进入完整三次通过的动态子集。

原始文件字节、run_id、Repeat、状态、原图及嵌入旧路径不修改。当前读取用new_relative_path或path_map，审计中的旧路径是来源快照。旧固件资料独立保存于../history/pre_variable_spi_20260906。本次没有替换论文PDF。
''')
doc(DATA/'DELTA/README.md','''# DELTA 数据：63条

零载45条覆盖N=1～4全部15组合，每组合三个主窗通过。动态18条中13条主窗符合独立检查、5条CHECK；四个完整三次通过的动态批次共12条用于性能子集，N4单段PASS另留在诊断批次。

- [全部63条索引](run_index.csv) / [零载主矩阵45条](primary_matrix.csv)
- [零载结果](Zero_load/README.md) / [动态场景与异常](Dynamic_load/README.md)
- [完整通过的动态12条](dynamic_analysis_selected.csv) / [动态全部6批次](dynamic_diagnostic_statistics.csv)
- [整套实验总结](../../analysis/20260907_final_data_review/FINAL_SUMMARY_CN.md)

原GUI main_status与独立审核字段分开；不能仅按main_status筛选最早的大面积批次。动态误填zero_load的原始标签保留，索引condition使用用户确认的实际输入。ESKF成本均计入实测字节统计。
''')
doc(DATA/'DELTA/Dynamic_load/README.md','''# DELTA 动态负载：18条，6个三连录批次

'''+dynamic_table+'''
主窗为固定10–40 s，表中均值±样本SD跨三个时间窗口。最早M1批次全部CHECK；N4批次R1 PASS、R2/R3 CHECK，该行统计保留全部失败窗口作为诊断。四个完整通过批次共12条用于动态性能子集，未将N4 R1凑成三次通过。

- [M1大面积两个批次](N=1/200Hz/M1/Large_area/README.md)
- [M1反复按压/释放](N=1/200Hz/M1/Large_area_press_release/README.md)
- [M1 Rolling](N=1/200Hz/M1/Rolling/README.md)
- [N2同时大面积覆盖](N=2/200Hz/M1_M3/Large_area_simultaneous/README.md)
- [N4同时全覆盖](N=4/200Hz/M0_M1_M2_M3/Full_coverage_all_modules/README.md)
- [全部18条索引](run_index.csv) / [完整通过12条](dynamic_analysis_selected.csv) / [全部批次诊断统计](dynamic_diagnostic_statistics.csv)

原metadata/图中的zero_load可能是误选值；实际条件按用户确认记录在索引中，原始文件不改。当前没有新固件N3动态和独立小面积动态批次。n=3是同一设置的连续时间重复。
''')
doc(DATA/'DELTA/Dynamic_load/N=1/200Hz/M1/Large_area/README.md','''# M1 大面积动态：两个批次分别保留

| 批次 | 位置 | 主窗独立结论 | 用途 |
|---|---|---|---|
| 04:06开始的原批次 | Repeat_1～3 | 三条均CHECK | 诊断证据 |
| 05:04开始的后续批次 | Batch_20260907_050453_154588/Repeat_1～3 | 三条均PASS | 完整动态性能批次 |

原批次共有12次序号回退至ESKF序号2、两次前跳，未查明原因。后续通过不覆盖这些错误，也不等于故障永久消除。两个批次不合并成六次无错重复。

原批次USB为0.433820±0.019034 Mbit/s（仅诊断），后续批次为0.452052±0.007582 Mbit/s。每批n=3是连续时间窗口；固定主窗10–40 s，所有ESKF计入字节量。原批次metadata为large_area/both，后续误选zero_load由用户确认大面积动态；具体力和动作节奏未量化。

[后续批次说明](Batch_20260907_050453_154588/README.md) / [全部六条索引](run_index.csv) / [选定动态三条](dynamic_analysis_selected.csv) / [两批诊断统计](all_runs_diagnostic_statistics.csv)。

原始六类测量文件和原图不改；path_map.csv覆盖两批36个测量文件。原primary_matrix.csv为空表是此前旧批次的零载/主矩阵视图，不用于选择新动态结果；当前动态选择以dynamic_analysis_selected.csv为准。
''')
change='''## 2026-09-07 - 最后N4同时全覆盖核验、15条动态分类与最终数据总结

- 固定新增N4三条060147_020562、060227_053987、060307_083182；用户确认四模块同时全覆盖按下。独立主窗R1 PASS、R2/R3 CHECK。R2/R3各缺4个外层编号、各7次跨ESKF模块内前跳，R2另有一个40 B有效包四槽未更新。CRC、布局/K、base及raw/log对照正常，后续ESKD可应用；保留异常，不归因于SCK或ESKF本身。
- N4三段含CHECK诊断统计：196.749261±2.206474 Hz、1674.366648±55.065612 B、2.634962±0.067917 Mbit/s。有效ESKF384/有效内帧70832；外包含任意ESKF比例另列。40 B空更新包保留，字节账按实际内帧数求和；完整三连录不选入无错性能子集。
- 分类所有15条待整理记录：M1大面积后续、按压释放、rolling、N2同时大面积、N4同时全覆盖。原失败目录不覆盖；140个已有文件（90个原始测量文件）、144509120 B全部搬迁前后SHA-256一致。标签纠正在派生索引，原summary/图/状态保持。
- 总索引111条=FULL48+DELTA零载45+动态18，主窗现有检查合格105、CHECK6。零载primary仍90条，完整通过动态12条另列，analysis_selected共102条；原FULL两条补充PASS及N4单段PASS保留，不按帧率拼组。root路径映射666条，未分类时间戳目录0；FULL/DELTA零载视图和旧96条索引已有字段保持。
- 新增analysis/20260907_final_data_review/FINAL_SUMMARY_CN.md、evidence_review、分类计划/映射/哈希验证；更新root、DELTA、Dynamic_load和各新条件说明。分类前catalog已备份。本次只整理数据与总结，未替换论文PDF或改动固件。

'''
changelog=BASE/'docs/CHANGELOG.md'
text=changelog.read_text(encoding='utf-8-sig')
if change.splitlines()[0] not in text:
    heading,rest=text.split('\n',1)
    updated=heading+'\n\n'+change+rest.lstrip()
    doc(HERE/'CHANGELOG.updated.md',updated)
    try:
        doc(changelog,updated)
    except PermissionError:
        print('Changelog requires a separately authorized copy from CHANGELOG.updated.md; other documents saved.')
print('Published final summary, N4 review, data guides, and changelog.')
