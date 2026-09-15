# SCLK reproduction frequency sweep — 2026-08-12

## Result

The approximate highest conservative ADC clock without the previously observed
bit-boundary distortion is **7.5 MHz** on this hardware. A 30-second final run
produced **439.299 complete dual-FSR plus ACC frames/s** with 100% transport
acceptance and every ADC-quality window passing.

`8.0 MHz` was marginal, `8.125 MHz` showed increasing frozen FSR1 cells, and
`8.75 MHz` showed clear FSR1 code collapse. The recommended experimental point
therefore retains margin below the observed failure transition.

## Constant acquisition method

All sweep points retained:

- MAX11633 setup `0x78`;
- Mode-0, SCLK-driven conversion;
- one continuous 33-byte full-duplex SPI1 DMA per ADC/MUX address;
- no EOC polling;
- no explicit MUX settling delay;
- complete 16-address scans of both 16 x 16 FSR layers;
- Combined frame with nine ACC records and Host SPI3 DMA.

Only the PLL/SPI divider combination changed. This avoids conflating ADC clock
with the earlier internal-clock/FIFO acquisition method.

## Automatic distortion criteria

Each non-overlapping 200-frame window and each FSR layer had to satisfy:

```text
bit-boundary-code proportion             < 65%
median unique values per physical cell   >= 4
fully frozen cells                       <= 5%
cells with no more than 3 unique values  <= 20%
cells changing between adjacent frames   >= 40%
CRC/Magic/Header/Sequence errors          = 0
```

The bit-boundary set was `0, 1, 3, 7, 15, 31, 63, 127, 255, 511, 1023,
2047, 4095`. Earlier 10 MHz failures concentrated heavily at these values even
though their packet CRC was correct.

## Sweep results

| ADC SCK | STM32 clock | Complete rate | Median FSR time | ADC-quality result |
|---:|---:|---:|---:|---|
| 2.500 MHz | 160 MHz | 205.444 Hz | 4,579 us | Baseline PASS |
| 5.000 MHz | 160 MHz | 360.880 Hz | 2,477 us | No bit collapse; several FSR1 frozen-cell windows marginal |
| 7.500 MHz | 120 MHz | 439.444 Hz | 1,902 us | Initial PASS |
| **7.500 MHz, 30 s** | **120 MHz** | **439.299 Hz** | **1,902 us** | **PASS: all 65 windows, both layers** |
| 8.000 MHz | 128 MHz | 425.444 Hz | 1,791 us | Marginal: one FSR1 window reached 5.47% frozen cells |
| 8.125 MHz | 130 MHz | 475.058 Hz | 1,755 us | Marginal/fail: FSR1 frozen cells 5.08–7.81% |
| 8.750 MHz | 140 MHz | 503.833 Hz | 1,635 us | FAIL: FSR1 boundary codes ~69.5%, unique median 3 |
| 10.000 MHz | 160 MHz | 581.667 Hz | 1,426 us | FAIL: severe bit-boundary code collapse |

The 8 MHz output anomaly (lower reported rate than adjacent points despite a
shorter median FSR phase) is another reason not to select that marginal point
without a longer timing trace.

## Final 7.5 MHz acceptance

| Measurement | Result |
|---|---:|
| Duration | 30 s |
| Diagnostic frames | 12,741 |
| Parsed binary frames | 13,181 |
| Complete output rate | **439.299 Hz** |
| Acceptance | **12,741 / 12,741 (100%)** |
| Sampled CRC errors | **0 / 398** |
| Sequence/Magic/Header errors | 0 / 0 / 0 |
| FSR1 boundary-code range | 33.115–34.135% |
| FSR1 frozen cells | 1.172–3.125% |
| FSR2 boundary-code range | 19.006–20.520% |
| FSR2 frozen cells | 0–0.391% |

Evidence:

- [`7.5 MHz final diagnostic`](../../test_results/20260812_225313_sclk33_refint7p5_final30s.txt)
- [`7.5 MHz decoded quality analysis`](../../test_results/20260812_225313_sclk33_refint7p5_final30s_quality.txt)
- [`2.5 MHz same-condition baseline`](../../test_results/20260812_224031_sclk33_refint2p5_baseline.txt)
- [`5 MHz sweep point`](../../test_results/20260812_223747_sclk33_refint5_sweep.txt)
- [`8 MHz sweep point`](../../test_results/20260812_225020_sclk33_refint8_sweep.txt)
- [`8.125 MHz sweep point`](../../test_results/20260812_224732_sclk33_refint8p125_sweep.txt)
- [`8.75 MHz failed point`](../../test_results/20260812_224536_sclk33_refint8p75_sweep.txt)

Binary captures remain local and ignored by Git.

## Recommendation and limitation

Use `refint7p5` as the highest current **experimental** setting on this tested
board:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_combined_sclk33_experiment.cmd" COM9 refint7p5 all I_ACCEPT_OUT_OF_SPEC_10MHZ
```

This is not a specification-compliant production setting: MAX11633 documents
a 4.8 MHz maximum external conversion clock. A compliant engineering choice is
4.75 MHz, followed by controlled-pressure, crosstalk, temperature and multi-board
validation. The 30-second 7.5 MHz result proves no detected bit-collapse in the
unloaded test; it does not prove calibrated analogue accuracy.

The board currently remains on the 7.5 MHz experiment. Restore the stable
internal-clock Combined firmware with:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_combined_pair.cmd" COM9
```
