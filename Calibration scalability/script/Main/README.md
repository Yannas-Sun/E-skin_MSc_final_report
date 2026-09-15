# Main scripts

| Path | Purpose |
| --- | --- |
| data_scalability_monitor.py | GUI entry point for acquisition, calibration, and validation. |
| calibration_measurement.py | Frozen-model validation capture and prediction writer. |
| calibration_shared_endpoints.py | Shared-endpoint sweep controller and model generation. |
| Calibration/calibrate_fsr.py | Endpoint calibration model builder. |
| Model/ | Monotonic response fitting and LINEAR/GAMMA/FIT PRESS comparison plots; Shared LUT is evaluated by Evaluation/shared_lut_baseline.py. |
| Evaluation/ | Capture distributions, load error, dispersion, and refresh preflight. |
| Utility/ | Portable path and range helpers. |


