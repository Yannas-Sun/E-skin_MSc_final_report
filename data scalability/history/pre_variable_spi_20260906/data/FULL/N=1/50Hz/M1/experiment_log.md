# Data Scalability Experiment N=1 / 50Hz / M1

## 记录内容

- 端口：`COM9`；波特率：`2000000`。
- 活动模块：M1。
- 模块数量 N：1。
- 目标扫描频率：50 Hz。
- 算法：FULL。
- 本次记录时长：30.00 s（目标 30 s）。
- 记录 USB 接收到的原始 MUL1 字节流。
- 从按钮触发后的下一个完整 MUL1 开始计时；记录每个候选 MUL1 包的开始时间、原始数据偏移、序号、长度、CRC、解析结果、模块状态和算法。
- 首个 MUL1 开始时间：2026-09-01T18:55:03.866+01:00。
- 观测到的算法：FULL。

## 结果

- 结论：**PASS: no recorded transport/parser/cache error**
- 候选包：7347；有效包：7347。
- 完整 MUL1 数量：1503。
- 记录字节：1629252 B；平均 USB 数据率：54302.19 B/s (0.434418 Mbit/s)；平均候选包率：50.09 Hz。
- CRC 错误：外层 0，内层 0。
- 序号间断：0；推断丢帧：0。
- 重复帧：0；乱序帧：0。
- 协议格式错误：0；Delta 基础序号失配：0。

## 输出文件

- 原始数据：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\FULL\N=1\50Hz\M1\mul1_raw.bin`
- 逐包记录：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\FULL\N=1\50Hz\M1\packet_log.csv`
- 机器可读总结：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\FULL\N=1\50Hz\M1\summary.json`
