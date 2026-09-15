# Data Scalability Experiment 20260901_211445

## 记录内容

- 端口：`COM9`；波特率：`2000000`。
- 活动模块：M1。
- 模块数量 N：1。
- 目标扫描频率：200 Hz。
- 负载情况：小面积动态负载（3 × 1.6 cm 矩形）。
- 负载流程：0–5 s 静止；5–20 s 使用 3 × 1.6 cm 矩形分别对 FSR1、FSR2 按压各 5 次；20–30 s 使用同样小面积同时对 FSR1、FSR2 按压 5 次。
- 记录开始时选择的算法：`FULL`；实际观测算法见下方。
- 本次记录时长：30.01 s（目标 30 s）。
- 记录 USB 接收到的原始 MUL1 字节流。
- 从按钮触发后的下一个完整 MUL1 开始计时；记录每个候选 MUL1 包的开始时间、原始数据偏移、序号、长度、CRC、解析结果、模块状态和算法。
- 首个 MUL1 开始时间：2026-09-01T21:14:45.324+01:00。
- 观测到的算法：DELTA, DELTA_SYNC。

## 结果

- 结论：**CHECK REQUIRED: one or more transport/parser/cache counters are non-zero**
- 候选包：387296；有效包：387295。
- 完整 MUL1 数量：6009。
- 记录字节：1668618 B；平均 USB 数据率：55609.62 B/s (0.444877 Mbit/s)；平均候选包率：200.26 Hz。
- CRC 错误：外层 0，内层 0。
- 序号间断：0；推断丢帧：0。
- 重复帧：0；乱序帧：0。
- 协议格式错误：0；Delta 基础序号失配：1。

## 输出文件

- 原始数据：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Dynamic_load\M1\Small_area_3x1.6cm\Repeat_3\mul1_raw.bin`
- 逐包记录：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Dynamic_load\M1\Small_area_3x1.6cm\Repeat_3\packet_log.csv`
- 机器可读总结：`D:\study\programming\ESKIN\E-SKIN\docs\Final\data scalability\data\DELTA\Dynamic_load\M1\Small_area_3x1.6cm\Repeat_3\summary.json`
