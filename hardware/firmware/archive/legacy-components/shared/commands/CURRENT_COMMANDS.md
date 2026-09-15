# 当前命令入口（2026-09-04）

本目录是 Windows 构建、烧录、上传和启动 GUI 的唯一入口。当前四模块链路只使用
`active/four-module-full-scan/`；旧脚本主体和实验版本保留在 `original/`、
`archive/` 或 `research/`，不属于当前四模块部署。

同一 COM 口一次只能被一个程序占用；上传或启动 GUI 前关闭旧 GUI、串口监视器
和其他串口程序。

## 当前四模块完整链路

| 操作 | 命令 | 结果 |
|---|---|---|
| 上传 Teensy、启动 MUL1 GUI | `flash_scalablity_four_module.cmd COM9 [default-scan-hz]` | 默认 `200 Hz`；读取最多四个已烧录 STM32；不烧录 STM32 |
| 构建/烧录活动版 STM32 | `flash_active_four_module_stm32.cmd [probe-uid] [swd-speed]` | 默认 `1M`；通信异常时可用 `100k` 或 `10k`；四个模块分别重复 |
| 清空活动版 STM32 | `erase_active_four_module_stm32.cmd [probe-uid] [swd-speed]` | 整片擦除；默认 `1M`，通信异常时可用 `100k` 或 `10k` |
| 只上传 Teensy | `upload_scalablity_four_module.cmd COM9 [default-scan-hz]` | 默认 `200 Hz`；可设 `0..1000 Hz`，该值在 Teensy 复位后保留 |
| 只打开 GUI | `start_scalablity_four_module.cmd COM9` | 启动四模块双 FSR `MUL1` 解析器 |
| 直接抓取 USB 原始数据 | `dump_usb_mul1.cmd COM9 10 2000000` | 保存并显示当前 `MUL1 v2` 二进制包 |

Teensy 上传后通过串口发送以下命令；命令由 Teensy 放入每次 Host SPI 事务的前 16 B，并转发给四个 STM32：

```text
MODE FULL
MODE DELTA
MODE SPATIAL
SCAN_HZ 200       # 0 表示不设定目标频率，按硬件最大速度运行
RESYNC DELTA      # parser 发现 Delta 缓存断链时自动使用
RESYNC SPATIAL    # parser 发现 Spatial 缓存断链时自动使用
```

当前有效 STM32 固件只扫描两个 16×16 FSR，输出 ESK v4。DELTA 使用两个 32 B 掩码和置位单元的 16-bit 值，不发送 `changed_count` 或 `ESK0`；每个 Host SPI 事务固定读取 1044 B。Teensy 输出 MUL1 v2，module block 按实际逻辑帧长度可变，PC 端负责 Delta/Spatial 缓存恢复。当前活动代码已恢复为上一版固定 Host SPI 和控制命令 v2 实现。

上传参数设置的是编译进 Teensy 的启动默认值；GUI 或串口 `SCAN_HZ` 设置的是本次
运行的临时值。临时值在 Teensy 复位后恢复为上传时指定的默认值。
| 只烧录完整 STM32 | `original\flash_combined.cmd` | 烧录一个 `combined-system` STM32，之后需手动复位 |

`flash_combined_pair.cmd` 只用于**单模块**组合链路：一个 STM32、一个 Teensy
bridge 和一个单模块 GUI。它不能替代四模块部署。

## 数据可扩展性

| 操作 | 命令 |
|---|---|
| 构建/烧录 STM32 编码器 | `flash_data_scalability.cmd FULL\|DELTA\|SPATIAL` |
| 上传指定模块 Teensy bridge | `upload_data_scalability.cmd COM9 0 FULL\|DELTA\|SPATIAL` |
| STM32 + Teensy 成对部署 | `flash_data_scalability_pair.cmd COM9 0 FULL\|DELTA\|SPATIAL` |
| 启动数据可扩展性 GUI | `start_data_scalability_monitor.cmd COM9 all 2000000 0` |

对应 GUI 与校准工具位于
[`docs/Final/Calibration scalability`](../../../../../docs/Final/Calibration%20scalability/)。

## 扫描率研究

| 操作 | 命令 |
|---|---|
| 内部时钟 + EOC，改变 MUX 等待 | `flash_internal_eoc_mux_pair.cmd COM9 1 100` |
| 内部时钟 FIFO/DMA | `flash_internal_fifo_dma_pair.cmd COM9 1 37 0` |
| 33 B 时序复刻 | `flash_combined_sclk33_experiment.cmd COM9 safe2p5 all` |
| ACC 速率基准 | `flash_acc_rate_benchmark.cmd hr1344\|lp5376` |

这些实验会替换 STM32 上当前运行的固件；完成后按脚本打印的恢复命令操作。

## 单项诊断

| 目标 | 命令 |
|---|---|
| FSR1 完整 16×16 热图 | `flash_fsr1_pair.cmd COM9` |
| FSR2 完整 16×16 热图 | `flash_fsr2_pair.cmd COM9` |
| Host SPI `0x55` 链路 | `flash_spi_pattern_test.cmd COM9` |
| Teensy 自检 | `flash_teensy_self_test.cmd COM9` |
| 单模块槽位选择 | `flash_scalablity_test.cmd COM9 0 all` |
| ACC 阵列 / GPIO / SPI 排障 | `flash_acc_array.cmd`、`flash_acc_spi_test.cmd`、`flash_acc_*_slow.cmd` |

固定工具链：STM32G474CETx、DAPLink `LU_2022_8888`、Teensy FQBN
`teensy:avr:teensy41` 和 Arduino CLI
`D:\study\programming\ArduinoCLI\arduino-cli.exe`。
