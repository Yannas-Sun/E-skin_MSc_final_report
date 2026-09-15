# N=2 FULL 新数据独立审计

固定 18 条已完成记录快照；实验开始时间 2026-09-06 23:22:05 至 23:47:51（英国当地 +01:00），末条约 23:48:31 结束。旧 12 条 N=1 是已知历史记录，不视为本轮新增未审计数据。仅本目录生成分析，不改变原始文件。

| 组合 | 时间重复 n | 主窗口帧率均值 ± 样本 SD / Hz | 完整包吞吐均值 ± SD / Mbit/s | 主/全窗口 PASS 条数 |
|---|---:|---:|---:|---:|
| M0+M1 | 3 | 200.074118 ± 0.016067 | 3.406062 ± 0.000274 | 3/0 |
| M0+M2 | 3 | 200.092789 ± 0.036402 | 3.406380 ± 0.000620 | 3/1 |
| M0+M3 | 3 | 200.150344 ± 0.016623 | 3.407359 ± 0.000283 | 3/1 |
| M1+M2 | 3 | 200.208530 ± 0.023024 | 3.408350 ± 0.000392 | 3/0 |
| M1+M3 | 3 | 200.397003 ± 0.028675 | 3.411559 ± 0.000488 | 3/0 |
| M2+M3 | 3 | 200.202033 ± 0.021590 | 3.408239 ± 0.000368 | 3/0 |

所有条件均为 FULL、N=2、zero_load，目标 200 Hz，每次录制 40 秒，保留前 10 秒；主窗口约 30 秒。均值/SD 以每段主窗口统计量为样本，n=3 是同一 setup 的连续时间重复，不能作为 3 个独立重新搭建 block。

独立检查 144,212 个完全落在 raw 内的 MUL1 包（主窗口 108,109），288,424 个有效 ESKF（主窗口 216,218），逐行核对 576,848 行 module_log。

完整包必须为 2128 B = 20 B 外头 + 4×4 B 槽描述符 + 2×1044 B ESKF + 4 B 外 CRC。普通 FULL 有效模块 flags 应为 0x13。脚本逐包检查内外 CRC、长度/版本/flags/mask、实际槽位和模式、MUL1 与 ESK 序号、packet_log 偏移/长度/序号，逐槽核对 module_log 状态、expected、有效性、payload、marker、mode、flags、序号、base、K 和时间窗口。另验证 raw SHA256、summary 包数和目标模块机会数。

独立异常（必须保留）：`{}`。

本次 18 段主窗口均可用。独立模块漏更新、CRC/序号/日志不一致均为 0；Session 和主窗口的 CRC、seq gaps、lost、重复、乱序、格式、base 错误增量全部为 0。全窗口 2 段 PASS，另 16 段只保留 1 B 尾部 M 的边界检查提示，无需因此重录；原始状态不修改。

逐段原状态与审计：
- `20260906_232205_264776`：完整包 8004 / 主包 6003；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_232245_299955`：完整包 8010 / 主包 6003；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_232325_329233`：完整包 8010 / 主包 6004；main=PASS，full=PASS（none）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=无。
- `20260906_232950_210894`：完整包 8006 / 主包 6004；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_233030_242504`：完整包 8011 / 主包 6005；main=PASS，full=PASS（none）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=无。
- `20260906_233110_283624`：完整包 8014 / 主包 6005；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_233400_039763`：完整包 8008 / 主包 6006；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_233440_083230`：完整包 8015 / 主包 6007；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_233520_115774`：完整包 8014 / 主包 6007；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_233935_041252`：完整包 8016 / 主包 6013；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_234015_080026`：完整包 8020 / 主包 6011；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_234055_124089`：完整包 8023 / 主包 6013；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_234339_617031`：完整包 8009 / 主包 6007；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_234419_667943`：完整包 8018 / 主包 6007；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_234459_699129`：完整包 8012 / 主包 6006；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_234631_872633`：完整包 8004 / 主包 6003；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_234711_905577`：完整包 8008 / 主包 6002；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。
- `20260906_234751_945640`：完整包 8010 / 主包 6003；main=PASS，full=CHECK REQUIRED（unassigned_raw_bytes_in_full_capture）；主窗理由=[]；MUL1/ESK序号异常=0/0；尾字节=4d。

本轮跨起点包 17 个，其中 11 个用前段真实 raw 尾字节 + 后段真实 raw 前缀验证；6 个每批首段只补推定 M 验证一致性。具体双层 CRC、序号连续性和来源见 JSON，不能把推定前缀表述为已记录字节。跨界包单列，未计入完整包率和 q。

可用性以独立异常、逐段主窗口和原始全窗口状态共同判断。仅末尾 1 字节 M 导致的全窗口检查提示属于录制结束边界，不能据此认定 CRC 错误或物理传输丢包；存在其他错误时必须另行复查，不覆盖原 summary。

本批覆盖 N=2 全部六种 FULL 零载组合；尚不能代替相同组合 DELTA 对照、N=3/4 或动态加载/K实验。M0–M3 是协议槽位，不提供唯一板卡身份。帧率分母是实际主窗口时长，完整包吞吐与 raw 按到达时间统计的吞吐是分开的字段。

新完成而未纳入记录：无（既有 N=1 不算新增）

迁移后原 summary 内历史 files 路径保持不变；可用父任务生成的 run_index.csv/path_map.csv 查新位置。本脚本按 summary.run_id 递归定位当前目录，不依赖历史绝对路径。复现：`python -B audit_records.py`。解码器复用同级 20260906_current_data_review/audit_records.py 的独立实现，不导入生产 GUI/recorder。
