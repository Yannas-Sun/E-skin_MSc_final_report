# Power scalability figures

_E-SKIN report figures · Updated 2026-09-02 · English artwork_

---

Seven figures generated from [power_raw.csv](../../../../DATA/raw/canonical/power_raw.csv). Numerical results and fits are unchanged.
Return to the [analysis report](../../../../archive/historical_documents/power_scalability_measurement_plan_cn_original.md).

| Figure | PNG preview | PDF | SVG | Data |
|---|---|---|---|---|
| **1. Frequency/load screening** | [PNG](single_module_screening.png) | [PDF](single_module_screening.pdf) | [SVG](single_module_screening.svg) | [Raw](../../../../DATA/raw/canonical/power_raw.csv) |
| **2. Current and power scaling** | [PNG](current_power_scaling.png) | [PDF](current_power_scaling.pdf) | [SVG](current_power_scaling.svg) | [Scaling](../power_scaling.csv) |
| **3. Voltage margin** | [PNG](voltage_scaling.png) | [PDF](voltage_scaling.pdf) | [SVG](voltage_scaling.svg) | [Scaling](../power_scaling.csv) |
| **4. Source-to-module voltage drop** | [PNG](module_voltage_drop.png) | [PDF](module_voltage_drop.pdf) | [SVG](module_voltage_drop.svg) | [Branches](../branch_summary.csv) |
| **5. Branch current** | [PNG](branch_current_balance.png) | [PDF](branch_current_balance.pdf) | [SVG](branch_current_balance.svg) | [Branches](../branch_summary.csv) |
| **6. Recorded temperatures** | [PNG](temperature_scaling.png) | [PDF](temperature_scaling.pdf) | [SVG](temperature_scaling.svg) | [Thermal](../thermal_summary.csv) |
| **7. Separately recorded maxima** | [PNG](peak_current_upper_estimate.png) | [PDF](peak_current_upper_estimate.pdf) | [SVG](peak_current_upper_estimate.svg) | [Scaling](../power_scaling.csv) |

All canvases are 180 mm wide. PNGs are opaque at 300 dpi; PDFs embed fonts; SVGs retain editable text.
Use PDF/SVG in a report or presentation when supported.

`N=1` combines four distinct module references, not four repeats of one module. `N=2–4` have one run per condition.
Grey matrix cells mean an absent module/run combination. Dashed model extensions are not validated measurements.
Temperature timing remains incomplete; sums of separately recorded maxima are not simultaneous current peaks.

Generation details and source/export hashes: [figure_manifest.json](figure_manifest.json).
File checks: [figure_validation.json](figure_validation.json).
Rebuild instructions: [folder README](../../../README.md).
