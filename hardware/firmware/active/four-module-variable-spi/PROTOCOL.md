# Host SPI 变长传输与 USB 契约

## 1. 连接和事务

- Teensy 4.1 为 SPI master；每个 STM32 为 SPI3 slave。
- 10 MHz，mode 0，8-bit，MSB first。多字节字段使用 little-endian。
- 模块 0..3 的 Teensy CS：10、14、15、16；IRQ：2、3、4、5。
- STM32 将一帧编码到最大容量 1044 B 的缓冲区，保存其实际长度 L；按 L 启动
  一次 Tx/Rx DMA，再拉高 IRQ。两个缓冲区各自保存长度，重编码时同步更新长度。
- Teensy 等待 IRQ，拉低该模块 CS，先读 16 B ESK 头，同时在 MOSI 发出 16 B DSCM
  命令。验证头后，保持 CS 为低，继续读 L−16 B。STM32 DMA 在两次调用之间不重启。
- 完整帧总时钟数为 8L；16 B 帧头本来就在 L 中，不是额外开销。剩余 MOSI 字节为零。
- Teensy 读完后拉高 CS，验证掩码数量和 CRC，并按原规则放入 USB 队列。
  STM32 在 DMA 完成后处理收到的命令。模式改变或请求完整同步时重编码下一缓冲区。

```text
IRQ   ____/-----------------------------------\____
CS    ______\________________________________/_____
SCK          [16 B header]  [L - 16 B remainder]
MISO         [ESK header ]  [masks/values/CRC  ]
MOSI         [DSCM command] [zero filler       ]
```

示意图只表示事务关系；IRQ 下降由 DMA 完成回调触发，不要求和 CS 上升同一时刻。
STM32 可并行采集下一帧，但不会覆盖正在传输的缓冲区。

## 2. ESK v4 帧

两种帧共用 16 B 头：

| 偏移 | 长度/B | 字段 |
|---:|---:|---|
| 0 | 4 | ASCII `ESKF` 或 `ESKD` |
| 4 | 1 | version = 4 |
| 5 | 1 | flags：0x10 表示 CRC；0x20 表示 DELTA 模式；低四位为采集状态 |
| 6 | 2 | 帧总长度 L，包含 CRC |
| 8 | 4 | sequence |
| 12 | 4 | base_sequence；完整帧为 0xffffffff |

flags 的高两位保留为零。结尾 CRC32 IEEE 为 4 B little-endian，覆盖从 magic
开始到 CRC 前的所有字节。

**ESKF：1044 B。** 头后依次为 FSR1 的 256 个 uint16 和 FSR2 的 256 个 uint16，
均按编码器的行优先顺序输出，然后是 CRC。FULL 模式和 DELTA 的完整同步共用此帧；
后者带 0x20 flag。

**ESKD：84+2K B。** 头后是 FSR1 的 32 B 掩码、FSR2 的 32 B 掩码、K 个 uint16
当前值及 CRC。每个掩码的 bit i 对应 `row*16+column=i`，字节内最低位优先。
当前值先按 FSR1 的置位索引升序输出，再输出 FSR2。K 是两个掩码置位数之和。
无变化也发送 84 B 全零掩码帧。最大 DELTA K=480，超过则使用 ESKF。

变化判断仍为 `abs(current - previous) > delta_threshold`，默认阈值为 8。
为保持原始 USB 数据一致，本次不更改上一帧缓存更新方式、数值量化、采集映射或
重建语义。阈值内的微小变化仍受现有 DELTA 近似行为影响。

完整同步条件仍为缓存无效、距上次完整同步至少 1000 ms、显式重同步、或 K 超限。
Teensy 保留序号跳变、队列溢出和模块重连后的 DELTA 恢复机制。

## 3. DSCM v2 下行命令

命令与帧头同时交换，不另占 SPI 事务：

| 偏移 | 长度/B | 字段 |
|---:|---:|---|
| 0 | 4 | ASCII `DSCM` |
| 4 | 1 | version = 2 |
| 5 | 1 | mode：0 FULL；1 DELTA |
| 6 | 2 | delta_threshold |
| 8 | 2 | reserved = 0 |
| 10 | 2 | scan_rate_hz，0..1000 |
| 12 | 1 | bit 0：请求 DELTA 完整同步；其余位保留 |
| 13 | 3 | reserved = 0 |

PC 文本命令为 `MODE FULL`、`MODE DELTA`、`RESYNC DELTA`、`SCAN_HZ n`，以换行结束。
命令作用于后续采集/编码；正在发送的帧保持不变。

## 4. 异常长度和中途终止

Teensy 在仅收到头时检查 marker、版本、flags、范围和偶数长度；ESKF 必须为
1044 B，ESKD 必须在 84..1044 B。头非法则在 16 B 后释放 CS，不继续按不可信
长度读取，不将其当作有效数据。头合法后才读剩余数据，再核验掩码置位数量及 CRC。

若长度损坏成一个较小的合法值，STM32 会看到未完成 DMA 的 NSS 提前释放。
若损坏成更大的合法值，主机仍最多读取 1044 B，内层 CRC/掩码校验用于拒绝坏帧。
该协议不为帧头添加新 CRC，以保持原 ESK 字节格式。

STM32 在等待传输时检测 `NSS=高` 且 `0 < RX剩余数量 < 本帧长度`，作为部分事务
被主机终止的证据，降低 IRQ、取消 DMA，并走 SPI 重置恢复路径。此检查在并行的
下一帧采集结束后运行；极低扫描率下仍可能先等待现有扫描周期。DMA 尚未收到
任何字节时不会因空闲 NSS 高而误取消；两段读取之间 CS 低时也不会误取消。
等待传输阶段仍保留 1500 ms 超时保护。

## 5. USB MUL1 v2 保持不变

外层结构为 20 B 公共头、四个模块槽、4 B CRC。每个槽含：

| 元数据字段 | 长度/B | 用途 |
|---|---:|---|
| module_id | 1 | 表示来自哪个模块，0..3 |
| status | 1 | 更新/错误状态 |
| length | 2 | 此槽后面实际携带的字节数 |

其后仅复制 length 字节的 ESK 内帧。未更新的槽保留 4 B 元数据，通常长度为零；
诊断错误可携带原有的 16 B 帧头前缀。公共头、槽顺序、状态编码、外层序号、时间戳、
CRC 算法、USB 队列深度 4 及部分 USB 写入的处理方式均沿用原实现。

因此精确字节模型为：

```text
L_USB = 20 + 4*4 + sum(slot_length[m], m=0..3) + 4
      = 40 + sum(slot_length[m], m=0..3)
```

40 B 来源于固定四槽封装；不能随着实际在线模块数量而缩减。
若 N 个在线模块都提交 FULL、其余槽无诊断载荷，则 `L_USB=40+1044N`。
若 N 个模块都提交 ESKD，则 `L_USB=40+84N+2*sum(K_m)`。
完整同步帧和混合帧必须按实际槽长度相加。

令 q 为某模块实际输出中完整同步帧的比例，K_mean_D 为仅 ESKD 帧的平均 K：

```text
L_SPI_mean = q*1044 + (1-q)*(84 + 2*K_mean_D)
wire_time = 8*L_SPI / 10,000,000 seconds
```

上述时间仅计算 SCK 时钟，不含 IRQ 等待、CS 建立/保持、读取头后软件判断和 DMA
准备时间。K=27 的 ESKD 从原 1044 B 降至 138 B，纯时钟时间从 835.2 us 降至
110.4 us；相同有效帧在 USB 上的长度完全相同。
