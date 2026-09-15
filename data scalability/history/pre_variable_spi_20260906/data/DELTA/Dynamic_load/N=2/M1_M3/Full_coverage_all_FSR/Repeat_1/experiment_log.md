# Data Scalability Experiment 20260901_220515

## 记录内容

- 端口：`COM9`；波特率：`2000000`。
- 活动模块：M1, M3。
- 模块数量 N：2。
- 目标扫描频率：200 Hz。
- 负载情况：M1、M3 的全部 4 个 FSR 同时全覆盖按压。
- 负载流程：30 s 内同时对 M1 和 M3 的 FSR1、FSR2 进行全覆盖按压。
- 记录开始时选择的算法：`FULL`；实际观测算法见下方。
- 本次记录时长：30.01 s（目标 30 s）。
- 记录 USB 接收到的原始 MUL1 字节流。
- 从按钮触发后的下一个完整 MUL1 开始计时；记录每个候选 MUL1 包的开始时间、原始数据偏移、序号、长度、CRC、解析结果、模块状态和算法。
- 首个 MUL1 开始时间：2026-09-01T22:05:15.784+01:00。
- 观测到的算法：DELTA, DELTA_SYNC。
- 其中 `DELTA_SYNC` 同步帧共 77 个，普通 `DELTA` 帧共 5844 个。

## 结果

- 结论：**PASS: no recorded transport/parser/cache error**
- 候选包：468501；有效包：468501。
- 完整 MUL1 数量：5921。
- 记录字节：5170844 B；平均 USB 数据率：172296.67 B/s (1.378373 Mbit/s)；平均候选包率：197.29 Hz。
- CRC 错误：外层 0，内层 0。
- 序号间断：0；推断丢帧：0。
- 重复帧：0；乱序帧：0。
- 协议格式错误：0；Delta 基础序号失配：0。

## 输出文件

- 原始数据：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Dynamic_load\N=2\M1_M3\Full_coverage_all_FSR\Repeat_1\mul1_raw.bin`
- 逐包记录：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Dynamic_load\N=2\M1_M3\Full_coverage_all_FSR\Repeat_1\packet_log.csv`
- 机器可读总结：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Dynamic_load\N=2\M1_M3\Full_coverage_all_FSR\Repeat_1\summary.json`
