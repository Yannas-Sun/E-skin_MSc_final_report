# Hardware package

This directory contains the hardware evidence for the final project: prototype design records, manufacturing exports, shared KiCad libraries, renderings and firmware.

## System principle

Each replaceable module contains two flexible FSR electrode layers and a local STM32G474CETx. Orthogonal copper rows and columns surround a pressure-sensitive resistive foam layer, producing a 16 x 16 sensing matrix. The rigid mainboard provides the FSR interfaces, ADC and multiplexing paths, branch power, connectors and programming access.

The Teensy 4.1 acts as the host bridge. It selects modules over the shared 10 MHz HOST SPI link, aggregates ESKF FULL or ESKD DELTA frames into MUL1 v2 packets and forwards them to the PC over USB. The ACC interface is retained as an existing prototype record and is outside the reported FSR evaluation.

## Renderings

<table>
<tr>
<td><img src="libraries/Figures/Module%202.0.png" alt="Module stack" width="220"><br>Module stack</td>
<td><img src="libraries/Figures/Mainboard.png" alt="Rigid mainboard" width="220"><br>Rigid mainboard</td>
</tr>
<tr>
<td><img src="libraries/Figures/FSR.png" alt="Flexible FSR layer" width="220"><br>Flexible FSR layer</td>
<td><img src="libraries/Figures/ACC.png" alt="ACC prototype" width="220"><br>ACC prototype</td>
</tr>
</table>

## Navigation

- [Prototype design records](prototype/README.md): mainboard, flexible FSR array and ACC prototype design/manufacturing files.
- [Shared libraries](libraries/README.md): KiCad symbols and footprints, models, datasheets, BOMs and exported figures.
- [Firmware](firmware/README.md): active four-module firmware, protocol notes and archived firmware records.

Each prototype directory separates design files from manufacturing outputs. KiCad projects use paths relative to this hardware package.