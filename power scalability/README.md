# Power scalability

Evidence package for the report's module current, voltage, temperature and power analysis.

## Report links

- `Imperial College Individual Project Template_LaTeX/method/power.tex`
- `Imperial College Individual Project Template_LaTeX/result/power.tex`
- `Imperial College Individual Project Template_LaTeX/discussion/power_outline.tex`
- `Imperial College Individual Project Template_LaTeX/appendix/power.tex`
- Current figures: `Imperial College Individual Project Template_LaTeX/figures/power/`

## Contents

- `DATA/raw/canonical/`: source YAML, photographs, retests and `power_raw.csv`.
- `DATA/raw/intake/`: voltage-intake supplements.
- `DATA/analysis/current/`: current reviews, tables and figure exports.
- `DATA/analysis/retest_reviews/`: pointwise retest provenance.
- `DATA/analysis/provenance/`: path and hash manifests.
- `DATA/reference/`: frozen earlier inputs retained by current manifests.
- `DATA/archive/`: superseded previews.
- `script/Main/`: analysis utilities and pipeline entry points.

The report uses all 15 non-empty module combinations under configured 200 Hz `FULL` acquisition. Electrical readings are static descriptive measurements; they do not establish transient supply capacity or thermal equilibrium.

The neighbouring LaTeX source is excluded by its `.gitignore`.
