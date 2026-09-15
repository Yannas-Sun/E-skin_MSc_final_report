# Current data snapshot

The current variable-length FULL/DELTA campaign contains 114 recordings and 684 source files. The CSV indexes below define the evidence selection used by the report.

| Group | Recordings | Main-window PASS | CHECK | Selected windows |
|---|---:|---:|---:|---:|
| FULL zero load | 48 | 47 | 1 | 45 |
| DELTA zero load | 45 | 45 | 0 | 45 |
| DELTA dynamic | 21 | 16 | 5 | 15 |
| Total | 114 | 108 | 6 | 105 |

- All 114 records: run_index.csv
- 90-window zero-load matrix: primary_matrix.csv
- 15-window dynamic performance set: dynamic_analysis_selected.csv
- 105-window combined selection: analysis_selected.csv
- Seven-batch dynamic diagnostics: dynamic_diagnostic_statistics.csv
- Source paths and hashes: path_map.csv
- FULL matrix: FULL/README.md
- DELTA overview: DELTA/README.md
- DELTA zero-load matrix: DELTA/Zero_load/README.md
- DELTA dynamic batches: DELTA/Dynamic_load/README.md

Each run retains its raw binary stream, packet and module logs, summary metadata and experiment log. The first 10 seconds remain in the files; the main report window starts at 10 seconds and ends at recording stop. Historical pre-variable-SPI records are kept separately in history/ and are not pooled with this snapshot.
