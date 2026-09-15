# Archived four-module fixed-slot HOST SPI firmware

Historical branch; do not use for reproducing the final report. The final deployment source is `../../../active/four-module-variable-spi`.

- STM32: ESK v4, two 16 x 16 FSR arrays, fixed 1044-byte HOST SPI slots.
- Teensy: 4.1 bridge, MUL1 v2, up to four modules, 10 MHz HOST SPI.
- PC: `four-module-fsr-monitor.py`, with FULL/DELTA/SPATIAL parsing.

Source directories are `stm32/combined-system`, `teensy/four_module` and `pc/`. This branch contains the historical fixed-slot transport and shared command assumptions. Older ACC and 1188-byte work is under `../previous-source` and `../../legacy-components/research`.

