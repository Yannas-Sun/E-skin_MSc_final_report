# Current paper workflow

## Acquisition

Calibration is performed independently for FSR1 and FSR2 on module M1. For each layer, the operator records a 22-point whole-layer loading sweep from 0 to 5000 g. Every point contains 200 fresh FULL frames; a per-cell temporal median produces one 16x16 RAW ADC matrix. Loading pieces are centred and a silicone pad with rigid support boards distributes the load as evenly as practicable. The experiment reports equivalent whole-layer mass because local force is not measured.

## Calibration models

The zero-load and final-load matrices from the same sweep define the shared two-point endpoints. Four mappings are evaluated on that common range:

- LINEAR uses each cell's measured endpoints.
- GAMMA applies the fixed gamma value of 4 between those endpoints.
- FIT PRESS uses a monotonic per-cell inverse LUT fitted to all sweep points.
- Shared LUT uses one monotonic inverse LUT fitted to the layer-mean response.

The source sweep, endpoint model, fitted model, and source hashes are retained for reproducibility. FSR1 and FSR2 are never pooled as one calibration model.

## Validation and analysis

Validation captures are independent from the training sweep. Each saved capture contains 200 fresh FULL frames, the temporal-median RAW matrix, the four model predictions, and exact endpoint/fitted model copies. FSR2 has 21 captures at 20 distinct loads from 0 to 1969 g; FSR1 has 20 captures at the corresponding distinct loads, with 213 g replacing 212 g.

The evaluation scripts generate single-capture distributions, cumulative load-error summaries, and spatial CV, variance, IQR, and MAD. Capture-to-capture SD is shown only where a load has at least two captures. The 200 frames and 256 cells are not independent loading repeats.

## Reproduction entry points

- script/Main/data_scalability_monitor.py starts acquisition and validation.
- script/Main/Calibration/calibrate_fsr.py derives shared endpoints.
- script/Main/Model/plot_pressure_calibration_monotonic.py fits the 256-cell response model.
- script/Main/Model/plot_calibration_comparison.py generates model comparisons.
- script/Main/Evaluation/analyze_view_distributions.py handles one capture.
- script/Main/Evaluation/analyze_validation_session.py and the companion error/dispersion scripts generate current report summaries.
