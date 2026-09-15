# Scalablity selectable-module test

This is the first two-module communication test. The folder name intentionally
matches the project request (`scalablity`). The sketch reuses the proven
combined bridge and selects one physical module at compile time:

| Module | Teensy CS | Teensy IRQ |
|---|---:|---:|
| 0 | 10 | 2 |
| 1 | 14 | 3 |
| 2 | 15 | 4 |
| 3 | 16 | 5 |

The USB stream remains the existing 1188-byte `ESK1` format. This means the
existing `live_combined_monitor.py` GUI works unchanged. This first test is
single-module selection, not yet simultaneous multi-module scheduling or the
future `MUL1` envelope.

## Build and upload

From the firmware root:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\upload_scalablity_test.cmd" COM9 0
& "D:\study\programming\ESKIN\firmware\tools\commands\upload_scalablity_test.cmd" COM9 1
```

The second argument is the selected module number. Only one module should be
selected for the first electrical test. After upload, open the unchanged GUI:

The upload helper uses the Teensy-specific `build.flags.defs` property. The
installed Teensy 1.62.0 platform does not consume the generic
`compiler.cpp.extra_flags` property, so compiling manually with only the latter
will silently fall back to Module 0.

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\original\start_combined_monitor.cmd" COM9 all
```

The combined upload-plus-GUI command is:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_scalablity_test.cmd" COM9 1 all
```

This command uploads only the selectable Teensy bridge. Flash the existing
STM32 `combined_system` image to each module first; the STM32 image is the same
for Module 0 and Module 1 in this first test.

The normal `ESKIN_COMBINED_BRIDGE` sketch still defaults to Module 0 and is
unchanged in behaviour when compiled without a module define. The Module 1
image was compiled and uploaded successfully to COM9 on 2026-08-15; runtime
capture is still pending.

## Four-module combined bridge

After the four independent module tests pass, use the dedicated sketch in
`four_module/`. It polls all four CS/IRQ pairs on the shared SPI bus and emits
one `MUL1` USB packet after all four modules have updated, or after a 100 ms
partial-round timeout. Every packet contains the latest frame and status for
all four modules, so the GUI can keep eight FSR maps and four nine-ACC views on
screen at the same time without repeating the packet four times per round.

The outer packet is 4,792 bytes:

```text
MUL1 | version/count/updated-mask | packet metadata |
      (module-id, status, reserved, 1188-byte ESK1 frame) x 4 | outer CRC32
```

The inner ESK1 frames and their CRC rules remain unchanged. A non-zero module
status means that module has not supplied a valid frame yet; the GUI shows it
as `waiting` instead of displaying stale data.

Upload the Teensy bridge after all four STM32 boards have been flashed and
manually reset:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\flash_scalablity_four_module.cmd" COM9
```

To open the GUI separately:

```powershell
& "D:\study\programming\ESKIN\firmware\tools\commands\start_scalablity_four_module.cmd" COM9
```

The default `All` view is arranged as four module columns: FSR1, FSR2 and ACC.
The top module selector can switch between `All Modules` and an individual
Module 0–3. The right-side selector independently switches between `All`,
`FSR` and `ACC`, so for example `Module 2` + `FSR` shows only its two FSR
maps. The four-module bridge is a round-robin aggregate stream; its packet
rate is the combined rate of all modules, not 700 complete four-module packets
per second.
