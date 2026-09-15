# Regression results

Final complete run: **2026-09-06, PASS**. The native regression suite uses MSVC 14.50 C/C++ on Windows and the installed Python environment with NumPy and Matplotlib. The baseline is read directly from the sibling firmware directory.

| Check | Result |
|---|---|
| Real STM32 encoder, 212 shared frame vectors | PASS: old/new lengths and all 1044 output bytes equal |
| Independent CRC32, mask population, output guard bytes | PASS |
| Real PC parsers, all 212 C-generated frames with flags 0x13/0x33 | PASS: both 16×16 matrices and sequence numbers equal after every frame |
| Real Teensy bridge, 17 baseline and 30 candidate frame reads | PASS |
| Candidate 16-byte header plus actual payload under one CS | PASS |
| Bad headers stop after 16 bytes; payload/CRC errors reject | PASS |
| Two MUL1 packets with four ordered module descriptors | PASS: old/new bytes equal |
| Real STM32 acquisition, five pipeline rounds | PASS |
| DMA mode/resync lengths and active-buffer immutability | PASS |
| Six DMA completion/failure scenarios and invalid lengths | PASS |

Encoder stream SHA-256: `190748ac02b39809d34e23361c3a61a66434f331103961917283ba6ad8b22b36`.

Teensy packet stream SHA-256: `758495a3dad14b9920688ca963f4372ff3bcde880e977b916065b05040c4ecbc`.

The PC integration check initially exposed rejection of the real acquisition-status bits. After the PC flag validation was corrected, the entire suite was rerun successfully. The final machine-readable outcomes are in `regression_results.json`.

The tested DMA scenarios are CS held low between header and payload, NSS changing low between the two guard reads, partial reception followed by NSS high, explicit DMA error, no clocks until timeout, and DMA counter zero with no completion callback. A transfer with NSS low is allowed to finish; a partial transfer with NSS high is aborted immediately; an unstarted transfer waits for the existing timeout.

These are offline firmware behavior checks. Real clock gaps, throughput, IRQ latency and electrical behavior are not measured by this suite.
