# Archived fixed-slot STM32 FSR firmware

Historical STM32 image for the four-module fixed-slot branch. It is not the final-report firmware.

## Link format

| Item | Definition |
|---|---|
| Acquisition | Two 16 x 16 FSR arrays through MAX11633 converters |
| HOST SPI | SPI3 DMA with fixed 1044-byte slots; first 16 MOSI bytes are the command |
| FULL | `ESKF`, 1044 B |
| DELTA | `ESKF` base or masked `ESKD`; two 32 B masks and uint16 values |
| SPATIAL | `ESPF`, `ESPD` and `ESP0` reduce the USB logical payload |
| USB | MUL1 v2 module blocks |

The Teensy accepts `MODE FULL`, `MODE DELTA`, `MODE SPATIAL`, `SCAN_HZ <Hz>` and `SCAN_HZ 0`. It owns four module slots and reports `NO_IRQ`, `BAD_FRAME`, `BAD_VERSION`, `BAD_CRC` and `TIMEOUT` states.

SPATIAL still scans all 512 FSR values. It changes the logical payload only; this branch retains fixed HOST SPI transactions. Four STM32 boards use the same image; CS/IRQ wiring selects the slot.

