# ESKIN FSR1 fast bridge

Dedicated Teensy 4.1 bridge for the high-rate standalone FSR1 test. It keeps
the existing 515-byte protocol but clocks the STM32 SPI3 slave at 10 MHz with
50 us IRQ settling, 10 us CS setup, and 10 us CS hold delays.

This sketch is used only by `tools/commands/flash_fsr1_pair.cmd`. FSR2 and the
combined system retain their existing bridges.
