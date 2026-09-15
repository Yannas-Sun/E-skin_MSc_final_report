# FSR2

FSR2 is M1's second 16×16 sensing layer. All files below belong to this layer.

| Folder | Purpose |
| --- | --- |
| fit/raw/ | The complete multi-point training sweep. |
| fit/analysis/ | Frozen fitted model, per-cell parameters, and calibration plots. |
| two_point/ | Shared zero-load/U-load endpoint model from the same sweep. |
| evaluation/view_distribution/ | One directory per validation load; each contains capture data, plots, and model copies. |
| evaluation/analysis/ | Published cumulative error, dispersion, and latest-analysis pointer. |

The source sweep is fit/raw/FSR2_pressure_sweep_20260907_100734_973698.json; the endpoint model is two_point/FSR2_calibration_20260907_100736_029741.json.
