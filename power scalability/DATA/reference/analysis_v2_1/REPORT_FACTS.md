# Power report 2.1: reproducible recorded-data facts

18 continuous USB-read YAML records (9 ZERO, 9 MAX), FULL at 200 Hz; 13 separate legacy blocked-standby CSV records. Standby YAML duplicates are excluded.

Every exact continuous condition has R1 only. N=1: four labelled modules; N=2: two combinations; N=3: two combinations; N=4: one combination. Different combinations are not repeat recordings.

## Continuous USB-read results

| Load | N | Combination | Current sum (mA) | Output power estimate (mW) | Lowest module representative (V) | Lowest module MIN field (V) |
|---|---:|---|---:|---:|---:|---:|
| MAX | 1 | M0 | 19.689 | 64.600 | 3.231 | 3.231 |
| MAX | 1 | M1 | 20.110 | 65.981 | 3.250 | 3.249 |
| MAX | 1 | M2 | 19.897 | 65.282 | 3.247 | 3.247 |
| MAX | 1 | M3 | 20.340 | 66.715 | 3.248 | 3.248 |
| MAX | 2 | M0+M1 | 39.968 | 131.015 | 3.241 | 3.241 |
| MAX | 2 | M2+M3 | 39.379 | 129.084 | 3.245 | 3.244 |
| MAX | 3 | M0+M1+M2 | 59.328 | 194.359 | 3.237 | 3.237 |
| MAX | 3 | M1+M2+M3 | 59.617 | 195.305 | 3.232 | 3.232 |
| MAX | 4 | M0+M1+M2+M3 | 78.720 | 257.651 | 3.237 | 3.236 |
| ZERO | 1 | M0 | 18.160 | 59.565 | 3.235 | 3.235 |
| ZERO | 1 | M1 | 18.380 | 60.305 | 3.255 | 3.255 |
| ZERO | 1 | M2 | 18.360 | 60.239 | 3.249 | 3.249 |
| ZERO | 1 | M3 | 18.400 | 60.352 | 3.251 | 3.250 |
| ZERO | 2 | M0+M1 | 36.016 | 118.168 | 3.234 | 3.234 |
| ZERO | 2 | M2+M3 | 36.534 | 119.795 | 3.248 | 3.248 |
| ZERO | 3 | M0+M1+M2 | 54.481 | 178.480 | 3.224 | 3.224 |
| ZERO | 3 | M1+M2+M3 | 54.851 | 179.692 | 3.245 | 3.245 |
| ZERO | 4 | M0+M1+M2+M3 | 72.513 | 237.408 | 3.240 | 3.240 |

## Independent N=1 prediction

Residual = 100 × (observed branch sum − sum of separately recorded N=1 currents) / predicted sum. MAX results require equivalent loading; module labels are assumed consistent across runs.

| Load | Combination | Predicted (mA) | Observed (mA) | Residual (%) |
|---|---|---:|---:|---:|
| MAX | M0+M1 | 39.799 | 39.968 | 0.4246 |
| ZERO | M0+M1 | 36.540 | 36.016 | -1.4340 |
| MAX | M2+M3 | 40.237 | 39.379 | -2.1324 |
| ZERO | M2+M3 | 36.760 | 36.534 | -0.6148 |
| MAX | M0+M1+M2 | 59.696 | 59.328 | -0.6165 |
| ZERO | M0+M1+M2 | 54.900 | 54.481 | -0.7632 |
| MAX | M1+M2+M3 | 60.347 | 59.617 | -1.2097 |
| ZERO | M1+M2+M3 | 55.140 | 54.851 | -0.5241 |
| MAX | M0+M1+M2+M3 | 80.036 | 78.720 | -1.6443 |
| ZERO | M0+M1+M2+M3 | 73.300 | 72.513 | -1.0737 |

## Matched load comparisons

| Combination | ZERO (mA) | MAX (mA) | Increase (mA) | Increase (%) |
|---|---:|---:|---:|---:|
| M0 | 18.160 | 19.689 | 1.529 | 8.4196 |
| M1 | 18.380 | 20.110 | 1.730 | 9.4124 |
| M2 | 18.360 | 19.897 | 1.537 | 8.3715 |
| M3 | 18.400 | 20.340 | 1.940 | 10.5435 |
| M0+M1 | 36.016 | 39.968 | 3.952 | 10.9729 |
| M2+M3 | 36.534 | 39.379 | 2.845 | 7.7873 |
| M0+M1+M2 | 54.481 | 59.328 | 4.847 | 8.8967 |
| M1+M2+M3 | 54.851 | 59.617 | 4.766 | 8.6890 |
| M0+M1+M2+M3 | 72.513 | 78.720 | 6.207 | 8.5598 |

## Limits on interpretation

- Every exact continuous-state/mode/frequency/load/module-combination condition has one recording (R1); repeat SD is unavailable. Different modules/combinations are not repeats.
- Fields named avg are treated as recorded representative instrument readings, not verified time averages. DMM MIN/MAX are not repeat SD or verified high-speed transient extrema.
- Currents were measured sequentially by branch; their sum is a module-supply demand estimate, not a simultaneously measured total-current waveform or peak.
- Teensy USB power is excluded. V_source times the branch-current sum estimates module-supply output power, not converter input power, efficiency or whole-system power.
- MAX records state 2000 g but omit area and application: per-module versus whole-system mass, position and layer are unresolved. Loaded prediction comparisons are conditional on equivalent module loading.
- Continuous YAML dates, start times and operator are absent; nominal 30 s warm-up and 10 s measurement fields are prefilled and not independently confirmed.
- Fault counters are template-default zero without confirmed observation; they do not establish fault-free operation.
- M0..M3 identify modules as written in experiment records; consistent physical identity across combinations has not been independently verified by hardware UID.
- Temperature readings do not establish thermal equilibrium. Startup, fast transients, full supply-board capacity, maximum module count and 20% headroom are unverified.
- Blocked and continuous results come from separate records, not a randomized paired intervention; state differences are descriptive, not an isolated causal estimate.

5 continuous current representative readings fall outside their recorded MIN/MAX range by at most 0.005 mA. Original readings are retained.

- PS01_N2_F200_ZERO_M0-M1_USB_RX_R1 / M1: Representative=18.055 mA; MIN=18.06; MAX=18.31; outside by 0.005000 mA. Check instrument display/rounding; do not replace values.
- PS01_N3_F200_ZERO_M0-M1-M2_USB_RX_R1 / M0: Representative=17.968 mA; MIN=17.97; MAX=17.99; outside by 0.002000 mA. Check instrument display/rounding; do not replace values.
- PS01_N3_F200_ZERO_M0-M1-M2_USB_RX_R1 / M2: Representative=18.383 mA; MIN=18.35; MAX=18.38; outside by 0.003000 mA. Check instrument display/rounding; do not replace values.
- PS01_N3_F200_ZERO_M1-M2-M3_USB_RX_R1 / M3: Representative=18.383 mA; MIN=18.35; MAX=18.38; outside by 0.003000 mA. Check instrument display/rounding; do not replace values.
- PS01_N4_F200_ZERO_M0-M1-M2-M3_USB_RX_R1 / M1: Representative=18.302 mA; MIN=18.27; MAX=18.3; outside by 0.002000 mA. Check instrument display/rounding; do not replace values.

Lowest continuous module MIN field: 3.224 V, PS01_N3_F200_ZERO_M0-M1-M2_USB_RX_R1, M0; margin above 3.135 V: 89.0 mV. This is a recorded DMM value, not a high-speed transient guarantee.
