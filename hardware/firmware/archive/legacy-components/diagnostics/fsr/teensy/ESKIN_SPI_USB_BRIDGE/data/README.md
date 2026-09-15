# E-SKIN Generated Data

This directory keeps generated measurement data separate from the Teensy and
Python source files.

```text
data/
├── calibration/
│   ├── fsr1.json
│   ├── fsr2.json
│   └── archive/
├── raw_frames/
│   ├── fsr1/
│   └── fsr2/
└── row_tests/
```

- `calibration/fsr1.json` and `calibration/fsr2.json` are historical
  per-region calibration records. The current raw-data GUI does not load them.
- `calibration/archive/` contains calibration files created before this folder
  structure was introduced. They are preserved for traceability and are not
  selected automatically.
- `raw_frames/fsr1/` and `raw_frames/fsr2/` contain timestamped raw 16 x 16 ADC
  CSV files created by the **Save raw frame** button.
- `row_tests/` contains timestamped JSON results from `test_adc_rows.py`.

Select the region when starting the Heatmap:

```powershell
python -u live_fsr_heatmap.py --port COM9 --region fsr1
python -u live_fsr_heatmap.py --port COM9 --region fsr2
```

The current GUI accepts `--raw-output-directory` to override the automatic
raw-frame destination. `test_adc_rows.py` accepts `--output` for its JSON
result. Calibration command-line options have been removed from the live GUI.
