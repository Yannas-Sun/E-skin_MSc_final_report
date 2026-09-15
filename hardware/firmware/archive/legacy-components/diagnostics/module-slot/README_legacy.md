# Scalablity STM32 test contract

The STM32 side intentionally keeps the proven `combined_system` acquisition
image. Every module has the same local FSR/ACC scanner and the same SPI3 Host
slave pins; the Teensy selects a module by its separate `HOST_nCS` and
`HOST_IRQ` wires. A different STM32 acquisition algorithm is not needed for
the first communication test.

`scalablity_test.c/.h` records the optional module-ID contract and the local
Host SPI mapping. It is a small test support unit, not a replacement for
`combined_acquisition.c`. Until a multi-module STM32 image is required, flash
the existing combined image to each board:

```text
stm32/applications/combined_system
```

The module number is selected in the Teensy sketch/build command. This keeps
the existing `ESK1` frame and GUI compatible while validating one CS/IRQ slot
at a time. Simultaneous two-module scheduling and a `MUL1` envelope are a
separate next step.

Per-module Host connector allocation is recorded in:

```text
docs/WORKFLOW.md
docs/updates/2026-08-14-four-module-power-evaluation/PROGRESS_UPDATE.md
```
