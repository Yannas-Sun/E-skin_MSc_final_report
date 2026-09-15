# Four-module FSR firmware with variable-length HOST SPI

This STM32 image is the final-report sensing firmware. All four modules use the same image; the Teensy CS/IRQ wiring determines the module slot. ACC is not sampled or transmitted.

## Frame and link format

| Item | Definition |
|---|---|
| Acquisition | Two 16 x 16 FSR arrays using the shared MUX and two MAX11633 converters |
| HOST SPI | SPI3 slave; one full-duplex DMA transaction for the encoded frame length |
| FULL | `ESKF`, 1044 B: 16 B header, 512 B FSR1, 512 B FSR2, 4 B CRC |
| DELTA | `ESKD`, `84 + 2K` B: 16 B header, two 32 B masks, `K` uint16 values, 4 B CRC |
| DELTA base | FULL on the first frame, resynchronisation, 1000 ms base timeout or `K > 480` |
| USB | Teensy carries frames in MUL1 v2 module blocks |

The Teensy reads the 16-byte header, then clocks `length - 16` additional bytes while CS remains low. A zero-change DELTA frame clocks 84 bytes; unused buffer capacity is not clocked.

## HOST SPI command

The first 16 MOSI bytes are `DSCM` v2. Fields are: version at byte 4; mode at byte 5 (`0` FULL, `1` DELTA); little-endian DELTA threshold at bytes 6–7; target scan rate at bytes 10–11; and DELTA resync at bit 0 of byte 12. Reserved bytes are transmitted as zero.

The Teensy may send `MODE FULL`, `MODE DELTA` and `SCAN_HZ <Hz>`. Commands apply after a completed DMA transaction and preserve the existing acquisition and cache rules.

## Buffering and recovery

Acquisition and encoding use the buffer not being transmitted. DMA completion or error lowers IRQ; a new transfer waits for NSS release and reinitialises HOST SPI. Invalid or truncated transactions are aborted and retried after the existing timeout/back-off path. DELTA resynchronisation requests a new FULL base.

## Build

```powershell
cmake --preset Release
cmake --build --preset Release
```

Output: `build/Release/ESKIN_STM32.elf`. Building does not flash a device. Deploy this image with the matching variable-length Teensy bridge.
