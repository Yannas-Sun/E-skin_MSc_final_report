# ACC1 / ACC5 WHO_AM_I PC Monitor

Keep the standard Teensy `ESKIN_SPI_USB_BRIDGE` application installed, then
run:

```powershell
python .\read_a1_a5_whoami.py --port COM9
```

Build and flash the matching STM32 isolation firmware first:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_stm32_project.cmd" acc-whoami
```

Use `--frames 1 --show-samples` to print every raw value from one complete
100-read ACC1 plus 100-read ACC5 cycle.
