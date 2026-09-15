# Firmware

This directory contains the active STM32 and Teensy firmware used by the final four-module prototype, plus archived firmware records.

## Principle

Each STM32G474CETx scans its local 16 x 16 FSR matrix and sends a complete ESKF frame or a change-driven ESKD frame over the shared 10 MHz HOST SPI link. The Teensy 4.1 selects modules, aggregates the returned frames into a MUL1 v2 packet and forwards the packet to the PC over USB. The ACC interface is a prototype record and is outside the reported FSR evaluation.

<img src="renderings/report-data-path-flow.png" alt="Layered acquisition and communication path from the report" width="900">

## Contents

- active/: firmware used for the final report.
- active/four-module-variable-spi/: STM32 module firmware, Teensy bridge, commands, protocol notes and tests.
- archive/: superseded firmware and historical records.
- renderings/: the report data-path figure used for orientation.

## Active workflow

From active/four-module-variable-spi/:

1. Build the STM32 and Teensy targets with the supplied command scripts.
2. Flash each STM32 with its probe UID.
3. Upload the matching Teensy bridge image.
4. Start the serial monitor with the actual port name.

Required tools are CMake, Ninja, arm-none-eabi-gcc, arduino-cli, pyocd and Python on PATH. Do not commit generated build output or live measurement captures; the firmware ignore rules exclude them.