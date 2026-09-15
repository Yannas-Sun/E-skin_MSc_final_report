# Internal-clock FIFO-DMA sweep

Module: 1; MUX settle: 0 us; capture per point: 8 s.

| Command-to-read gap | Result | USB output | Complete FSR scan profile |
| ---: | :---: | ---: | ---: |
| 20 us | PASS | 419.546 Hz | 457.457 Hz |
| 40 us | FAIL | 338.141 Hz | 353.732 Hz |
| 50 us | FAIL | 305.163 Hz | 317.864 Hz |
| 60 us | FAIL | 277.748 Hz | 288.517 Hz |
| 70 us | FAIL | 255.277 Hz | 264.061 Hz |
| 80 us | FAIL | 235.942 Hz | 243.427 Hz |

Highest short-run passing point: **457.457 Hz** at **20 us** command-to-read gap.

This is an unloaded short-run validity test, not a controlled-pressure qualification.
