# Stable internal-clock + EOC MUX-settle sweep

Module: 1; capture per point: 8 s.
The acquisition path remains the stable EOC-qualified path; only external MUX settle changes.

| MUX settle | Readout status | Legacy 200-frame gate | USB output | Complete FSR scan | FSR1 raw | FSR2 raw |
| ---: | :---: | :---: | ---: | ---: | :--- | :--- |
| 100 us | EOC_QUALIFIED | FAIL | 239.409 Hz | 269.76 Hz | 0..700 | 0..612 |
| 75 us | EOC_QUALIFIED | FAIL | 241.435 Hz | 272.331 Hz | 0..692 | 0..496 |
| 50 us | EOC_QUALIFIED | FAIL | 242.94 Hz | 274.123 Hz | 0..690 | 0..593 |
| 25 us | EOC_QUALIFIED | FAIL | 244.249 Hz | 275.938 Hz | 0..702 | 0..587 |
| 10 us | EOC_QUALIFIED | FAIL | 244.875 Hz | 276.702 Hz | 0..696 | 0..544 |
| 0 us | EOC_QUALIFIED | FAIL | 245.854 Hz | 277.932 Hz | 0..697 | 0..537 |

Lowest tested EOC-qualified MUX settle: **0 us**.
This is a no-load timing sweep; pressure-response and row-to-row crosstalk still decide whether the interval is electrically acceptable.
