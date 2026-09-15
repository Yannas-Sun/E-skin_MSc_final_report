# Original Teensy-direct 700 Hz hardware result — 2026-08-12

## Result

The original hardware with Teensy 4.1 directly controlling both MAX11632/33
ADCs and the multiplexers achieved the requested complete-frame rate.

| Measurement | Result |
|---|---:|
| Test duration | 10.004 s |
| Complete 1,132-byte `ESKN` frames | 7,005 |
| Wall-clock frame rate | **700.210 FPS** |
| Mean FSR timestamp interval | **1,428.000 us** |
| Timestamp-derived rate | **700.280 Hz** |
| Invalid frames | 0 |
| Discarded/resynchronisation bytes | 0 |
| Raw FSR range | 0..29 |

This confirms that the old architecture can perform 700 complete cycles per
second in this 10-second run. Each cycle contains 16 accelerometers and both
full 16 x 16 FSR layers; this is not a partial-row or rolling-frame result.

## Firmware reproduced

The test sketch is
[`ESKIN_ORIGINAL_700HZ.ino`](../../../teensy/experiments/ESKIN_ORIGINAL_700HZ/ESKIN_ORIGINAL_700HZ.ino).
It leaves the preserved source unchanged and directly reuses its original pin
map and sensor drivers. Its active-stream loop matches the old software's
generated 700 Hz loop.

The key acquisition behaviour is:

- Teensy drives the ADCs and MUX directly; there is no STM32/Host-SPI hop.
- MAX11632/33 conversion is driven by 10 MHz Mode-0 SCLK.
- Conversion request and result retrieval share the same continuous SPI
  transaction.
- There is no EOC polling and no explicit MUX settling delay.
- USB carries fixed 1,132-byte `ESKN` frames directly from Teensy.

## Remaining validation

The transport-rate test passed, but the unattended raw FSR range was only
0..29. A controlled pressure test is still required to verify physical signal
response, row/column mapping, adjacent-channel crosstalk and long-duration
stability at this aggressive 10 MHz ADC clock.

Raw measurement:
[`20260812_113947_original_teensy_direct_700hz_10s.txt`](../../test_results/20260812_113947_original_teensy_direct_700hz_10s.txt)
