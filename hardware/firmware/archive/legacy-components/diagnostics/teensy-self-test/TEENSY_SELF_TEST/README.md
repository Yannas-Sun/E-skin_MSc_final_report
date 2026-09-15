# Teensy 4.1 standalone self-test

This sketch verifies basic Teensy operation before connecting it to the STM32:

- firmware upload through the Teensy USB connection;
- USB Serial enumeration;
- continuous execution using an increasing uptime counter;
- the onboard LED toggling every 500 ms.

Run the complete compile/upload/monitor flow from any PowerShell directory:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_teensy_self_test.cmd" COM9
```

Disconnect the STM32 Host SPI wiring during this test. On Teensy 4.1,
`LED_BUILTIN` and the default SPI SCK signal both use GPIO13.

Arduino IDE settings:

```text
Board: Teensy 4.1
USB Type: Serial
CPU Speed: default
Port: the Teensy USB serial port (currently COM9 on the test PC)
```

Open `TEENSY_SELF_TEST.ino`, click Upload, and press the Teensy Program button
once if the loader requests it. Open Serial Monitor at 115200 baud. A healthy
board prints an increasing `count` and `uptime_ms` once per second.
