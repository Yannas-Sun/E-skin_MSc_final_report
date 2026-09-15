# GUI recording update — 2026-09-06

This document records the PC-side recording changes. STM32/Teensy firmware and USB frame formats are unchanged.

## Paths and scheduling

- Default output: `docs/Final/data scalability/data/<run_id>/`.
- Default schedule: `docs/Final/new_firmware_experiment_plan/halfday_schedule.csv`.
- `Use row` loads the planned modules, mode, condition, block and duration, then sends `MODE` and `SCAN_HZ`.
- Settings stores operator metadata only. Repeat is generated as 1/2/3. A short record defaults to 40 s with a 10 s startup segment; long records default to 310 s with a 10 s startup segment.

## Three-record batches

- Manual recording detects recently valid slots and mode before starting.
- `Record x3` locks the batch configuration and records three consecutive windows without resending `MODE` or `SCAN_HZ`.
- Each run has its own directory. The same `batch_id` and block are used with repeats 1/2/3. Dynamic loading remains operator-controlled.
- A missing module remains an anomaly in the planned configuration; the recorder does not silently reduce `N`.

## Parsing and integrity

- Serial buffering, sequence tracking and DELTA cache state persist across recording files.
- `seq gaps` counts forward sequence jumps in complete MUL1 packets. `missing MUL1` estimates missing packets from those jumps; it is not a physical ADC-scan loss count.
- A packet split across the start boundary is completed and parsed, but only bytes received inside the window are written to the new raw file. Cross-boundary fragments are recorded as events and are excluded from window byte, `K` and `q` totals.
- CRC, missing-module, unexpected-module, stale-update and mode mismatches can produce `CHECK REQUIRED`. The recorder does not retry or overwrite a run because of a check result.
- Byte ownership follows read time; packet ownership follows completion time. PC-to-packet time is not ADC acquisition time.
- Local build hashes identify local files. The matching-flash checkbox is an operator statement, not device flash read-back.
- M0–M3 identify CS/IRQ slots, not unique physical boards. Hardware mapping requires labels or notes. Target scan rate records the GUI/plan setting; measured packet rate is separate.

## Output files

Each run writes raw bytes, `packet_log.csv`, `module_log.csv`, `events.jsonl`, `summary.json`, `experiment_log.md` and initial metadata. `summary.schema_version=2` separates `scopes.full_run` from `scopes.main` and retains per-module `K/q`, update rates, missing updates, CRC results and cache-base chains.

## Runtime controls

- `Event` and `Mark` store PC-time annotations.
- `Resync` sends an explicit synchronisation command.
- `Stop` saves received data and cancels later windows.
- Disconnects and write failures cancel remaining windows.
- Opening Settings pauses heatmap refresh only; serial receive, parsing and recording continue.
- `Next` loads the next schedule row but does not start recording.

The offline test suite covers parser recovery, three-record batches, raw offsets, configuration locking, stop/cancel paths and error attribution. These tests do not establish hardware throughput or electrical timing.
