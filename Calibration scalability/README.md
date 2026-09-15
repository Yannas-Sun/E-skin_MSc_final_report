# Calibration scalability

Evidence package for the two independently calibrated 16×16 FSR layers used by the report.

## Report links

- `Imperial College Individual Project Template_LaTeX/method/calibration.tex`
- `Imperial College Individual Project Template_LaTeX/result/calibration.tex`
- `Imperial College Individual Project Template_LaTeX/discussion/calibration.tex`
- `Imperial College Individual Project Template_LaTeX/appendix/calibration.tex`
- Current figures: `Imperial College Individual Project Template_LaTeX/figures/calibration/v2_7/`

## Contents

- `DATA/`: M1 training sweeps, validation captures, fitted models and per-cell outputs.
- `script/`: acquisition, calibration, fitting and plotting scripts.
- `audit/`: checks and machine-readable summaries used by the report.
- `docs/`: calibration notes and provenance.

## Evidence boundary

Each layer uses a separate 22-point, 0–5000 g whole-layer sweep with 200 `FULL` frames per point. The report evaluates FSR2 in the main text and FSR1 in Appendix E. Validation captures are separate from training sweeps.

## Reproduction

Run scripts from this directory with relative paths, for example:

```text
python script/Main/calibrate_fsr.py --port COM9 --module 0 --fsr FSR1
```

The neighbouring LaTeX source is excluded by its `.gitignore`; this package retains evidence and supporting material.
