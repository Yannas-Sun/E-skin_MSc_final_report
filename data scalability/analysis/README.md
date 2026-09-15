# Data scalability analyses

The analysis directories are dated evidence snapshots. The current paper relies on the 2026-09-07 final campaign and keeps the associated audits together.

| Directory | Role |
|---|---|
| 20260907_final_data_review | Final 114-record index, selection manifests and evidence review |
| 20260907_delta_zero_review | 45-window DELTA zero-load audit and per-slot activity statistics |
| 20260907_delta_followup_review | Passing M1 large-area follow-up batch |
| 20260907_delta_press_release_review | Passing M1 repeated press/release batch |
| 20260907_delta_rolling_review | Passing M1 rolling batch |
| 20260907_n2_large_area_review | Passing simultaneous M1+M3 batch |
| 20260907_n4_connector_retest_review | Passing N=4 post-reinstallation batch and hash verification |
| 20260907_n4_full_coverage_review | Diagnostic pre-reinstallation N=4 batch |
| 20260907_delta_large_area_review | Earliest M1 large-area diagnostic audit |
| 20260907_full_completion_review | Campaign completion and timing audit |
| 20260907_n3_full_review | Earlier 2026-09-07 FULL review retained for provenance |

The 2026-09-06 review snapshots were superseded by the final campaign and are in ../archive/legacy_analysis/. They are preserved byte-for-byte and are not used by the current paper. The active final-review files are aligned to the PDF counts (114 retained, 90 zero-load selected, 15 dynamic selected, 105 total selected). The former 111/102 snapshot is preserved under `20260907_final_data_review/history/superseded_111_102_20260913/`.
