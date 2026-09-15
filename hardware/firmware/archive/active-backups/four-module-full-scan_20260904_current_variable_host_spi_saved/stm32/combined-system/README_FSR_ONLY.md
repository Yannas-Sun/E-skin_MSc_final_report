# Historical variable-length STM32 snapshot

Snapshot of the STM32 side of the variable-HOST-SPI transition. It samples two 16 x 16 FSR arrays, excludes ACC, and sends ESK v4 FULL/DELTA frames with actual encoded lengths.

- HOST SPI: actual frame length, maximum 1044 B; 12-byte v3 control command.
- FULL: `ESKF`, 1044 B.
- DELTA: `ESKD`, `84 + 2K` B.
- USB bridge: Teensy MUL1 v2.

This snapshot is not the current deployment path. Use `../../../../../active/four-module-variable-spi` and its matching Teensy source.

