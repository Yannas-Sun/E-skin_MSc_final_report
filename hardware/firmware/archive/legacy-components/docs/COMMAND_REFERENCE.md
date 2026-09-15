# E-SKIN Firmware Command Reference

> **2026-08-30 路径更新：** 本文保留历史命令解释；可运行脚本已统一移至
> [`../shared/commands/`](../shared/commands/)，请优先使用
> [`../shared/commands/CURRENT_COMMANDS.md`](../shared/commands/CURRENT_COMMANDS.md)。

This is the single operational index for STM32 builds/flashing, Teensy
uploads, serial readers, GUIs, and diagnostic flags. Historical reasoning stays
in `docs/WORKFLOW.md`; use this file for day-to-day commands.

> 中文：本文件只保留实际操作所需内容。先选择固件，再选择匹配的 Teensy
> bridge，最后启动对应的 PC reader/GUI。不要同时打开 Arduino Serial Monitor
> 和 Python reader，因为一个 COM port 只能被一个程序占用。

## 1. Command directory

All Windows command files are located in:

```text
firmware/tools/commands/
```

The original low-level implementations are grouped under
`tools/commands/original/`. Same-name compatibility launchers remain in the
top-level directory, so existing commands and historical documentation keep
working. See `tools/commands/README.md` for Chinese descriptions and complete
absolute command lines for every script.

From PowerShell, set the command directory once:

```powershell
$cmd = "D:\study\programming\ESKIN\firmware\tools\commands"
Set-Location $cmd
```

| Command | Arguments | Purpose |
|---|---:|---|
| `flash_combined.cmd` | none | Build/flash FSR1 + FSR2 + all 9 ACCs |
| `flash_combined_pair.cmd` | `[COM port]` | Build/flash combined STM32, then compile/upload its Teensy bridge |
| `flash_combined_sclk33_experiment.cmd` | `[COM] [profile] [view] [confirmation] [FSR Hz] [ACC Hz]` | Isolated 33-byte SCLK scan experiment, Teensy upload and GUI; optional independent sensor update rates; 10 MHz profiles require explicit confirmation |
| `flash_acc_rate_benchmark.cmd` | `[hr1344\|lp5376]` | Build/flash the isolated nine-slot ACC rate benchmark, read a one-second SRAM result through SWD, and save JSON evidence |
| `flash_spi_pattern_test.cmd` | `[COM port]` | Build/flash STM32 `0x55` test, then compile/upload its Teensy receiver |
| `flash_fsr1_pair.cmd` | `[COM port]` | Build/flash high-rate FSR1, upload its dedicated 10 MHz bridge, then open 16x16 heatmap |
| `flash_fsr2_pair.cmd` | `[COM port]` | Build/flash complete FSR2, upload bridge, then open 16x16 heatmap |
| `flash_teensy_self_test.cmd` | `[COM port]` | Compile/upload the standalone Teensy self-test |
| `upload_teensy_sketch.cmd` | `<sketch> [COM] [name]` | Generic Teensy 4.1 compile/upload helper |
| `monitor_teensy_serial.cmd` | `[COM] [baud]` | Open Arduino CLI serial monitor; defaults `COM9 115200` |
| `flash_acc_array.cmd` | `[0..9]` | Production ACC stream; `0`=all, `1..9`=one ACC |
| `flash_acc_spi_test.cmd` | `[0..9]` | Diagnostic ACC summary stream |
| `flash_acc_mosi_slow.cmd` | `[1..9]` | Selected nCS low, CLK low, MOSI toggles slowly |
| `flash_acc_ncs_slow.cmd` | `[1..9]` | Selected ACC nCS alternates high/low |
| `flash_acc_or_gate_static.cmd` | `[ACC] [MOSI]` | Static OR-gate test; ACC `1..9`, MOSI `0/1` |
| `flash_acc_sck_slow.cmd` | none | SCK alternates low/high every second |
| `flash_stm32_project.cmd` | `<alias>` | Build/flash an FSR or focused STM32 test |
| `start_combined_monitor.cmd` | `[COM port] [view]` | Start combined GUI; defaults `COM9 all`; view=`all|fsr1|fsr2|acc` |

Most legacy/diagnostic flash commands use STM32G474CETx, DAPLink UID
`LU_2022_8888`, 10 kHz SWD, `under-reset`, hardware reset, and sector erase.
The maintained Combined and standalone FSR1/FSR2 commands use 1 MHz SWD with
`under-reset --no-reset`; manually reset or power-cycle the STM32 after they
finish. The FSR pair scripts pause for this manual reset before uploading the
Teensy bridge.

Paired and Teensy commands default to `COM9`, use
`teensy:avr:teensy41`, and prefer the Arduino CLI installed at
`D:\study\programming\ArduinoCLI\arduino-cli.exe`.

```powershell
.\flash_teensy_self_test.cmd COM9
.\flash_fsr1_pair.cmd COM9
.\flash_fsr2_pair.cmd COM9
.\flash_spi_pattern_test.cmd COM9
.\flash_combined_pair.cmd COM9
```

The self-test and SPI pattern one-command scripts open the serial monitor
automatically after upload. The combined-pair script opens the Python GUI in
the `all` view automatically after upload.

The standalone FSR1 command now builds Release firmware at 80 MHz. It retains
MAX11633 clock mode 10 and EOC validation, reads the FIFO at 10 MHz, uses an
experimental 25 us MUX settling interval, pipelines the next-row settling with
the current FIFO read, and uploads `ESKIN_FSR1_FAST_BRIDGE`. Its 515-byte Host
SPI transaction is 10 MHz instead of the old 100 kHz bring-up setting. FSR2's
acquisition algorithm is unchanged; only the STM32 programming/reset path is
shared with FSR1's safer no-reset procedure.

## 2. Recommended complete-system workflow

### 2.1 Flash STM32

```powershell
.\flash_combined.cmd
```

该命令现在以 1 MHz、`under-reset --no-reset` 完成 STM32 编程。烧录结束后
必须手动复位或对 STM32 断电重启，才开始判断运行时数据；不要把没有自动
复位误判为烧录失败。

Expected data source: FSR1 16x16 + FSR2 16x16 + ACC1..ACC9. The current
protocol-v2 frame is 1188 bytes with `ESK1` magic, sequence, timestamp, status
flags, and a CRC-present flag. Sequence multiples of 32 carry IEEE CRC32;
other v2 frames carry a zero trailer. Combined mode always reads all nine ACC
positions and has no single-ACC flag.

The current combined Teensy bridge uses hardware Mode-0 SPI at `10 MHz`, with
IRQ/CS/hold waits of `50/10/10 us` and a `700 frame/s` maximum pacing target.
STM32 ADC SPI1 and ACC SPI2 are both `10 MHz`; FSR MUX settle is `100 us`.
Every output cycle scans all 16 MUX addresses for both FSR arrays, overlaps the
two ADC conversions, pipelines the next MUX settle with FIFO reads, and reads
all ACC positions at a configured 1.344 kHz ODR. The measured complete-cycle
rate is `238.475 Hz` for 30 seconds. The command builds `Release`.

This is the active experiment. Commit `5468ec8` is the last stable 700.181
packets/s rolling-acquisition release; its complete fresh FSR rate is only
43.76 Hz. See `docs/updates/2026-08-11-full-scan-700hz/PROGRESS_UPDATE.md`.

### 2.1.1 Isolated legacy SCLK scan experiment

The independent command below does not modify or build the normal
`combined_system` acquisition source:

```powershell
.\flash_combined_sclk33_experiment.cmd COM9 safe2p5 all
```

The replicated Combine can refresh FSR and ACC independently. Append the two
target rates in Hz; `0` (the default) refreshes that group on every output loop.
Frames continue to use the fixed complete-frame wire format. If a group is not
due, its previous values are retained and the corresponding update flag is
cleared:

```powershell
.\flash_combined_sclk33_experiment.cmd COM9 safe2p5 all "" 200 100
```

The complete argument order is `COM profile view confirmation fsr_hz acc_hz`.
This is a build-time setting, not a runtime GUI slider. A requested rate above
the actual transport loop is limited by that loop.

`safe2p5` performs the initial 33-byte runtime stream check at 2.5 MHz with
100 us MUX settling. The 2026-08-11 initial test passed at about 138.4 complete
frames/s; controlled pressure/mapping and logic-analyser checks remain.
`legacy10_settle100` changed only ADC SCLK to 10 MHz and reached about 229.2
frames/s, but the ADC code distribution collapsed, so it failed data integrity
despite zero frame-level errors and all sampled CRC checks passing. Zero-settle
`legacy10` was therefore skipped. Both 10 MHz profiles exceed the MAX11633
4.8 MHz external-clock specification and remain diagnostic-only reproduction
commands. They are rejected unless the fourth argument is the exact explicit
confirmation token:

```powershell
.\flash_combined_sclk33_experiment.cmd COM9 legacy10_settle100 all I_ACCEPT_OUT_OF_SPEC_10MHZ
.\flash_combined_sclk33_experiment.cmd COM9 legacy10 all I_ACCEPT_OUT_OF_SPEC_10MHZ
```

Restore the normal firmware with:

```powershell
.\flash_combined_pair.cmd COM9
```

### 2.2 Upload Teensy 4.1

Open this sketch in Arduino IDE:

```text
teensy/applications/ESKIN_COMBINED_BRIDGE/ESKIN_COMBINED_BRIDGE.ino
```

Select `Teensy 4.1`, USB type `Serial`, then Upload. `SPI` and USB Serial are
included in Teensyduino; no third-party Arduino library is required.

### 2.3 Start the combined GUI

```powershell
.\start_combined_monitor.cmd
.\start_combined_monitor.cmd COM10
.\start_combined_monitor.cmd COM9 fsr1
.\start_combined_monitor.cmd COM9 fsr2
.\start_combined_monitor.cmd COM9 acc
```

Direct Python form:

```powershell
python -u "$cmd\..\..\teensy\applications\ESKIN_COMBINED_BRIDGE\live_combined_monitor.py" --port COM9
```

`live_combined_monitor.py` flags:

| Flag | Default | Meaning |
|---|---:|---|
| `--port PORT` | `COM9` | Teensy USB serial port |
| `--baud BAUD` | `2000000` | USB serial baud setting |
| `--view all|fsr1|fsr2|acc` | `all` | Initial panel; the same choice remains available inside the GUI |
| `--interval-ms N` | `30` | GUI polling/redraw interval |
| `--demo` | off | Synthetic data; no hardware required |
| `--self-test` | off | Validate parser and CRC, then exit |

The combined FSR panels deliberately reuse the standalone GUI geometry and
mapping: hexagonal PCB cells, transport-axis transpose, default physical
left-right mirror, horizontal `C16..C1`, and vertical `R1..R16`. The ACC panel
reuses the standalone mirrored 3 x 3 physical positions and vector axes.

## 3. Standalone STM32 applications

Use the generic alias command for the two FSR applications and focused tests:

```powershell
.\flash_stm32_project.cmd fsr1
.\flash_stm32_project.cmd fsr2
.\flash_stm32_project.cmd fsr1-adc
.\flash_stm32_project.cmd acc-whoami
.\flash_stm32_project.cmd spi-pattern
```

The `fsr1` and `fsr2` aliases now use 1 MHz SWD with
`under-reset --no-reset`. After a successful flash, manually reset or
power-cycle the STM32 before starting the matching Teensy bridge. The focused
`fsr1-adc`, `acc-whoami`, and `spi-pattern` aliases retain their original
automatic-reset path.

| Alias | STM32 source | Matching purpose |
|---|---|---|
| `fsr1` | `stm32/applications/fsr1` | MUX1 + ADC1 16x16 scan |
| `fsr2` | `stm32/applications/fsr2` | MUX2 + ADC2 reversed/transposed scan |
| `fsr1-adc` | `stm32/tests/fsr1_adc_channel` | Fixed-MUX, per-AIN raw ADC test |
| `acc-whoami` | `stm32/tests/acc_a1_a5_whoami` | Repeated ACC1/ACC5 WHO_AM_I test |
| `spi-pattern` | `integration_tests/SPI_PATTERN_TEST/ESKIN_STM32_PATTERN` | STM32-Teensy `0x55` link test |

### ACC application selection

```powershell
.\flash_acc_array.cmd 0     # all ACC1..ACC9
.\flash_acc_array.cmd 5     # only ACC5
.\flash_acc_array.cmd       # interactive selection
```

The equivalent CMake cache flag is `-DACC_SELECTED=N`, where `N=0..9`.
PowerShell implementation flags are `-Acc 0..9`, `-BuildDirectory PATH`,
`-Target NAME`, and `-ProbeUid UID`.

## 4. ACC hardware diagnostics

Only run these during measurement; restore `flash_acc_array.cmd 0` or
`flash_combined.cmd` afterwards.

```powershell
.\flash_acc_spi_test.cmd 0
.\flash_acc_spi_test.cmd 3
.\flash_acc_mosi_slow.cmd 3
.\flash_acc_ncs_slow.cmd 3
.\flash_acc_or_gate_static.cmd 5 0
.\flash_acc_or_gate_static.cmd 5 1
.\flash_acc_sck_slow.cmd
```

| Test | Observable behaviour |
|---|---|
| ACC SPI test | WHO_AM_I, status, XYZ and SPI diagnostics in Host frame |
| MOSI slow | Selected nCS=0, CLK=0, MOSI alternates 0/1 |
| nCS slow | CLK=0, MOSI=0, selected nCS alternates 0/1 |
| OR static | Selected nCS=0, CLK=0, MOSI held at requested `0` or `1` |
| SCK slow | SCK remains low 1 s, high 1 s repeatedly |

Slow-test PowerShell flags:

- MOSI/nCS: `-Acc 1..9`, `-BuildDirectory PATH`, `-Target NAME`, `-ProbeUid UID`.
- OR static: the same plus `-Mosi 0|1`.
- SCK: `-BuildDirectory PATH`, `-Target NAME`, `-ProbeUid UID`.

## 5. FSR tools and all flags

Paths below are relative to `firmware/teensy/applications/ESKIN_SPI_USB_BRIDGE`.

### `live_fsr_heatmap.py`

```powershell
python live_fsr_heatmap.py --port COM9 --region fsr1
python live_fsr_heatmap.py --port COM9 --region fsr2
```

| Flag | Default | Meaning |
|---|---:|---|
| `--port PORT` | required unless demo | Teensy COM port |
| `--baud N` | `2000000` | Serial baud |
| `--timeout S` | `0.5` | Serial timeout |
| `--refresh-ms N` | `10` | GUI queue polling interval |
| `--vmin X`, `--vmax X` | `0`, `4095` | Fixed colour limits |
| `--region fsr1|fsr2` | `fsr1` | Mapping and data folders |
| `--calibration-file PATH` | automatic | Override calibration JSON |
| `--raw-output-directory PATH` | automatic | Override raw-frame folder |
| `--calibration-frames N` | `250` | Frames per calibration endpoint |
| `--min-calibration-span X` | `50` | Minimum valid full-zero span |
| `--autoscale` | off | Scale colours per live frame |
| `--mcu-normalized` | off | Interpret input as MCU-normalized 0..4095 |
| `--transpose` / `--no-transpose` | transpose | Exchange matrix axes |
| `--flip-rows` | off | Reverse displayed row direction |
| `--flip-columns` / `--no-flip-columns` | flipped | Physical left-right display |
| `--demo` | off | Synthetic input |

### `read_teensy_fsr.py`

| Flag | Default | Meaning |
|---|---:|---|
| `--port PORT` | required | Teensy COM port |
| `--baud N` | `2000000` | Serial baud |
| `--timeout S` | `2.0` | Read timeout |
| `--print-matrix` | off | Print all 16x16 values |
| `--summary-only` | off | Suppress each-frame output |
| `--frames N` | `0` | Stop after N valid frames; 0=continuous |
| `--max-time S` | `0` | Stop after seconds; 0=disabled |

### `test_adc_rows.py`

| Flag | Default | Meaning |
|---|---:|---|
| `--port PORT` | none | COM port; omit only with self-test |
| `--baud N` | `2000000` | Serial baud |
| `--timeout S` | `2.0` | Read timeout |
| `--rows LIST` | `1,12,13,14` | One-based rows under test |
| `--baseline-frames N` | `50` | Unpressed reference frames |
| `--test-frames N` | `75` | Pressed/test frames |
| `--threshold X` | `50` | Minimum detected change |
| `--output PATH` | timestamped JSON | Result file |
| `--self-test` | off | Offline mapping/decision test |

### `test_peak_neighborhood.py`

Flags: `--port` (required), `--baud` (`2000000`), `--timeout` (`0.5`),
`--refresh-ms` (`10`), and `--mcu-normalized` (off).

### `build_flash_normalized_fsr1.py`

Flags: `--calibration-file`, `--project`, `--build-dir`, `--minimum-span`
(`50`), `--minimum-calibration-frames` (`250`), `--require-all-valid`,
`--build`, `--flash`, `--probe` (`LU_2022_8888`), `--target`
(`stm32g474cetx`), and `--frequency` (`10k`).

## 6. ACC PC readers and flags

Paths are under `firmware/teensy/tests`.

| Script | Flags |
|---|---|
| `ACC_SPI_ARRAY_TEST/live_acc_3d.py` | `--port COM9`, `--baud 2000000`, `--interval-ms 40`, `--vector-scale 0.9`, `--demo`, `--self-test` |
| `ACC_SPI_ARRAY_TEST/read_acc_array.py` | `--port COM9`, `--baud 2000000`, `--timeout 2.0`, `--frames 0`, `--sensor 1..9`, `--summary-only` |
| `ACC_A1_A5_WHOAMI_TEST/read_a1_a5_whoami.py` | `--port COM9`, `--baud 2000000`, `--timeout 2.0`, `--frames 0`, `--show-samples` |

`--frames 0` means continuous operation.

## 7. ADC-channel test reader

After flashing alias `fsr1-adc`, upload
`teensy/tests/FSR1_ADC_CHANNEL_TEST_BRIDGE/FSR1_ADC_CHANNEL_TEST_BRIDGE.ino`,
then run:

```powershell
python read_adc_channel_test.py --port COM9
```

Flags: `--port` (`COM9`), `--baud` (`2000000`), `--timeout` (`15.0`), and
`--output-directory PATH` (automatic test-data folder).

## 8. Standard tool flags

| Tool flag | Purpose |
|---|---|
| CMake `-S` / `-B` | Source directory / out-of-tree build directory |
| `-G Ninja` | Select Ninja generator |
| `-DCMAKE_BUILD_TYPE=Debug` | Debug build |
| `-DACC_SELECTED=N` | ACC `0`=all, `1..9`=single device where supported |
| pyOCD `-u UID` | Select DAPLink `LU_2022_8888` |
| `-t stm32g474cetx` | Target MCU |
| `-f 10k` / `-f 1M` | SWD clock; the maintained Combined flash uses 1 MHz |
| `-M under-reset` | Connect while reset is asserted |
| `-O reset_type=hw` | Use physical nRESET |
| `-e sector` | Erase only required flash sectors |
| `-W` | Do not wait forever when no probe exists |

## 9. Fast fault isolation

| Symptom | First action |
|---|---|
| `ninja: no work to do` | Normal; ELF is already current |
| `pyocd list` hangs | Stop residual pyOCD, reseat DAPLink USB/SWD cable |
| `core is not halted` | Check nRESET continuity; use under-reset/hardware reset |
| `DAP_TRANSFER response error` | Check DAPLink/USB/SWD contact before changing code |
| `PermissionError(13)` on COM | Close Arduino Serial Monitor/other Python reader |
| GUI waits for frames | Confirm matching STM32 and Teensy protocols are loaded |

Run any Python script with `--help` for its installed authoritative usage.
