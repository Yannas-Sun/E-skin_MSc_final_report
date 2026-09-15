# E-SKIN Progress Update — 31 July 2026

> **中文速览：** FSR 采集、STM32–Teensy 传输和 Heatmap 已稳定工作。主要硬件问题已定位为 FFC connector 和部分 FSR 本体。下一步是优化下拉电阻量程，并解决 ACC 的 MOSI/片选写入问题。

## Overall status

| Area | Status | Key result |
|---|---|---|
| STM32 build and SWD programming | Complete | Repeatable CMake/Ninja build and reliable 10 kHz under-reset flashing |
| STM32–Teensy–PC transport | Complete | Stable 515-byte frames at approximately 25 frame/s with zero sequence gaps |
| FSR1/FSR2 acquisition | Complete | 16 x 16 raw ADC scanning, correct physical orientation and separate firmware copies |
| Heatmap and recording | Complete | Calibration, raw-data saving, per-cell display and diagnostic test tools |
| FSR hardware faults | Identified | Connector fault repaired; remaining fixed rows traced to the FSR itself |
| ACC acquisition | In progress | Most devices return the correct ID, but configuration writes do not yet verify |
| ACC 3D GUI | Complete | Demo and live 16-device 3D vector display available |

## Main progress and lessons learned

| Problem observed | Root cause / how it was identified | Action taken | Result |
|---|---|---|---|
| STM32 programming was unreliable | SWD could not connect consistently at normal speed | Used DAPLink at 10 kHz with `under-reset` and explicit STM32G474 target | Firmware can now be programmed repeatably |
| Teensy initially received `0x00` or unstable SPI data | HOST connector contact and power-domain problems; static GPIO tests separated wiring from protocol | Resoldered the connector and avoided paralleling DAPLink and Teensy 3.3 V supplies | STM32–Teensy SPI link passed |
| Acquisition repeatedly dropped to approximately 1 frame/s | STM32 SPI3 RX FIFO was not drained; Teensy USB writes could also block when the PC reader closed | Changed STM32 to full-duplex `HAL_SPI_TransmitReceive()` and made Teensy USB output non-blocking | Stable approximately 25 frame/s, including after GUI reconnection |
| Pressure appeared on incorrect rows | Parser could mistake payload byte `0xA5` for a frame marker | Added three-frame, fixed-width, consecutive-sequence locking | Frame misalignment and false row mapping removed |
| Missing/unstable complete FSR lines | Readings changed with FFC contact while SPI sequence remained valid | Resoldered and replaced the FFC connector | Widespread intermittent fault resolved (**Stage 9**) |
| Several fixed FSR rows still failed after connector repair | Direct resistance tests remained abnormal while MUX, ADC, SPI, USB and GUI passed | Isolated the FSR layer from the electronics | Remaining fault attributed to the FSR material/assembly (**Stage 10**) |
| Heatmap axes did not initially match physical motion | FSR1 and FSR2 have different orientation | Verified movement direction physically and corrected transpose/direction independently | GUI now matches the real sensor layout |
| Calibration produced false unloaded pressure | Noise, drift, short capture time and invalid per-cell span | Added approximately 10-second captures, raw mode and per-cell validation | More stable calibration without hiding hardware faults |

> **关键结论：** 第九阶段是 FFC connector 接触不良；更换 connector 后，仍固定不工作的行被确认是 FSR 本体问题，而不是 STM32、Teensy 或 GUI。

## Current FSR result

- FSR1 and FSR2 can be scanned as raw 12-bit `0..4095` matrices.
- The full STM32 → Teensy → USB → Python chain operates at approximately 25 frame/s.
- Raw frames and calibration/test results can be saved into classified folders.
- Software can now distinguish transport faults, ADC/MUX faults, connector faults and FSR-layer faults.
- The current pressure response is very sensitive over a narrow range.

### Pull-down resistor decision

For the present divider:

\[
ADC=4095\frac{R_{PD}}{R_{FSR}+R_{PD}}
\]

If light pressure rapidly drives the ADC towards 4095, the pull-down resistor
should be reduced by one standard value. This will reduce excessive sensitivity,
delay saturation and extend the useful range towards higher pressure.

Recommended next comparison:

1. save raw no-load, medium-load and full-load data with the current resistor;
2. reduce the resistor by one step (for example, 10 kOhm to 4.7 kOhm if 10 kOhm is currently fitted);
3. repeat the same load test;
4. select the value that places the main working range approximately within ADC 1000–3500;
5. recalibrate only after the final resistor is selected.

> **中文辅助：** 轻轻按就接近 4095，应换更小的下拉电阻；始终接近 0，才需要更大的电阻。

## Current ACC result

- An independent 16-device ACC SPI test firmware has been built and flashed.
- Most decoder positions return the expected `WHO_AM_I=0x33`.
- ACC1 and ACC2 returned invalid identity values in the latest connected test.
- Expected configuration readback is `CTRL_REG1=0x57` and `CTRL_REG4=0x88`, but incorrect repeated patterns were received.
- Reducing ACC SPI from approximately 1 MHz to 62.5 kHz did not change the failure, so excessive clock speed is not the main cause.
- The 3D GUI is ready, but it currently shows crosses because the firmware correctly rejects configuration-failed XYZ values.

**Most likely remaining ACC fault:** the common STM32 `PB15/MOSI1` write path,
decoder/chip-select behaviour, or bus contention. The STM32–Teensy–PC transport
and GUI are not the current blocker.

> **中文辅助：** ACC 全部显示叉号是状态保护，不是 GUI 故障；下一步检查 MOSI 和片选。

## Next priorities

1. **FSR analogue range:** test a smaller pull-down resistor using controlled raw ADC captures.
2. **Recalibration:** capture new zero/full data only after the resistor and FSR assembly are final.
3. **ACC MOSI test:** toggle PB15 low/high slowly and measure at the STM32, connector and FPC endpoint.
4. **ACC chip-select test:** verify decoder enable/address inputs and confirm that only one `nCS` output is low.
5. **Mechanical FSR review:** inspect spacer alignment, electrode overlap, cut edges and failed-cell resistance.

## Demonstrable outcomes for the meeting

- Live 16 x 16 FSR Heatmap at approximately 25 frame/s.
- Raw FSR frame capture and per-cell inspection.
- FSR1/FSR2 switching with corrected orientation.
- ACC 3D GUI in synthetic demo mode.
- Clear evidence separating connector, protocol and sensor-material faults.

Detailed chronological evidence and commands remain in `docs/WORKFLOW.md`.
