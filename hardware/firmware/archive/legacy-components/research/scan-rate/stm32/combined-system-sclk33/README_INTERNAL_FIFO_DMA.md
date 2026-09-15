# MAX11633 internal-clock FIFO-DMA experiment

This isolated profile keeps the validated Combined board support, ESK1 frame,
Host SPI DMA and Teensy USB bridge, but replaces the FSR acquisition sequence.
The stable `stm32/applications/combined_system` image is unchanged.

For every MUX address and each MAX11633, the profile performs:

```text
CS low:  1 B 0xF8 scan command
CS high: ADC internal oscillator performs the AIN0..AIN15 scan
gap:     0..1000 us build-time command-to-read interval
CS low:  32 B SPI1 DMA FIFO read at 10 MHz
```

`gap=0` implements the requested immediate-read experiment: there is no
deliberate delay between the command transaction and the FIFO transaction.
This deliberately reads before checking EOC and therefore must be qualified by
the captured raw-data gates. It is not assumed correct merely because packets
and CRCs pass.

The STM32 runs at 160 MHz to reduce software overhead. The MAX11633 still uses
its own internal conversion oscillator; 10 MHz SPI1 is only the FIFO data I/O
clock. FSR1 and FSR2 are fully refreshed every output loop. ACC values remain
in the fixed frame but are refreshed at 1 Hz so this experiment measures the
complete dual-FSR scan rather than the nine-ACC scan cost.

## Module 1 pair

```powershell
& "D:\study\programming\ESKIN\E-SKIN\hardware\new\firmware\tools\commands\flash_internal_fifo_dma_pair.cmd" COM9 1 0 0
```

Arguments are `COM-port`, `module-id`, command-to-FIFO gap in microseconds and
MUX settling in microseconds.

## Automatic sweep

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  "D:\study\programming\ESKIN\E-SKIN\hardware\new\firmware\tools\run_internal_fifo_dma_sweep.ps1" `
  -Port COM9 -Module 1 -GapUs 0,20,40,50,60,70,80 -MuxUs 0
```

Each point is rebuilt and flashed, then captured over the real Module-to-Teensy
path. Selection requires continuous transport and no unloaded `>=3072` ADC-code
signature associated with reading the FIFO too early. The older 200-frame
boundary/variation gate is still reported, but is not used to select the timing
because legitimate unloaded zeros can fail it while corrupted variation can
falsely pass it.

The Module 1 boundary sweep found that 36 us still produces 3840/3841 codes,
while 37 us removes that signature. At 37 us, the measured complete dual-FSR
profile rate is 366.300 Hz and the USB-observed output rate is about 349.2 Hz.
This is an unloaded digital timing result; controlled-pressure qualification is
still required before merging the profile into stable Combined firmware.

Restore the stable Combined pair with:

```powershell
& "D:\study\programming\ESKIN\E-SKIN\hardware\new\firmware\tools\commands\flash_combined_pair.cmd" COM9
```
