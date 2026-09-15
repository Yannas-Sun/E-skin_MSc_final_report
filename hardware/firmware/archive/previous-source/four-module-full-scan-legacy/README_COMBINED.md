# E-SKIN combined STM32 firmware (historical notes)

> The active implementation is now documented in
> [`README_FSR_ONLY.md`](README_FSR_ONLY.md). This file describes the former
> FSR + ACC `ESK1` build and is retained only for historical comparison.

This STM32G474 application acquires FSR1, FSR2, and nine LIS2DH12 positions,
packs one fixed 1188-byte `ESK1` record, and serves it to a Teensy 4.1 through
SPI3 slave full-duplex DMA.

## Current experimental configuration

| Item | Active value |
|---|---:|
| STM32 SYSCLK / HCLK | 80 MHz |
| APB1 / APB2 | 80 MHz / 80 MHz |
| ADC SPI1 / ACC SPI2 | 10 MHz / 10 MHz |
| Host SPI3 | slave, Mode 0; Teensy supplies 10 MHz SCK |
| MUX settling | 100 us; addresses 1..15 overlap previous FIFO reads |
| FSR work per frame | all 16 shared MUX addresses for FSR1 + FSR2 |
| ADC scheduling | ADC1 and ADC2 conversions overlap; FIFO reads are sequential |
| ACC configuration | `CTRL_REG1=0x97` (1.344 kHz normal mode); all positions read each frame |
| Protocol | v2; IEEE CRC32 present every 32 frames |
| Host transfer | two STM32 frame buffers; SPI3 full-duplex DMA |
| Validated complete-cycle rate | 238.475/s for 30 s |

The true acceptance unit is one fresh dual-FSR 16x16 scan, one read of all
nine ACC positions, packing, and one Host SPI transfer. The 30-second result
had 6,916/6,916 accepted transactions, zero magic/header/sequence/sampled-CRC/
USB-short/NSS-release errors, and 3.123% CRC coverage.

This is an experimental update, not the last stable release. The pushed stable
snapshot is commit `5468ec8`: it transports 700.181 packets/s by updating only
one FSR MUX address per packet, giving 43.76 fresh full scans/s. See
`docs/updates/2026-08-11-full-scan-700hz/PROGRESS_UPDATE.md` for the distinction,
all five new attempts, timings, and the hardware path required for 700 fresh
scans/s.

## Acquisition pipeline

For the first MUX address, firmware waits the full 100 us settle interval. It
then starts ADC1 and ADC2 before waiting for either EOC, so their internal
16-channel conversion phases overlap. After both conversions complete, the
next MUX address begins settling while SPI1 sequentially reads the two current
32-byte FIFOs. DOUT remains shared, so the two ADC chip selects are never low
at the same time.

FSR matrices are contiguous little-endian `uint16_t` arrays. Packing uses two
block copies instead of 512 element-wise calls. The measured final stage times
are approximately 3,721 us for dual-FSR acquisition, 267 us for ACC reads,
106 us for packing, and 193 us only on a CRC-sampled frame.

## Protocol v2

The 1188-byte layout remains `ESK1`, version, flags, length, sequence,
timestamp, FSR1, FSR2, nine 16-byte ACC records, and a four-byte trailer.

- Flag `0x04`: ACC records are present.
- Flag `0x08`: rolling FSR mode; clear in the current full-scan build.
- Flag `0x10`: the trailer contains IEEE CRC32.
- Sequence multiples of 32 set `0x10` and carry CRC32.
- Other v2 frames clear `0x10` and carry a zero trailer.

The first ACC record's reserved bytes report the last MUX address and the
number of addresses freshly scanned; the current build reports 16. Reserved
fields in ACC records 1..5 report FSR, ACC, pack, DMA-wait, and CRC times in
microseconds.

Periodic CRC is a performance experiment. It does not protect the other 31
payloads, and old v1-only receivers will reject v2. A production revision
should use STM32 hardware CRC and restore per-frame protection.

## Data mappings

- FSR1: `frame[MUX1][ADC1]`
- FSR2: reverse MUX2 selection and transpose ADC2 into the logical display map
- ACC: CD74HC154 decoder indices 0..8 map to physical ACC1..ACC9

One ACC receives a `WHO_AM_I` health check every 100 ms, covering all nine in
about 0.9 s. Invalid all-zero/all-`0xFF` axis payloads are rejected, and a
device is reinitialised when its health-check slot fails.

## Build and flash

Connect DAPLink SWDIO, SWCLK, nRESET, GND and target reference voltage. Build
and flash the current STM32 Release firmware with:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_combined.cmd"
```

Build/flash STM32, compile/upload the matching Teensy bridge, and open the GUI:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_combined_pair.cmd" COM9
```

The script builds under `D:\study\programming\builds\ESKIN_COMBINED_SYSTEM`
and flashes with pyOCD. The additional FSR2 PB1/PB2/PB11 GPIO setup is
performed by `CombinedAcquisition_Init()`. CubeMX regeneration can replace
`main.c`, so retain its USER changes and `combined_acquisition.c`.
