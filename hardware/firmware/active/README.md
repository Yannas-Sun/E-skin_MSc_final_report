# Active firmware

This directory contains the firmware branch used by the final report: four STM32G474CETx sensing modules and one Teensy 4.1 bridge.

Entry point: four-module-variable-spi/.

Build and deploy from that directory:

```powershell
.\commands\build.ps1
.\commands\flash_stm32.ps1 -ProbeUid <probe-uid>
.\commands\upload_teensy.ps1 -Port COM9 -ScanHz 200
.\commands\start_monitor.ps1 -Port COM9
```

Build and flash each STM32 separately, then upload the matching Teensy image. Use the actual COM port and probe UID.

Required tools are cmake, ninja, arm-none-eabi-gcc, arduino-cli, pyocd and python on PATH. Run tests with python tests/run_protocol_regression.py.
