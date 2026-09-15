# 稳定内部时钟 + EOC 的 MUX 等待时间扫点

## 测试范围

- Module：1
- Teensy：COM9
- 每个点：8 s，无载荷
- MAX11633：内部转换时钟，setup `0x64`
- 扫描命令：`0xF8`
- EOC：两个 ADC 均完成后才读取 FIFO
- FIFO 数据读取：10 MHz SPI、32 B DMA
- 唯一变化量：外部 MUX 等待时间 `FSR_MUX_SETTLE_US`

## 结果

| MUX 等待 | 状态 | 解析错误 | 序号错误 | USB 输出 | 完整双 FSR 扫描 | FSR1 原始范围 | FSR2 原始范围 |
| ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 us | EOC_QUALIFIED | 0 | 0 | 239.410 Hz | 269.760 Hz | 0..694 | 0..614 |
| 75 us | EOC_QUALIFIED | 0 | 0 | 241.435 Hz | 272.331 Hz | 0..692 | 0..496 |
| 50 us | EOC_QUALIFIED | 0 | 0 | 242.940 Hz | 274.123 Hz | 0..690 | 0..593 |
| 25 us | EOC_QUALIFIED | 0 | 0 | 244.249 Hz | 275.938 Hz | 0..702 | 0..587 |
| 10 us | EOC_QUALIFIED | 0 | 0 | 244.875 Hz | 276.702 Hz | 0..696 | 0..544 |
| **0 us** | **EOC_QUALIFIED** | **0** | **0** | **245.872 Hz** | **277.932 Hz** | **0..699** | **0..579** |

## 判定

`0 us` 是本次无载荷数字扫点中最低的 EOC 合格点。相对 `100 us`，完整双 FSR
扫描提高约 `3.03%`，USB 输出提高约 `2.70%`。这只是数字时序结果；无载荷条件
不能确认模拟 MUX 的建立时间、满压力响应或相邻行串扰。

稳定默认配置没有被替换，Module 1 测试结束后已恢复为 `100 us`。

对应原始采集文件：

- `20260828_215822_internal_fifo_gap0_mux100.json`
- `20260828_215843_internal_fifo_gap0_mux75.json`
- `20260828_215905_internal_fifo_gap0_mux50.json`
- `20260828_215926_internal_fifo_gap0_mux25.json`
- `20260828_215947_internal_fifo_gap0_mux10.json`
- `20260828_220025_internal_fifo_gap0_mux0.json`
