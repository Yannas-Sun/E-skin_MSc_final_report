# Four-module variable-length HOST SPI

Final-project firmware for four STM32G474CETx modules and one Teensy 4.1 bridge.

- stm32/combined-system/: STM32 source and CMake project.
- teensy/four_module/: Teensy SPI/USB bridge.
- pc/: parser, GUI and recorder.
- commands/: build, flash, upload and monitor scripts.
- tests/: offline protocol tests.
- PROTOCOL.md: frame and byte definitions.

Run from this directory:

```powershell
.\commands\build.ps1
.\commands\flash_stm32.ps1 -ProbeUid <probe-uid>
.\commands\upload_teensy.ps1 -Port COM9 -ScanHz 200
.\commands\start_monitor.ps1 -Port COM9
```

FULL frames are 1044-byte ESKF records; DELTA frames are 84 + 2K-byte ESKD records. The default scan rate is 200 Hz and HOST SPI is 10 MHz. Keep STM32 and Teensy images matched.
