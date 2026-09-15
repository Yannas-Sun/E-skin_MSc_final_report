# Data Scalability Experiment 20260901_192407

## 记录内容

- 端口：`COM9`；波特率：`2000000`。
- 活动模块：M0。
- 模块数量 N：1。
- 目标扫描频率：200 Hz。
- 算法：DELTA。
- 负载情况：无负载（手动添加；当前记录未采集力值）。
- 本次记录时长：30.00 s（目标 30 s）。
- 记录 USB 接收到的原始 MUL1 字节流。
- 从按钮触发后的下一个完整 MUL1 开始计时；记录每个候选 MUL1 包的开始时间、原始数据偏移、序号、长度、CRC、解析结果、模块状态和算法。
- 首个 MUL1 开始时间：2026-09-01T19:24:07.964+01:00。
- 观测到的算法：DELTA, DELTA_SYNC。

## 结果

- 结论：**PASS: no recorded transport/parser/cache error**
- 候选包：15418；有效包：15418。
- 完整 MUL1 数量：6006。
- 记录字节：1076736 B；平均 USB 数据率：35886.96 B/s (0.287096 Mbit/s)；平均候选包率：200.18 Hz。
- CRC 错误：外层 0，内层 0。
- 序号间断：0；推断丢帧：0。
- 重复帧：0；乱序帧：0。
- 协议格式错误：0；Delta 基础序号失配：0。

## 输出文件

- 原始数据：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Zero_load\N=1\M0\Repeat_1\mul1_raw.bin`
- 逐包记录：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Zero_load\N=1\M0\Repeat_1\packet_log.csv`
- 机器可读总结：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Zero_load\N=1\M0\Repeat_1\summary.json`
