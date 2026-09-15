# ACC Slow-SCK Continuity Test

This isolated STM32 diagnostic makes the shared accelerometer clock easy to
measure with a multimeter:

- PB13 / ACC SCK is held low for 1 second;
- PB13 / ACC SCK is held high for 1 second;
- the sequence repeats continuously;
- PC13 / ACC_EN remains high, so every CD74HC154 nCS output remains inactive;
- PB15 / MOSI remains low;
- no valid LIS2DH12 SPI transaction is generated;
- no Host SPI or USB frame is produced.

All nine accelerometers share SCK. To check ACC5, compare the voltage directly
at STM32 PB13, mainboard ACC connector pin 3, ACC FPC pin 3, and the ACC5
LIS2DH12 SCL/SPC pin. Every point should alternate between approximately 0 V
for 1 second and the board I/O rail (normally 3.2-3.3 V) for 1 second.

Build and flash:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_acc_sck_slow.cmd"
```

After this test, restore normal ACC5 acquisition from
`stm32/applications/acc_array`:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_acc_array.cmd" 0
```
