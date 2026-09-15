# ACC maximum-rate hardware benchmark

Date: 2026-08-12

## Result

The isolated STM32 benchmark established two different limits that must not be
reported as one number:

| Configuration | Resolution | Nominal sensor ODR | Complete A1..A9 bus scans | Time per nine-slot scan | Fresh samples captured per online ACC |
|---|---:|---:|---:|---:|---:|
| `hr1344` (`CTRL1=0x97`, `CTRL4=0x88`) | 12-bit high resolution | 1.344 kHz | 4235.717/s | 236.088 us | 1244.917..1357.909/s |
| `lp5376` (`CTRL1=0x9F`, `CTRL4=0x80`) | 8-bit low power | 5.376 kHz | 4233.012/s | 236.238 us | 4233.012/s |
| `lp5376` independent repeat | 8-bit low power | 5.376 kHz | 4233.009/s | 236.238 us | 4233.009/s |

There were zero SPI errors in all recorded windows. The repeat differed by
only 0.003 complete scans/s. Therefore the measured maximum for a **complete
nine-slot ACC pass using the current HAL/GPIO implementation** is about
**4.233 kHz**. At that rate the 5.376 kHz sensor mode produces a new sample
before every bus visit, but some sensor samples occur between visits and are
not captured.

The 12-bit operating point remains limited by the sensor ODR, not the bus. Its
six online devices produced a mean 1312.246 fresh samples/s (median 1329.911,
range 1244.917..1357.909) while the STM32 polled each slot about 4236 times/s;
the extra polls were correctly counted as duplicates.

中文结论：如果保留 12-bit 高分辨率，在线 ACC 的实际新数据约为 1.3 kHz；
如果允许降为 8-bit 低功耗模式，当前代码可以稳定完成约 4.233 kHz 的九地址
轮询，且本次在线的 6 颗 ACC 每次访问都有新数据。4.233 kHz 是九个地址全部
访问一遍的频率，不是单个 SPI 字节频率，也不是 9/9 传感器功能通过。

## What was measured

The benchmark is isolated from FSR acquisition, Host SPI, Teensy USB and the
GUI. The STM32G474 runs at 160 MHz and its ACC SPI2 peripheral at the
LIS2DH12 documented maximum of 10 MHz. Every one-second window performs:

1. select decoder addresses A1 through A9 in order, including offline slots;
2. keep chip select low for one eight-byte transaction;
3. transmit `0xE7`, then seven dummy bytes;
4. receive `STATUS_REG` (`0x27`) followed by X/Y/Z (`0x28..0x2D`);
5. count `ZYXDA=1` as a newly generated physical sample;
6. publish the counters in SRAM and read them through SWD after the window.

This avoids treating repeated register reads as new physical samples. `BDU`
prevents split axis words, but it does not make faster polling create samples.

## Current hardware population

All nine decoder addresses were included in every timed pass, but only six
devices passed identity and configuration:

| ACC | Result |
|---:|---|
| 1, 2, 3, 4, 7, 8 | online; `WHO_AM_I=0x33`; register readback passed |
| 5 | offline; `WHO_AM_I=0x11` |
| 6, 9 | offline; `WHO_AM_I=0xFF` |

The online mask was `0x0CF`; the failed-init mask was `0x130`. Consequently,
the test proves the timing of a complete nine-address bus pass, but validates
real acceleration data for six physical devices. It must not be described as
a 9/9 sensor-function pass.

## Timing interpretation

One slot transfers 8 bytes or 64 clocks. At 10 MHz the pure wire time is
6.4 us/slot and 57.6 us for nine slots. The measured complete pass is about
236.2 us. The remaining approximately 178.6 us is decoder GPIO selection,
the two conservative 64-NOP guards, HAL transaction setup/polling and loop
overhead. This is the next optimisation target if more than 4.233 kHz is
required; raising SPI beyond 10 MHz is not the valid next step.

For the complete E-SKIN product, 700 ACC updates/s is comfortably inside both
tested modes. The deciding trade-off is resolution:

- keep `0x97/0x88` for 12-bit high-resolution data near 1.344 kHz ODR;
- use `0x9F/0x80` only when 8-bit resolution is acceptable and more than
  1.344 kHz of fresh data is required.

## Evidence and reproduction

Raw decoded snapshots:

- [`20260812_acc_rate_hr1344.json`](../../test_results/20260812_acc_rate_hr1344.json)
- [`20260812_231140_acc_rate_lp5376.json`](../../test_results/20260812_231140_acc_rate_lp5376.json)
- [`20260812_acc_rate_lp5376_repeat.json`](../../test_results/20260812_acc_rate_lp5376_repeat.json)

Benchmark source and reader:

- [`combined_acquisition_acc_rate.c`](../../../stm32/experiments/acc_rate_benchmark/combined_acquisition_acc_rate.c)
- [`README.md`](../../../stm32/experiments/acc_rate_benchmark/README.md)
- [`read_acc_rate_snapshot.py`](../../../tools/read_acc_rate_snapshot.py)

Commands:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_acc_rate_benchmark.cmd" hr1344
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_acc_rate_benchmark.cmd" lp5376
```

After measurement, restore the validated combined experiment without opening
a GUI:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\original\flash_combined_sclk33_experiment.cmd" refint7p5 I_ACCEPT_OUT_OF_SPEC_10MHZ
```

The register modes and 10 MHz SPI limit are defined by the official
[LIS2DH12 datasheet](https://www.st.com/resource/en/datasheet/lis2dh12.pdf).

## Post-test restoration

The STM32 was restored to the previously validated `refint7p5` combined
experiment. A five-second COM9 diagnostic then accepted 1757/1757 transfers
at 439.140 Hz with zero CRC, magic, header, sequence, USB-short or NSS-release
errors. The text evidence is
[`20260812_231744_post_acc_rate_restore.txt`](../../test_results/20260812_231744_post_acc_rate_restore.txt).
