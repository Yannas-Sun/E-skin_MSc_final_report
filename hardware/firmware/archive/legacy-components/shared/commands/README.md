# Archived command index

This directory contains historical Windows build, flash, upload and monitor scripts. It is not the final project entry point.

Use `../../../../active/four-module-variable-spi/commands` for the final report firmware. The archived scripts target fixed-slot, ACC, diagnostic or legacy branches and may contain absolute paths from the original workspace.

## Script groups

| Group | Purpose |
|---|---|
| `flash_active_*`, `upload_scalablity_*`, `start_scalablity_*` | Former four-module fixed-slot chain |
| `flash_data_scalability*`, `upload_data_scalability*` | ACC/data-scalability research chain |
| `flash_fsr1_pair`, `flash_fsr2_pair` | Standalone FSR diagnostics |
| `flash_acc_rate_benchmark` | ACC-rate isolation benchmark |
| `flash_internal_*` | STM32 FIFO, EOC and DMA experiments |
| `flash_spi_pattern_test` | STM32–Teensy link test |
| `upload_teensy_sketch`, `monitor_teensy_serial` | Generic legacy Teensy helpers |

Detailed historical results and path notes are in [`docs/HISTORICAL_COMMANDS.md`](docs/HISTORICAL_COMMANDS.md).
