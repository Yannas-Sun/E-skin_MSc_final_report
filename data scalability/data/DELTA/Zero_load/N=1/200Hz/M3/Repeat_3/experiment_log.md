# Experiment 20260907_014038_027023

Started: 2026-09-07T01:40:38.027023+01:00
Actual duration: 40.002449 s; requested: 40 s; settle: 10 s.
Result (main window): PASS: main window checks passed

## Conditions

```json
{
  "target_modules": [
    3
  ],
  "module_selection_source": "automatic",
  "target_mode": "DELTA",
  "target_hz": 200,
  "delta_threshold": 8,
  "spi_setting_hz": 10000000,
  "condition": "zero_load",
  "block": "1",
  "repeat": "3",
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
      3
    ],
    "mode": "DELTA",
    "slot_modes": {
      "3": "DELTA"
    },
    "slot_last_success_monotonic": {
      "3": 195354.3028746
    },
    "last_packet_monotonic": 195354.3028746,
    "observed_at_monotonic": 195354.3028746,
    "window_span_seconds": 1.4977557999955025,
    "window_seconds": 1.5,
    "stale_seconds": 0.5,
    "packet_count": 301,
    "limitation": "No response cannot establish whether a board is physically attached. The recent union can retain a briefly missing slot; recording freezes the set."
  },
  "observed_mode_at_record": "DELTA",
  "observed_mul1_rate_at_record_Hz": 200.58076614163866,
  "spi_setting_source": "local firmware configuration; not measured or read back",
  "delta_threshold_source": "local firmware configuration; not measured or read back",
  "module_identity_source": "CS/IRQ slot; protocol carries no unique board identity",
  "N": 1,
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
        "sha256": "f3cb2910054e26300a223cbac611e08eb4eae6ac6fa2a60ebd3c414695758949"
      },
      "pc_recorder": {
        "path": "D:\\study\\programming\\ESKIN\\E-SKIN\\hardware\\new\\firmware\\active\\four-module-variable-spi\\pc\\experiment_recording.py",
        "sha256": "aff5787daa91bdb16719b0601d71707307e9d3471f636192cc5308445bf1b9ed"
      },
      "pc_controls": {
        "path": "D:\\study\\programming\\ESKIN\\E-SKIN\\hardware\\new\\firmware\\active\\four-module-variable-spi\\pc\\experiment_controls.py",
        "sha256": "9e7ff3b5678de04c46dbf9653385e7dbac9a8ec59f95737122020de50299b194"
      },
      "pc_module_detection": {
        "path": "D:\\study\\programming\\ESKIN\\E-SKIN\\hardware\\new\\firmware\\active\\four-module-variable-spi\\pc\\module_detection.py",
        "sha256": "52e35e8991c13e70e8f1e64d7b32d6b25bfa0fa7aeda8ec2333033540eb59ec1"
      }
    }
  },
  "batch_id": "BATCH_6f194970f8d14e3c94be44510f39fa22",
  "batch_repeat_index": 3,
  "batch_repeat_count": 3,
  "batch_recording_method": "consecutive_capture_windows_same_setup",
  "batch_interpretation": "Temporal repeats under one setup; not independent setup blocks or automatic reloading",
  "batch_initial_observations": "GUI at_record fields describe the initial batch request; each run measures its own statistics",
  "module_detection_at_repeat_start": {
    "source": "recent_successful_protocol_slots_not_board_uids",
    "ready": true,
    "modules": [
      3
    ],
    "mode": "DELTA",
    "slot_modes": {
      "3": "DELTA"
    },
    "slot_last_success_monotonic": {
      "3": 195434.3204445
    },
    "last_packet_monotonic": 195434.3204445,
    "observed_at_monotonic": 195434.7222886,
    "window_span_seconds": 1.0302823999954853,
    "window_seconds": 1.5,
    "stale_seconds": 0.5,
    "packet_count": 244,
    "limitation": "No response cannot establish whether a board is physically attached. The recent union can retain a briefly missing slot; recording freezes the set."
  },
  "pre_record_commands": [
    {
      "command": "MODE DELTA",
      "source": "user",
      "sent_at": "2026-09-07T01:31:23.516160+01:00"
    }
  ],
  "stream_start_offset": 747463480,
  "live_parser_buffer_bytes_at_start": 0,
  "live_parser_continuous_across_recordings": true,
  "module_count": 1,
  "algorithm": "DELTA",
  "modules": [
    "M3"
  ],
  "active_module_ids": [
    "M3"
  ],
  "scan_hz": 200,
  "target_scan_rate_hz": 200,
  "load_label": "zero_load"
}
```

## Scope checks

- full_run: CHECK REQUIRED; 40.002449 s; 8111 valid MUL1; 8111/8111 target updates.
  Review reasons: initial_delta_prefix_cache_not_verifiable_from_file, unassigned_raw_bytes_in_full_capture.
- main: PASS; 30.002449 s; 6012 valid MUL1; 6012/6012 target updates.
  Review reasons: none.

Raw bytes are assigned by chunk arrival; complete packet bytes by completion time.
Start-boundary packets: 0; suffixes are audited separately and excluded from complete packet rates, K and q.
Missing updates and unknown initial cache prefixes are not proven physical-scan losses.
Local artifact hashes identify source/build files; no device flash readback was performed by this recorder.
