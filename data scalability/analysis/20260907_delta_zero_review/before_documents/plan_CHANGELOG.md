# Changelog

## 2026-09-07 - FULL zero-load primary matrix complete after M012 retest and N=4

- Six new captures passed all main-window checks: three M012 retests and three N=4 runs. Independently verified 48,070 MUL1 packets, 168,243 ESKF frames and 192,280 module_log rows without new CRC/sequence/slot/log inconsistencies. The three full-capture CHECK results contain only a 1 B trailing recording fragment.
- Organized the retest under `FULL/N=3/200Hz/M0_M1_M2/Batch_20260907_004948_668301/Repeat_1..3/`, leaving the original three directories intact. N=4 uses `FULL/N=4/200Hz/M0_M1_M2_M3/Repeat_1..3/`. All 36 original files (208,073,646 bytes) passed pre/post-move SHA256 checks.
- Selected one complete three-window batch for each of all 15 configurations: the whole M012 retest batch replaces the original batch's position in the 45-run primary matrix. This is a batch-level choice, not a rate-based filter; the old slow M013 PASS run remains selected. All 48 recorded windows remain indexed, including the earlier failure and two supplemental M012 PASS windows.
- Added explicit eligibility versus primary-selection fields, a 45-run primary_matrix.csv, primary statistics, all-PASS supplemental statistics, all-run diagnostics and per-batch results. Totals: 47 main PASS / 1 CHECK, 16 recorded batches, 288 original files. The retest does not establish that all recordings were error-free.
- Evidence and selection manifest: `data scalability/analysis/20260907_full_completion_review/`. Updated data/FULL/N3/N4 catalogs; no schedule CSV, original data, firmware, GUI, report or figures changed. Completion covers FULL zero-load only; temporal repeats are not independent rebuilt Blocks.

## 2026-09-07 - N=3 FULL data organized with one failed main window

- All four three-slot configurations have three recorded windows: 12 captures, 11 main PASS and one main CHECK. The M0_M1_M2 first capture contains a CRC failure at 19.4723392 s and a 1024 B shortfall relative to the declared frame layout; a second sequence skipped by the live parser is recoverable as a complete CRC-valid packet from raw. Preserve the failed original and do not equate the two skipped sequence numbers with two physically lost packets.
- M0_M1_M3 Repeat 3 remains eligible despite its 199.123828 Hz rate. A 123 ms bridge enqueue gap and a separate 301.3735 ms PC completion gap are documented; do not remove the slower PASS run or infer SPI saturation from these timestamps alone.
- Organized all twelve captures into `data scalability/data/FULL/N=3/200Hz/<combination>/Repeat_1..3/`. All 72 originals (364,788,907 bytes) passed pre/post-move SHA256 verification; original metadata, states and bytes remain unchanged.
- The performance table uses eligible n=2 for M0_M1_M2 and n=3 for the other configurations. All-run diagnostic statistics retain each original n=3, including the failure for reliability assessment. Combined indexes contain 42 runs / 14 configurations / 252 files, with 41 eligible main windows and an explicit CHECK flag.
- Evidence, time analysis and mapping are in `data scalability/analysis/20260907_n3_full_review/`. One additional clean M0_M1_M2 window and the three N=4 windows remain necessary. No firmware, GUI, schedule CSV, historical data or report figures were changed.

## 2026-09-06 - N=2 FULL zero-load combinations completed

- Audited all six two-slot combinations, three consecutive captures each: 18/18 main windows PASS. Independently checked 144,212 complete MUL1 packets, 288,424 ESKF frames and 576,848 module_log rows; all complete packets are 2128 B, with no CRC/sequence/slot/log mismatch. Full windows: 2 PASS and 16 CHECK for a 1 B trailing recording fragment only.
- Organized into `data scalability/data/FULL/N=2/200Hz/<slot_combination>/Repeat_1..3/`. All 108 original files (393,046,829 bytes) passed pre/post-move SHA256 verification. Original metadata, content and embedded capture paths are preserved.
- Added combination mean ± sample SD and temporal n=3 / batch n=1, with evidence and mappings in `data scalability/analysis/20260906_n2_full_review/`. Combined active indexes now cover N=1 and N=2: 30 runs, 10 configurations and 180 original files.
- FULL zero-load coverage under the three-window recording workflow is 30/45 captures. N=3 four combinations and N=4 one combination remain; these temporal repeats do not complete three independent planned Blocks. The schedule CSV, report and historical data were not rewritten.

## 2026-09-06 - First completed FULL zero-load data classified

- Verified twelve completed N=1 / target 200 Hz / FULL / zero-load captures, three consecutive windows for each slot M0–M3. All main windows passed; independently checked 96,193 complete packets and 72,096 main-window packets. Full-capture CHECK is limited to a 1 B trailing recording fragment.
- Organized into `data scalability/data/FULL/N=1/200Hz/M0..M3/Repeat_1..3/`. Preserved all original content and metadata; all 72 files (159,181,044 bytes) passed pre/post-move SHA256 comparison. Run/file mapping and audit are in `data scalability/analysis/20260906_current_data_review/`.
- Added per-slot mean ± sample SD and temporal n=3, batch n=1. These windows do not mark three independent planned Blocks complete. N=2–4, DELTA and dynamic conditions remain outstanding in this snapshot; the schedule CSV and report were not rewritten.

## 2026-09-06 - Continuous parsing across recording boundaries

- Fixed Record clearing an incomplete MUL1 packet from the live framer, which could create false session sequence gaps and DELTA cache errors. Keep live parsing continuous and translate stream offsets into per-recording raw offsets.
- Audit start-crossing packets separately: retain only the bytes actually received within the file, exclude them from complete-packet rate/K/q and file-cache baselines, and preserve genuine sequence/CRC/module/parser errors. Rename the GUI lost label to missing MUL1 to distinguish packet-sequence estimates from physical scans.
- Read-only audit of the three current FULL/M0 captures found a complete CRC-valid packet split between the first and second raw files; all three main windows passed. Preserve the original data and summaries. Evidence: data scalability/analysis/20260906_record_boundary/ANALYSIS_CN.md.
- Validation: 20 recorder, 26 GUI/serial integration and 7 detector tests plus parser self-test passed, including FULL/DELTA boundaries in three consecutive captures and a genuine missing packet. Backup and deployment hashes: tmp/gui_stream_boundary_20260906. Restart the GUI to load the fix; no device firmware change.

## 2026-09-06 - Record x3

- Each GUI Record click now queues three consecutive captures under the same frozen configuration. Default: 3 x 40 s, each retaining its own 10 s prefix and separate files.
- Repeat is automatic 1/2/3 with a shared batch_id and unchanged Block. These are consecutive time windows under one setup, not independently rebuilt blocks or automatic physical reloading.
- Stop/disconnection/recording IO failure cancels remaining captures. Settings pauses display only. Preserve original plan repeat as planned_repeat; the existing single-run CSV is not automatically converted into a three-block completion record.
- Installed after 22 GUI/serial integration, 13 recorder and 7 detector tests plus parser self-test passed. No hardware capture or firmware flashing performed.

## 2026-09-06 - Simplified GUI and automatic slot detection

- Manual recordings detect recent successfully decoded slots/mode and freeze their expected set at Record; scheduled recordings keep the explicit planned set. Record does not resend mode/rate commands.
- Settings now uses human-condition radio selections and optional notes, with automatic/control-derived values read-only. Opening Settings pauses heatmap refresh only; Save/Cancel/window close resumes the latest frame while recording remains independent.
- Clearly label slot identity, local configuration, commanded target rate and measured packet rate. Protocol slot identity limitations were added to the current report 2.0 PDF.
- Installed after 14 GUI/serial integration, 7 detector and 13 recorder tests plus parser self-test passed; reviewed both main and settings renders. No real device capture or flashing was performed.

## 2026-09-06

- Final experiment scope is Data only; Power/Calibration retesting was removed at the user's request.
- Added the 142-row half-day schedule and 154-row extended Data schedule; no experimental measurements were generated.
- Implemented the variable-SPI PC GUI's configurable recording windows, schedule/metadata editor, per-run and main-window audits, complete received-byte capture, per-module status/K/q logs, and event markers.
- Default new recordings now use `docs/Final/data scalability/data`. The 88 existing runs (470 files, 503,037,879 bytes) were moved to `history/pre_variable_spi_20260906/data` and every original file SHA-256 verified. Original embedded paths are preserved and mapped by `path_map.csv`.
- Added explicit historical data-root arguments to figure/review tools; theoretical plots no longer require a nonempty measured-data directory.
- Legacy figure/review loaders reject schema_version>=2 explicitly until main-window statistics and run selection are adapted; they cannot silently substitute zero for missing legacy rates.
- Validation: 13 recorder backend tests, 8 GUI/serial integration tests, visual layout inspection, and the existing native protocol regression including 212 STM32-generated frame vectors passed. No real hardware capture or firmware flashing was performed.
