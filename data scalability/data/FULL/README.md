# FULL zero-load matrix

This directory contains the 48 FULL zero-load recordings for all 15 non-empty subsets of the four configured slots. The report selects 45 windows: three consecutive windows for each combination. Selected packet lengths follow the fixed envelope model 24 + 4M + 1044N with M=4.

| Active modules N | Combinations | Selected windows | Mean packet length (B) | USB at 200 Hz (Mbit/s) |
|---:|---:|---:|---:|---:|
| 1 | 4 | 12 | 1,084 | 1.736573 +/- 0.001025 |
| 2 | 6 | 18 | 2,128 | 3.407991 +/- 0.001895 |
| 3 | 4 | 12 | 3,172 | 5.076696 +/- 0.007657 |
| 4 | 1 | 3 | 4,216 | 6.747828 +/- 0.001148 |

The original 48 records and their PASS/CHECK history remain in ../run_index.csv. The replacement M0+M1+M2 batch is represented in the selected matrix without deleting earlier records. Window-level standard deviations describe temporal and combination variation, not independent hardware repeatability.
