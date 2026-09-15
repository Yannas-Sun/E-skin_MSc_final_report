# Four-module FSR-only three-mode update

Date: 2026-08-30

## Scope

The active four-module implementation was changed to a two-FSR data path. ACC
initialisation, sampling, health checks, frame fields and transport are no
longer part of the active STM32 image or the active PC GUI.

## Current data path

- Each STM32 scans FSR1 and FSR2 as two 16×16 matrices.
- FSR2 now uses the same MUX address order as FSR1.
- Host SPI remains a fixed 1044-byte DMA slot so the STM32/Teensy timing is
  deterministic.
- The first 16 MOSI bytes select the mode and scan rate for the next STM32
  acquisition.
- Teensy emits variable-length `MUL1` v2 blocks, so Delta and Spatial frames do
  not carry the unused 1044-byte tail over USB.
- The new GUI reconstructs FULL, DELTA and SPATIAL data per module and shows
  only the two FSR heatmaps per module.

## Commands

```text
MODE FULL
MODE DELTA
MODE SPATIAL
SCAN_HZ 200
SCAN_HZ 0
```

`SCAN_HZ 0` leaves the rate uncapped. A non-zero value is applied in both the
Teensy polling interval and the STM32 start-of-scan gate. Four STM32 modules
use the same binary; CS and IRQ wiring identifies the module slot.

## Verification

| Check | Result |
|---|---|
| STM32 Release CMake build | PASS; `ESKIN_STM32.elf` linked, 13,776 B Flash / 9,344 B RAM |
| Teensy 4.1 Arduino build | PASS; 13,892 B code / 17,536 B RAM1 / 12,416 B RAM2 |
| PC parser self-test | PASS; variable MUL1, FULL, DELTA base reconstruction and outer CRC rejection |
| PC Python syntax check | PASS |
| Hardware upload | Not performed in this update |

## Follow-up GUI fix

Matplotlib's `PolyCollection` does not accept `vmin` and `vmax` as direct
constructor arguments in the installed version. The active GUI now passes the
same 0–4095 ADC range through `matplotlib.colors.Normalize`, so the heatmap
starts normally after a Teensy upload.

| Check | Result |
|---|---|
| GUI Python syntax check after fix | PASS |
| FSR-only parser self-test after fix | PASS |

## Follow-up serial error handling

The GUI now catches a busy or disconnected COM port and reports the actual
serial error in its window instead of leaving an unhandled worker-thread
traceback. The port still has to be released by the other application before
the GUI can receive data.

| Check | Result |
|---|---|
| GUI Python syntax check after serial handling change | PASS |
| FSR-only parser self-test after serial handling change | PASS |
| GUI constructor test after serial handling change | PASS |

## Follow-up font warning cleanup

Serial-port status messages are now rendered in English. This avoids Matplotlib
font warnings on installations that only provide DejaVu Sans, while preserving
the displayed error information.

| Check | Result |
|---|---|
| GUI Python syntax check after font cleanup | PASS |
| FSR-only parser self-test after font cleanup | PASS |
| COM9 open test | PASS |

## Follow-up GUI mode and scan-rate controls

The active GUI now sends `MODE FULL`, `MODE DELTA`, `MODE SPATIAL`, and
`SCAN_HZ 0..1000` through its existing serial connection. This keeps binary
MUL1 reception and control commands on one COM port, so a separate serial
monitor is not needed and cannot compete for the port.

| Check | Result |
|---|---|
| GUI Python syntax check after controls | PASS |
| FSR-only parser self-test after controls | PASS |
| GUI controls and constructor test | PASS |

## Follow-up real-time rate and algorithm display

The GUI now reports the algorithm recovered from incoming module frames, the
PC-measured `MUL1` packet rate in Hz, the current GUI target scan rate, the
measured USB byte rate, and the module IDs updated in the latest packet. The
scan-rate value is measured from received packets, not calculated from the
configured target.

| Check | Result |
|---|---|
| GUI Python syntax check after live status change | PASS |
| FSR-only parser self-test after live status change | PASS |
| GUI live-status and control test | PASS |

## Follow-up GUI responsiveness fix

The mode and Apply widget objects are now retained by the GUI, so their
callbacks remain active after construction. The display redraws only when a
new packet arrives and uses a 100 ms display refresh interval; serial reception
continues independently.

| Check | Result |
|---|---|
| GUI Python syntax check after responsiveness fix | PASS |
| FSR-only parser self-test after responsiveness fix | PASS |
| GUI controls, refresh gating and status test | PASS |

## Operational boundary

The old `four-module-monitor.py` and the historical README remain for
comparison only. Use `four-module-fsr-monitor.py`,
`README_FSR_ONLY.md`, and the shared four-module commands for the current path.

## Final data scalability calculation: FSR-only

The Final data scalability document was aligned with the active dual-FSR
protocol. ACC bytes were removed from the ESKF, ESKD, ESK0, ESPF, and ESPD
calculations. Full, Delta, and Spatial formulas now include the current
`module block` and `MUL1` overhead. The four-module full baseline at 200 Hz is
now 843,200 B/s = 6.7456 Mbit/s. The linked Delta chart was updated to the same
FSR-only baseline, and the Spatial calculations now use the current MUL1
wrapping instead of direct per-module USB addition.

| Check | Result |
|---|---|
| Final data scalability document contains no stale ACC payload sizes | PASS |
| Four-module Full calculation | PASS; 4216 B/frame, 843200 B/s, 6.7456 Mbit/s |
| Four-module Delta calculation | PASS; ESK0 25600 B/s, ESKD 25600 + 3200K B/s |
| Spatial calculation includes MUL1 wrapping | PASS |
| Delta throughput chart matches FSR-only values | PASS |

The document also records an implementation boundary: the current Spatial C
constant still permits 255 changed records, while the fixed 1044 B Host SPI
slot safely carries at most 249 records. This is documented as a firmware
follow-up and was not changed in this documentation-only update.

## Active Host SPI clock set to 10 MHz

The enabled FSR-only Teensy bridge now requests a 10 MHz Host SPI clock for
the STM32 SPI3 slave. This is the conservative active setting for checking
whether the current `BAD_FRAME` result is caused by Host SPI signal timing.
Historical experiment versions remain unchanged.

| Check | Result |
|---|---|
| Active Teensy SPI setting | PASS; `SPI_HZ = 10000000` |
| Hardware frame validation at 10 MHz | Pending; re-upload Teensy and retest M0/M3 |

The 10 MHz change was compile-checked successfully: Teensy 4.1 uses 14,628 B
flash code, 17,536 B RAM1, and 12,416 B RAM2. The STM32 image and PC parser
were unchanged and remain build/self-test passing.

## USB rate display uses a one-second accumulation window

The active PC monitor now accumulates received MUL1 packet bytes and packet
counts for one second before calculating the displayed USB byte rate and MUL1
packet rate. This reduces short-window jitter caused by USB buffering and
bursty packet delivery while preserving the measured-data method.

## Mode switching and Delta cache recovery

The active bridge no longer replays a previous module frame when a multi-module
packet is emitted after a partial round. Unchanged module slots are now marked
as not updated with zero payload, so the PC keeps its cache instead of applying
the same Delta frame twice. Mode changes also discard queued packets from the
old mode. The STM32 pipeline re-encodes the already acquired sample after a
mode command is accepted, removing the stale-mode buffer from the next Host
SPI transfer. The PC parser now applies a MUL1 packet transactionally, so a
packet rejected for a bad Delta base cannot leave a partially updated cache.

| Check | Result |
|---|---|
| PC parser self-test | PASS; FULL, DELTA, SPATIAL and CRC checks |
| STM32 Release build | PASS; ESKIN_STM32.elf linked |
| Teensy 4.1 compile-only check | PASS; 13,956 B code, 17,536 B RAM1, 12,416 B RAM2 |
| Hardware mode-switch test | Pending; requires re-flashing and connected modules |

The STM32 full-frame flags now distinguish a Delta resynchronisation frame
(`DELTA_SYNC`) and a Spatial overflow fallback (`SPATIAL_FALLBACK`) from a
normal Full frame. This prevents the GUI status from hiding the active mode's
recovery path.

## Delta queue-loss and mode-transition fix

The previous cache-recovery change still allowed the Teensy to read newer Delta
frames after its USB queue became full. Because the STM32 had already advanced
the Delta base sequence, the PC could receive a frame whose base was never
delivered. The Teensy now detects this condition, requests a complete Delta
sync from each affected module, and suppresses normal Delta frames until that
module has returned a `DELTA_SYNC` frame. The same recovery is triggered when
a multi-module packet cannot be queued. Spatial deltas use the same mechanism
and request a complete `ESPF` base frame. The resync flag is sent per module,
so a module that has already recovered is not repeatedly forced into full
frames while another module is still recovering.

Mode changes are now filtered at the Teensy boundary: frames produced under
the previous mode are not added to the outgoing packet after a mode command.
This prevents a transition packet from mixing FULL, DELTA, and SPATIAL data
from different modules. The PC parser also reports dropped protocol frames in
the GUI instead of silently hiding the error. Teensy module polling no longer
waits for the USB CDC ready flag; USB readiness only controls packet draining,
so the modules can start producing frames before the host driver finishes
opening the COM port.

| Check | Result |
|---|---|
| PC parser self-test with dropped Delta/Spatial base | PASS; mismatch rejected, state unchanged, resync base accepted |
| STM32 Release build | PASS; `ESKIN_STM32.elf` linked after resync-command change |
| Teensy 4.1 compile-only check | PASS; 14,644 B code, 17,536 B RAM1, 12,416 B RAM2 |
| Hardware queue-loss and mode-transition test | Pending; requires re-flashing and connected modules |

## No-data diagnosis and active-firmware deployment fix

- Added a low-rate diagnostic `MUL1` packet when no module produces a valid frame.
  The per-module status byte retains `NO_IRQ`, `BAD_FRAME`, `BAD_CRC`, `TIMEOUT`,
  `MODE_TRANSITION`, or `RESYNC_NEEDED`, so the GUI no longer appears silently
  frozen when the STM32/Teensy protocol is mismatched.
- Updated the GUI to display the per-module status codes.
- Removed the Teensy `Serial` boolean gate from USB queue draining; the bridge
  now relies on `availableForWrite()` so a configured CDC port can receive data
  even when the boolean connection flag is temporarily stale.
- Added `shared/commands/flash_active_four_module_stm32.cmd`, which explicitly
  builds and flashes the current active `1044 B / protocol version 3` STM32 image.
  The existing `flash_scalablity_four_module.cmd` only uploads the Teensy bridge;
  it does not update STM32 firmware.
- Removed the obsolete `STATUS` entry from the command reference because the
  active Teensy bridge does not implement a textual `STATUS` command.

| Check | Result |
|---|---|
| PC parser self-test after diagnostic status change | PASS |
| Diagnostic no-update `MUL1` packet parse test | PASS; `0x83` is shown as `NO_IRQ` |
| Active STM32 Release build after diagnostic status change | PASS; 14,076 B flash, 9,344 B RAM |
| Teensy 4.1 compile-only check after diagnostic status change | PASS; 14,644 B code, 17,536 B RAM1, 12,416 B RAM2 |
| Teensy USB queue drain after removing `Serial` gate | PASS; same memory footprint |
| Hardware no-data diagnosis | Pending; requires uploading the new bridge and active STM32 image |

## Adjustable STM32 flash speed

- Updated `flash_active_four_module_stm32.cmd` to accept an optional SWD speed.
- The default active-firmware flash speed is now `1M` instead of `100k`.
  `100k` and `10k` remain available for unstable SWD wiring.

## STM32 full erase procedure

- The active target can be fully erased with pyOCD before reprogramming:
  `pyocd erase -W -u LU_2022_8888 -t stm32g474cetx -f 1M -M under-reset --mass`.
- If the probe cannot establish SWD at `1M`, retry the same command at `100k`
  or `10k`; this changes only the debug-programming link speed.
- Added `shared/commands/erase_active_four_module_stm32.cmd` so the complete
  erase can be run without PowerShell line-continuation syntax.

## Active entry reduced to one protocol version

- Removed the disabled legacy 1188-byte/ACC implementation from the active
  Teensy source; it is no longer mixed with the current 1044-byte FSR-only
  implementation.
- Moved the obsolete active GUI, STM32 backup source, historical README, and
  stale prebuilt ELF to
  `archive/previous-source/four-module-full-scan-legacy/`.
- Added an explicit `BAD_VERSION` module status. A module returning an ESK
  frame whose version is not `3` is now reported separately from a malformed
  current frame.
- Added an active-version README and updated the command reference to state
  that the deployed contract is ESK v3, MUL1 v2, dual FSR, and 1044-byte Host
  SPI.

| Check | Result |
|---|---|
| PC parser self-test | PASS |
| STM32 Release build | PASS; no STM32 source change required |
| Cleaned Teensy 4.1 compile-only check | PASS; 14,596 B code, 17,536 B RAM1, 12,416 B RAM2 |
| Hardware protocol-version check | Pending; reflash every connected STM32 with the active image |

## Raw USB MUL1 capture tool

- Added `active/four-module-full-scan/tools/dump_usb_stream.py` to capture the
  actual Teensy-to-PC byte stream without using the GUI parser.
- Added `shared/commands/dump_usb_mul1.cmd`; it saves a `.bin` capture and a
  human-readable dump containing MUL1 version/length/sequence, outer CRC,
  per-module status, payload length, inner marker, and ESK version.
- Added a valid current-packet formatter self-test; it reports ESK v3 inside
  MUL1 v2 with 1044-byte payloads correctly.

## Invalid Host SPI prefix diagnosis

- Diagnostic `MUL1` module blocks now retain the first 16 bytes actually read
  from Host SPI for `BAD_FRAME`, `BAD_CRC`, `TIMEOUT`, and `BAD_VERSION`.
- The PC monitor accepts this fixed 16-byte diagnostic payload but does not
  apply it to the FSR state cache.
- The raw USB dump prints the bytes as `raw_prefix`, allowing an all-zero,
  all-`FF`, old-protocol, or shifted `ESKF` prefix to be distinguished directly.

| Check | Result |
|---|---|
| PC parser diagnostic-payload self-test | PASS; 16-byte error payload is ignored by the FSR cache |
| Raw dump diagnostic formatter | PASS; `raw_prefix` is printed with the original byte order |
| Teensy 4.1 compile-only check | PASS; 14,676 B code, 17,536 B RAM1, 12,416 B RAM2 |
| Hardware prefix capture | FAIL isolated; all four STM32 frames contain exactly 3 stale bytes before a valid `ESKF` v3 prefix |

## Host SPI3 FIFO hardware reset

- The captured Host SPI prefixes place a valid `ESKF` v3 frame at byte offset
  3 on every module. This common offset identifies stale SPI3 transmit state,
  rather than a USB, MUL1, parser, module-specific wiring, or Host SPI clock
  problem.
- `Combined_ReinitializeHostSPI()` now asserts and releases the RCC SPI3 reset
  after `HAL_SPI_DeInit()` and before `MX_SPI3_Init()`. The hardware reset clears
  the SPI3 peripheral state and transmit FIFO before each DMA transaction is
  armed.
- The active ESK v3 and MUL1 v2 layouts, 1044-byte Host SPI slot, Teensy bridge,
  PC parser, and 10 MHz Host SPI setting are unchanged.

| Check | Result |
|---|---|
| Source inspection | PASS; SPI3 RCC reset is between HAL deinitialisation and reinitialisation |
| STM32 Release build | PASS; 14,108 B flash and 9,344 B RAM |
| Hardware prefix alignment | PASS at 10 MHz after reflashing all four STM32 modules |

## Active Host SPI clock restored to 40 MHz

- After the SPI3 hardware-reset fix removed the three stale prefix bytes, the
  active four-module Teensy bridge Host SPI clock was changed from 10 MHz to
  40 MHz.
- The ESK v3 and MUL1 v2 layouts, 1044-byte module slot, 200 Hz default scan
  target, STM32 firmware, and PC parser are unchanged.

| Check | Result |
|---|---|
| Active Teensy SPI setting | PASS; `SPI_HZ = 40000000` |
| Teensy 4.1 compile-only check | PASS; 14,644 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| Four-module hardware validation at 40 MHz | FAIL; `BAD_FRAME` returned after uploading and running the four-module link |

## Active Host SPI rollback to validated 10 MHz

- The 40 MHz hardware test reintroduced `BAD_FRAME`, so the active Teensy Host
  SPI clock was restored to the previously successful 10 MHz setting.
- This rollback changes only `SPI_HZ`; the SPI3 FIFO reset, ESK v3/MUL1 v2
  protocol, 1044-byte module slot, and 200 Hz default target remain enabled.

| Check | Result |
|---|---|
| Active Teensy SPI setting | PASS; `SPI_HZ = 10000000` |
| Teensy 4.1 compile-only check | PASS; 14,676 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| Four-module hardware validation at 10 MHz | Pending; re-upload the Teensy bridge |

## Active Host SPI 30 MHz trial

- The active four-module Teensy Host SPI clock was changed from the validated
  10 MHz setting to 30 MHz as an intermediate hardware test below the failed
  40 MHz setting.
- Only `SPI_HZ` changed. The SPI3 FIFO reset, ESK v3/MUL1 v2 protocol,
  1044-byte module slot, and 200 Hz default target remain unchanged.

| Check | Result |
|---|---|
| Active Teensy SPI setting | PASS; `SPI_HZ = 30000000` |
| Teensy 4.1 compile-only check | PASS; 14,644 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| Four-module hardware validation at 30 MHz | Pending; upload Teensy and inspect module status/CRC |

## Active Host SPI 20 MHz trial

- The active four-module Teensy Host SPI clock was reduced from 30 MHz to
  20 MHz for the next intermediate hardware validation point.
- Only `SPI_HZ` changed. The SPI3 FIFO reset, ESK v3/MUL1 v2 protocol,
  1044-byte module slot, and 200 Hz default target remain unchanged.

| Check | Result |
|---|---|
| Active Teensy SPI setting | PASS; `SPI_HZ = 20000000` |
| Teensy 4.1 compile-only check | PASS; 14,644 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| Four-module hardware validation at 20 MHz | Pending; upload Teensy and inspect module status/CRC |

## Active Host SPI 5 MHz trial

- The active four-module Teensy Host SPI clock was reduced from 20 MHz to
  5 MHz for a conservative hardware validation point.
- Only `SPI_HZ` changed. The SPI3 FIFO reset, ESK v3/MUL1 v2 protocol,
  1044-byte module slot, and 200 Hz default target remain unchanged.

| Check | Result |
|---|---|
| Active Teensy SPI setting | PASS; `SPI_HZ = 5000000` |
| Teensy 4.1 compile-only check | PASS; 14,676 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| Four-module hardware validation at 5 MHz | Pending; upload Teensy and inspect module status/CRC |

## Active Host SPI 11 MHz trial

- The active four-module Teensy Host SPI clock was changed from 5 MHz to
  11 MHz for the next hardware validation point above the successful 10 MHz
  setting.
- Only `SPI_HZ` changed. The SPI3 FIFO reset, ESK v3/MUL1 v2 protocol,
  1044-byte module slot, and 200 Hz default target remain unchanged.

| Check | Result |
|---|---|
| Active Teensy SPI setting | PASS; `SPI_HZ = 11000000` |
| Teensy 4.1 compile-only check | PASS; 14,676 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| Four-module hardware validation at 11 MHz | Pending; upload Teensy and inspect module status/CRC |

## Active Host SPI 15 MHz trial

- The active four-module Teensy Host SPI clock was changed from 11 MHz to
  15 MHz for the next hardware validation point.
- Only `SPI_HZ` changed. The SPI3 FIFO reset, ESK v3/MUL1 v2 protocol,
  1044-byte module slot, and 200 Hz default target remain unchanged.

| Check | Result |
|---|---|
| Active Teensy SPI setting | PASS; `SPI_HZ = 15000000` |
| Teensy 4.1 compile-only check | PASS; 14,676 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| Four-module hardware validation at 15 MHz | FAIL; the four-module link reports `BAD_FRAME` |

## Final Host SPI rollback to validated 10 MHz

- Following the failed 15 MHz four-module hardware test, the active Teensy
  Host SPI clock was restored to the validated 10 MHz setting.
- Only `SPI_HZ` changed. The SPI3 FIFO reset, ESK v3/MUL1 v2 protocol,
  1044-byte module slot, and 200 Hz default target remain unchanged.

| Check | Result |
|---|---|
| Active Teensy SPI setting | PASS; `SPI_HZ = 10000000` |
| Teensy 4.1 compile-only check | PASS; 14,676 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| Four-module hardware validation at 10 MHz | Previously PASS; re-upload Teensy to restore the validated configuration |

## Dynamic online-module round completion

- MUL1 round completion no longer requires the hard-coded mask `0x0F` after a
  module is switched off. The Teensy now tracks an `activeModuleMask` from the
  four IRQ inputs and completes each round when every currently online module
  has supplied a frame.
- A module is marked offline after at least 100 ms without IRQ activity. For
  low requested scan rates, the timeout expands automatically to three scan
  periods so a healthy slow module is not removed.
- A returning IRQ immediately places the module back online. Delta and Spatial
  modes request a new base frame before accepting incremental data from the
  reconnected module.
- Offline modules remain represented in MUL1 as `NO_IRQ`; the wire protocol
  version, four module blocks, 10 MHz Host SPI, and 200 Hz default target are
  unchanged.

| Check | Result |
|---|---|
| Teensy 4.1 compile-only check | PASS; 14,916 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| PC parser self-test | PASS |
| Three-module rate after one module powers off | Pending hardware validation |

## Restored high-performance FSR acquisition path

- Restored the previously tested MUX pipeline in the active FSR-only STM32
  firmware. After both ADC conversions complete for row N, row N+1 is selected
  and begins its analogue settling interval while the two row-N FIFO blocks are
  read sequentially over SPI1.
- The validated 100 us MUX settle target remains enabled. The 0 us point that
  produced the highest no-load benchmark was not deployed because pressure
  response and adjacent-row crosstalk were not validated at that setting.
- FSR1 and FSR2 retain the current identical MUX address order; the restored
  pipeline does not restore the historical FSR2 transpose/reversal.
- The Teensy now performs each fixed 1044-byte Host SPI transaction with the
  optimized block-transfer API instead of 1044 individual `SPI.transfer()`
  calls. The first 16 transmitted bytes still contain the DSCM command and the
  received buffer still contains the complete module frame.
- The 10 MHz Host SPI setting, dynamic online-module mask, SPI3 FIFO hardware
  reset, ESK v3/MUL1 v2 protocol, and 200 Hz default target are unchanged.

| Check | Result |
|---|---|
| STM32 Release build | PASS; 14,180 B flash and 9,344 B RAM |
| Teensy 4.1 compile-only check | PASS; 14,996 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| PC parser self-test | PASS |
| Four-module 200 Hz hardware test | Pending; reflash four STM32 modules and upload Teensy |

## Default scan target changed to 300 Hz

- The Teensy default scan target and the PC monitor's initial target/value were
  changed from 200 Hz to 300 Hz so both ends present and command the same
  default.
- This is an intentional saturation test target. At the validated 10 MHz Host
  SPI clock, four 1044-byte FULL module slots have a raw theoretical ceiling of
  about 299.3 complete rounds/s before CS, IRQ, software, and USB overhead.
  Therefore a four-module FULL run is expected to remain below 300 Hz.
- Host SPI frequency, protocol layout, acquisition pipeline, dynamic online
  module handling, and sensor timing remain unchanged.

| Check | Result |
|---|---|
| Teensy 4.1 compile-only check | PASS; 14,996 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| PC parser self-test | PASS |
| Four-module 300 Hz saturation test | Pending hardware validation |

## Host SPI changed to 20 MHz with 300 Hz default target

- The active Teensy Host SPI request was changed from the validated 10 MHz
  setting to 20 MHz while retaining the 300 Hz default scan target.
- This is an experimental configuration above the previously failed 15 MHz
  four-module test point; `BAD_FRAME` or CRC errors remain possible on the
  current shared bus.
- Protocol layout, STM32 acquisition pipeline, dynamic online-module handling,
  and GUI target remain unchanged.

| Check | Result |
|---|---|
| Active Teensy SPI setting | PASS; `SPI_HZ = 20000000` |
| Teensy 4.1 compile-only check | PASS; 14,996 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| Four-module 20 MHz / 300 Hz test | Pending hardware validation |

## Host SPI restored to 10 MHz

- The active Teensy Host SPI clock was restored from the experimental 20 MHz
  setting to the previously validated 10 MHz setting.
- The ESK v3/MUL1 v2 protocol, STM32 acquisition pipeline, dynamic module
  handling, and 300 Hz default target are unchanged.

| Check | Result |
|---|---|
| Active Teensy SPI setting | PASS; `SPI_HZ = 10000000` |
| Four-module hardware validation at 10 MHz | Pending; upload the Teensy bridge and inspect module status/CRC |

## Coordinated one-second mode switching

- A new `MODE FULL`, `MODE DELTA`, or `MODE SPATIAL` command now starts a
  one-second quiet window in the Teensy bridge.
- During the window, old-mode MUL1 and round data are discarded and the four
  modules are not polled. After the delay, the new mode is activated and all
  modules receive a fresh mode command; Delta and Spatial also request a new
  base frame for every module.
- The GUI now shows `1 s coordinated switch` after a mode command is queued.
- Scan-rate commands, Host SPI 10 MHz, the protocol layouts, and the STM32
  acquisition code are unchanged.

| Check | Result |
|---|---|
| PC parser self-test | PASS; four-module parser self-test |
| Teensy 4.1 compile-only check | PASS; 15,268 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| Four-module mode-switch hardware test | Pending; verify the new mode begins after the one-second window |

## Delta/Spatial cache resynchronisation hardening

- STM32 now re-encodes the already acquired sample immediately after applying
  a mode-change or Delta/Spatial resynchronisation command. This removes the
  stale incremental frame that could otherwise be sent before the new base.
- The PC parser now preserves valid module caches when another module in the
  same MUL1 packet has an incremental-chain error, preventing one module from
  cascading the failure to the other three.
- When the parser detects a Delta or Spatial cache-chain error, it automatically
  sends `RESYNC DELTA` or `RESYNC SPATIAL` to Teensy. Teensy then clears pending
  transport data and requests a fresh base from all four modules.
- The new resynchronisation commands are documented in
  `shared/commands/CURRENT_COMMANDS.md`.

| Check | Result |
|---|---|
| PC parser self-test | PASS; FULL/DELTA/SPATIAL and CRC checks |
| Teensy 4.1 compile-only check | PASS; 15,508 B code, 17,536 B RAM1, and 12,416 B RAM2 |
| STM32 Release build | PASS; 14,256 B flash and 9,344 B RAM |
| Hardware Delta/Spatial recovery test | Pending; force a parser chain error and verify automatic base recovery |

## Delta/Spatial resynchronisation queue and offline-module fix

- Increased the Teensy USB packet queue from 2 to 4 complete MUL1 packets to
  absorb short USB scheduling delays.
- When a Delta/Spatial sequence discontinuity or queue overflow is detected,
  Teensy now discards already queued transport data before requesting new base
  frames. This prevents stale incremental packets from being delivered after
  the cache has become invalid.
- Delta/Spatial base recovery now waits only for currently active modules;
  modules that are offline are removed from the resynchronisation wait set and
  are added again when they reconnect.

| Check | Result |
|---|---|
| Teensy source inspection | PASS; stale queued data is cleared on resynchronisation |
| PC parser self-test | PASS; FULL/DELTA/SPATIAL and CRC checks |
| Teensy 4.1 compile-only check | PASS; 15,652 B code, 25,984 B RAM1, and 12,416 B RAM2 |
| Hardware Delta/Spatial recovery test | Pending; flash all modules and Teensy, then test with all modules and with an offline module |

## FSR2 physical row/column exchange correction

- Kept the shared MUX address order unchanged, as required for the current
  hardware.
- Corrected the active STM32 storage mapping for FSR2 from
  `fsr2[mux_row][adc_column]` to `fsr2[physical_row][physical_column]` by
  storing each ADC channel at `fsr2[column][mux_row]`.
- This changes only FSR2's row/column interpretation; FSR1, the protocol
  layout, and the GUI geometry are unchanged. FULL, DELTA, and SPATIAL now use
  the same corrected FSR2 coordinates.

| Check | Result |
|---|---|
| STM32 Release build | PASS; 14,248 B flash and 9,344 B RAM |
| FSR1 acquisition path | Unchanged |
| FSR2 physical orientation | Pending; flash one module and verify known row/column presses |

## Teensy-local Delta conversion (reverted)

- The GUI `DELTA` mode now commands STM32 to send stable FULL ESK frames.
- Teensy reconstructs the two 16 × 16 layers, compares each new sample with
  its per-module local cache, and emits ESKF/ESKD/ESK0 Delta frames to the PC.
- A local base frame is emitted after mode entry, resynchronisation, module
  reconnection, or when more than 255 cells change. This removes the STM32
  incremental-cache dependency from the Delta transport path.
- FULL and SPATIAL behaviour is unchanged.
- The active README files now describe the Teensy-local Delta path and its
  resynchronisation behaviour.

| Check | Result |
|---|---|
| Teensy 4.1 compile-only check | PASS; 16,612 B code, 30,112 B RAM1, and 12,416 B RAM2 |
| PC parser self-test | PASS; local ESKF/ESKD/ESK0 output is compatible with existing parser |
| Hardware Delta validation | Pending; upload Teensy, select DELTA, and verify the first frame is `ESKF` with Delta flag |

## Restore STM32-local Delta conversion

- Reverted the Teensy-local Delta experiment at the user's request.
- `MODE DELTA` once again commands each STM32 to generate `ESKF`, `ESKD`, and
  `ESK0`; Teensy only validates, transports, and packages those frames.
- The queue-depth increase, stale-queue clearing, online-module-aware
  resynchronisation, and FSR2 row/column correction remain in the active code.
- The earlier successful behaviour was obtained when the STM32 Delta cache and
  the PC cache started from the same base frame and no intermediate Delta frame
  was lost. A dropped incremental frame breaks the required `base_sequence`
  chain, so the retained resynchronisation hardening is still necessary.

| Check | Result |
|---|---|
| Teensy 4.1 compile-only check | PASS; 15,652 B code, 25,984 B RAM1, and 12,416 B RAM2 |
| PC parser self-test | PASS; FULL/DELTA/SPATIAL and CRC checks |
| Hardware STM32-local Delta validation | Pending; upload the restored Teensy bridge and all current STM32 images |

## Unified four-module scan-rate limiter

- Replaced independent per-module timing as the effective output limiter with
  one global interval for each complete four-module acquisition round.
- `SCAN_HZ N` now limits the number of complete MUL1 packets to approximately
  `N` per second, preventing staggered IRQ timing from producing two packets in
  one requested period.
- The limiter is reset when a new scan rate is received or transport state is
  cleared, so a new setting takes effect immediately.

| Check | Result |
|---|---|
| Teensy 4.1 compile-only check | PASS; 15,700 B code, 25,984 B RAM1, and 12,416 B RAM2 |
| Hardware `SCAN_HZ 100` validation | Pending; upload Teensy and confirm measured MUL1 rate is approximately 100 Hz |

## Remove the duplicate Teensy scan-rate limiter

- Removed the global and per-module Teensy polling intervals added by the
  previous scan-rate change. The STM32 scan clock already applies `SCAN_HZ`;
  applying the same period independently on Teensy caused phase misses where
  an IRQ became ready just after a poll and was not checked again until the
  following period.
- Teensy now polls module IRQ lines continuously and reads a completed frame
  immediately. `SCAN_HZ` is still sent to every STM32 and remains the single
  acquisition-rate control; `SCAN_HZ 0` still selects the hardware-limited
  maximum rate.
- This restores the earlier maximum-throughput behaviour while keeping the GUI
  frame-rate control functional.

| Check | Result |
|---|---|
| Teensy 4.1 compile-only check | PASS; 15,476 B code, 25,984 B RAM1, and 12,416 B RAM2 |
| Hardware maximum-rate and `SCAN_HZ 100/200/300` validation | Pending; upload Teensy and compare measured MUL1 rate |

## Preserve pending Delta frames during four-module assembly

- Fixed the root cause of persistent `Delta base sequence ... does not match
  cache ...` errors. `pendingUpdateMask` previously remembered that a module
  had contributed to the current round, but the single `moduleFrames[module]`
  buffer remained writable. A faster module could therefore overwrite an
  unsent ESKF/ESKD/ESK0 while Teensy waited for another module.
- A module with a pending frame is now left untouched until that MUL1 round is
  queued. The same rule preserves the first Delta ESKF returned by each module
  during coordinated resynchronisation, so the PC receives the base before any
  dependent ESKD frame.
- Clearing stale transport data no longer truncates a MUL1 packet that has
  already been partially written to USB. Its remaining bytes are completed at
  the packet boundary, while later unsent packets are discarded.

| Check | Result |
|---|---|
| Teensy 4.1 compile-only check | PASS; 15,668 B code, 25,984 B RAM1, and 12,416 B RAM2 |
| PC parser self-test | PASS; FULL/DELTA/SPATIAL, incremental cache, and CRC checks |
| Four-module DELTA hardware validation | Pending; verify continuous ESKF/ESKD/ESK0 without base-sequence warnings |

## Abort an in-progress round when Delta resynchronisation starts

- Fixed a second cache-recovery fault that could occur when a later module
  detected a sequence gap after an earlier module had already been accepted in
  the same Teensy polling pass. `beginResync()` cleared the global pending
  state, but the old local `updatedMask` was subsequently merged back into it,
  leaving an old frame locked while the resynchronisation mask still required a
  new base from that module.
- Valid module frames are now committed to `pendingUpdateMask` immediately.
  Transport resets increment a generation counter, and the current polling pass
  aborts as soon as that generation changes. No pre-resync frame can therefore
  be reintroduced after the pending state has been cleared.

| Check | Result |
|---|---|
| Teensy 4.1 compile-only check | PASS; 15,620 B code, 25,984 B RAM1, and 12,416 B RAM2 |
| PC parser self-test | PASS; FULL/DELTA/SPATIAL, incremental cache, and CRC checks |
| Hardware DELTA resynchronisation | Pending; switch FULL to DELTA and verify all online modules deliver a base before deltas |

## Restore the stable 200 Hz default

- Restored the default scan target to `200 Hz` in the Teensy bridge and PC GUI.
- The user can still enter another value, including `0` for uncapped maximum
  throughput; only the startup default has changed.
- The DELTA cache and transport fixes remain unchanged.

## Convert SPATIAL to real hardware-sparse acquisition

- SPATIAL now controls which analogue MUX addresses are scanned, instead of
  scanning both complete 16 x 16 arrays and applying a mask only while packing.
- Mode entry performs one full acquisition for the zero-load baseline. Idle
  scanning then keeps only MUX addresses 2, 5, 7, 10, 12, and 15 (one-based),
  reducing ADC/MUX work from 512 to 192 values per dual-FSR acquisition, or
  37.5% of a complete scan.
- A trigger on a scanned FSR1 row or the physically rotated FSR2 column enables
  the neighbouring MUX addresses for approximately one second. Mask changes
  take effect on the following acquisition, ensuring every ESPF value was
  physically sampled before transmission.
- ESP masks now describe electronic MUX-address/channel slots. ESPF parsing
  maps FSR1 to `[mux][channel]` and FSR2 to `[channel][mux]`, preserving the
  common physical GUI orientation.
- A transport-only SPATIAL resynchronisation no longer recaptures the baseline,
  so recovering a lost packet cannot silently tare a loaded sensor.
- Corrected the PC GUI's internal startup target from `300 Hz` to `200 Hz`,
  matching the visible field and the Teensy default.

| Check | Result |
|---|---|
| STM32 Release build | PASS; FLASH `14,360 B`, RAM `9,408 B` |
| Teensy 4.1 compile-only check | PASS; code `15,620 B`, RAM1 variables `25,984 B` |
| PC parser self-test with FSR2 SPATIAL transpose | PASS |
| Hardware sentinel/expansion validation | Pending; verify six idle MUX addresses and neighbour activation with a logic analyser |

## Bound SPATIAL USB payload after hardware-sparse conversion

- Added an independent `32`-count SPATIAL frame-change threshold so normal ADC
  noise is not encoded using DELTA's more sensitive `8`-count threshold.
- The STM32 now compares the candidate ESPD length with the active-mask ESPF
  length. When `K >= S`, it sends ESPF because the snapshot is no larger and
  also provides a fresh parser base.
- The GUI now reports each module's exact SPATIAL frame type, active MUX count,
  and `K` (changed values) or `S` (sampled electronic slots).

| Check | Result |
|---|---|
| STM32 Release build | PASS; FLASH `14,316 B`, RAM `9,408 B` |
| PC parser self-test and syntax check | PASS |

## Restore the original software-only SPATIAL strategy

- Reverted the hardware acquisition mask: FULL, DELTA, and SPATIAL now all
  traverse every one of the 16 MUX addresses and read all 16 channels from both
  MAX11633 devices on every acquisition.
- Restored the original two-dimensional software mask: one-based rows and
  columns 2, 5, 7, 10, 12, and 15 form the idle sentinel grid; detected points
  expand to the union of their 3 x 3 neighbourhoods and remain active for about
  one second after the last trigger.
- Restored physical row/column ESP packing and PC reconstruction for both FSR
  layers. SPATIAL now reduces only the variable USB payload, not ADC work.
- Restored the original SPATIAL per-frame change comparison to the shared
  `8`-count delta threshold and the original `changed > 255` ESPF fallback.
- Removed the GUI's hardware-MUX count because SPATIAL now always acquires all
  16 MUX addresses; the GUI retains frame type and `K/S` diagnostics.

| Check | Result |
|---|---|
| STM32 Release build | PASS; FLASH `14,312 B`, RAM `9,344 B` |
| PC parser self-test and syntax check | PASS; restored 156-position sentinel grid |
| Teensy 4.1 compile-only check | PASS; code `15,620 B`, wire format compatible |

## Select the startup scan rate during Teensy upload

- Added an optional `default-scan-hz` argument to the active four-module Teensy
  upload and upload-plus-GUI commands. The accepted range is `0..1000 Hz`, and
  omitting the argument keeps the current `200 Hz` default.
- The selected value is compiled into the Teensy bridge and therefore becomes
  the value restored after power-up or reset. Teensy then sends that value to
  all four STM32 modules through the existing Host SPI command field.
- Runtime GUI and serial `SCAN_HZ` control remains unchanged and can temporarily
  override the compiled default until the next Teensy reset.
- Extended the generic Teensy uploader with an optional compile-definition
  argument without changing existing three-argument callers.
- Updated the current command references and removed obsolete ACC-era details
  from the four-module command documentation.

| Check | Result |
|---|---|
| Script validation | PASS; non-numeric and values above `1000` are rejected before compile/upload |
| Teensy compile with default `200 Hz` | PASS; code `15,620 B`, RAM1 variables `25,984 B` |
| Teensy compile with non-default `150 Hz` | PASS; `-DESKIN_DEFAULT_SCAN_HZ=150` confirmed in generated compile commands; code `15,620 B` |

## Mask-only Delta protocol

- Replaced the previous Delta `changed_count` plus 4 B coordinate record layout
  with an ESK v4 mask layout.
- Each `ESKD` contains one 32 B mask for FSR1 and one 32 B mask for FSR2,
  followed by one 16-bit current value for every set bit. The PC derives the
  number of values from the masks; no `changed_count` is transmitted.
- Zero changes remain an `ESKD` frame with two all-zero masks (84 B including
  header and CRC). `ESK0` is no longer generated or accepted by the active
  STM32, Teensy, or PC parser.
- The normal Delta frame no longer switches between coordinate records and a
  heartbeat based on the number of changes. If more than 480 values would be
  required, the STM32 sends a complete `ESKF` because the 1044 B Host SPI slot
  cannot contain the mask plus all 512 values.
- Updated the active protocol documentation, command reference, throughput
  formula, and comparison SVG. FULL, SPATIAL, and MUL1 v2 remain unchanged.
- All four STM32 modules and the Teensy must be reflashed together because the
  ESK protocol version changed from v3 to v4.

| Check | Result |
|---|---|
| PC parser syntax check | PASS |
| PC parser self-test | PASS; two-layer mask Delta, zero-mask Delta, CRC, and base-sequence rejection |
| STM32 Release build | PASS; FLASH `14,340 B`, RAM `9,344 B` |
| Teensy compile-only check | PASS; code `15,604 B`, RAM1 variables `25,984 B`, RAM2 variables `12,416 B` |
| Four-module hardware Delta validation | Pending; reflash all STM32 modules and Teensy, then verify `ESKF` followed by mask `ESKD` frames |
