# Data acquisition and plotting scripts

- four-module-fsr-monitor.py is the current four-module FSR-only monitor for the variable-length MUL1 stream. It records FULL and DELTA runs under the active firmware.
- plot_delta_mul_length.py reads each DELTA packet_log.csv and creates a packet-length trace beside the recording or in an explicit output directory.
- generate_current_delta_repeats.py is the diagnostic figure builder for the three M1 large-area repeats.
- enrich_existing_experiment_metadata.py is a maintenance helper for existing records; it derives metadata without changing raw measurements.

Paths are derived from __file__ or explicit command-line arguments, so the scripts do not depend on a machine-specific working directory or drive letter. The one-time legacy archive utility is preserved under archive/legacy_scripts/.
