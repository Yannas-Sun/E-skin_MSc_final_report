# Scan-rate limitation analysis: why the current STM32 path does not reach 700 Hz

Date: 2026-08-19  
Scope: timing, ADC clock limits, transport overhead, the comparison between the
original Teensy-direct scan and the current STM32 + Teensy architecture, and
the four-module transport/software roadmap.

Status: **700 Hz is not achieved by the current STM32 full-scan path.** The
original Teensy-direct architecture did reach 700.210 complete frames/s in a
10-second transport run, but that result used a materially different timing
path and still requires a controlled pressure/analogue validation. The
four-module bridge, fixed `MUL1` packet, parser and module-aware simulator page
are implemented; the next work is to make the four-module path more adaptive,
fault-aware and bandwidth-efficient.

## 1. What “700 Hz” means

For one complete module frame, 700 Hz means one fresh dual-FSR plus nine-ACC
frame every:

```text
1 / 700 = 1,428.6 microseconds
```

The frame is not only an FSR scan. The deadline includes all 16 MUX addresses,
both 16-channel ADCs, MUX settling, nine accelerometers, frame packing, CRC or
status handling, Host SPI handshaking and the STM32-to-Teensy transfer.

For four modules, 700 Hz per module would require 2,800 complete module frames
per second on one shared Host SPI bus. That is a separate and substantially
harder target than 700 four-module aggregate packets per second.

## 2. The measured current baseline

The maintained Combined image performs the complete acquisition on STM32 and
uses Teensy only as the Host SPI master and USB bridge. Its documented
30-second full-scan result is:

| Configuration | Complete-frame rate | Data-quality result |
|---|---:|---|
| Stable current Combined image | **238.475 frames/s** | Valid transport, fresh FSR rate much lower than 700 |
| SCLK33 at 2.5 MHz | 205.444 frames/s | Baseline ADC-quality pass |
| SCLK33 at 7.5 MHz | **439.299 frames/s** | Transport/quality windows pass, but out of ADC specification |
| SCLK33 at 10 MHz and STM32 160 MHz | 581.667 frames/s | CRC/transport pass, ADC bit-boundary distortion |
| Old Teensy-direct scan | **700.210 frames/s** | Transport pass; analogue pressure validation still required |

The 7.5 MHz and 10 MHz SCLK33 values are diagnostic experiments, not
specification-compliant production settings. The stable current result remains
well below the 700 Hz deadline.

Evidence is retained in:

- [`2026-08-11-full-scan-700hz`](../2026-08-11-full-scan-700hz/PROGRESS_UPDATE.md)
- [`2026-08-12-sclk-frequency-sweep`](../2026-08-12-sclk-frequency-sweep/PROGRESS_UPDATE.md)
- [`2026-08-12-sclk33-second-reproduction`](../2026-08-12-sclk33-second-reproduction/PROGRESS_UPDATE.md)
- [`2026-08-12-original-teensy-700hz`](../2026-08-12-original-teensy-700hz/PROGRESS_UPDATE.md)

## 3. ADC SCLK lower bound

The reproduced 33-byte transaction needs 33 bytes for each ADC and MUX
address. A complete dual-FSR scan therefore clocks:

```text
2 ADCs × 16 addresses × 33 bytes = 1,056 bytes
```

The wire-only FSR time is:

| ADC external SCLK | FSR wire time only |
|---:|---:|
| 10 MHz | 844.8 us |
| 7.5 MHz | 1,126.4 us |
| 4.8 MHz | 1,760.0 us |

The MAX11633 external conversion SCLK limit is 4.8 MHz. To clock the FSR
bytes alone at 700 Hz would require:

```text
1,056 × 8 × 700 = 5.9136 MHz
```

That is already above the 4.8 MHz external-conversion limit and leaves no time
for MUX settling, ACC, packing or Host SPI. The 10 MHz values used in the
legacy reproduction are therefore out-of-spec experiments. The normal
internal-conversion Combined path must not be confused with a 10 MHz external
conversion clock: its read clock and ADC conversion timing are different.

## 4. Host SPI budget

One complete `ESK1` frame is 1,188 bytes. At the current 10 MHz Host SPI:

```text
1,188 × 8 / 10 MHz = 950.4 us per module frame
```

At 700 Hz, only about 478.2 us remains in the 1,428.6 us period for the STM32
to acquire both FSR layers, read ACC, pack the frame and manage IRQ/NSS.
The current acquisition phase exceeds that remaining budget.

For four modules sharing the same Host SPI, transferring one frame from each
module already takes approximately:

```text
4 × 950.4 us = 3.80 ms
```

before acquisition and scheduling overhead. A 700 Hz complete update for every
module therefore cannot be obtained from the current single 10 MHz Host SPI
link.

## 5. Why the old Teensy-direct code was faster

The verified old run used `ESKIN_ORIGINAL_700HZ.ino` and had a different
critical path:

1. Teensy directly drove the MUX and both ADCs.
2. The ADC conversion and result read used one continuous Mode-0 transaction.
3. EOC was not polled.
4. No explicit MUX settling delay was inserted.
5. There was no STM32 acquisition/packing/Host-SPI hop.
6. The fixed 1,132-byte frame went directly from Teensy to USB.

This explains why identical MUX and ADC hardware does not produce identical
rates. The old run proves that the direct architecture can meet the timing
target, not that the current STM32 pipeline can do so with the same analogue
and protocol guarantees. Its unloaded FSR range was only 0..29, so controlled
pressure response, crosstalk, mapping and long-duration analogue validation
remain required.

## 6. Why the current optimisations are insufficient

The current firmware already uses several optimisations:

- overlapping ADC conversion phases where possible;
- SPI1 DMA for FSR transfers in the SCLK33 experiment;
- Host SPI3 DMA and ping-pong buffers;
- pipelined frame packing and USB queueing;
- periodic CRC experiments.

These reduce CPU blocking but do not remove the physical ADC SCLK budget,
MUX/analogue settling requirement, serial Host SPI wire time or the nine-ACC
transactions. The 160 MHz experiment improved the FSR phase to about 1,426 us,
but that alone consumed essentially the entire 1,428.6 us target period before
the approximately 159 us ACC phase and 53 us packing phase. Its ADC data also
failed the quality criteria despite zero sampled packet CRC errors.

## 7. Final conclusion

The current STM32 architecture fails to reach 700 Hz for two independent
reasons:

1. **Timing:** the complete FSR + ACC + packing + transport path is longer than
   1,428.6 us.
2. **ADC integrity:** the SCLK needed to close that gap is above the MAX11633
   external-conversion specification, and the out-of-spec 8.75–10 MHz tests
   produced ADC bit-boundary/frozen-code distortion.

Consequently, increasing only the STM32 CPU clock, changing CRC cadence or
changing the GUI cannot establish a valid 700 Hz result. A future 700 Hz
design needs a different hardware/timing budget: parallel ADC conversion or
additional acquisition hardware, reduced/partial payloads, multiple Host SPI
links, or a validated direct-Teensy-style analogue path. For the current
hardware, the specification-compliant rate must be measured and accepted below
700 Hz, with ADC-quality and pressure-response tests reported separately from
packet throughput.

## 8. Simulator session

The local software simulator was started on 2026-08-19 and responded at:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/multi-module-live.html
```

The simulator is useful for viewing parsed frames and module layouts; it does
not change the physical scan-rate limit or substitute for the STM32/Teensy
hardware measurements above.

## 9. Four-module functionality implemented so far

The current four-module implementation is a transport and visualisation layer
around the existing single-module `ESK1` frame. It does not pretend that the
four modules can each deliver 700 fresh full scans per second.

### 9.1 Shared-SPI Teensy bridge

The Teensy four-module sketch now provides:

- four independent `HOST_nCS` and `HOST_IRQ` slots;
- shared Host SPI SCK/MOSI/MISO, with only the selected CS driving MISO;
- round-robin polling of Module 0 through Module 3;
- per-module sequence, CRC, timeout, bad-frame and release-timeout counters;
- a 10 MHz Mode-0 Host SPI transaction for each valid STM32 frame;
- a small USB transmit queue so USB draining does not overwrite the next
  assembled packet;
- a 100 ms partial-round timeout, so one absent or slow module does not stop the
  other modules indefinitely;
- an `updatedMask` that records which modules supplied a new frame in the
  current outer packet.

The pin map and upload commands are documented in
[`four-module-communication`](../2026-08-18-four-module-communication/PROGRESS_UPDATE.md)
and [`scalablity/README.md`](../../../teensy/applications/scalablity/README.md).

### 9.2 `MUL1` multi-module packet

The outer packet is implemented as a fixed four-slot envelope:

```text
MUL1 header (20 B)
+ 4 × (module ID + status + reserved + 1,188-byte ESK1 frame)
+ outer CRC32 (4 B)
= 4,792 B
```

This gives the host a stable packet boundary while preserving each module's
independent inner sequence and timestamp. A partial packet can still carry
valid frames from the other modules, which is useful for fault isolation and
scalability tests.

### 9.3 Parser and four-module GUI

The software-simulation integration now supports:

- strict `MUL1` magic, version, module-count, length and block-size checks;
- outer CRC32 validation followed by per-module `ESK1` validation;
- reconstruction of the latest FSR1 and FSR2 matrices for every module;
- reconstruction of the nine ACC records for every module;
- `All modules` or a single Module 0–3 selector;
- `FSR + ACC`, `FSR only` and `ACC only` views;
- packet FPS, USB bit rate, packet sequence and CRC/parse-error counters;
- a separate four-module live page that does not interfere with the legacy
  single-module live page.

The current page is available at
[`multi-module-live.html`](../../../software-simulation/frontend/multi-module-live.html).

### 9.4 What this implementation already proves

The present implementation demonstrates that four modules can be identified,
framed, parsed and routed independently over one shared-SPI topology. It also
provides the instrumentation needed for the next evaluation stage: per-module
fairness, updated-mask behaviour, queue pressure, CRC/sequence integrity and
GUI fault visibility. It does **not** yet prove a four-module 700 Hz complete
round, nor does it make a previously valid frame fresh after a module has been
unplugged.

## 10. Scanning and transport strategies available in the software simulator

The copied software simulator already models several strategies that can guide
the next firmware revision. These are algorithmic references, not claims that
the corresponding strategy is already running on the STM32 boards. The source
comparison is documented in
[`software-simulation/docs/FIRMWARE_ALGORITHMS.md`](../../../software-simulation/docs/FIRMWARE_ALGORITHMS.md).

### 10.1 Time-sparse full-frame mode

The simulator's Combined mode uses a low idle rate (10 Hz), performs a tare or
baseline comparison, switches to a requested high-speed rate when pressure
exceeds a threshold, and returns to the idle rate after approximately one
second without a trigger. This can reduce average bandwidth and power without
changing the full-frame format during an active touch.

Candidate four-module adaptation:

- keep a low-rate health/heartbeat scan for every module;
- promote only the module(s) whose sentinel values cross the trigger threshold;
- retain the normal full `ESK1` frame for the active module;
- include per-module scan mode and freshness in `MUL1` status metadata.

### 10.2 Delta transport

The simulator's Delta strategy sends a complete synchronisation frame
periodically and sends only FSR cells whose baseline-relative value changed
above a deadband on intervening frames. The current reference uses a change
threshold of 8 ADC codes and reconstructs the full matrix in the receiver.

Candidate `MUL1` extension:

```text
MUL1D header
+ module ID, base sequence, changed-count
+ (layer, row, column, value) records
+ periodic full-frame checkpoint
+ outer CRC32
```

This reduces USB traffic when most cells are stationary, but requires a
per-module receiver state, explicit checkpoint loss recovery and a timeout that
marks reconstructed data stale.

### 10.3 Spatial sparse scanning

The simulator's spatial strategy keeps six sentinel rows/columns active during
idle operation (1-based rows/columns 2, 5, 7, 10, 12 and 15). A triggered point
enables its local 3×3 neighbourhood; multiple points are combined by mask
union; the neighbourhood remains active for about one second after the last
trigger so release values are not lost.

The corresponding sparse transport uses:

- `ESP0`: short idle/no-change packet;
- `ESPD`: changed points in the current scan mask;
- `ESPF`: a periodic synchronisation packet containing the mask and current
  baseline-relative values.

This strategy has the greatest potential to reduce the current 16-row FSR
cost, but it must first be validated against MUX settling, crosstalk, missed
small contact areas and pressure release behaviour on real hardware.

### 10.4 Independent FSR and ACC rates

The simulator and the SCLK33 experiment both support independent FSR and ACC
refresh targets. The current hardware can therefore be scheduled as, for
example, a high-rate FSR path with a lower ACC update rate while keeping one
fixed output envelope. The receiver must expose freshness flags rather than
presenting a retained ACC sample as a newly sampled value.

### 10.5 Patch-level aggregation and throughput accounting

The simulator already models arbitrary module placement, patch grouping and
throughput as a function of module count and sample rate. This should become a
planning tool for the hardware scheduler: choose which modules are active,
calculate aggregate payload/USB rate before flashing, and reject a requested
rate that cannot fit the shared Host SPI budget.

## 11. Further functionality to add

The next additions should be staged so that rate improvements never hide data
quality or fault-isolation failures.

### Priority 1 — freshness and fault correctness

1. Add a per-module `last_valid_ms` or age field to `MUL1`.
2. Mark a previously valid module stale/offline after a bounded number of
   missed updates; do not continue labelling its last frame `valid`.
3. Make the GUI distinguish `fresh`, `stale`, `waiting`, `CRC error` and
   `timeout` states.
4. Add a recovery test: unplug, reconnect and reset one module while the other
   three continue without relabelling.

### Priority 2 — adaptive four-module scheduling

1. Replace the fixed round-robin assumption with a per-module scheduler and
   measured deadlines.
2. Support independent FSR and ACC rates per module.
3. Keep low-rate health polling for inactive modules and allocate bus time to
   modules with fresh IRQs or trigger activity.
4. Record per-module rate, fairness, scan age and Host SPI utilisation in the
   diagnostic stream.

### Priority 3 — bandwidth-aware packet formats

1. Prototype a `MUL1D` delta envelope with periodic full checkpoints.
2. Prototype a `MUL1S` spatial-sparse envelope based on sentinel rows/columns
   and 3×3 mask union.
3. Add packet version negotiation or an explicit bridge mode so old `ESK1`
   receivers continue to work.
4. Define resynchronisation behaviour after a dropped delta or sparse packet;
   the next full checkpoint must restore the module without restarting the
   Teensy or GUI.

### Priority 4 — hardware validation of sparse algorithms

For one module first, then four modules, measure:

- missed contacts between sentinel lines;
- response latency when a new contact appears outside the current mask;
- adjacent-row/column crosstalk;
- pressure release and hysteresis;
- FSR quality metrics and ACC freshness;
- actual Host SPI, USB and power reductions.

Only after these tests pass should sparse scanning be used to claim a higher
*event-response* rate. It must not be reported as 700 Hz full-matrix refresh.

### Priority 5 — scalability beyond four modules

The current packet and parser deliberately fix the module count at four. To
support a fifth module or a larger patch, add a capability/count field, a
variable-length or segmented packet format, dynamic CS/IRQ configuration and a
GUI module registry. A fifth module connected to an unconfigured pin is not
discovered by the current bridge.

## 12. Updated roadmap and acceptance rule

The next evaluation sequence is:

1. Complete the four-module freshness/offline fix and replay tests using
   synthetic `MUL1` packets in the simulator.
2. Run the current full-frame four-module rate sweep at 100, 150 and 200
   Hz/module with power and queue instrumentation.
3. Implement and parser-test one delta or spatial-sparse `MUL1` prototype.
4. Validate that prototype on one module under controlled pressure.
5. Repeat on two, three and four modules, measuring payload, fairness, power,
   temperature, CRC and recovery time.
6. Compare full-frame and sparse modes in the simulator and with raw hardware
   captures.

The acceptance criterion remains: a mode is successful only when its stated
scan semantics, ADC quality, CRC/sequence integrity, fairness, power budget
and fault recovery all pass. A smaller packet or a higher GUI update rate by
itself is not evidence of a 700 Hz full 16×16 scan.
