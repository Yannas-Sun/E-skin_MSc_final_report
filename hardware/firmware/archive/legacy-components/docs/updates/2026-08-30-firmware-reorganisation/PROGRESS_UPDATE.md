# Firmware reorganisation

Date: 2026-08-30

## Purpose

The firmware tree was reorganised by operational role so that the normal
four-module system, experimental variants, focused diagnostics and historical
sources are no longer mixed under chip-specific top-level folders.

## New locations

| Purpose | Location |
|---|---|
| Current four-module system | `active/four-module-full-scan/` |
| Data scalability encoder and bridge | `research/data-scalability/` |
| Scan-rate experiments | `research/scan-rate/` |
| FSR, ACC, Host SPI and single-module diagnostics | `diagnostics/` |
| Simulator | `simulation/software-simulation/` |
| Legacy sources and historical 700 Hz code | `archive/` |
| Windows launchers | `shared/commands/` |
| Calibration scripts, data and analyses | `docs/Final/Calibration scalability/` |

## Compatibility work

- Updated every maintained `.cmd` launcher to use its new source, sketch,
  monitor or calibration path.
- Updated the four-module monitor import path to its moved shared parser.
- Updated scan-rate sweep scripts to find `shared/commands/` from their new
  location.
- Preserved Arduino sketch-folder naming where required, for example
  `four_module/four_module.ino`, so Arduino CLI can still compile the sketches.
- Kept the legacy command spellings (including `scalablity`) as compatibility
  entry points; their purpose is documented in
  `shared/commands/CURRENT_COMMANDS.md`.

## Scope

No acquisition algorithm, protocol layout, calibration data or historical
measurement result was changed. This update only relocates files and repairs
the references required to build, upload and start the existing components.

## Operational note

Historical reports retain their original paths intentionally. Use
`STRUCTURE.md` and `shared/commands/CURRENT_COMMANDS.md` for current locations
and commands.
