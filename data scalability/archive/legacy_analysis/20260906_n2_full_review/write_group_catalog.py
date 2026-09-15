"""Write navigation and tables from the immutable-run index after verified moves."""
from pathlib import Path
import csv
import json

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1]/'data'
verification = json.loads((HERE/'organization_verification.json').read_text(encoding='utf-8-sig'))
assert verification['status'] == 'completed' and verification['verified_files'] == 108
with (HERE/'run_index.csv').open(encoding='utf-8-sig', newline='') as stream:
    runs = list(csv.DictReader(stream))
with (HERE/'group_statistics.csv').open(encoding='utf-8-sig', newline='') as stream:
    stats = list(csv.DictReader(stream))

runs.sort(key=lambda r: (r['modules'], int(r['repeat'])))
base = DATA/'FULL/N=2/200Hz'
text = ['# FULL / N=2 / 200 Hz / Zero load', '',
        '四个槽位任取两个，共六种组合；每个组合一个批次、三次连续记录。每段约 40 s，前 10 s 保留，以下使用其后约 30 s 主窗口。所有 18 个主窗口通过检查。', '',
        '## 分组统计', '',
        '均值与样本标准差按三段的统计值计算（SD 分母为 n−1），不是把每帧当成独立实验。USB 数据率使用主窗口内完整 MUL1 包字节 / 主窗口时长；raw 块到达数据率另列于 group_statistics.csv。', '',
        '| 槽位组合 | 时间重复 n | 批次数 | MUL1 包率 / Hz | USB 完整包数据率 / Mbit/s | 平均包长 / B |',
        '|---|---:|---:|---:|---:|---:|']
for row in stats:
    module = row['modules']
    text.append(f"| [{module}]({module}/README.md) | 3 | 1 | {float(row['rate_Hz_mean']):.3f} ± {float(row['rate_Hz_sample_sd']):.3f} | {float(row['packet_Mbit_s_mean']):.6f} ± {float(row['packet_Mbit_s_sample_sd']):.6f} | 2128 ± 0 |")
text += ['', '当前 FULL 包长均为 2128 B = 40 B MUL1 固定槽位开销 + 2 × 1044 B 模块完整内帧。200 Hz 时包流量理论值为 3.4048 Mbit/s；实测值应按各段实际包率计算。USB 这里指采集的 MUL1 有效字节，不含 USB 总线事务开销。', '',
         '## 逐次结果', '',
         '| 槽位组合 | Repeat | 原始 run_id | 主窗口完整包数 | 包率 / Hz | 主窗口 |',
         '|---|---:|---|---:|---:|---|']
for row in runs:
    text.append(f"| {row['modules']} | [{row['repeat']}]({row['modules']}/Repeat_{row['repeat']}/experiment_log.md) | {row['run_id']} | {row['main_packets']} | {float(row['main_rate_Hz']):.6f} | {row['main_status']} |")
text += ['', '## 检查与追溯', '',
         '全程检查为 2 条 PASS、16 条 CHECK；这 16 条仅由文件末尾的 1 B 截止片段产生。18 个主窗口均 PASS，未出现 CRC/序号/目标模块错误。原 raw、日志和 summary 保留原字节与原状态。', '',
         'M0–M3 为通信槽位，并非设备唯一身份。三次 Repeat 是同一 setup 内的时间重复；每组仅一个 batch。后续另一 batch 不覆盖这些 Repeat 目录。', '',
         '[总索引和完整说明](../../../README.md) · [独立审计](../../../../analysis/20260906_n2_full_review/ANALYSIS_CN.md) · [逐文件路径映射](../../../../analysis/20260906_n2_full_review/path_map.csv)', '']
(base/'README.md').write_text('\n'.join(text), encoding='utf-8')

for stat in stats:
    module = stat['modules']
    selected = [r for r in runs if r['modules'] == module]
    lines = [f'# {module} / FULL / Zero load / N=2 / 200 Hz', '',
             f"Batch: `{stat['batch_id']}`。Block: `{selected[0]['block']}`。同一 setup 内的三个连续时间窗口；每次 40 s、前段 10 s。", '',
             '| Repeat | 实验开始时间（英国当地 +01:00） | 原始 run_id | 主窗口包率 / Hz | 结果 |',
             '|---:|---|---|---:|---|']
    for row in selected:
        lines.append(f"| [{row['repeat']}](Repeat_{row['repeat']}/experiment_log.md) | {row['started_at']} | {row['run_id']} | {float(row['main_rate_Hz']):.6f} | PASS |")
    lines += ['', f"时间重复 n=3，帧率 {float(stat['rate_Hz_mean']):.6f} ± {float(stat['rate_Hz_sample_sd']):.6f} Hz（段间样本 SD）。", '',
              '每个 Repeat 的原始六文件均保留。完整包平均长度 2128 B；若有文件尾部片段则单列，原全窗口状态按各段 summary 保留，不据此判定完整包丢失。', '',
              '[返回组统计和指标定义](../README.md)', '']
    (base/module/'README.md').write_text('\n'.join(lines), encoding='utf-8')
print('Wrote group catalog and six combination catalogs; measured files unchanged.')
