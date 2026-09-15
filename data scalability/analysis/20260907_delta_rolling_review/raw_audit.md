# Rolling 三条 DELTA 记录：独立原始协议审计

固定记录：20260907_053858_001637、20260907_053938_027960、20260907_054018_056649。原始目录未移动或分类，GUI与原始summary未修改。

记录元数据均为zero_load；用户明确说明实际为rolling。派生分析保留recorded_condition=zero_load，并记录actual_condition=rolling与用户说明，不改写原始summary，也不补写未记录的力值、滚动物尺寸、路线或速度。

完整扫描24,051个MUL1候选、24,051个有效模块内帧，并逐项核对96,204条模块CSV。共28个原始/记录生成文件前后SHA-256一致：True。

|窗口|候选MUL1|有效MUL1|ESKD|ESKF|初始无锚点ESKD|模块序号不连续|
|---|---:|---:|---:|---:|---:|---:|
|full_run|24051|24051|23931|120|539|0|
|initial|6018|6018|5988|30|539|0|
|main|18033|18033|17943|90|0|0|

|Repeat|原主窗口状态|独立协议结论|主窗K_D|主窗q_ESKF|主窗平均包B|主窗PC包率Hz|
|---|---|---|---:|---:|---:|---:|
|1|PASS|NO DETECTED PROTOCOL ANOMALY|108.566054|0.00499168|344.840266|200.327872|
|2|PASS|NO DETECTED PROTOCOL ANOMALY|118.640027|0.00499085|364.887040|200.343414|
|3|PASS|NO DETECTED PROTOCOL ANOMALY|117.907054|0.00499002|363.427811|200.395985|

跨ESKD与ESKF统一检查模块sequence，共发现0次不连续。有效ESKF建立新基线不会使本审计跳过sequence检查；此项独立检查覆盖原GUI的检查盲点，原GUI状态保持不变。

## CRC、缓存和文件边界

- 20260907_053858_001637：raw/log/summary差异={}；外CRC坏候选=0；外层序号事件=0；base不连续=0；目标缺更新=0；锚点后未应用=0。
  开始边界=[{"packet_sequence": 485359, "prefix_bytes": 1, "suffix_bytes": 135, "evidence": "inferred_single_magic_byte_not_recorded", "verified": true, "errors": [], "event_errors": [], "previous_run_id": null}]；未分配区=[{"offset": 2347419, "bytes": 1, "kind": "trailing"}]。
- 20260907_053938_027960：raw/log/summary差异={}；外CRC坏候选=0；外层序号事件=0；base不连续=0；目标缺更新=0；锚点后未应用=0。
  开始边界=[{"packet_sequence": 493372, "prefix_bytes": 1, "suffix_bytes": 393, "evidence": "actual_previous_raw_tail", "verified": true, "errors": [], "event_errors": [], "previous_run_id": "20260907_053858_001637"}]；未分配区=[{"offset": 2700163, "bytes": 1, "kind": "trailing"}]。
- 20260907_054018_056649：raw/log/summary差异={}；外CRC坏候选=0；外层序号事件=0；base不连续=0；目标缺更新=0；锚点后未应用=0。
  开始边界=[{"packet_sequence": 501392, "prefix_bytes": 1, "suffix_bytes": 125, "evidence": "actual_previous_raw_tail", "verified": true, "errors": [], "event_errors": [], "previous_run_id": "20260907_053938_027960"}]；未分配区=[]。

初始未锚定ESKD表示文件尚未包含基线，不证明传输丢帧；开始边界包不混入完整包数、K或q。实际前一文件尾部拼接与仅补magic单字节的推断在JSON中分别标注。

q=全部有效ESKF/(ESKF+ESKD)，K_D仅由普通ESKD两层mask计数。ESKF触发原因没有独立事件字段，不能由ESKF或其出现时刻确诊硬件重启、供电原因或丢失物理扫描。序号跳变仅表明记录中的编号不连续。

PC包完成时间决定初始/主窗口，桥host_ms是桥端时间字段；两者都不是直接SCK波形测量。三次连续录制是同一setup的时间重复。复现：`python -B -X utf8 raw_audit.py`。
