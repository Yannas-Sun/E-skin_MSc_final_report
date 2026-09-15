# Native firmware regression tests

Run from a Windows machine with Python, NumPy, Matplotlib and MSVC C/C++ Build Tools:

```powershell
python tests/run_protocol_regression.py --report tests/regression_results.json
```

The runner discovers Visual Studio with `vswhere`; an x64 Developer Command Prompt also works. All C/C++ wrappers and executables are built in a unique temporary directory and removed afterwards. The tests include the actual source files by path. They do not copy or modify the baseline firmware, flash a board, open a serial port, or start a GUI. Python bytecode writes are disabled.

The reference is the sibling `four-module-full-scan` directory. The candidate is the directory containing these tests.

## Executed checks

- **STM32 encoder:** compile the real baseline and candidate `data_scalability_protocol.c` independently and supply identical samples, commands, times and acquisition status `3`. Compare all 1044 buffer bytes for 212 frames, including logical lengths and cleared tails. Exercise FULL/DELTA switches, threshold equality versus exceedance, no-change DELTA, changes in both layers, 480-update capacity versus 481-update fallback, explicit/periodic resynchronisation, unsigned clock wrap and deterministic changing samples. Guard bytes catch writes outside the output buffer. Python independently checks the returned frame length, mask population and CRC32.
- **PC reconstruction:** import both actual PC applications without starting them, pass all 212 C-generated frames through `ProtocolState`, and compare both reconstructed 16×16 matrices and sequence numbers after each frame. Flags `0x13` and `0x33` exercise the real acquisition-status bits.
- **Teensy bridge:** compile each complete real `.ino` with mock Arduino pins, SPI and USB. The mock records every clocked byte, transfer boundary and CS transition. The candidate must clock 16 header bytes and exactly the remaining declared length under one CS assertion; rejected headers must stop after 16 bytes. Valid 84/88/1044-byte DELTA and FULL, invalid marker/version/length/flags, CRC damage, mask mismatch, unknown commands and sequence-gap resynchronisation are exercised. Compare baseline and candidate MUL1 output byte-for-byte for a complete four-module round and a partial round containing not-updated/diagnostic slots. Independently verify the outer CRC and all four ordered module descriptors.
- **STM32 DMA pipeline:** compile actual `combined_acquisition.c` and the actual encoder with a minimal HAL stub. Five real `CombinedAcquisition_RunOnce` calls verify initial FULL, mode switching, short DELTA, resynchronisation back to FULL, per-buffer stored lengths and unchanged DMA-owned contents during the next scan. Direct real DMA-start/wait calls check header-to-payload pauses with CS low, the NSS sampling race, partial transfer released early, DMA error, no clocks until timeout, absent completion callback, and invalid buffer lengths.

The mocks exercise firmware control flow and protocol bytes. They do not measure physical SPI timing, electrical signal integrity, real DMA interrupt priority, throughput or power. Those require the matching STM32 and Teensy firmware on hardware.

`regression_results.json` stores machine-readable outcomes. `RESULTS.md` records the last completed run and its scope.
