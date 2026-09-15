# E-SKIN Scalability Evaluation

本文按当前活动固件计算：每个模块只传输两个 `16×16` FSR 阵列，ACC 不参与采集、封装或 USB 传输。

## 当前研究范围

当前以 `FULL` 作为基准，仅研究 `DELTA` 能否降低数据传输量、缓解带宽限制并改善数据可拓展性。数据精度只作为基本可用性约束，不深入研究 Delta 算法本身。

本章只考虑数据传输量、带宽限制等数据可拓展性指标。元件功耗将在下一章 `Power Scalability` 中系统研究；功耗不是当前的首要限制，暂不考虑通过软件算法减少功耗。

## DATA

### 1.1 Data Throughput Model

本节只计算当前协议在 **200 Hz、完整传输（Full transmission）** 条件下的数据吞吐量。

#### 1.1.1 当前协议尺寸

| 协议层 | 组成 | 单帧尺寸 |
|---|---|---:|
| `ESKF` | 16 B header + 512 B FSR1 + 512 B FSR2 + 4 B inner trailer | **1044 B** |
| `module block` | 活动模块：1 B `module_id` + 1 B `status` + 2 B `frame_length` + 1044 B `ESKF`；非活动模块只保留 4 B 元数据 | 活动模块 **1048 B**；非活动模块 **4 B** |
| `MUL1` | 20 B header + 4 个固定 `module block` header + `N × 1044 B ESKF` + 4 B outer CRC | `40 + 1044N` B，`N` 为活动模块数 |

当前完整四模块协议为：

$$
L_{\mathrm{MUL1}}(4)=20+4\times4+4\times1044+4=4216\ \mathrm{B/frame}
$$

当前 `MUL1` 始终保留四个模块位置的 4 B 元数据；当实验只启用部分模块时，非活动模块不携带 `ESKF` 数据。因此，按活动模块数 `N` 绘制 FULL 理论参考线时使用：

$$
L_{\mathrm{FULL,plot}}(N)=40+1044N\ \mathrm{B/frame},\qquad 0\le N\le4
$$

#### 1.1.2 通用 USB 传输量公式

设：

- $f$ 为完整 round 频率，单位为 `frame/s`；
- $N$ 为模块数；
- $L_{\mathrm{ESKF}}=1044$ B，为单个完整 `ESKF` 的字节数；
- $L_{\mathrm{meta}}=4$ B，为每个固定 `module block` 的元数据字节数；
- $L_{\mathrm{MUL1,H}}=20$ B，为 `MUL1` header 的字节数；
- $L_{\mathrm{MUL1,T}}=4$ B，为 `MUL1` outer CRC 的字节数。

每个完整 `MUL1` 包通过 USB 发送到 PC，因此 USB 的传输量为：

$$
B_{\mathrm{USB/frame}}(N)
 =20+4L_{\mathrm{meta}}+NL_{\mathrm{ESKF}}+4
 =40+1044N\ \mathrm{B/frame}
$$

$$
R_{\mathrm{USB}}(N)
=(40+1044N)f\ \mathrm{B/s}
$$

如需换算为比特率：

$$
R_{\mathrm{USB,bit}}(N)=8(40+1044N)f\ \mathrm{bit/s}
$$

#### 1.1.3 当前四模块在 200 Hz 下的 USB 传输量

当前四模块的完整 `MUL1` 为 4216 B/frame，因此：

$$
R_{\mathrm{USB}}(4)=4216\times200
=843200\ \mathrm{B/s}
$$

换算为比特率：

$$
R_{\mathrm{USB,bit}}(4)=843200\times8
=6.7456\ \mathrm{Mbit/s}
$$

因此，四模块在 200 Hz、完整传输模式下的 USB 传输量为：

$$
\boxed{843200\ \mathrm{B/s}=6.7456\ \mathrm{Mbit/s}}
$$

### 1.2 Delta Transmission Model

本节只计算 **Delta 模式**下的协议长度和 USB 传输量。Delta 仍由 STM32 完整扫描两个 `16×16` FSR 阵列，但连续帧只发送掩码置位单元的当前值。

#### 1.2.1 Delta 协议层与帧类型

Delta 只使用完整同步帧 `ESKF` 和掩码增量帧 `ESKD`。每个 FSR 阵列各使用一个 32 B 掩码，因此双 FSR 共使用 64 B 掩码；不再发送 `changed_count`，PC 直接从掩码统计置位数量。

<table>
<thead>
<tr><th>协议层</th><th>帧类型</th><th>组成</th><th>单帧尺寸</th></tr>
</thead>
<tbody>
<tr>
<td rowspan="2"><code>ESK</code></td>
<td><code>ESKF</code></td>
<td>16 B ESK header + 512 B FSR1 + 512 B FSR2 + 4 B inner trailer</td>
<td><strong>1044 B</strong></td>
</tr>
<tr>
<td><code>ESKD</code></td>
<td>16 B ESK header + 32 B FSR1 mask + 32 B FSR2 mask + <code>2K</code> B values + 4 B inner trailer</td>
<td><strong>84 + 2K B</strong></td>
</tr>
<tr>
<td><code>module block</code></td>
<td>—</td>
<td>1 B <code>module_id</code> + 1 B <code>status</code> + 2 B <code>frame_length</code> + 1 个 Delta 帧</td>
<td><code>ESKF: 1048 B</code><br><code>ESKD: 88 + 2K B</code></td>
</tr>
<tr>
<td><code>MUL1</code></td>
<td>—</td>
<td>20 B header + <code>N × module block</code> + 4 B outer CRC</td>
<td><code>ESKF: 24 + 1048N B</code><br><code>ESKD: 24 + N(88 + 2K) B</code></td>
</tr>
</tbody>
</table>

掩码按 FSR1、FSR2 分开排列，均按 `row × 16 + column` 映射到 256 个 bit。掩码之后依次写入 FSR1 和 FSR2 的置位单元值，每个值 2 B，按行优先顺序排列。$K$ 只用于由掩码计算实际帧长，不参与帧类型选择；理论范围为 0–512，固定 1044 B Host SPI 槽位下最多容纳 480 个值。

Delta 复用 ESK 的 16 B header：

```text
frame_type | version/flags | seq | base_seq
```

其中 `seq` 是当前帧序号，`base_seq` 是当前掩码增量帧依赖的缓存序号。收到序号间断时，PC 停止应用增量并等待新的 `ESKF`。

#### 1.2.2 通用 USB 传输量公式

设：

- $N$ 为模块数；
- $f$ 为完整 round 频率；
- $p_F$、$p_D$ 分别为 `ESKF` 和 `ESKD` 的帧比例，且 $p_F+p_D=1$；
- $K_{avg}$ 为 `ESKD` 掩码中的平均置位单元数；
- $L_{block,H}=4$ B；
- $L_{MUL1,H}=20$ B；
- $L_{MUL1,T}=4$ B。

单个模块的平均 Delta 帧长度为：

$$
L_{D,avg}=p_F(1044)+p_D(84+2K_{avg})
$$

每个完整 `MUL1` 包的平均字节数为：

$$
B_{MUL1,D/frame}(N)=20+N(4+L_{D,avg})+4
=[24+N(4+L_{D,avg})]\ \mathrm{B/frame}
$$

USB 字节率为：

$$
R_{USB,D}(N)=[24+N(4+L_{D,avg})]f\ \mathrm{B/s}
$$

USB 比特率为：

$$
R_{USB,D,bit}(N)=8[24+N(4+L_{D,avg})]f\ \mathrm{bit/s}
$$

`frame_length` 使 Teensy 和 PC 能够跳过当前模块块，读取下一个模块；掩码使 PC 能够在没有 `changed_count` 的情况下确定值的数量和位置。

#### 1.2.3 当前四模块在 200 Hz 下的 USB 传输量

原完整传输方法的传输量为：

$$
R_{USB,full}(4)=4216\times200
=843200\ \mathrm{B/s}
$$

四个模块使用掩码 Delta 时：

$$
\begin{aligned}
R_{USB,Delta}(K)
&=[24+4(88+2K)]\times200\\
&=(75200+1600K)\ \mathrm{B/s},\quad 0\le K\le480
\end{aligned}
$$

$K=0$ 时仍发送两个全 0 掩码和 CRC，帧长为 84 B；$K=480$ 时 Delta 帧达到固定槽位上限，与完整传输相同。若掩码置位数超过 480，STM32 发送 `ESKF`，避免超出 1044 B Host SPI 槽位：

$$
R_{USB,Delta}(K)=843200\ \mathrm{B/s},\quad K>480
$$

换算为图中的 `Mbit/s`：

$$
R_{\mathrm{Mbit/s}}=R_{\mathrm{B/s}}\times\frac{8}{10^6}
$$

![四模块、200 Hz：完整传输与 Delta 传输量](../../Evaluation%20plan/E-SKIN_Delta_Throughput_Comparison.svg)

图中完整传输为 843200 B/s；掩码 Delta 从 $K=0$ 的 75200 B/s 线性增加，在 $K=480$ 达到完整传输量，超过槽位容量时回退 `ESKF`。

#### 1.2.4 Delta 的切换和重建规则

1. 首次运行、每隔约 1 s、模块重新连接或收到重同步请求时发送 `ESKF`，PC 用它建立完整缓存。
2. STM32 将满足 $|x_{current}-x_{previous}|>\Delta_{threshold}$ 的 FSR1/FSR2 单元对应 bit 置 1。
3. 每一帧都发送 `ESKD` 掩码；没有变化时发送全 0 掩码，不再切换到 `ESK0`。
4. PC 按掩码的 FSR1、FSR2 位图读取后续 16-bit 值，未置位单元保留上一帧缓存。
5. 如果置位单元超过 480，STM32 发送 `ESKF`；这只是固定 Host SPI 槽位的容量保护。

掩码 Delta 小于完整传输的条件为：

$$
84+2K<1044
$$

即 $K<480$ 时，Delta 的单个 ESKD 帧小于完整 `ESKF`；$K=480$ 时两者相等。

## EXPERIMENTS

本阶段的实验目标是判断 `DELTA` 是否能够支持更多模块或更高刷新率，而不是分析 Delta 算法内部的参数优化。

### 核心实验

| 实验 | 固定或改变的条件 | 主要采集数据 | 需要得到的结论 |
|---|---|---|---|
| `FULL` 基准 | `N=1–4`，先固定 200 Hz | USB 字节率、Mbit/s、实际 `MUL1` 帧率 | 完整传输随模块数增加的数据增长基线 |
| `FULL` 与 `DELTA` 可拓展性对比 | 相同 `N`、刷新率和压力场景；使用无压力、少量变化、正常变化和大面积变化 | 两种模式的 USB 字节率、数据减少比例、实际帧率、基本完整性 | `DELTA` 是否在不同模块数量和活动程度下减少带宽占用 |
| 扩展边界 | 在 `N=1–4` 下逐步提高目标刷新率 | 目标/实际帧率、USB 带宽、有效帧数 | 在相同带宽限制下，`DELTA` 是否支持更多模块或更高刷新率 |

每个核心条件建议运行 30 s，重复 3 次。主要比较 USB 传输量和有效刷新率；数据重建只检查是否能够正常恢复，不对 Delta 阈值和内部编码机制展开单独优化实验。

### 动态测试模块选择与已完成实验

无负载 DELTA 对比中，M1 的三次平均刷新率最高且最稳定，为 `200.450 Hz`；平均 USB 数据率为 `0.2881 Mbit/s`，平均 MUL1 长度为 `179.66 B`。因此，后续动态负载测试统一优先使用 M1，作为比较不同负载场景下 DELTA 数据传输表现的基准模块。该选择仅基于刷新率稳定性，不代表 M1 的传感器精度已经优于其他模块。

目前已完成 M1 单模块大面积动态负载测试 3 次：前 5 s 静止，随后 15 s 分别对 FSR1、FSR2 全覆盖按压各 5 次，最后 10 s 同时对两层全覆盖按压 5 次。三次平均 USB 数据率为 `0.5520 Mbit/s`，平均刷新率为 `199.765 Hz`。该结果用于验证变化量增加时 DELTA 的传输量变化；三次记录各有 1 次 Delta 基础序号失配，后续 FULL 对照和最终结论需保留该检查结果。

随后完成相同时间流程的小面积动态负载测试，使用 `3 × 1.6 cm` 矩形接触区域。三次平均 USB 数据率为 `0.4517 Mbit/s`，平均刷新率为 `200.301 Hz`，相较大面积测试低约 `18.2%`。该结果进一步表明，DELTA 的数据量会随实际变化区域扩大而增加；三次记录同样各有 1 次 Delta 基础序号失配。

随后完成 M1 单模块高频滚动动态负载测试：在 30 s 内使用一根棍子在两个 FSR 上来回滚动，制造持续的高频变化。该次记录得到 `6008` 个完整 MUL1，平均 USB 数据率为 `0.887710 Mbit/s`，平均 MUL1 长度为 `554.09 B`，平均刷新率为 `200.262 Hz`。普通 DELTA 帧长度为 `164–696 B`，另有 `30` 个 `DELTA_SYNC` 同步帧；外层/内层 CRC、序号间断、丢帧、重复帧、乱序帧、格式错误和 Delta 基线失配均为 `0`。该结果作为高频变化场景下的单模块数据量记录，后续可与 FULL 理论值及低频、低面积动态记录进行对比。

随后完成两模块大面积同时变化测试：活动模块为 M1、M3，两个模块的全部 4 个 FSR 同时进行全覆盖按压。30 s 内得到 `5921` 个完整 MUL1，平均 USB 数据率为 `1.378373 Mbit/s`，平均 MUL1 长度为 `873.31 B`，实际刷新率为 `197.292 Hz`。N=2 时 FULL 理论值为 `2128 B/frame`，200 Hz 下约为 `3.4048 Mbit/s`；本次 DELTA 平均传输量减少约 `59.5%`。所有 CRC、序号、丢帧、格式和 Delta 基线检查均为 `0`。

最后完成四模块大面积同时变化测试：M0–M3 的全部 8 个 FSR 同时进行全覆盖按压。30 s 内得到 `5841` 个完整 MUL1，平均 USB 数据率为 `3.347529 Mbit/s`，平均 MUL1 长度为 `2149.77 B`，实际刷新率为 `194.645 Hz`。N=4 时 FULL 理论值为 `4216 B/frame`，200 Hz 下约为 `6.7456 Mbit/s`；本次 DELTA 平均传输量减少约 `50.4%`。所有 CRC、序号、丢帧、格式和 Delta 基线检查均为 `0`。该结果补充了多模块大面积变化场景，说明即使接近 FULL 的高负载条件，DELTA 仍能降低平均 USB 传输量，但刷新率会出现一定下降。

### 基本检查

协议正确性、序号连续性、解析错误、丢帧、阈值敏感性和缓存恢复只作为运行前后的基本记录，不作为本阶段的主要实验方向。
