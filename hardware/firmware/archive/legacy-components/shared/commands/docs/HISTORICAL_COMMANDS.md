# Historical command notes

This document records the purpose and limits of the command set kept under `../`.

## Provenance

The commands were used for earlier STM32 + Teensy experiments, including a 10 MHz Mode-0 HOST SPI chain with fixed-width 1188-byte frames, dual FSR acquisition and nine ACC positions. A 30-second run reached 238.475 complete cycles/s with clean CRC, magic, header, sequence, USB-short and NSS-release checks. These results are not the final report's variable-length FSR-only data.

A separate transport result reached 700.181 packets/s by updating one MUX address per packet; the equivalent complete FSR refresh rate was 43.76 Hz. These rates must not be combined with the 238.475-cycle/s full-scan result.

## Historical command groups

- `flash_teensy_self_test.cmd`: Teensy-only self-test and serial monitor.
- `flash_spi_pattern_test.cmd`: STM32–Teensy `0x55` SPI pattern test.
- `flash_fsr1_pair.cmd` and `flash_fsr2_pair.cmd`: standalone 16 x 16 FSR acquisition and heatmap tests.
- `flash_combined_pair.cmd`: legacy STM32 + Teensy combined deployment.
- `flash_combined_sclk33_experiment.cmd`: SCLK33 reproduction with build-time FSR/ACC rates.
- `flash_internal_fifo_dma_pair.cmd`, `flash_internal_eoc_mux_stm32.cmd` and `flash_internal_eoc_mux_pair.cmd`: FIFO, EOC and DMA timing experiments.
- `flash_acc_rate_benchmark.cmd`: isolated nine-slot ACC benchmark.
- `upload_teensy_sketch.cmd` and `monitor_teensy_serial.cmd`: generic legacy Teensy helpers.

## Historical constraints

The older combined chain used fixed-width slots, ACC paths and command wrappers that no longer match the final variable-length firmware. Some 10 MHz ADC/SCLK profiles were diagnostic or outside the normal validated operating range. A failed SWD connection required checking NRST, VTref, GND, SWDIO and SWCLK.

## Outputs

Historical capture tools wrote raw streams and diagnostics under the former firmware `docs/test_results/` tree. Current report records belong under `docs/Final/data scalability/data/` and must be collected with the active variable-length monitor.
