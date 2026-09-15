# Current calibration data manifest

The `DATA` tree contains only the M1/FSR1 and M1/FSR2 records used by the current report. FSR2 supplies the main-text calibration results; FSR1 is the independent second-layer application reported in Appendix E.

| Path | Current-paper content |
| --- | --- |
| `module_1/FSR1/fit/raw/` | Complete 22-point FSR1 RAW sweep, 0–5000 g. |
| `module_1/FSR2/fit/raw/` | Complete 22-point FSR2 RAW sweep, 0–5000 g. |
| `module_1/*/two_point/` | Shared zero and final-load endpoint models derived from the same sweep. |
| `module_1/*/fit/analysis/` | Frozen 256-cell monotonic inverse models and calibration plots. |
| `module_1/*/evaluation/view_distribution/load_*/` | Current validation captures by recorded load, with RAW predictions and frozen model copies. FSR2 has two capture directories at 140 g; every other recorded load has one. |
| `module_1/*/evaluation/analysis/error/` | Published cumulative LINEAR, GAMMA, FIT PRESS, and Shared LUT error outputs. |
| `module_1/*/evaluation/analysis/dispersion/` | Published CV, variance, IQR, MAD, and supplementary SD outputs. |
| `module_1/*/evaluation/analysis/latest_analysis.json` | Pointer to the retained canonical full-session analysis. |

The capture roots and model copies are read-only evidence. Timestamped analysis histories from superseded reruns and material from earlier calibration workflows are not retained.
