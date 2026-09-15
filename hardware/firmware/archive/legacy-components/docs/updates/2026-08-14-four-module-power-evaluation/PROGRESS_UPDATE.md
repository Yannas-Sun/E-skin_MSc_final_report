# Four-module evaluation plan: data, power, calibration and scalability

Date: 2026-08-15

Status: design only. No multi-module hardware test has been executed.

## 1. Purpose and realistic baseline

This plan evaluates one Teensy 4.1 controlling up to four STM32-based E-SKIN
modules through one shared Host SPI bus and one external regulated power supply.
It is a practical four-module validation slice of the planning report's
five-module objective. The experiment is not allowed to claim four modules at
700 Hz unless that rate is measured on every module with valid analogue data.

The current evidence must be separated into three cases:

| Path | Measured single-module result | Use in this plan |
|---|---:|---|
| Normal STM32 Combined | 238.475 complete fresh scans/s | Primary data baseline |
| SCLK33 refint7p5 | 439.299 complete scans/s | Diagnostic, out-of-spec ADC clock |
| Original direct Teensy | 700.210 frames/s | Historical comparison; bypasses STM32/Host SPI |

The production-oriented multi-module test therefore starts at 100 Hz, uses
150 Hz as the first candidate, and tests 200 Hz as a stress point. The actual
per-module rate, not the requested rate, is the acceptance result.

Each current ESK1 frame is 1188 bytes: 1024 bytes of two FSR matrices, 144
bytes of nine ACC records, 16 bytes of header and 4 bytes of trailer.

~~~
wire_bits_per_second = 1188 * 8 * sum(measured_module_rate)
SPI_utilisation       = wire_bits_per_second / Host_SPI_Hz
~~~

At the validated 10 MHz Host SPI:

| Configuration | Raw data rate | Approx. bus use |
|---|---:|---:|
| 1 x 238.475 Hz | 2.266 Mbps | 22.7% |
| 1 x 439.299 Hz | 4.175 Mbps | 41.8% |
| 4 x 238.475 Hz | 9.066 Mbps | 90.7% |
| 4 x 439.299 Hz | 16.700 Mbps | 167.0% - impossible at 10 MHz |

The four-module plan must therefore identify the highest fair rate that fits
the measured bus, rather than assume the historical 700 Hz target.

## 2. Three evaluation pillars

~~~mermaid
flowchart LR
    D["Data capacity and quality"] --> X["1 to 4 module scalability decision"]
    P["Power and thermal scaling"] --> X
    C["Calibration and repeatability"] --> X
    X --> R["Measured boundary and five-module extrapolation"]
~~~

### Pillar A - Data

Data evaluation has two separate pass conditions:

1. transport correctness: bytes, identity, sequence and CRC are correct;
2. sensor correctness: FSR and ACC values are fresh and non-collapsed.

The existing periodic CRC mode is useful for throughput profiling, but final
acceptance must include a diagnostic build with CRC checked on every frame.
CRC success alone does not prove that ADC values are valid.

For every module and every non-overlapping 200-frame FSR window, record:

~~~
boundary-code proportion       < 65% on both FSR layers
median unique values per cell  >= 4
frozen cells                   <= 5%
cells with <=3 unique values   <= 20%
changed-cell proportion        >= 40%
~~~

Also record per module:

- measured frame rate and p95 inter-frame interval;
- frame drops, sequence gaps, magic/header errors and CRC errors;
- inner and outer CRC coverage separately;
- ACC WHO_AM_I, online mask and genuinely fresh sample rate;
- Teensy queue high-water and PC write drops;
- fairness: min(module_rate) / mean(module_rate).

The nominal multi-module pass target is frame drop <1%, p95 interval <1.5
times the requested period, fairness >=0.90, no sustained queue growth, and zero
errors in the all-frame diagnostic-CRC run.

### Pillar B - Power

Power is evaluated independently from data. A system that streams correctly
but browns out or has nonlinear branch loading does not pass.

Use the permitted module input, currently documented as FPGA_3V3_IN; verify
the board revision before applying voltage. Use a current-limited regulated
supply, star-distributed branches, and a fuse or current monitor per module.
Teensy USB and DAPLink must not back-power the module rail.

Measure for N = 1, 2, 3 and 4 modules:

- no-load and idle current;
- inrush current;
- current at 100, 150, 200 Hz and the measured data boundary;
- current with no contact, uniform pressure and dynamic press/release;
- branch voltage, connector voltage, rail droop, ripple and temperature;
- current after a 5-minute warm-up and throughout each 10-minute run.

Power pass conditions:

- no brownout, reset or current-limit event;
- every module rail remains within +/-5% of nominal;
- at least 20% supply headroom at the four-module worst case;
- no abnormal heating or monotonic thermal runaway;
- total and branch current are approximately predictable as module count rises.

Report the fitted current slope, intercept, residuals and any nonlinear step.

### Pillar C - Calibration and repeatability

Calibration is per module, not one global correction table. Each calibration
record must contain:

~~~
module_id, board serial, CS/IRQ slot, firmware hash
raw zero capture, reference-load capture, timestamp, operator/setup metadata
~~~

Run the following sequence:

1. unloaded zero capture for each module;
2. identical reference load applied to the same physical locations;
3. release and repeat to measure hysteresis/repeatability;
4. compare normalized response between modules;
5. disassemble/reassemble three times and repeat the zero/reference test;
6. correlate shared press/release events with ACC timestamps.

Calibration must not hide a failed raw-data quality test. Store raw frames and
calibrated values separately so the transformation is reproducible.

Targets inherited from the planning report are:

- inter-run calibration variation <10%;
- inter-module variation after normalization <10%;
- post-reassembly force performance within 20% of the baseline;
- median residual FSR-ACC timing error <5 ms with no systematic drift.

## 3. Shared-bus architecture

~~~text
Teensy SCK/MOSI/MISO  -> all modules
Teensy CS0            -> Module 0       Module 0 IRQ -> Teensy IRQ0
Teensy CS1            -> Module 1       Module 1 IRQ -> Teensy IRQ1
Teensy CS2            -> Module 2       Module 2 IRQ -> Teensy IRQ2
Teensy CS3            -> Module 3       Module 3 IRQ -> Teensy IRQ3
Common GND            -> all boards
~~~

### Recorded J1-to-Teensy allocation

The following is the wiring record used by the evaluation plan. It is a
proposed four-module harness and has not yet been hardware-validated. J1 pin
numbers follow the corrected connector numbering in `docs/WORKFLOW.md`.

| Module | J1-4 `HOST_SCK` | J1-5 `HOST_MOSI` | J1-6 `HOST_MISO` | J1-7 `HOST_nCS` | J1-8 `HOST_IRQ` |
|---|---|---|---|---|---|
| Module 0 | Teensy pin 13 (shared) | pin 11 (shared) | pin 12 (shared) | pin 10 | pin 2 |
| Module 1 | Teensy pin 13 (shared) | pin 11 (shared) | pin 12 (shared) | pin 14 | pin 3 |
| Module 2 | Teensy pin 13 (shared) | pin 11 (shared) | pin 12 (shared) | pin 15 | pin 4 |
| Module 3 | Teensy pin 13 (shared) | pin 11 (shared) | pin 12 (shared) | pin 16 | pin 5 |

For every module, connect J1-2 and J1-3 to the common ground. Connect J1-1
(`FPGA_3V3_IN`) to an individually protected external regulated 3.3 V branch;
the four-module setup must not draw its supply from the Teensy 3.3 V pin. Leave
J1-9 (`HOST_SYNC`) unconnected with the current bridge. Keep J1-10 (`NRST`) on
the module's DAPLink reset path rather than a Teensy data GPIO.

Only one CS may be LOW. Every deselected STM32 must release MISO to high-Z, and
the four push-pull IRQ lines must remain separate. This allocation records the
physical proposal; it does not mean that the current firmware already supports
four-module scheduling or the `MUL1` envelope.

During evaluation, Teensy uses round-robin service, a per-module timeout and an
offline state so one failed module cannot block the remaining modules.

Keep the 1188-byte STM32 ESK1 payload unchanged initially. Add a Teensy-side
MUL1 envelope containing module ID, payload length, global sequence, module
sequence and an outer CRC32. The inner ESK1 sequence remains independent for
each module.

## 4. Practical test sequence

### Stage 0 - single-module regression

- Build with MAX_MODULES=1 and verify the existing GUI/parser.
- Run 30 seconds unloaded and 30 seconds with controlled pressure.
- Use the normal Combined path as the primary baseline.
- Save measured rate, all-frame CRC result, FSR quality, ACC health and power.

No multi-module test proceeds if this regression fails.

### Stage 1 - power commissioning

- Verify supply voltage and current limit with SPI disconnected.
- Connect modules one at a time and record inrush, idle current and rail voltage.
- Enable all four for 10 minutes before attaching the shared bus.

### Stage 2 - shared-bus electrical test

- With all CS HIGH, verify every MISO is high-Z.
- Select each module alone and inspect CS setup/hold, first/last SCK and IRQ.
- Add modules one at a time and check for MISO contention or false IRQs.

Logic-analyser failure is an electrical failure even if a short CRC test passes.

### Stage 3 - identity and protocol test

- Read one frame from each module with scheduling gaps.
- Verify MUL1, module ID, length, outer CRC and inner ESK1 header.
- Check module sequence and global interleaved sequence separately.
- Reset one module and verify the other modules continue.

### Stage 4 - data-capacity sweep

Run equal target rates on N = 1, 2, 3 and 4 modules:

| Point | Target | Duration | Role |
|---|---:|---:|---|
| D1 | 100 Hz/module | 10 min x 3 | baseline |
| D2 | 150 Hz/module | 10 min x 3 | first nominal candidate |
| D3 | 200 Hz/module | 10 min x 3 | stress candidate |
| D4 | +25 or +50 Hz | 2 min/point | find measured boundary |
| D5 | 238.475 Hz | single module | normal Combined reference |
| D6 | 439.299 Hz | single module | labelled out-of-spec diagnostic |

Do not use 700 Hz as a four-module acceptance point. The historical 700 Hz
result is a direct-Teensy bypass and is recorded only as an architectural
comparison.

### Stage 5 - data quality and long-run test

At the selected four-module nominal point, run ten 10-minute tests. Only after
those pass, run three 50-minute tests and one capture/replay at the measured
boundary. Record raw binary, parsed summaries, CRC coverage, queue high-water,
PC CPU/memory and write drops.

### Stage 6 - power scaling test

Repeat the selected data points while measuring total and branch current. Fit
power against module count and rate. Repeat the four-module nominal point three
times and compare no-contact, uniform-load and dynamic-load conditions.

### Stage 7 - calibration and reassembly test

Perform the per-module zero/reference/release sequence, three reassemblies and
the shared press/ACC timing test. Reject any result that only passes after
calibration but fails the raw FSR criteria.

### Stage 8 - fault isolation

Test one fault at a time: module power removal, STM32 reset, IRQ disconnect, CS
held HIGH, MISO disconnect and queue pressure. Other modules must continue; the
failed module must be labelled offline/timeout; recovery must not require
restarting Teensy.

## 5. Scalability decision

Plot N = 1..4 against:

~~~
aggregate and per-module frame rate
fairness and SPI utilisation
transport/data-quality errors
total and branch current
rail droop and temperature
calibration variation and reassembly error
queue high-water and PC CPU
~~~

The design is scalable only if adding a module requires a configuration-table
entry plus CS/IRQ assignment, while protocol, GUI routing, logging, calibration
metadata and fault handling remain unchanged.

The report must distinguish three possible boundaries:

1. data-limited: Host SPI or acquisition cannot sustain the requested rate;
2. power-limited: rail, current or thermal margin is insufficient;
3. calibration/mechanical-limited: raw data works but repeatability or
   reassembly fails.

Finally extrapolate the measured N=1..4 curves to five modules. If five modules
at 700 Hz remain a requirement, the current 10 MHz Host SPI is insufficient;
the next architecture requires a faster link, shorter/compressed payload or a
module-level aggregator/FPGA.

## 6. Required software and deliverables

Before the shared-bus test, implement and test:

- the initial selectable single-module test in
  `teensy/applications/scalablity/` (same ESK1 stream and GUI, module ID
  selected through the CS/IRQ slot);
- MAX_MODULES and a CS/IRQ module table;
- round-robin scheduling, timeouts and offline/rejoin states;
- the MUL1 envelope and module-aware GUI/parser;
- per-module transport, data-quality, power-run and calibration counters;
- diagnostic all-frame CRC mode;
- command-line configuration for module count, IDs and FSR/ACC rates;
- MAX_MODULES=1 regression and an unchanged stable rollback command.

Deliverables:

- wiring and external-power diagram;
- module inventory and firmware/build hashes;
- logic-analyser captures;
- raw binary frames and parsed CSV/JSON summaries;
- power and temperature CSV;
- calibration/reassembly records;
- N=1..4 rate, power and quality plots;
- measured capacity boundary and five-module extrapolation;
- reproducible commands and rollback steps.

This plan is complete only when data integrity, power margin, calibration
repeatability and module-level fault isolation are all reported separately.
