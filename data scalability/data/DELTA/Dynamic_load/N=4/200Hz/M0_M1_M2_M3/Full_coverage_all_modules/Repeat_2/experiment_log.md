# Experiment 20260907_060227_053987

Started: 2026-09-07T06:02:27.053987+01:00
Actual duration: 40.002539 s; requested: 40 s; settle: 10 s.
Result (main window): CHECK REQUIRED: outer_sequence_gap_events; missing_valid_expected_updates; session_lost_frames; session_sequence_gap_events

## Conditions

```json
{
  "target_modules": [
    0,
    1,
    2,
    3
  ],
  "module_selection_source": "automatic",
  "target_mode": "DELTA",
  "target_hz": 200,
  "delta_threshold": 8,
  "spi_setting_hz": 10000000,
  "condition": "zero_load",
  "block": "1",
  "repeat": "2",
  "operator": "",
  "load_protocol_id": "",
  "load_layers": "unspecified",
  "load_notes": "",
  "notes": "",
  "deployment_note": "",
  "deployment_confirmed": false,
  "board_identity_handling": "slots_only",
  "physical_modules_to_slots": {},
  "board_identity_source": "unknown_not_transmitted_by_protocol",
  "target_hz_source": "GUI default 200 Hz; not firmware readback",
  "module_detection_at_record": {
    "source": "recent_successful_protocol_slots_not_board_uids",
    "ready": true,
    "modules": [
      0,
      1,
      2,
      3
    ],
    "mode": "DELTA",
    "slot_modes": {
      "0": "DELTA",
      "1": "DELTA",
      "2": "DELTA",
      "3": "DELTA"
    },
    "slot_last_success_monotonic": {
      "0": 211103.3694323,
      "1": 211103.3694323,
      "2": 211103.3694323,
      "3": 211103.3694323
    },
    "last_packet_monotonic": 211103.3694323,
    "observed_at_monotonic": 211103.3694323,
    "window_span_seconds": 1.4985062000050675,
    "window_seconds": 1.5,
    "stale_seconds": 0.5,
    "packet_count": 301,
    "limitation": "No response cannot establish whether a board is physically attached. The recent union can retain a briefly missing slot; recording freezes the set."
  },
  "observed_mode_at_record": "DELTA",
  "observed_mul1_rate_at_record_Hz": 200.19296211348032,
  "spi_setting_source": "local firmware configuration; not measured or read back",
  "delta_threshold_source": "local firmware configuration; not measured or read back",
  "module_identity_source": "CS/IRQ slot; protocol carries no unique board identity",
  "N": 4,
  "M": 4,
  "local_provenance": {
    "source": "local_files_not_device_flash_readback",
    "firmware_variant": "four-module-variable-spi",
    "files": {
      "stm32_elf": {
        "path": "D:\\study\\programming\\ESKIN\\E-SKIN\\hardware\\new\\firmware\\active\\four-module-variable-spi\\stm32\\combined-system\\build\\Release\\ESKIN_STM32.elf",
        "sha256": "8fb1791504f3c2bf23dce9d57ca9b877b8cd1653d167dfe5a58b0c5176c4c8b6"
      },
      "teensy_hex": {
        "path": "D:\\study\\programming\\ESKIN\\E-SKIN\\hardware\\new\\firmware\\active\\four-module-variable-spi\\build\\teensy\\four_module.ino.hex",
        "sha256": "32a95ff60bef1029a8b25a62d4ece524abc97813955e6586fc50fc9bf4cd2a67"
      },
      "pc_monitor": {
        "path": "D:\\study\\programming\\ESKIN\\E-SKIN\\hardware\\new\\firmware\\active\\four-module-variable-spi\\pc\\four-module-fsr-monitor.py",
        "sha256": "7e7f93fcd3f3648196d3b8e69314869371be86084e218230df43de33030e5df1"
      },
      "pc_recorder": {
        "path": "D:\\study\\programming\\ESKIN\\E-SKIN\\hardware\\new\\firmware\\active\\four-module-variable-spi\\pc\\experiment_recording.py",
        "sha256": "aff5787daa91bdb16719b0601d71707307e9d3471f636192cc5308445bf1b9ed"
      },
      "pc_plot_jobs": {
        "path": "D:\\study\\programming\\ESKIN\\E-SKIN\\hardware\\new\\firmware\\active\\four-module-variable-spi\\pc\\recording_plot_jobs.py",
        "sha256": "91fba986845ec48dc8eefa48887eb04cf867ec077e79713b86f673a174180a22"
      },
      "pc_recording_plots": {
        "path": "D:\\study\\programming\\ESKIN\\E-SKIN\\hardware\\new\\firmware\\active\\four-module-variable-spi\\pc\\recording_plots.py",
        "sha256": "ef567d416479340e7c14602d1675187c7416fc184725eed7eb6aef15e42be23a"
      },
      "pc_controls": {
        "path": "D:\\study\\programming\\ESKIN\\E-SKIN\\hardware\\new\\firmware\\active\\four-module-variable-spi\\pc\\experiment_controls.py",
        "sha256": "fd205d447388bbda5b2151b8a926a7cf64a4ba9a3a0dd08a1303181a52ebc257"
      },
      "pc_module_detection": {
        "path": "D:\\study\\programming\\ESKIN\\E-SKIN\\hardware\\new\\firmware\\active\\four-module-variable-spi\\pc\\module_detection.py",
        "sha256": "52e35e8991c13e70e8f1e64d7b32d6b25bfa0fa7aeda8ec2333033540eb59ec1"
      }
    }
  },
  "batch_id": "BATCH_3753f717b6b1403ebfc4ce0313e8e63e",
  "batch_repeat_index": 2,
  "batch_repeat_count": 3,
  "batch_recording_method": "consecutive_capture_windows_same_setup",
  "batch_interpretation": "Temporal repeats under one setup; not independent setup blocks or automatic reloading",
  "batch_initial_observations": "GUI at_record fields describe the initial batch request; each run measures its own statistics",
  "module_detection_at_repeat_start": {
    "source": "recent_successful_protocol_slots_not_board_uids",
    "ready": true,
    "modules": [
      0,
      1,
      2,
      3
    ],
    "mode": "DELTA",
    "slot_modes": {
      "0": "DELTA",
      "1": "DELTA",
      "2": "DELTA",
      "3": "DELTA"
    },
    "slot_last_success_monotonic": {
      "0": 211143.3861018,
      "1": 211143.3861018,
      "2": 211143.3861018,
      "3": 211143.3861018
    },
    "last_packet_monotonic": 211143.3861018,
    "observed_at_monotonic": 211143.4179078,
    "window_span_seconds": 1.4673567999852821,
    "window_seconds": 1.5,
    "stale_seconds": 0.5,
    "packet_count": 295,
    "limitation": "No response cannot establish whether a board is physically attached. The recent union can retain a briefly missing slot; recording freezes the set."
  },
  "pre_record_commands": [],
  "stream_start_offset": 47759885,
  "live_parser_buffer_bytes_at_start": 1,
  "live_parser_continuous_across_recordings": true,
  "module_count": 4,
  "algorithm": "DELTA",
  "modules": [
    "M0",
    "M1",
    "M2",
    "M3"
  ],
  "active_module_ids": [
    "M0",
    "M1",
    "M2",
    "M3"
  ],
  "scan_hz": 200,
  "target_scan_rate_hz": 200,
  "load_label": "zero_load"
}
```

## Scope checks

- full_run: CHECK REQUIRED; 40.002539 s; 7860 valid MUL1; 31436/31440 target updates.
  Review reasons: outer_sequence_gap_events, missing_valid_expected_updates, initial_delta_prefix_cache_not_verifiable_from_file, session_lost_frames, session_sequence_gap_events, unassigned_raw_bytes_in_full_capture.
- main: CHECK REQUIRED; 30.002539 s; 5852 valid MUL1; 23404/23408 target updates.
  Review reasons: outer_sequence_gap_events, missing_valid_expected_updates, session_lost_frames, session_sequence_gap_events.

Raw bytes are assigned by chunk arrival; complete packet bytes by completion time.
Start-boundary packets: 1; suffixes are audited separately and excluded from complete packet rates, K and q.
Missing updates and unknown initial cache prefixes are not proven physical-scan losses.
Local artifact hashes identify source/build files; no device flash readback was performed by this recorder.
