# Progress update — independent FSR/ACC rates in the replicated Combine

Date: 2026-08-13

## Goal

Allow the isolated `combined_system_sclk33` reproduction to refresh FSR and ACC
at different rates without changing the stable production Combine application.
This is useful when the FSR scan is the limiting operation but ACC data only
needs to be refreshed at its sensor ODR (or when an ACC-only diagnostic rate is
being evaluated).

## Implementation

- Added CMake cache options `SCLK33_FSR_HZ` and `SCLK33_ACC_HZ`.
- `0` means refresh on every output loop, preserving the previous behaviour.
- Positive values schedule each group independently with the STM32 DWT cycle
  counter. The scheduler is wrap-safe and does not use the 1 ms HAL tick.
- The transport continues to send the same fixed-size complete frame each loop.
  If a group is not due, its previous matrix or axis values are retained.
- Added frame flags `0x40` (FSR updated in this frame) and `0x80` (ACC updated
  in this frame). Existing FSR validity, ACC-present, CRC and SCLK33 bits are
  unchanged. The existing record-0 FSR row-count field becomes `0` on a skipped
  FSR update.
- ACC health/WHO_AM_I servicing remains independent and continues at one slot
  per 100 ms, even when the ACC data target is lower.
- The normal `stm32/applications/combined_system` source and
  `flash_combined_pair.cmd` were not modified.

## Commands

The complete argument order is:

```text
COM profile view confirmation fsr_hz acc_hz
```

Example: 200 Hz FSR and 100 Hz ACC on the specification-compliant 2.5 MHz
profile:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_combined_sclk33_experiment.cmd" COM9 safe2p5 all "" 200 100
```

The underlying build-only options are:

```text
-DSCLK33_FSR_HZ=200 -DSCLK33_ACC_HZ=100
```

The command still performs the normal STM32 build/flash, Teensy bridge upload
and GUI launch. Omitting both rate arguments is backward compatible. A target
above the actual output-loop rate is naturally limited by that loop; this
feature does not make the fixed transport faster.

## Verification status

This update has been source-reviewed and build-verified for the default
configuration and an independent `FSR=200 Hz / ACC=100 Hz` configuration. No
hardware was flashed as part of this documentation/code change. A hardware
run should check the new update flags and confirm that repeated frames contain
the expected retained values before using the rate combination in an experiment.
