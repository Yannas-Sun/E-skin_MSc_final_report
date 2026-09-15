# SCLK33 second reproduction experiment — 2026-08-12

## Objective

Repeat the old Teensy-direct MAX11632/33 scan on STM32 after the original
hardware was independently measured at 700.210 complete frames/s. This update
corrects the prior experiment's known setup-byte difference and then tests
continuous SPI1 DMA without modifying the stable combined application.

## Exact settings reproduced

- MAX11633 setup byte `0x78`: SCLK conversion plus the original internal
  reference selection.
- Mode-0 ADC SPI at 10 MHz.
- One CS-low 33-byte full-duplex transaction per ADC and MUX address.
- TX sequence `86 00 8E 00 ... FE 00 00`.
- No EOC polling.
- No explicit MUX settling delay.
- Both MUX layers enabled and both ADCs read sequentially for all 16 addresses.

The new profile is `legacy10_refint`. The former `legacy10` profile remains
unchanged at `0x74`, preserving the first experiment exactly.

## Attempt 2: correct `0x78`, HAL polling transfer

| Measurement | Result |
|---|---:|
| Output rate | 365.444 Hz |
| Accepted frames | 3,289 / 3,289 (100%) |
| Sampled CRC errors | 0 / 103 |
| Sequence/magic/header errors | 0 |
| Median FSR acquisition | 2,262 us |
| FSR1 range | 0..3072 |
| FSR2 range | 0..1536 |

Both ADCs returned nonzero data and both FSR-valid flags remained set, but the
recent values collapsed to only 54 FSR1 and 74 FSR2 codes, dominated by bit
boundaries. Correcting `0x74` to `0x78` therefore did not restore valid ADC
conversion by itself.

Evidence:
[`20260812_130646_sclk33_legacy10_refint_attempt2.txt`](../../test_results/20260812_130646_sclk33_legacy10_refint_attempt2.txt)

## Attempt 3: `0x78` plus continuous SPI1 DMA

SPI1 RX/TX was moved to DMA2 Channel 1/2. Host SPI3 retains its established
DMA1 channels, so the two DMA paths do not conflict. CS stays low until the
33-byte DMA completes.

| Measurement | Result |
|---|---:|
| Output rate | **454.727 Hz** |
| Accepted frames | 4,093 / 4,093 (100%) |
| Sampled CRC errors | 0 / 128 |
| Sequence/magic/header errors | 0 |
| Median FSR acquisition | **1,717 us** |
| FSR1 unique codes, last 200 frames | 65 |
| FSR2 unique codes, last 200 frames | 95 |

DMA removed about 545 us from the complete dual-FSR scan and raised output by
89.283 frames/s. It did not fix the analogue data: values still concentrate at
`0, 1, 3, 7, 63, 127, 255, 511, 1023` and related boundaries. Attempt 3 is
therefore a **digital transport pass but sensor-data failure**, and it did not
reach 700 complete output frames/s.

Evidence:

- [`20260812_131107_sclk33_legacy10_refint_spi1dma_attempt3.txt`](../../test_results/20260812_131107_sclk33_legacy10_refint_spi1dma_attempt3.txt)
- [`20260812_131107_sclk33_refint_spi1dma_value_analysis.txt`](../../test_results/20260812_131107_sclk33_refint_spi1dma_value_analysis.txt)

The `.bin` captures are retained locally for byte-level reanalysis but remain
excluded by the repository's generated-binary policy.

## Conclusion

The old setup byte and a continuous 33-byte transaction have now both been
reproduced. Their digital behaviour is correct, but they are still insufficient
to reproduce the old Teensy's valid 10 MHz ADC result on STM32.

The next experiment must compare measured electrical timing rather than change
more firmware blindly. Capture both controllers with the same logic analyser:

1. CS-to-first-SCK setup and last-SCK-to-CS hold.
2. Actual SCK frequency and duty cycle.
3. Inter-byte gaps, especially around each next-channel command.
4. MISO transition/settling relative to the STM32 sampling edge.
5. MUX address and enable timing before ADC1 and ADC2.
6. The complete 33-byte MOSI/MISO pair for a fixed channel and pressure.

The STM32 currently remains on `legacy10_refint` with SPI1 DMA to make this
measurement immediately possible. Restore the stable combined firmware with:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_combined_pair.cmd" COM9
```

## Attempt 4: STM32 increased from 80 to 160 MHz

The isolated `legacy10_refint` profile was subsequently raised to 160 MHz.
Range-1 boost mode and four Flash wait states are enabled. APB1 and APB2 remain
at 160 MHz; SPI1 and SPI2 changed from `/8` to `/16`, preserving both ADC and
ACC SCK at exactly 10 MHz. The stable combined build remains at 80 MHz.

| Measurement | 80 MHz attempt 3 | 160 MHz attempt 4 |
|---|---:|---:|
| Complete output rate | 454.727 Hz | **581.667 Hz** |
| Median FSR acquisition | 1,717 us | **1,426 us** |
| Median ACC acquisition | 267 us | **159 us** |
| Median packing | 106 us | **53 us** |
| Transport acceptance | 100% | 100% |
| Sampled CRC errors | 0 / 128 | 0 / 163 |

The frequency increase worked, but 700 Hz was not reached. The FSR phase alone
now consumes 1,426 us, essentially the entire 1,428.6 us frame budget, before
the 159 us ACC phase and 53 us packing phase. The raw FSR codes also remain
dominated by the same bit-boundary values, so analogue data acceptance still
fails.

Evidence:

- [`20260812_133623_sclk33_refint_spi1dma_stm160_attempt4.txt`](../../test_results/20260812_133623_sclk33_refint_spi1dma_stm160_attempt4.txt)
- [`20260812_133623_sclk33_refint_spi1dma_stm160_value_analysis.txt`](../../test_results/20260812_133623_sclk33_refint_spi1dma_stm160_value_analysis.txt)
