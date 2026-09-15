"""Publish current DELTA zero-load summaries from frozen, audited derived CSVs."""
from collections import defaultdict
from pathlib import Path
import csv
import json
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / 'data'
FINAL = ROOT.parent

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))

def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + '\n', encoding='utf-8')

def ms(row, name, digits=3):
    mean, sd = float(row[name+'_mean']), row[name+'_sample_sd']
    return f'{mean:.{digits}f} ± {float(sd):.{digits}f}' if sd != '' else f'{mean:.{digits}f} ± —'

def main():
    index = read_csv(HERE/'run_index.csv')
    combinations = read_csv(HERE/'stats_combinations_pass.csv')
    by_n = read_csv(HERE/'stats_by_n_balanced.csv')
    comparisons = {r['modules']:r for r in read_csv(HERE/'stats_full_comparison.csv')}
    raw = json.loads((HERE/'raw_audit.json').read_text(encoding='utf-8'))
    assert len(raw['runs']) == 45 and all(not r['cross_check_errors'] for r in raw['runs'])
    for r in raw['runs']:
        assert not r['anomalies'] and not r['raw_bad_outer_candidates']
        assert not r['raw_valid_unlogged_packets']
        assert all(e['event'] == 'initial_anchor' and e['affected_after_anchor_frames'] == 0
                   for e in r['cache_events'])
    verified = json.loads((HERE/'organization_verification.json').read_text(encoding='utf-8-sig'))
    assert verified['verified_files'] == 270
    ntable = ['| N | 组合数 | 时间段数 n | USB完整包流量 / Mbit/s | 普通 ESKD K | 平均包长 / B | 等帧率USB字节减少 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for r in by_n:
        n=int(r['N']); full_bytes=40+1044*n
        ntable.append(f'| {n} | {r["combination_n"]} | {r["temporal_window_n"]} | '
            f'{float(r["packet_Mbit_s_mean"]):.4f} ± {float(r["packet_Mbit_s_across_run_sample_sd"]):.4f} | '
            f'{float(r["K_ESKD_mean"]):.2f} ± {float(r["K_ESKD_across_run_sample_sd"]):.2f} | '
            f'{float(r["Lmean_B_mean"]):.2f} | {100*(1-float(r["Lmean_B_mean"])/full_bytes):.2f}% |')
    group_head = ['| N | 组合 | PC包率 / Hz | 平均包长 / B | USB / Mbit/s | 普通 K | 总 ESKF / % | 等帧率USB字节减少 |',
                  '|---|---|---:|---:|---:|---:|---:|---:|']
    group_rows=[]
    for r in combinations:
        c=comparisons[r['modules']]
        group_rows.append(f'| {r["N"]} | {r["modules"].replace("_", "+")} | {ms(r,"rate_Hz")} | '
          f'{ms(r,"Lmean_B")} | {ms(r,"packet_Mbit_s",4)} | {ms(r,"K_ESKD",2)} | '
          f'{ms(r,"q_ESKF_pct",6)} | {float(c["equal_rate_USB_reduction_pct_mean"]):.2f}% |')
    common = '''每组合三段是同一次设置下的连续时间重复，n=3、batch_n=1；不是三次独立重新接线或装配。
均值 ± SD 使用段间样本标准差，不把数千帧当作独立实验重复。各段统一保留40秒原记录，主分析使用10秒之后的实际约30秒。
PC包率与流量按包完成时间窗口统计，不能直接当作ADC扫描频率或SPI边沿频率。ESKF已计入平均包长和实测流量，不能再重复加算。'''
    summary = '# DELTA 零负载 N=1～4：整理与核验总结\n\n'
    summary += '**全部15种组合完成，每组合三段，共45条主窗口PASS；本轮零负载主矩阵已齐，无需为补齐组合或重复次数再测。**\n\n'
    summary += common+'\n\n## 覆盖与主要结果\n\n'+'\n'.join(ntable)+'\n\n'
    summary += ('此表在每个N内等权汇总各组合，因每组合都是三段，也等于所有段的等权均值。'
      '表中SD为跨该N全部段的样本SD，包含组合差异；每组合的三次段间SD见下表。N=4仅有一种组合。'
      'USB减少按同一实际帧率的 `1−L_DELTA/L_FULL` 计算，FULL包长分别1084、2128、3172、4216 B；'
      '它将帧率变化与字节压缩收益分开。两种模式分时采集，并非同时配对测量。\n\n')
    summary += '## 每组合结果\n\n每行n=3、batch_n=1；保留全部45条，没有按帧率或K筛选。\n\n'+'\n'.join(group_head+group_rows)+'\n\n'
    summary += '''## 完整性检查

- 独立解析全程360,824个完整有效MUL1及769,607个有效模块内帧，并逐行核对packet_log、module_log和summary。
- 主窗口270,412个MUL1、576,926次预期模块更新，包含574,042个ESKD和2,884个ESKF；有效更新覆盖率100%。
- 主窗口内外CRC、布局/长度错误、内外序号缺口、重复/倒序、DELTA基线断裂、缺失目标模块更新、诊断载荷、内部未分配字节均未检出；三个阶段分别保留计数。
- 45条full_run仍保持原CHECK REQUIRED。记录从运行中的DELTA流截取，文件起点尚无本文件ESKF基线，累计10,540个初始无锚点ESKD；不是已证实的实时GUI丢帧。96个“记录×活跃模块”的文件基线都在首秒内建立，主窗口前已完成。
- 30条文件末端各有1 B边界碎片；35个跨文件起点包另记账。其中20个用前段真实尾字节核对，15个只补单字节标记的分析属于推断，不视为完整原始证据。边界字节不回填或删改。
- 锚点后未应用更新与由已观测错误导致的FULL恢复事件均为0。本轮没有故障恢复样本，不能由此估计发生故障后的恢复时长或宣称物理扫描绝不丢失。

## ESKF与K：能回答什么

总ESKF比例约0.5%，各段为0.4901%～0.5162%；分母是有效模块内帧而非USB外包。marker不含触发原因，因此不把这些计数全部命名为“周期FULL”，也不把高于0.5%的部分直接判为异常恢复。

普通ESKD的K只由掩码计算；ESKF不伪记为真实K=480。新的N=1/2/3/4普通K均值为8.26、8.64、9.10、10.04。
本轮的跨N变化比历史记录温和，但不能据此证明K为常数或将变化归因于固件。记录跨组合、时间和接线条件，尚无ABBA顺序控制。
同一槽位标签的结果也并不一致：M2的普通K大约21～25，主要来自FSR1；M1多数明显较低。需要区分模块/层差异与模块数量效应。
M0～M3是CS/IRQ槽位，记录没有唯一板卡身份；跨组合物理板一致性仍依赖实际接线约定。逐槽位、逐层结果单独保存。

## 时间戳的限制

PC相邻包完成时间最大间隔为4.0409秒；对应两包序号连续、Teensy host_ms仅差5 ms。
所有主窗口相邻桥端时间戳间隔为3～7 ms。PC存在批量处理和调度停顿，不能称为SPI时钟不稳定。
主窗口PC包率范围199.3419～204.0041 Hz；按同一批包的桥端首尾时间估计约200.0733～200.4065 Hz。
例如最高PC包率记录在约30秒接收窗口中包含源端约30.549秒跨度的数据。这是窗口与缓冲效应，不是扫描频率已升至204 Hz。
本次保留这些记录及其实际接收统计，不事后挑选“更稳定”的窗口。USB流量图与字节模型检验应同时报告Lmean、PC窗口时长及时间戳来源。

## 整理与可追溯性

45个目录已分类为 `DELTA/Zero_load/N=<N>/200Hz/<槽位组合>/Repeat_1..3/`。
270个原文件合计306,090,893 B，搬迁前后SHA256逐文件一致；原run_id、batch_id、Repeat、采集时间、状态及嵌入旧路径均保留。
当前data总索引93条（FULL48＋DELTA45），其中92条主PASS、1条先前FULL失败。
用于主矩阵的90条为FULL45＋DELTA45，30种“模式×组合”配置；原FULL补测选择和失败证据完整保留。
本地固件与记录器哈希一致，属于本地文件来源记录，不是设备Flash读回。原deployment_confirmed字段不补造。
旧固件历史数据仍独立归档；本次没有更新论文PDF或将历史结果改名为新版实测。

## 文件入口

- [整理后的DELTA零载数据](../../data/DELTA/Zero_load/README.md)
- [45条run索引](run_index.csv) / [15组合统计](stats_combinations_pass.csv) / [N汇总](stats_by_n_balanced.csv)
- [匹配FULL比较](stats_full_comparison.csv) / [逐槽位跨N活动量](module_activity_by_slot_n.csv)
- [独立原始流审计](raw_audit_CN.md) / [覆盖与时间戳复核](coverage_review.md) / [详细统计说明](statistical_note.md)
- [270文件路径和哈希](path_map.csv) / [搬迁验证](organization_verification.json) / [总目录验证](catalog_validation.json)

本轮完成的是FULL/DELTA零载主矩阵。DELTA动态负载、独立恢复实验、SPI波形/时序和长时稳定性需分别按相应证据确认，不能由零载PASS代替。
'''
    put(HERE/'ANALYSIS_CN.md', summary)
    overview = '# DELTA 零负载：全部组合已完成\n\n'
    overview += '**N=1～4的15组合、每组3次，共45条主窗口PASS。**\n\n'+common+'\n\n'
    overview += '\n'.join(ntable)+'\n\n表中SD跨该N所有时间段，包含组合差异；每组合统计均为n=3。\n\n'
    overview += '\n'.join(group_head+group_rows)+'\n\n'
    overview += '''主窗口CRC、序号、缺模块更新和缓存链错误均未检出。全程CHECK保留：每个文件初始ESKD未在文件内获得基线，30条另有尾部1 B；主窗口已建立基线，不能把边界CHECK等同主窗口故障。

PC完成时间最大停顿4.0409 s，对应桥端仅5 ms且序号连续；PC包率变化不能证明SPI时钟不稳定。普通K和总ESKF占比分开统计，周期/其他触发原因仍不可区分。

- [完整核验总结](../../../analysis/20260907_delta_zero_review/ANALYSIS_CN.md)
- [主矩阵45条](primary_matrix.csv) / [15组合均值±SD](group_statistics.csv) / [路径和哈希](path_map.csv)
- [N=1](N=1/200Hz/README.md) / [N=2](N=2/200Hz/README.md) / [N=3](N=3/200Hz/README.md) / [N=4](N=4/200Hz/README.md)
- [与FULL比较](stats_full_comparison.csv) / [跨N逐槽位K](module_activity_by_slot_n.csv)

三次为同一设置下连续时间重复；原记录与元数据不修改。ESKF成本已经包含在流量中。模块ID为槽位，本地固件哈希不是设备回读。
'''
    put(DATA/'DELTA/Zero_load/README.md', overview)
    put(DATA/'DELTA/README.md', '# DELTA 数据\n\n[零负载全部15组合：45条主窗口PASS](Zero_load/README.md)。\n\n本目录仅整理已核验的零载矩阵，动态条件不以零载结果代替。\n\n[模式主矩阵](primary_matrix.csv) / [模式索引](run_index.csv) / [组合统计](group_statistics.csv)')
    for n in range(1,5):
        selected=[r for r in combinations if int(r['N'])==n]
        nrows=[group_rows[combinations.index(r)] for r in selected]
        body=f'# N={n} DELTA 零负载\n\n{len(selected)}种组合，{3*len(selected)}条主窗口PASS；每组合n=3、batch_n=1。\n\n'+common+'\n\n'
        body+='\n'.join(group_head+nrows)+'\n\n'+ '\n'.join(f'- [{r["modules"]}]({r["modules"]}/README.md)' for r in selected)
        body+='\n\n[返回DELTA零载总览](../../README.md)\n'
        put(DATA/f'DELTA/Zero_load/N={n}/200Hz/README.md',body)
        for r in selected:
            records=[i for i in index if i['modules']==r['modules']]
            groupbody=f'# {r["modules"]}：DELTA 零载\n\nN={n}，目标200 Hz，每段40 s，前10 s不进入主分析。三次主窗口PASS。\n\n'+common+'\n\n'
            groupbody+='\n'.join(group_head+[group_rows[combinations.index(r)]])+'\n\n'
            groupbody+='| Repeat | run_id | 主窗口状态 | 全程状态 |\n|---|---|---|---|\n'
            for i in sorted(records,key=lambda i:int(i['repeat'])):
                groupbody+=f'| [Repeat {i["repeat"]}](Repeat_{i["repeat"]}/summary.json) | {i["run_id"]} | {i["main_status"]} | {i["full_status"]} |\n'
            groupbody+='\n全程CHECK源于文件初始DELTA基线尚未建立；部分记录还含尾部边界碎片。原状态与文件内容保留，主窗口已建立基线。\n\n[返回N组合列表](../README.md)\n'
            put(DATA/f'DELTA/Zero_load/N={n}/200Hz/{r["modules"]}/README.md',groupbody)
    # Retain the detailed FULL description and its failure/retest discussion,
    # explicitly label it as the preserved FULL section under the new overview.
    original=(HERE/'before_catalog/README.md').read_text(encoding='utf-8-sig')
    original=original.replace('# 当前 Data 实验数据','# 已保留的 FULL 实验详录',1)
    for name in ['run_index.csv','primary_matrix.csv','group_statistics.csv',
                 'all_pass_group_statistics.csv','all_runs_diagnostic_statistics.csv',
                 'batch_statistics.csv','path_map.csv']:
        original=original.replace(f']({name})',f'](FULL/{name})')
    prefix='''# 当前 Data 实验数据

**FULL 与 DELTA 零负载主矩阵均已齐：各15组合×3次，共90条主窗口PASS。** 每组的三次为同一次设置下连续时间重复。

| 模式 | 已采记录 | 主窗口PASS / CHECK | 主矩阵 | 组合 |
|---|---:|---:|---:|---:|
| FULL零载 | 48 | 47 / 1 | 45 | 15 |
| DELTA零载 | 45 | 45 / 0 | 45 | 15 |
| 合计 | 93 | 92 / 1 | 90 | 30种模式×组合 |

- [DELTA零载：整理结果与各组合](DELTA/Zero_load/README.md)
- [本轮DELTA审计总结](../analysis/20260907_delta_zero_review/ANALYSIS_CN.md)
- [FULL零载结果](FULL/README.md)
- [当前全部93条索引](run_index.csv) / [主矩阵90条](primary_matrix.csv) / [30配置统计](group_statistics.csv)
- [558个原文件路径与哈希](path_map.csv)，其中本轮DELTA270文件搬迁前后全部一致。

总CSV已显式区分mode，读取时应按FULL/DELTA过滤；需要纯FULL输入可使用FULL/primary_matrix.csv，需要纯DELTA输入可使用DELTA/Zero_load/primary_matrix.csv。
历史审计目录的旧快照脚本不应直接覆盖当前总索引；本轮合并器为analysis/20260907_delta_zero_review/build_catalogs.py。
原FULL失败和补测选择仍保留。DELTA全程CHECK来自初始未锚定ESKD及部分尾部边界，与主窗口PASS分开解释。
PC批量接收与调度会影响完成时间戳，不能据此认定SPI时钟不稳定。动态、SPI波形及恢复实验单独核验。

以下保留FULL阶段的详细说明；其中数字指FULL范围。当前根目录索引已经扩展为上面的93/90条，FULL专用视图保存在FULL/目录。

'''
    put(DATA/'README.md', prefix+original+'\n')
    print('Wrote DELTA overview, 4 N summaries, 15 combination summaries, analysis and current data overview.')

if __name__ == '__main__':
    main()
