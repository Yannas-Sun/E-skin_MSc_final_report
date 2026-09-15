# ACC Slow-MOSI / OR-Gate Test

This isolated STM32 diagnostic makes the shared MOSI path and the selected
ACC's local OR-gate output easy to measure with a multimeter.

- PB13 / SCK remains at 0 V continuously;
- the selected ACC nCS remains at 0 V continuously;
- every other nCS remains high;
- PB15 / MOSI is low for 1 second and high for 1 second, repeatedly;
- no SCK edge is generated, so no SPI command is transferred;
- no Host SPI or USB frame is produced.

Build and flash the default ACC3 test:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_acc_mosi_slow.cmd" 3
```

Replace `3` with any installed ACC number from 1 through 9. For the selected
device, `SDI = nCS OR MOSI`; because its nCS is held low, the local SDI output
must follow MOSI:

| Signal | Low phase | High phase |
|---|---:|---:|
| SCK | 0 V | 0 V |
| selected nCS | 0 V | 0 V |
| MOSI | 0 V | approximately 3.3 V |
| selected OR output / SDI | 0 V | approximately 3.3 V |

For every unselected ACC, nCS remains high and its OR output / SDI must remain
high during both phases. The test does not damage or configure the LIS2DH12:
all levels remain within the 3.3 V I/O range and there is no clock edge.

After testing, restore the normal ACC application:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_acc_array.cmd" 0
```
