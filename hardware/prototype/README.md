# Prototype design records

This directory contains the current KiCad design and manufacturing records for the evaluated mainboard and flexible FSR layers, plus the ACC prototype interface.

## Hardware principles

- mainboard/: four-layer rigid FR4 board with local STM32G474CETx acquisition, FSR readout, branch power distribution, connectors and programming access.
- fsr_array/: flexible FSR electrode carrier. Orthogonal row and column electrodes surround a pressure-sensitive resistive foam layer to form a 16 x 16 matrix.
- acc_prototype/: ACC prototype interface retained as hardware evidence; it is outside the reported FSR evaluation.

Each board directory separates design files from manufacturing exports. The renderings below are orientation images; the KiCad projects and Gerbers are the source records.

## Renderings

<table>
<tr>
<td><img src="renderings/Module%202.0.png" alt="Module stack" width="220"><br>Module stack</td>
<td><img src="renderings/Mainboard.png" alt="Rigid mainboard" width="220"><br>Rigid mainboard</td>
</tr>
<tr>
<td><img src="renderings/FSR.png" alt="Flexible FSR layer" width="220"><br>Flexible FSR layer</td>
<td><img src="renderings/ACC.png" alt="ACC prototype" width="220"><br>ACC prototype</td>
</tr>
</table>

## Contents

- mainboard/: schematic, PCB, project and manufacturing files.
- fsr_array/: flexible FSR schematic, PCB and manufacturing files.
- acc_prototype/: ACC prototype schematic, PCB and manufacturing files.
- renderings/: small reference images used by this README.

Open each KiCad project from its design directory with the shared libraries available under hardware/libraries/.