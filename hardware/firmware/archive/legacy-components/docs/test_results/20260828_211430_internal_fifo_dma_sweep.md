# Internal-clock FIFO-DMA sweep

Module: 1; MUX settle: 0 us; capture per point: 5 s.

| Command-to-read gap | Result | USB output | Complete FSR scan profile |
| ---: | :---: | ---: | ---: |
| 25 us | FAIL | 403.426 Hz | 426.257 Hz |
| 30 us | FAIL | 378.56 Hz | 399.042 Hz |
| 35 us | PASS | 357.224 Hz | 375.094 Hz |
| 38 us | FAIL | 345.521 Hz | 361.925 Hz |
| 40 us | FAIL | 337.981 Hz | 353.732 Hz |

Highest short-run passing point: **375.094 Hz** at **35 us** command-to-read gap.

This is an unloaded short-run validity test, not a controlled-pressure qualification.
