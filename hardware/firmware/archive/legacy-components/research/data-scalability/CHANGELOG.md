# Data Scalability changelog

## 2026-09-05 - Grouped calibration GUI support code under Main

- Updated the research README to point to `script/Main/` and its companion
  directories: `Main/Calibration`, `Main/Model`, `Main/Evaluation`, and
  `Main/Utility`.
- Updated the documented standalone commands and links after moving those
  directories under the GUI directory.
- No firmware source, build artefact, measurement data, or protocol logic was
  changed.

## 2026-08-30

- Updated the STM32 flash command to use pyOCD `halt` connection mode and the
  default post-program reset. This avoids waiting indefinitely for an
  unreliable or unconnected DAPLink `nRESET` line during normal flashing.

- Moved this package to `hardware/new/firmware/research/data-scalability/` and
  updated its build, upload and monitor launchers.
- Moved its shared calibration GUI, scripts, data and analysis outputs to
  `docs/Final/Calibration scalability/`; the firmware encoder and wire
  protocol are unchanged.

## 2026-08-29

- Reorganized fitted-analysis output into three fixed directories under each
  FSR: `fit/analysis/load_code/`, `fit/analysis/pressure_code/`, and
  `fit/analysis/pressure_resistance/`. New results are written directly into
  these directories instead of creating a timestamped analysis subdirectory;
  previous analysis directories are moved to `fit/archive/<timestamp>/` before
  replacement.
- Added `plot_pressure_resistance.py`. It converts ADC codes to FSR resistance
  using the current circuit (`3.3 V -> 1 kOhm -> FSR -> ADC node -> 10 kOhm ->
  GND`), converts load to per-cell pressure with the CAD effective-area matrix,
  and generates raw/fitted/mean/16x16 pressure-resistance plots, CSV
  parameters, and `pressure_resistance_model.json`.
- Updated the GUI fit-calibration completion chain to generate `load_code`,
  `pressure_code`, and `pressure_resistance` automatically. Existing model
  loading now prefers the fixed `load_code` and `pressure_code` paths while
  retaining legacy-layout read compatibility.
- Regenerated the current M1/FSR1 analysis from the existing sweep and placed
  its pressure-resistance results under the fixed `pressure_resistance`
  directory.
- Updated `estimate_pressure_from_frame.py` so its fixed pressure model and
  estimate outputs use `pressure_code/` (with legacy-layout read fallback),
  and documented the 1 kOhm series-resistor term in the ADC-to-resistance
  formula.
- Added `analyze_view_distributions.py` and the GUI `Capture 3 Views` workflow.
  One entered validation load now records the one-second per-cell mean as RAW,
  Gamma-adjusted NORM CAL, and FIT PRESS matrices, then generates per-cell CSV/JSON statistics
  plus combined and individual histogram/normal-reference plots under each
  FSR's `evaluation/view_distribution/<run>/` directory.
- Added `analyze_load_accuracy.py` to compare each recorded actual load with the
  256-cell mean FIT PRESS load, annotate mean/max/min absolute error rates, and
  save the plot, CSV, and JSON summary under `evaluation/analysis/error/`.
- Updated the two independent load-error plots: `load_error_rate_vs_load.png`
  shows absolute error rate (%), while `load_error_vs_load.png` now shows only
  `absolute error = inferred - actual` (g). Positive values indicate
  overestimation and negative values indicate underestimation. Zero-load records
  remain excluded from percentage-error statistics.
- Added `analyze_dispersion.py`, which first normalizes RAW, NORM CAL, and FIT
  PRESS with one shared zero-load baseline and one shared highest-load reference
  per data type, then calculates unitless CV, normalized IQR, normalized MAD,
  and variance at each load. It writes one plot per metric under
  `evaluation/analysis/dispersion/`; repeated loads are averaged before plotting.
- Moved load-accuracy outputs into `evaluation/analysis/error/` so error and
  dispersion analyses have separate output directories.
- Changed `CURRENT LOAD` and `Capture 3 Views` to collect all valid FULL/DELTA
  frames for one second, average each cell first, and only then calculate the
  load or generate the derived views and distributions.
- Changed the normal-reference curve in the distribution plots from white to
  red for clearer visual distinction.
- Documented the area-scaled pressure workflow: convert a fitted response with
  `build_pressure_area_model.py`, then estimate the current pressure from a
  RAW GUI frame with `estimate_pressure_from_frame.py`; results are stored in
  each FSR's `fit/analysis/pressure/` directory.
- The GUI now records fit-calibration loads as grams and automatically runs
  the area-scaled pressure conversion after the ADC fit completes.
- Updated `Start Fit Cal` to capture the current complete matrix immediately
  as the first `0 g` point; subsequent loads are entered and recorded manually.
- Extended FIT archiving to include each older
  `fit/analysis/pressure/<sweep>/` directory, preserving its area-pressure/Load
  model, CSV files, and plots under `fit/archive/<timestamp>/analysis/pressure/`.
- Added a `CURRENT LOAD` button in `TOOLS & SAVE`; it reports the mean load
  inferred from the one-second per-cell mean raw FSR frame and the area-scaled inverse LUT.
- Updated GUI Load estimation to discard cell estimates outside the central
  95% percentile interval before averaging; the status line reports excluded
  and clipped cell counts.
- Moved the `TOOLS & SAVE` panel to the upper-left of the GUI and enlarged the
  current-load readout; `CURRENT LOAD`, `pyOCD Reset`, and `Save Frame` remain
  grouped in the collapsible panel.
- Inset the FSR plotting grids after the panel relocation so the upper-left
  controls no longer cover the flat-top hexagon visualisations.
- Fixed the panel's child controls to move with it instead of remaining at
  their former bottom-left absolute positions.
- Moved the GUI and its calibration/fit scripts to
  hardware/new/firmware/tools/Calibration/script/Main/.
- Updated GUI data paths to the per-module/per-FSR DATA layout:
  two-point calibration, fit raw input, fit analysis, and fit archive.
- Enabled the per-cell response grid by default for automatic fit analysis.

## 2026-08-27

- Changed automatic `FIT PRESS` analysis to use
  `plot_pressure_calibration_monotonic.py`: per-cell isotonic regression,
  monotonic PCHIP forward interpolation, and inverse linear LUT. New
  pressure-response calibrations no longer default to the cubic polynomial
  analysis path.
- Extended `FIT PRESS` model loading to accept the monotonic
  isotonic/PCHIP/inverse-LUT result written by the shared Calibration analysis
  directory, while retaining compatibility with the original polynomial model.
- The fitted-calibration pressure input is now cleared after each successfully
  recorded pressure point; invalid entries remain visible for correction.
- Fixed duplicate pressure-submit callbacks when the input box loses focus;
  clearing the field no longer produces a false numeric-input error or duplicate
  pressure point.
- Added an independent GUI `Start Norm Cal` workflow. It captures 200 valid
  no-load frames and 200 valid full-load frames at each of six hexagon vertices,
  then writes a `calibrate_fsr.py`-compatible two-point JSON. The existing
  `Start Fit Cal` pressure sweep remains a separate workflow.
- Separated normalised calibration from fitted pressure calibration in the GUI:
  `NORM CAL`, `FIT PRESS`, and `RAW` are now independent display controls.
  Missing normalisation data no longer falls through to the fitted model, and
  missing fitted data no longer changes the selected display mode. The pressure
  capture controls are explicitly labelled `Start Fit Cal`/`End Fit Cal`, while
  the legacy two-point workflow remains `calibrate_fsr.py`.
- Added a standalone pressure-response analysis script under
  `hardware/new/firmware/tools/Calibration/`. It fits the captured raw ADC
  response per cell and for the all-cell mean, and exports plots plus models
  for subsequent calibration.
- Connected `End Cal` to the analysis script. Each completed pressure sweep
  now launches background fitting automatically; generated results are stored
  in the shared `Calibration/analysis/` directory.
- Added GUI pressure display mode. The display button now cycles through raw
  ADC, legacy normalised load, and per-cell fitted pressure; the newest model
  is loaded by module/FSR and bounded by its recorded pressure range.
- Reorganised the GUI sidebar into collapsible `VIEW & DISPLAY`,
  `CALIBRATION`, and `TOOLS & SAVE` panels. Panel layering now keeps controls
  readable above the FSR colour bars, and the tools panel starts collapsed.
- Updated display-mode fallback so a new pressure model can be opened directly
  when the legacy two-point normalisation JSON is not available.
- Updated the shared analysis workflow to archive older same-module/FSR JSON
  and processed results after a successful fit, keeping the newest calibration
  active.
- Archive discovery also covers the older per-module analysis directory naming
  used before results were moved to the shared `Calibration/analysis/` path.
- Cleaned generated Calibration outputs by retaining the newest calibration
  and pressure-sweep file for each module/FSR and the newest saved frame per
  data category; older outputs were moved to the Windows Recycle Bin.
- Fixed pressure-point entry in the GUI so both TextBox submission and the
  `Record` button use the entered numeric value; recorded values now remain in
  the field instead of being cleared automatically.
- Replaced the GUI's fixed zero-load/four-corner capture with an interactive
  pressure-response session. Each `Record` stores the entered pressure and
  the current complete 16x16 raw ADC matrix; `End Cal` saves a timestamped
  pressure-sweep JSON under the selected module.

## 2026-08-26

- Restored the original flat-top hexagonal FSR panel geometry in the GUI;
  the 16x16 data ordering and all other controls remain unchanged.
- Added a GUI `Gamma (1–10)` field and `Apply` button for changing the
  calibrated-display curve during a session. The default is `gamma = 4`, and
  `gamma = 1` restores linear display; raw ADC data and calibration references
  are unchanged.
- Changed the calibrated-load curve from `linear_load^2` to
  `linear_load^4`. Low-pressure variation is now suppressed more strongly,
  while the full-load endpoint remains 1. Raw ADC data and calibration
  references are unchanged.
- Fixed GUI calibration finalisation for the current four-corner workflow;
  calibration summaries now use the corner captures that were actually
  collected instead of requiring the standalone script's six-corner `right`
  capture. Repositioned the pyOCD, calibrated-display, module, calibration,
  and frame-save controls so their axes and status labels no longer overlap.
- Changed calibrated FSR display normalization from linear to a square curve:
  `calibrated_load = linear_load^2`. Low-load variation is compressed while
  changes near the calibrated full-load value become more visible. Raw ADC
  mode and the saved zero/full calibration references are unchanged. The
  STM32 normalized-output path uses the same curve when enabled.
- Added a GUI `Save Frame` button that writes the latest valid FSR matrix to a
  timestamped CSV in `Calibration/data/`.
- `Save Frame` writes direct labelled 16x16 FSR matrices matching the GUI;
  `All` saves separate FSR1 and FSR2 matrix files.
- Changed the FSR GUI from the hexagonal panel to a square 16x16 panel and
  reduced pressure calibration capture from six corners to four square
  corners. Grid labels and data ordering remain unchanged.
- Changed FSR2 acquisition storage to keep the MUX address in increasing order,
  removing the previous `15 - mux_address` reversal. The protocol and parser
  matrix dimensions remain unchanged.
- Removed the parser-global direction-calibration workflow from the GUI and
  parser display path. FSR panels now use only the fixed legacy
  `transpose + fliplr` mapping; existing direction-calibration JSON files are
  retained as historical data but are no longer loaded or applied.
- Added GUI FSR calibration controls: module `M0`–`M3` selection, current-view
  `FSR1`/`FSR2` selection, zero-load capture, and six-corner full-load capture.
- Added shared-stream calibration capture so the GUI does not open a second
  serial connection; results use the existing `Calibration/module_<id>/`
  output structure and timestamped JSON format.
- Added GUI-side calibration summary generation for per-cell zero median,
  full-load maximum, response span, noise interval, and problem flags.
- Added a GUI `Show CAL`/`Show RAW` toggle. Calibrated heatmaps normalise each
  cell using its saved zero-load and full-load limits, and the colour bar
  changes to a 0–1 calibrated load range.
- Added module/view-aware calibration-file reloads so changing module or view
  cannot reuse a different module's calibration range.
- Added GUI `Start DIR` direction calibration. The six-corner workflow records
  a no-load baseline and pressed response, selects a display transform, and
  saves it separately from pressure calibration.
- Added persistent parser-global direction loading and a live highlighted
  corner marker. One direction result applies to all modules and both FSR
  layers across GUI restarts.
- Added an asynchronous `pyOCD Reset` button to the data-scalability GUI.
  The button runs `pyocd reset --no-wait`, reports success or the final error
  line in the GUI, and supports optional probe UID and target arguments.

- Added a one-second Delta `ESKF` resynchronisation interval so a GUI/parser
  that starts after boot does not receive unusable `ESKD` frames without a
  cache baseline.
- Updated algorithm detection to use the ESK Delta flag, so a Delta full-sync
  `ESKF` is shown as `DELTA` rather than `FULL`.
- Added a GUI algorithm indicator derived from received frame markers, showing
  `FULL`, `DELTA`, or `SPATIAL SPARSE` and the active protocol frame type.
- Added a live measured USB data-rate line showing actual received `B/s`,
  `Mbit/s`, logical frame rate, and last frame length.
- Removed the ACC 3D image from the main GUI; ACC remains available as a
  text-only status view.
- Updated the new monitor to use the original GUI's regular-hexagon geometry,
  labels, FSR orientation, and `transpose + fliplr` display mapping.
- Added a new Python parser/GUI for `ESKF/ESKD/ESK0` and `ESPF/ESPD/ESP0`.
- Added Delta cache reconstruction, Spatial cache reconstruction, CRC32 checks,
  and `base_seq` validation to the monitor.
- Added `start_data_scalability_monitor.cmd` and an optional GUI view argument
  to `flash_data_scalability_pair.cmd`.
- Added an independent `data Scalability` firmware package under the existing
  `scalablity` experiment directory.
- Added a shared STM32 encoder with `FULL`, `DELTA`, and `SPATIAL` modes.
- Added `ESKF/ESKD/ESK0` Delta framing, cache comparison, `base_seq`, and CRC32.
- Added `ESPF/ESPD/ESP0` Spatial Sparse framing with the current six-row/six-column
  sentinel mask and a fixed-slot safety fallback for large change sets.
- Added a Teensy 4.1 bridge that sends mode commands over MOSI and forwards the
  validated logical frame length over USB.
- Added mode-specific STM32/Teensy build-and-flash scripts and operating notes.
- Preserved the existing `combined_system`, original `scalablity` sketch, and
  their upload scripts unchanged.
# Research data-scalability changelog

## 2026-09-05 - Updated calibration script references

- Updated the research README to point to the reorganised calibration scripts:
  `Main`, `Calibration`, `Model`, and `Evaluation`.
- No firmware source, build artefact, measurement data, or protocol logic was
  changed.
