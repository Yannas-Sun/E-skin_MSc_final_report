from pathlib import Path
import csv
import os

HERE=Path(__file__).resolve().parent
DATA=HERE.parents[1]/'data'
GROUP=DATA/'DELTA/Dynamic_load/N=1/200Hz/M1/Large_area'

def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def link(path,folder):return Path(os.path.relpath(path,folder)).as_posix()

rows=read_csv(HERE/'run_index.csv')
body=['# M1 大面积动态加载：三次记录已分类，均待复核','',
      '**原记录器主窗口：3 PASS；独立模块序号检查：3 CHECK。暂不纳入正式性能主矩阵。**','',
      '条件：DELTA，M1槽位，N=1，200 Hz目标，SPI本地设置10 MHz，阈值8；元数据为large_area、both（两层）。同一批次连续三段，每段40 s、前10 s保留、主窗约30 s。面积数值、实际力、动作节奏未记录，不代填。','',
      '| Repeat | run_id | 原主窗状态 | 独立检查 | 平均包长 B | USB Mbit/s |',
      '|---|---|---|---|---:|---:|']
for r in rows:
    body.append(f"| [Repeat {r['repeat']}](Repeat_{r['repeat']}/) | {r['run_id']} | {r['main_status']} | CHECK | {float(r['main_Lmean_B']):.3f} | {float(r['main_packet_Mbit_s']):.6f} |")
body += ['',
    'Repeat 1出现1次、Repeat 2出现11次模块内序号回退到ESKF序号2；Repeat 3出现4724→4728→4730，两次前跳合计4个未观测序号。全部14次事件位于主窗口。外层USB序号连续、内外CRC和DELTA base链正常，不等于模块序号连续。',
    '', '反复回到序号2提示重新初始化/复位等可能性，尚未确定原因。第三次异常对应桥端126 ms间隔，不能将所有变化归为PC缓冲，也不能直接断言SCK不稳定或丢失了四次物理扫描。',
    '', '原summary、experiment_log及图标题仍保留录制时的PASS；这不覆盖新增独立序号检查。当前索引main_eligible=False、primary_matrix_selected=False，独立原因另列，不改写原始测量状态。',
    '', '**仅作诊断的描述统计**（全部三段等权，样本SD；n=3时间重复、1个batch）：USB 0.433820 ± 0.019034 Mbit/s；平均包长272.234655 ± 11.242027 B；普通ESKD K=70.668405 ± 5.597340；ESKF总比例0.842627% ± 0.171190个百分点。此n不代表三次独立装配/独立加载。',
    '', f"[完整独立审计]({link(HERE/'raw_audit_CN.md',GROUP)}) / [逐次索引](run_index.csv) / [诊断统计](all_runs_diagnostic_statistics.csv)",
    '', '[原文件映射](path_map.csv)记录18个测量文件；[派生文件映射](derived_path_map.csv)记录6张PNG和3份plot_status。全部27文件搬迁前后哈希一致。run_id、batch_id、Repeat、图及原文件内容和嵌入旧路径均保留。',
    '', 'primary_matrix.csv和group_statistics.csv目前只有表头，没有合格的本条件主分析记录。待核查模块重新初始化/序号前跳原因后，再决定补测。']
(GROUP/'README.md').write_text('\n'.join(body)+'\n',encoding='utf-8')
(DATA/'DELTA/Dynamic_load/README.md').write_text('''# DELTA 动态负载数据

已分类一个条件的三条记录：[N=1 / M1 / 大面积 / 双层 / 200 Hz](N=1/200Hz/M1/Large_area/README.md)。

三条原记录器主窗均PASS，但独立模块内序号检查均为CHECK，当前合格主矩阵记录数为0。原始数据与图保留，诊断统计包含全部异常；不以帧率或K挑选时段。

[全部记录](run_index.csv) / [诊断统计](all_runs_diagnostic_statistics.csv) / [原文件映射](path_map.csv)。其余动态条件未因本批采集而标为完成。
''',encoding='utf-8')
(DATA/'DELTA/README.md').write_text('''# DELTA 数据

当前48条：45条零负载主窗口通过，另3条大面积动态记录因独立模块内序号异常待复核。

- [零负载15组合、45条主记录](Zero_load/README.md)
- [动态负载：M1大面积双层三条待复核](Dynamic_load/README.md)
- [全部48条索引](run_index.csv) / [正式主矩阵45条](primary_matrix.csv) / [合格组合统计](group_statistics.csv)

索引同时保留原记录器main_status与independent_raw_audit、main_eligible。动态三条原main_status=PASS不代表独立序号检查通过；已明确排除正式主矩阵。加载条件须按condition区分。
''',encoding='utf-8')
old=(HERE/'before_catalog/root/README.md').read_text(encoding='utf-8')
retained=old[old.index('# 已保留的 FULL 实验详录'):]
head='''# 当前 Data 实验数据

**FULL与DELTA零负载主矩阵均已齐：各15组合×3段，共90条。新增三条M1大面积动态数据已分类，但独立模块序号检查待复核。**

| 模式/条件 | 已采记录 | 原记录器主PASS / CHECK | 独立待复核 | 正式主矩阵 |
|---|---:|---:|---:|---:|
| FULL零载 | 48 | 47 / 1 | 1 | 45 |
| DELTA零载 | 45 | 45 / 0 | 0 | 45 |
| DELTA大面积动态 | 3 | 3 / 0 | 3 | 0 |
| 合计 | 96 | 95 / 1 | 4 | 90 |

- [新增动态三条分类与异常说明](DELTA/Dynamic_load/N=1/200Hz/M1/Large_area/README.md)
- [DELTA零载全部组合](DELTA/Zero_load/README.md) / [FULL零载结果](FULL/README.md)
- [全部96条索引](run_index.csv) / [正式主矩阵90条](primary_matrix.csv) / [30个合格配置统计](group_statistics.csv)
- [全部记录诊断统计](all_runs_diagnostic_statistics.csv)：保留动态三条独立CHECK的数值。
- [576个原始测量文件路径与哈希](path_map.csv)；本次另有9个派生绘图文件随记录一起搬迁，见本次分类映射。

模式与condition均须过滤。动态三条发现12次内序号回退至2和两次前跳；原summary以及图片中的主PASS保留，但索引main_eligible和primary_matrix_selected均为False。不以三条较低包率选择性删点，也不混入零载平均。

三连录为同一设置的时间重复，不是独立装配Block。原FULL失败、补测批次选择和零载专用CSV均保持原样。只有原main_status不足以筛选当前性能数据，应同时使用main_eligible或明确的primary_matrix.csv。

分类证据与更新器位于[本次审计目录](../analysis/20260907_delta_large_area_review/)。旧快照脚本可能只含旧记录，不应直接覆盖当前总索引。SPI波形、其他动态条件及故障恢复仍需分别验证。

以下为保留的FULL阶段详录，其中数字仅指FULL。

'''
(DATA/'README.md').write_text(head+retained,encoding='utf-8')
print('Updated data, DELTA, Dynamic_load and Large_area README files.')
