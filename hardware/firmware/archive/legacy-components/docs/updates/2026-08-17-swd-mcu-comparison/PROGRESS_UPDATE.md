# SWD comparison: fresh and original STM32 devices

Date: 2026-08-17  
Scope: explain why an unused STM32 programmed successfully while two original
devices repeatedly returned `No ACK`/`Unexpected ACK '5'`.

## Result

The same DAPLink (`LU_2022_8888`), STM32 target (`stm32g474cetx`), build and
combined ELF worked with an unused STM32. The two original STM32 devices still
failed during SWD target/debug-core setup. The latest failed attempt did not
print `Erased` or `Programmed`, so it is not evidence of a successful flash.

The compiler warnings in `main.c` are unused legacy functions and variables;
the Release build completed and they are unrelated to the SWD failure.

After the successful replacement-device flash, `pyocd list` still showed
`Target: n/a`. This is a probe-list display limitation, not a contradiction:
the actual flash session had already identified the STM32 and completed the
erase/program operation. Treat `pyocd list` as probe enumeration only;
`DP IDR`, `Cortex-M4`, `Erased`, `Programmed` and the pyOCD exit code are the
authoritative target/flash evidence.

## Evidence

- `pyocd list` detected the DAPLink but reported `Target: n/a` for the failing
  original device.
- Failing attempts included `DebugPortSetup: No ACK`, `Unexpected ACK '5'`,
  and failures while creating Cortex-M4 debug components (SCS, DWT, FPB, ITM,
  TPIU) and reset catch state.
- A prior successful log contained `erased 16384 bytes` and `programmed 15360
  bytes`, proving the toolchain can program a responding target.

## Interpretation

When only the MCU changes, the leading explanations are target-specific
option-byte protection (RDP/write protection) or physical damage/marginal
behaviour of the original MCU's SWDIO, SWCLK, NRST or power pins. If a complete
module was exchanged, inspect the module SWD traces and power path as well.
Firmware contents alone should not block an under-reset attach when SWD and
NRST are electrically available.

## Next controlled comparison

1. Use one power source and disconnect Teensy/Host signals during SWD testing.
2. Record VDD at the MCU, VTref at DAPLink, NRST before/during reset and the
   exact direct SWD wiring.
3. Run the same 1 kHz `under-reset` command on the fresh and original devices.
4. Record the first pyOCD milestone and the full erased/programmed counts.
5. Use ST-Link/STM32CubeProgrammer to read RDP and option bytes on an original
   device. A protected device must be recovered deliberately; RDP Level 2 is
   not recoverable through SWD.

## Read-only Option Bytes result

The original STM32 responded to a 1 kHz pyOCD commander read:

```text
address: 0x40022020 (FLASH_OPTR)
value:   0xFBEFF8AA
```

The low byte `0xAA` is RDP Level 0. `nSWBOOT0` (bit 26) is clear and `nBOOT0`
(bit 27) is set, matching the project's known post-correction value and
selecting main Flash independently of physical PB8. This read did not modify
Option Bytes. It also proves that this original target can answer an SWD
memory read; therefore `pyocd list` showing `Target: n/a` is only a probe-list
display limitation, not evidence of missing or protected STM32 hardware.
6. If a second probe also fails on an original device while the fresh device
   passes, classify the original device/module as hardware-fault suspect.

The detailed per-attempt record is
`docs/test_results/20260817_swd_fresh_vs_original_mcu.txt`.

## 1 kHz no-reset flash result

The user subsequently confirmed that the following lower-speed command
completed the STM32 flash operation successfully:

```powershell
pyocd flash -v -W -u LU_2022_8888 -t stm32g474cetx `
  -f 1k -M under-reset --no-reset -e sector `
  "D:\study\programming\builds\ESKIN_COMBINED_SYSTEM\ESKIN_STM32.elf"
```

This is a meaningful separation from the normal command, which uses 10 kHz,
requests a hardware reset during the flash session, and then runs a second
`pyocd reset -m hw` command. The successful command changes two variables at
once: it lowers SWD to 1 kHz and suppresses the post-program reset. `-v`, `-W`,
the target, connect mode and sector erase selection do not explain the reset
difference.

Current interpretation:

- **Programming/verification: PASS** at 1 kHz with `--no-reset`.
- **Automatic reset/session uninitialisation: not yet proven**; the normal
  10 kHz reset path remains the failing path.
- **Application execution: not proven by this flash alone**; the new image
  must be started by a separate low-speed reset, manual NRST operation, or a
  complete power cycle.

The result strongly implicates either reset handling or SWD signal margin at
10 kHz, but it does not distinguish them because both frequency and reset
behaviour changed together. The next controlled comparison is to test 1 kHz
with reset enabled and 10 kHz with `--no-reset`, recording whether each flash
and reset stage completes independently.

## 1 MHz comparison result

The user also reports that a 1 MHz pyOCD operation completed normally. This is
important because 1 MHz is substantially above both 1 kHz and 10 kHz. It rules
out a simple monotonic explanation of the form "the SWD clock is too fast".

The exact 1 MHz command and whether it used `--no-reset` were not included in
the report, so the reset/session and frequency variables are not yet fully
separated. The current interpretation is therefore:

- a general SWD frequency limit is unlikely;
- the 10 kHz failure may be a reset/session timing interaction or a
  target-specific transient state;
- the 1 MHz result must be repeated with the same reset options as the normal
  script before changing the production command.

## 1 MHz automatic-reset confirmation

The controlled repeat was run with the same 1 MHz SWD clock but with hardware
reset enabled and no `--no-reset` option:

```powershell
pyocd flash -v -W -u LU_2022_8888 -t stm32g474cetx `
  -f 1M -M under-reset -O reset_type=hw -e sector `
  "D:\study\programming\builds\ESKIN_COMBINED_SYSTEM\ESKIN_STM32.elf"
```

Result: **PASS**, process exit code `0`. The log showed reset assertion before
connect, successful DP IDR/Cortex-M4 discovery, reset deassertion after
connect, and:

```text
Erased 0 bytes (0 sectors), programmed 0 bytes (0 pages),
identical 15360 bytes (15 pages)
```

This proves that hardware automatic reset is functional at 1 MHz. Together
with the earlier 1 MHz no-reset success, a generally broken NRST path is
unlikely. The next isolating test is 10 kHz with `reset_type=hw` but without
the normal script's second standalone `pyocd reset -m hw` command.

## Main Combined flash command changed to the successful no-reset path

The maintained `tools/commands/original/flash_combined.cmd` was changed to
match the reliable manual result:

```text
pyocd flash -W -u LU_2022_8888 -t stm32g474cetx
  -f 1M -M under-reset --no-reset -e sector ESKIN_STM32.elf
```

The previous `-f 10k -O reset_type=hw` invocation and the separate trailing
`pyocd reset -m hw` were removed. The script now reports that programming is
complete and requires a manual NRST action or a complete power cycle before
runtime testing. This change is limited to the maintained Combined entry
point; it does not rewrite historical diagnostic scripts.
