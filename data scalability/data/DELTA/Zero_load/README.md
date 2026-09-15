# DELTA zero-load matrix

The 45 selected windows cover every non-empty subset of the four slots, with three consecutive windows per combination. Main-window integrity checks found no CRC, sequence, missing-update or cache-chain findings in the selected set.

| N | Combinations | Windows | DELTA USB at 200 Hz (Mbit/s) | Mean ordinary K | Mean packet (B) | Same-rate byte reduction |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4 | 12 | 0.232562 +/- 0.026405 | 8.26 | 145.24 | 86.60% |
| 2 | 6 | 18 | 0.403900 +/- 0.025933 | 8.64 | 251.98 | 88.16% |
| 3 | 4 | 12 | 0.577646 +/- 0.038721 | 9.10 | 360.74 | 88.63% |
| 4 | 1 | 3 | 0.762543 +/- 0.012375 | 10.04 | 475.15 | 88.73% |

Averages include every valid ESKF frame and use complete packet bytes in the fixed 10-second-to-stop window. The three windows per combination are temporal repeats within one setup. Detailed per-combination tables and full audit notes remain in the CSV files and in analysis/20260907_delta_zero_review/.
