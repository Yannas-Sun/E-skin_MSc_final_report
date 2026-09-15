# Shared hardware libraries

This directory stores the component references shared by the prototype records: KiCad symbols and footprints, 3-D models, datasheets, BOM files and exported hardware figures.

## Hardware principles

- FSR sensing uses two orthogonal 16-electrode layers. A pressure-sensitive resistive foam layer between the copper surfaces changes resistance at each row-column intersection, forming a 16 x 16 matrix.
- The rigid mainboard hosts the STM32G474CETx, multiplexers, ADC interfaces, connectors and branch power distribution.
- The optional ACC interface is documented as an existing prototype. It is not used in the reported FSR performance results.
- The LM2596 records document the external regulated supply used by the electrical measurements.

## Reference renderings

<table>
<tr>
<td><img src="Figures/Module%202.0.png" alt="Module rendering" width="220"><br>Module stack</td>
<td><img src="Figures/Mainboard.png" alt="Mainboard rendering" width="220"><br>Rigid mainboard</td>
</tr>
<tr>
<td><img src="Figures/FSR.png" alt="FSR rendering" width="220"><br>Flexible FSR layer</td>
<td><img src="Figures/ACC.png" alt="ACC rendering" width="220"><br>ACC prototype</td>
</tr>
</table>

## Contents

- Figures/: source renderings, schematics and PCB-layout exports.
- 3dmodels/: STEP models used by the KiCad projects.
- datasheet/: component datasheets grouped by board.
- bom/: component lists and procurement records.
- e_skin.pretty/: custom footprints.
- e_skin_custom_symbols.kicad_sym: shared KiCad symbols.

The KiCad design files use paths relative to this package. Open a project from its design directory with the shared libraries available under this directory.