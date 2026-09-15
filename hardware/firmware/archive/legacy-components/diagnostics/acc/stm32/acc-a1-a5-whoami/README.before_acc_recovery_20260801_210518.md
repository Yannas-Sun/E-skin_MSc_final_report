# STM32 ACC SPI Array Test

> Archived snapshot retained for experiment traceability. It predates the
> ACC1/ACC5 isolation test and is not current; use [`README.md`](README.md).

This isolated test scans the 9 installed LIS2DH12 accelerometers on the shared
SPI2 bus. Decoder addresses 0..8 select `nCS_1`..`nCS_9`; addresses 9..15 are
not populated on the current ACC flex. The 16x16 Host SPI frame is retained for
compatibility, with unused rows cleared to zero. It reuses the production Host
SPI and Teensy USB transport so ACC bring-up does not disturb the working FSR
applications.

## Build and flash

```powershell
cmake --build "D:\study\programming\builds\ESKIN_ACC_SPI_ARRAY_20260729"

pyocd flash `
  -t stm32g474cetx `
  -f 10k `
  -M under-reset `
  -e sector `
  "D:\study\programming\builds\ESKIN_ACC_SPI_ARRAY_20260729\ESKIN_STM32.elf"
```

The diagnostic SPI2 clock is currently 62.5 kHz and uses mode 3.

## Read the result

The production Teensy `ESKIN_SPI_USB_BRIDGE` may remain installed.

```powershell
python `
  "..\..\..\teensy\tests\ACC_SPI_ARRAY_TEST\read_acc_array.py" `
  --port COM9 `
  --frames 100 `
  --summary-only
```

A sensor passes only when:

- `WHO_AM_I` is `0x33`;
- status is `OK`;
- `CTRL1` is `0x57`;
- `CTRL4` is `0x88`;
- X/Y/Z respond to orientation changes.

Do not use XYZ values from a row marked `CONFIG_ERROR`.

## 2026-08-01 nine-device correction and test

The firmware, command-line reader, and 3D GUI were corrected to use the nine
devices present in ACC revision 2.2. A 10 kHz under-reset flash succeeded on
the second attempt after a hardware reset. A 100-frame COM9 test produced no
sequence gaps at 20.58 frames/s:

- ACC2, ACC4, ACC5, ACC7, and ACC8: `WHO_AM_I=0x33`, configuration readback
  `CTRL1=0x57` and `CTRL4=0x88`, with valid XYZ data;
- ACC1, ACC6, and ACC9: `WHO_AM_I=0xFF` (`BAD_ID`);
- ACC3: `WHO_AM_I=0x00` (`BAD_ID`).

The old apparent responses from ACC10..ACC16 were not real devices and must
not be used for fault analysis.
