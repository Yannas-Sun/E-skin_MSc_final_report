# PDF-aligned data evidence review

This active review is aligned to the existing `main_final.pdf`. It records the evidence boundary used by the report and does not change raw measurements, the LaTeX source, or the PDF. The previous 111-record review is preserved in `history/superseded_111_102_20260913/`.

## Active inventory

| Group | Retained records | PASS | CHECK | Selected for report analysis |
|---|---:|---:|---:|---:|
| `FULL`, zero load | 48 | 47 | 1 | 45 |
| `DELTA`, zero load | 45 | 45 | 0 | 45 |
| `DELTA`, dynamic | 21 | 16 | 5 | 15 |
| **Total** | **114** | **108** | **6** | **105** |

The selected set is the union of 90 zero-load records and 15 dynamic records. The 15 dynamic records are five complete three-window batches: later M1 large-area loading, repeated press/release, rolling, simultaneous M1+M3 coverage, and the post-reinstallation M0-M3 full-coverage retest. The pre-reinstallation N=4 batch and the earliest M1 dynamic batch remain diagnostic evidence and are not counted as selected performance batches.

## Zero-load matrix

`FULL` and `DELTA` each cover all 15 non-empty subsets of the four slots. Each subset has three consecutive windows. The selected zero-load matrix therefore contains 45 `FULL` and 45 `DELTA` records. These are temporal windows within one setup, not independent physical replicates.

## Dynamic selection

The post-reinstallation N=4 batch is independently audited PASS for all three windows. Its audit and statistics are in [`20260907_n4_connector_retest_review/`](../20260907_n4_connector_retest_review/). The earlier N=4 batch remains a two-CHECK/one-PASS diagnostic batch, so it is retained but excluded from the selected dynamic set.

## Source files and indexes

Each of the 114 records retains six source files (684 files in total): `mul1_raw.bin`, `packet_log.csv`, `module_log.csv`, `events.jsonl`, `summary.json`, and `experiment_log.md`.

- [`data/run_index.csv`](../../data/run_index.csv) - complete 114-record inventory.
- [`data/primary_matrix.csv`](../../data/primary_matrix.csv) - 90 selected zero-load records.
- [`data/dynamic_analysis_selected.csv`](../../data/dynamic_analysis_selected.csv) - 15 selected dynamic records.
- [`data/analysis_selected.csv`](../../data/analysis_selected.csv) - union of the two selected sets, 105 records.
- [`evidence_review.json`](evidence_review.json) - machine-readable counts, batch metrics, and audit links.

The indices are eligibility lists, not a population to pool across loading conditions. Reported means and SDs retain the definitions in the PDF; CHECK records are not silently converted to PASS.