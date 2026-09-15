# N=4 simultaneous full-coverage retest after connector reinstallation

The operator confirmed simultaneous full-coverage loading of M0--M3. The earlier
fault was diagnosed as poor connector contact and the connector was reinstalled
before this batch. Original `zero_load` labels inside acquisition files are
preserved; `condition_correction.json` records the derived correction.

All three fixed 10--40 s main windows independently pass the raw audit. Across
the batch, 17,948 valid outer packets contain
71,792/71,792
expected module updates, with no CRC/layout, outer-sequence, inner-sequence,
base-chain or post-anchor reconstruction finding.

| Quantity | mean ± sample SD | n |
|---|---:|---:|
| packet rate / Hz | 199.413612 ± 0.068191 | 3 |
| mean MUL1 length / B | 1471.549848 ± 29.888287 | 3 |
| valid USB byte rate / Mbit/s | 2.347583 ± 0.048143 | 3 |
| ordinary ESKD K per module frame | 135.151943 ± 3.770944 | 3 |
| ESKF fraction / % | 0.519556 ± 0.008611 | 3 |
| same-rate saving versus 4216 B FULL / % | 65.096066 ± 0.708925 | 3 |

The three windows are consecutive temporal repeats in one post-reinstallation
setup. The observed recovery supports the practical connector diagnosis but is
not a randomized hardware-causality experiment.
