# Internal-clock FIFO-DMA sweep

Module: 1; MUX settle: 0 us; capture per point: 8 s.

| Command-to-read gap | Result | USB output | Complete FSR scan profile |
| ---: | :---: | ---: | ---: |
| 36 us | FAIL | 353.236 Hz | 370.645 Hz |
| 37 us | FAIL | 349.16 Hz | 366.3 Hz |
| 38 us | FAIL | 345.302 Hz | 361.925 Hz |

No point passed both transport and unloaded FSR quality gates.

This is an unloaded short-run validity test, not a controlled-pressure qualification.
