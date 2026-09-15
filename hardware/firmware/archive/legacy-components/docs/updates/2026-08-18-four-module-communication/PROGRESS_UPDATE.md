# Four-module communication test: implementation and staged hardware validation

Date: 2026-08-18  
Scope: the first complete four-module shared-SPI bridge, its `MUL1` transport
packet, the module-aware GUI, and the subsequent data, electrical, power,
calibration and scalability tests.

Status: **software implementation complete; staged hardware validation is the
next activity.** This report is intentionally separate from the 2026-08-15
evaluation-plan document. The older report defines the acceptance philosophy;
this report records the executable implementation and every four-module test
result as it is collected.

## 1. What is being tested

The test connects up to four STM32 sensor modules to one Teensy 4.1. The four
modules share the Host SPI clock and data wires, but each module has an
independent chip-select (`HOST_nCS`) and interrupt (`HOST_IRQ`). The Teensy
polls the four interrupt lines in round-robin order, reads valid STM32 frames,
and publishes one module-aware USB stream to the PC.

The test is not a claim that four complete modules can run at 700 full rounds
per second. The historical 700 Hz result was a direct-Teensy architecture and
is retained as an architectural comparison only. The four-module acceptance
rate must be measured with the current STM32-to-Teensy Host SPI path.

## 2. Software under test

| Component | Path | Purpose |
|---|---|---|
| Four-module Teensy bridge | `teensy/applications/scalablity/four_module/four_module.ino` | Shared SPI master, four CS/IRQ slots, round-robin reads, packet queue and diagnostics |
| Four-module GUI/parser | `teensy/applications/scalablity/four_module_monitor.py` | Validates `MUL1` and inner `ESK1`, displays 8 FSR maps and 4 ACC views |
| Upload command | `tools/commands/upload_scalablity_four_module.cmd` | Compiles/uploads the four-module Teensy sketch |
| Upload + GUI command | `tools/commands/flash_scalablity_four_module.cmd` | Uploads the bridge and starts the four-module GUI |
| GUI-only command | `tools/commands/start_scalablity_four_module.cmd` | Starts the GUI without reprogramming the Teensy |
| Wiring/usage notes | `teensy/applications/scalablity/README.md` | Pin map, packet overview and operator commands |

The STM32 side remains the existing `combined_system` image. Flash the same
STM32 image to each module before this test; module identity is assigned by the
Teensy CS/IRQ slot, not by changing the STM32 firmware.

The Teensy sketch compiled successfully for `teensy:avr:teensy41`, and the
Python parser and GUI layout self-tests passed on 2026-08-18. These are
software checks, not a substitute for a four-module electrical run.

## 3. Wiring and power configuration

### 3.1 Shared Teensy bus

| Signal | Teensy 4.1 pin | Connection rule |
|---|---:|---|
| Host SPI SCK | 13 | Common to all STM32 modules |
| Host SPI MOSI | 11 | Common to all STM32 modules |
| Host SPI MISO | 12 | Common bus; only the selected module may drive it |
| Module 0 `HOST_nCS` | 10 | Dedicated to module 0 |
| Module 1 `HOST_nCS` | 14 | Dedicated to module 1 |
| Module 2 `HOST_nCS` | 15 | Dedicated to module 2 |
| Module 3 `HOST_nCS` | 16 | Dedicated to module 3 |
| Module 0 `HOST_IRQ` | 2 | Dedicated to module 0 |
| Module 1 `HOST_IRQ` | 3 | Dedicated to module 1 |
| Module 2 `HOST_IRQ` | 4 | Dedicated to module 2 |
| Module 3 `HOST_IRQ` | 5 | Dedicated to module 3 |
| Logic ground | GND | Common ground between Teensy, modules and supply |

All four CS lines must be HIGH while the Teensy is idle. Each module's MISO
must be high-impedance when its CS is HIGH. A shared MISO line that is driven by
two modules is an electrical failure even when a short capture happens to pass
CRC.

### 3.2 External power

Use the external regulated supply defined in the power-evaluation plan. Keep
the Teensy USB supply and module sensor supply electrically intentional: do not
use the Host SPI cable to back-power a module. Before attaching SPI, verify the
module rail, current limit, common ground and branch polarity with a meter.
Record total current and each branch current for N = 1, 2, 3 and 4 modules.

## 4. Transport format and scheduling

### 4.1 Inner STM32 frame

Each STM32 module continues to produce the existing `ESK1` frame:

- 1,188 bytes per frame;
- dual 16x16 FSR data and nine ACC records;
- existing inner header, sequence number and CRC rules;
- no change to the stable single-module protocol.

### 4.2 Outer `MUL1` packet

The Teensy wraps the latest valid frame from each slot in one outer packet:

```text
20-byte MUL1 header
  + 4 x (module_id[1] + status[1] + reserved[2] + ESK1[1188])
  + 4-byte outer CRC32
```

The resulting packet is:

```text
4,752 bytes of inner ESK1 payload
+   40 bytes of outer header/block/trailer overhead
= 4,792 bytes per USB packet
```

Important fields are:

| Field | Meaning |
|---|---|
| `MUL1` | Outer magic, used for stream synchronisation |
| version/count | Outer protocol version and four-slot count |
| updated mask | Which module slots supplied a new valid frame for this packet |
| packet length/block length | Fixed lengths used by the parser |
| packet sequence/time | Host-side packet ordering and timing diagnostics |
| module ID/status | Slot identity and offline/invalid state |
| inner `ESK1` | The latest valid per-module frame; its sequence remains independent |
| outer CRC32 | Detects corruption of the complete 4,788-byte pre-trailer packet |

The bridge sends immediately after all four modules update. If one module does
not update, a 100 ms partial-round timeout sends the latest valid states plus a
non-zero status for the missing/invalid module. This prevents one dead module
from blocking the other three indefinitely. A partial packet is useful for
fault isolation, but it is not counted as a complete four-module round.

### 4.3 Current conservative timing constants

The sketch currently uses 10 MHz Host SPI, a nominal 700 Hz per-module poll
limit, 50 us IRQ settling, 10 us CS setup and 10 us CS hold. The nominal 700 Hz
constant is a scheduling ceiling, not a measured guarantee. The measured
per-module and complete-round rates, queue high-water and packet intervals are
the acceptance evidence.

## 5. Theoretical capacity before hardware testing

At four modules, one complete `MUL1` packet is 4,792 bytes:

| Quantity | Calculation | Result |
|---|---:|---:|
| Inner sensor bytes/round | 4 x 1,188 | 4,752 B |
| USB bytes/round | 4,752 + 40 | 4,792 B |
| USB rate at 100 rounds/s | 4,792 x 100 | 479,200 B/s (3.834 Mbit/s) |
| USB rate at 200 rounds/s | 4,792 x 200 | 958,400 B/s (7.667 Mbit/s) |
| USB rate at 238.475 rounds/s | 4,792 x 238.475 | 1,142,772.2 B/s (about 9.14 Mbit/s) |
| USB rate at 700 rounds/s | 4,792 x 700 | 3,354,400 B/s (26.835 Mbit/s) |

The 700-round/s figure is therefore a useful stress calculation, not a current
target. At 10 MHz Host SPI, the four inner frames alone require
`4,752 x 8 = 38,016` SCK bits per complete round, or 3.8016 ms of pure wire
time at 100% bus occupancy. The current fixed delays and STM32 acquisition
time add to this. Consequently, the first acceptance sweep uses 100, 150 and
200 Hz/module and then searches for the measured boundary.

For each run calculate, rather than assume:

```text
aggregate USB bytes/s = valid MUL1 packets/s x 4,792
inner sensor bytes/s   = valid MUL1 packets/s x 4,752
SPI payload utilisation = 8 x 1,188 x sum(module frame rates) / 10,000,000
fairness                = min(module rate) / mean(module rate)
CRC error rate          = CRC failures / received candidate packets
```

The exact decimal value at 238.475 rounds is deliberately left to the parser
output; the raw capture, not hand-calculated estimates, is the authoritative
record.

## 6. Test stages

### Stage 0 — software and parser gate (completed)

1. Compile the four-module sketch for Teensy 4.1.
2. Run the `MUL1` parser self-test with valid and corrupted outer/inner CRCs.
3. Run the GUI layout self-test: all four modules, an individual module, FSR
   only and ACC only.
4. Confirm the packet length is 4,792 bytes and the parser rejects wrong magic,
   lengths, module IDs and CRCs.

Pass evidence: compile succeeds, parser self-test reports `PASS`, and every
module/sensor selector creates the expected view. This stage passed on
2026-08-18.

### Stage 1 — one-module regression through the new bridge

Run module 0, then modules 1, 2 and 3 individually while the other three CS/IRQ
slots remain disconnected or inactive. For each slot:

- verify `HOST_IRQ` asserts and releases;
- verify only the assigned CS toggles;
- capture 30 s unloaded and 30 s with controlled FSR pressure;
- move one pressure point and confirm only that module changes in the GUI;
- check inner/outer CRC, sequence gaps, frame rate and ACC validity.

Do not continue to Stage 2 if any slot silently maps to module 0 or if a single
module cannot produce a valid frame.

### Stage 2 — shared-bus electrical commissioning

With all modules powered and all CS lines HIGH:

1. Confirm every module MISO is high-impedance.
2. Select one module at a time and inspect CS setup/hold, SCK polarity/mode,
   first/last byte and IRQ release.
3. Add the second, third and fourth module without changing firmware.
4. Check for MISO contention, false IRQs, ringing, ground bounce and rail
   disturbance with a logic analyser and oscilloscope.

Record screenshots or analyser files. CRC success alone cannot waive a bus
contention finding.

### Stage 3 — two-, three- and four-module identity test

Run the combinations `0+1`, `0+1+2` and `0+1+2+3`.

For each combination, verify that:

- the `MUL1` updated mask matches the modules that actually supplied frames;
- each block's module ID remains stable;
- each inner sequence belongs to its own module;
- the outer packet sequence is monotonic;
- resetting or temporarily unplugging one module does not relabel another;
- an offline module is marked with non-zero status and the remaining modules
  continue to update.

### Stage 4 — data-capacity sweep

Use equal requested rates for all active modules. Run each point for at least
10 minutes, with three repeats for the nominal point:

| Point | Active modules | Requested rate | Duration | Purpose |
|---|---:|---:|---:|---|
| D1 | 1, 2, 3, 4 | 100 Hz/module | 10 min x 3 | Conservative baseline |
| D2 | 1, 2, 3, 4 | 150 Hz/module | 10 min x 3 | Nominal candidate |
| D3 | 1, 2, 3, 4 | 200 Hz/module | 10 min x 3 | Stress candidate |
| D4 | 1, 2, 3, 4 | +25 or +50 Hz steps | 2 min/point | Locate measured boundary |
| D5 | 1 | 238.475 Hz | 10 min | Existing normal Combined reference |
| D6 | 1 | 439.299 Hz | short diagnostic | Existing SCLK33 reference; label out-of-spec where applicable |

The accepted four-module rate is the highest point that passes every integrity,
quality, queue and electrical criterion in three repeats. Do not call a test
“700 Hz” merely because a 700 Hz constant exists in the source.

### Stage 5 — data integrity and long-run capture

At the selected nominal four-module point:

- run ten 10-minute captures;
- then run three 50-minute captures;
- save the raw USB binary and parsed CSV/JSON summary;
- record outer CRC, inner CRC, magic/header failures, sequence gaps, module
  timeouts, queue high-water and USB write drops;
- record host CPU, memory and disk-write drops.

After the long run, replay at least one raw capture through the parser and
confirm that online and offline counts agree.

### Stage 6 — GUI and module-selection behaviour

For each run exercise:

- `All Modules` + `All`;
- each module selector + `All`;
- each module selector + `FSR`;
- each module selector + `ACC`.

Press one known FSR on one module at a time. The corresponding two FSR maps
must respond only in that module column; ACC views must remain associated with
the same module. If a module is offline, the GUI must show its waiting/offline
state rather than silently copying another module's data.

### Stage 7 — power and thermal scaling

For N = 1, 2, 3 and 4 modules, record:

- supply voltage at the source and at each module;
- total current, branch current and inrush current;
- minimum rail voltage during SPI/USB bursts;
- ripple/noise and module/Teensy temperature;
- ten-minute steady-state behaviour at unloaded, uniform-load and dynamic-load
  conditions.

Reject a rate if data quality passes but rail droop, current-limit activity or
  thermal rise is outside the power budget. Keep the power result separate from
  the data-rate result.

### Stage 8 — calibration and repeatability

For each module:

1. Record raw zero data without pressure.
2. Apply the same reference load and record the response.
3. Release and record recovery/hysteresis.
4. Repeat after three connector/module reassemblies.
5. Compare equal loads across modules after applying only documented
   normalization.
6. Check the timestamp separation between the FSR scan and the nine-ACC read.

Target checks from the evaluation plan are: inter-run variation below 10%,
inter-module variation below 10% after normalization, reassembly deviation
below 20%, and FSR/ACC timestamp separation below 5 ms. A result that passes
only after calibration but fails the raw-data quality gate is not accepted as a
transport success.

### Stage 9 — fault isolation and scalability

Inject one fault at a time: remove module power, reset an STM32, disconnect
IRQ, leave CS HIGH, disconnect MISO, and deliberately fill the Teensy USB
queue. The other modules must continue, the failed module must be labelled
offline/timeout, and recovery must not require restarting the Teensy or GUI.

Plot N = 1, 2, 3 and 4 against:

- per-module and aggregate frame rate;
- fairness and Host SPI utilisation;
- outer/inner CRC and sequence errors;
- total/branch current, rail droop and temperature;
- calibration variation and reassembly error;
- queue high-water, USB write drops and PC resource use.

The implementation is considered scalable only if adding a module requires a
configuration-table entry plus CS/IRQ wiring while packet parsing, GUI routing,
logging, calibration metadata and fault handling remain unchanged.

## 7. Pass/fail criteria

Every row in the test log must include the active module set, requested rate,
duration, power condition and evidence file. The following are the minimum
gates; stricter project limits may be applied in the final acceptance report.

| Category | Minimum pass condition |
|---|---|
| Identity | No module-ID swaps; each slot maps to its physical module |
| Transport | Outer magic/header/length valid; outer and inner CRC error rate 0 in acceptance runs |
| Sequencing | No unexplained outer sequence gaps; per-module gaps and timeouts recorded as failures |
| ADC/FSR quality | Use the established quality gates: boundary codes <65%, median cell unique values >=4, frozen cells <=5%, low-unique cells <=20%, changed cells >=40% |
| Fairness | `min(module_rate) / mean(module_rate)` >= 0.90 at the selected nominal point |
| Queue | No sustained queue growth, USB write drop or overflow |
| GUI | Correct module-only response for FSR and ACC selectors; offline state visible |
| Power | No current-limit event; rail and temperature remain within the approved budget |
| Calibration | Inter-run <10%, normalized inter-module <10%, reassembly <20%, FSR/ACC separation <5 ms |
| Fault isolation | One failed module cannot stop or relabel the remaining modules |

Any failure must be classified as **data-limited**, **electrical**,
**power/thermal**, **calibration/mechanical** or **software/host**. Do not hide a
failure by averaging it into the aggregate rate.

## 8. Test-result log

Append one row after every meaningful run. Link the raw binary, analyser file,
power CSV or parser summary in the Evidence column.

| Date/time | Stage | Modules | Requested rate | Duration | CRC/sequence | Power | GUI | Result | Evidence |
|---|---|---:|---:|---:|---|---|---|---|---|
| 2026-08-18 | Stage 0: Teensy compile | software | n/a | n/a | parser self-test PASS | n/a | layout self-test PASS | PASS (software gate) | local build/self-test output |
| 2026-08-18 | Stage 0: `MUL1` parser | software | n/a | n/a | valid/corrupt outer and inner cases PASS | n/a | n/a | PASS (software gate) | `four_module_monitor.py` self-test |
| 2026-08-18 | Stage 0: GUI layout | software | n/a | n/a | n/a | n/a | 8 FSR + 4 ACC and selectors PASS | PASS (software gate) | GUI layout self-test |
| — | Stage 1: module 0 regression | 0 | — | — | pending | pending | pending | PENDING | add capture/log link |
| — | Stage 1: module 1 regression | 1 | — | — | pending | pending | pending | PENDING | add capture/log link |
| — | Stage 1: module 2 regression | 2 | — | — | pending | pending | pending | PENDING | add capture/log link |
| — | Stage 1: module 3 regression | 3 | — | — | pending | pending | pending | PENDING | add capture/log link |
| — | Stage 3: two-module identity | 0+1 | — | — | pending | pending | pending | PENDING | add analyser/capture link |
| — | Stage 3: three-module identity | 0+1+2 | — | — | pending | pending | pending | PENDING | add analyser/capture link |
| — | Stage 3: four-module identity | 0+1+2+3 | — | — | pending | pending | pending | PENDING | add analyser/capture link |
| — | Stage 4–9: four-module acceptance | 0+1+2+3 | — | — | pending | pending | pending | PENDING | add complete evidence set |

## 9. Reproducible operator commands

Run from PowerShell. Close any other program that owns `COM9`, confirm all four
STM32 modules are powered and flashed with the stable `combined_system` image,
then manually reset/power-cycle the modules before opening the GUI.

```powershell
# Upload the four-module Teensy bridge and start its GUI
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_scalablity_four_module.cmd" COM9

# Upload only (useful when the GUI is already running)
& "D:\study\programming\ESKIN\firmware\tools\commands\upload_scalablity_four_module.cmd" COM9

# Start the four-module GUI without reflashing
& "D:\study\programming\ESKIN\firmware\tools\commands\start_scalablity_four_module.cmd" COM9
```

During a test, keep a raw serial capture and the Teensy diagnostic lines:

```text
#MULDBG ... packet_bytes=4792 spi_hz=10000000 ...
#MULMOD id=... cs=... irq=... ok=... bad=... crc=... gaps=... timeout=...
```

Diagnostics are evidence only when saved with a timestamp and the active module
set. A GUI screenshot without the raw stream cannot prove CRC, sequence or
fairness.

## 10. Next action

Start at Stage 1 with one module at a time, then proceed to the shared-bus
electrical check before connecting all four. After each run append the result
row above and, when a failure occurs, append the technical cause and recovery
to `docs/WORKFLOW.md`. The final four-module conclusion must report the
measured N=1..4 boundary separately for data, power, calibration and
scalability; it must not replace those four dimensions with one aggregate FPS
number.
