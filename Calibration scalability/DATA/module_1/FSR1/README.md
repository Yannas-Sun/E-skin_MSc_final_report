# FSR1

FSR1 is M1's first 16×16 sensing layer. All files below belong to this layer.

| Folder | Purpose |
| --- | --- |
| fit/raw/ | The complete multi-point training sweep. |
| fit/analysis/ | Frozen fitted model, per-cell parameters, and calibration plots. |
| two_point/ | Shared zero-load/U-load endpoint model from the same sweep. |
| evaluation/view_distribution/ | One directory per validation load; each contains capture data, plots, and model copies. |
| evaluation/analysis/ | Published cumulative error, dispersion, and latest-analysis pointer. |

The source sweep is fit/raw/FSR1_pressure_sweep_20260907_082602_404396.json; the endpoint model is two_point/FSR1_calibration_20260907_082603_458190.json.
