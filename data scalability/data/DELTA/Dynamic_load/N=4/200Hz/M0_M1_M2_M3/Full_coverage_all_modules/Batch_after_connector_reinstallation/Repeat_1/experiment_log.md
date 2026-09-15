# Experiment 20260907_115145_448767

Started: 2026-09-07T11:51:45.448767+01:00
Actual duration: 40.002018 s; requested: 40 s; settle: 10 s.
Result (main window): PASS: main window checks passed

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
  "repeat": "1",
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
      "0": 232101.3100941,
      "1": 232101.3100941,
      "2": 232101.3100941,
      "3": 232101.3100941
    },
    "last_packet_monotonic": 232101.3100941,
    "observed_at_monotonic": 232101.3100941,
    "window_span_seconds": 1.4986442999797873,
    "window_seconds": 1.5,
    "stale_seconds": 0.5,
    "packet_count": 301,
    "limitation": "No response cannot establish whether a board is physically attached. The recent union can retain a briefly missing slot; recording freezes the set."
  },
  "observed_mode_at_record": "DELTA",
  "observed_mul1_rate_at_record_Hz": 200.34357427749646,
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
  "batch_id": "BATCH_044efb5e7ab5440fa025a8237d0fe1f9",
  "batch_repeat_index": 1,
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
      "0": 232101.3448692,
      "1": 232101.3448692,
      "2": 232101.3448692,
      "3": 232101.3448692
    },
    "last_packet_monotonic": 232101.3448692,
    "observed_at_monotonic": 232101.3503231,
    "window_span_seconds": 1.4936854999978095,
    "window_seconds": 1.5,
    "stale_seconds": 0.5,
    "packet_count": 300,
    "limitation": "No response cannot establish whether a board is physically attached. The recent union can retain a briefly missing slot; recording freezes the set."
  },
  "module_detection_at_worker_start": {
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
      "0": 232101.3448692,
      "1": 232101.3448692,
      "2": 232101.3448692,
      "3": 232101.3448692
    },
    "last_packet_monotonic": 232101.3448692,
    "observed_at_monotonic": 232101.3504735,
    "window_span_seconds": 1.4936854999978095,
    "window_seconds": 1.5,
    "stale_seconds": 0.5,
    "packet_count": 300,
    "limitation": "No response cannot establish whether a board is physically attached. The recent union can retain a briefly missing slot; recording freezes the set."
  },
  "pre_record_commands": [
    {
      "command": "MODE DELTA",
      "source": "user",
      "sent_at": "2026-09-07T11:48:23.401434+01:00"
    }
  ],
  "stream_start_offset": 106233631,
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

- full_run: CHECK REQUIRED; 40.002018 s; 7983 valid MUL1; 31932/31932 target updates.
  Review reasons: initial_delta_prefix_cache_not_verifiable_from_file, unassigned_raw_bytes_in_full_capture.
- main: PASS; 30.002018 s; 5982 valid MUL1; 23928/23928 target updates.
  Review reasons: none.

Raw bytes are assigned by chunk arrival; complete packet bytes by completion time.
Start-boundary packets: 1; suffixes are audited separately and excluded from complete packet rates, K and q.
Missing updates and unknown initial cache prefixes are not proven physical-scan losses.
Local artifact hashes identify source/build files; no device flash readback was performed by this recorder.
