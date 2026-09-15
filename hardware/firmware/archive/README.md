# Firmware archive

This directory contains firmware and supporting material that is not the final report's deployment basis. Nothing here should be flashed for reproducing the final data unless a comparison experiment is explicitly intended.

## Contents

- `active/four-module-full-scan/` is the earlier fixed-width HOST SPI branch retained from the former active tree.
- `active/four-module-full-scan-current/` is the moved copy of the former active branch, preserved separately so the reorganisation did not overwrite history.
- `active-backups/` contains dated snapshots of the full-scan and variable-HOST-SPI development states.
- `legacy-components/research/` contains independent ACC/data-scalability and scan-rate experiments, including the 1188-byte fixed-slot protocol.
- `legacy-components/diagnostics/` contains hardware and link diagnostics.
- `legacy-components/shared/` contains older shared command files; several still target the fixed-slot or research branches.
- `legacy-components/simulation/` contains software-only simulations.
- `legacy-components/docs/` and `legacy-components/tools/` contain historical documentation and utility tools.
- `generated-builds/` contains the former top-level `.arduino-build` and `.cmake-build` caches. These are generated artifacts, not source.
- `historical-700hz/`, `previous-source/`, and `stm32/` preserve older firmware workspaces and snapshots.

The final implementation is kept separately in [`../active/four-module-variable-spi`](../active/four-module-variable-spi). Use its local `commands/` directory for build, STM32 flash, Teensy upload, and monitoring.
