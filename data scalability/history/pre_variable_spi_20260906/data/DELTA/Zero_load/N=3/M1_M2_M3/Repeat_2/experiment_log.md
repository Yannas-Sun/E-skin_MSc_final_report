# Data Scalability Experiment 20260905_191911

## 记录内容

- 端口：`COM9`；波特率：`2000000`。
- 活动模块：M1, M2, M3。
- 模块数量 N：3。
- 目标扫描频率：200 Hz。
- 负载情况：无负载（Zero load）。
- 记录开始时选择的算法：`FULL`；实际观测算法见下方。
- 本次记录时长：30.00 s（目标 30 s）。
- 记录 USB 接收到的原始 MUL1 字节流。
- 从按钮触发后的下一个完整 MUL1 开始计时；记录每个候选 MUL1 包的开始时间、原始数据偏移、序号、长度、CRC、解析结果、模块状态和算法。
- 首个 MUL1 开始时间：2026-09-05T19:19:11.674+01:00。
- 观测到的算法：DELTA, DELTA_SYNC。

## 结果

- 结论：**PASS: no recorded transport/parser/cache error**
- 候选包：423087；有效包：423087。
- 完整 MUL1 数量：6007。
- 记录字节：3441428 B；平均 USB 数据率：114699.99 B/s (0.917600 Mbit/s)；平均候选包率：200.21 Hz。
- CRC 错误：外层 0，内层 0。
- 序号间断：0；推断丢帧：0。
- 重复帧：0；乱序帧：0。
- 协议格式错误：0；Delta 基础序号失配：0。

## 输出文件

- 原始数据：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Zero_load\N=3\M1_M2_M3\Repeat_2\mul1_raw.bin`
- 逐包记录：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Zero_load\N=3\M1_M2_M3\Repeat_2\packet_log.csv`
- 机器可读总结：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Zero_load\N=3\M1_M2_M3\Repeat_2\summary.json`
