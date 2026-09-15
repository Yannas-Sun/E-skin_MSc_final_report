# ACC array CMake configuration fix — 2026-08-30

## Problem

The ACC array launcher failed during CMake configuration with exit code 1.
The shared build directory contained a stale `CMakeCache.txt` from an older
OneDrive checkout and retained the old source/toolchain paths.

## Fix

`stm32/applications/acc_array/flash_selected_acc.ps1` now invokes CMake with
`--fresh` before every ACC selection build. The requested `ACC_SELECTED` value
is therefore configured from the current repository path every time.

## Validation

- The current repository path is used as `CMAKE_HOME_DIRECTORY`.
- `ACC_SELECTED=0` remains the complete nine-device selection.
- `ACC_SELECTED=1..9` remains the single-device selection.
- The existing build directory is safely regenerated rather than using its
  previous source-path cache.

## Changelog

- 2026-08-30: fixed stale CMake-cache failures in the ACC array launcher;
  documented the recovery behaviour in the ACC application README.
- 2026-08-30: changed standalone ACC array DAPLink flashing from `10 kHz` to
  the project-validated `1 MHz` SWD clock; sensor SPI and ACC ODR are unchanged.
