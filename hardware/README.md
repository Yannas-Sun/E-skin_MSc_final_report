# Hardware package

This directory contains the hardware sources, manufacturing outputs, shared KiCad libraries, and firmware retained for the final project.

## Structure

- prototype/mainboard/
  - design/: KiCad schematic, PCB, project file, and library tables.
  - manufacturing/: Gerber, drill, BOM, and board renders.
- prototype/fsr_array/
  - design/: flexible FSR-array KiCad project.
  - manufacturing/: Gerber, drill, manufacturing archive, and board figure.
- prototype/acc_prototype/
  - design/: ACC prototype KiCad project and sensor schematics.
  - manufacturing/: Gerber, drill, manufacturing archive, and board renders.
- libraries/bom/: component BOM spreadsheets.
- libraries/datasheet/: component datasheets used by the hardware records.
- libraries/3dmodels/: local STEP models used by the PCB layouts.
- libraries/e_skin.pretty/: custom KiCad footprints.
- libraries/e_skin_custom_symbols.kicad_sym: custom KiCad symbols.
- libraries/Figures/: source hardware renders and exported schematics/layouts.
- firmware/: final firmware source and retained historical firmware packages.

## Report figures

The LaTeX project uses the report copies in ../Imperial College Individual Project Template_LaTeX/figures/hardware/. The source exports remain in libraries/Figures/.

## Portability

The retained KiCad project files use paths relative to this hardware package. Open each project from its design/ directory with the shared libraries available under libraries/.