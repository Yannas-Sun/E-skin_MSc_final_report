# Standalone FSR1 high-rate update — 2026-08-12

## Outcome

The standalone FSR1 test has been separated from the conservative shared FSR
bridge and rebuilt for maximum acquisition rate without switching the ADC to
the previously problematic external-clock reproduction mode.

The firmware and bridge compile and flash successfully. A 10-second hardware
capture reached **327.105 complete 16 x 16 frames/s** with zero sequence gaps,
zero invalid candidates, and zero discarded bytes.

## Bottleneck removed

The previous Teensy bridge used 100 kHz Host SPI plus 1 ms before CS, 1 ms
after CS, and 100 us after the frame. A 515-byte frame therefore required at
least:

```text
515 bytes * 8 / 100 kHz + 2.1 ms = 43.3 ms
```

This limited the complete link to about 23.1 frames/s regardless of ADC speed.
The dedicated FSR1 bridge now uses 10 MHz with 50 us IRQ settling, 10 us CS
setup, and 10 us CS hold:

```text
515 bytes * 8 / 10 MHz + 70 us = 482 us
```

The Host-link wire/timing ceiling is therefore about 2.07 kframes/s and is no
longer expected to dominate standalone FSR1 acquisition.

The first 10 MHz hardware run exposed a separate blocking-HAL limit: Teensy
received a valid frame, but STM32 SPI3 RX polling did not complete and waited
for the 1000 ms timeout, producing 0.998 FPS. SPI3 Host transfer was therefore
changed to full-duplex DMA, with RX DMA draining every MOSI dummy byte while TX
DMA feeds MISO. The same 10 MHz link then ran continuously without gaps.

## STM32 acquisition changes

- SYSCLK/HCLK/APB1/APB2: 80 MHz.
- MAX11633 remains in clock mode 10 (`0x64`): internal conversion clock,
  `0xF8` scan request, and EOC completion check.
- SPI1 data read: 10 MHz, Mode 0.
- MUX settling: experimental 25 us instead of `HAL_Delay(1)`.
- After EOC, the next MUX row begins settling while the current 32-byte FIFO is
  read.
- Raw 16-bit frame data is copied as one block on the little-endian STM32.
- Host SPI3 uses 10 MHz full-duplex DMA instead of blocking HAL polling.
- The FSR1 target is built in Release mode.

The 25 us settling value is an aggressive performance setting. Transport has
passed a 10-second capture, but controlled pressure, row mapping, adjacent-row
crosstalk, and a longer sustained capture must still be checked before calling
the analog result reliable.

## Hardware result

| Measurement | Result |
|---|---:|
| Duration | 10.003 s |
| Complete frames | 3,272 |
| Complete 16 x 16 rate | **327.105 FPS** |
| Sequence gaps | 0 |
| Invalid frame candidates | 0 |
| Discarded bytes | 0 |
| Raw ADC range | 0..2410 |

Raw record:
[`20260812_110930_fsr1_fast_dma_10s.txt`](../../test_results/20260812_110930_fsr1_fast_dma_10s.txt)

## Paired command

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_fsr1_pair.cmd" COM9
```

This command builds/flashes the FSR1 STM32 image, uploads
`ESKIN_FSR1_FAST_BRIDGE`, and opens the existing FSR1 heatmap. FSR2 and the
combined firmware are unchanged.

## Compile verification

| Target | Result | RAM | Flash/code |
|---|---|---:|---:|
| STM32 FSR1 Release + SPI3 DMA | PASS | 3,584 B | 12,808 B |
| Teensy 4.1 FSR1 fast bridge | PASS | RAM1 variables 5,344 B | code 11,572 B |
