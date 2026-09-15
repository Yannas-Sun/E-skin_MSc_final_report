"""Read the 9-device ACC test frames forwarded by the Teensy USB bridge.

Each 515-byte frame reuses the proven FSR transport:

    rows 0..8 = installed ACC indices 1..9
    rows 9..15 = unused compatibility padding
    column 0 = WHO_AM_I (expected 0x33)
    column 1 = status (0 is OK)
    column 2 = signed X, approximately mg
    column 3 = signed Y, approximately mg
    column 4 = signed Z, approximately mg
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import serial


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
BRIDGE_DIRECTORY = (
    SCRIPT_DIRECTORY.parents[1] / "applications" / "ESKIN_SPI_USB_BRIDGE"
)
sys.path.insert(0, str(BRIDGE_DIRECTORY))

from read_teensy_fsr import FRAME_SIZE, FrameReader  # noqa: E402


STATUS_NAMES = {
    0: "OK",
    1: "BAD_ID",
    2: "ID_SPI_ERROR",
    3: "CONFIG_ERROR",
    4: "DATA_SPI_ERROR",
}

ACC_COUNT = 9


def signed_12(value: int) -> int:
    value &= 0x0FFF
    return value - 0x1000 if value & 0x0800 else value


def sensor_record(row: list[int]) -> tuple[int, int, int, int, int]:
    return row[0], row[1], signed_12(row[2]), signed_12(row[3]), signed_12(row[4])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--frames", type=int, default=0)
    parser.add_argument(
        "--sensor",
        type=int,
        choices=range(1, ACC_COUNT + 1),
        metavar="1..9",
        help="Print only one physical ACC number",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Suppress per-frame tables and print aggregate results",
    )
    args = parser.parse_args()

    try:
        with serial.Serial(args.port, args.baud, timeout=args.timeout) as port:
            reader = FrameReader(port)
            print(
                f"Listening on {args.port}; ACC protocol over "
                f"{FRAME_SIZE}-byte frames"
            )
            started = time.monotonic()
            valid_frames = 0
            first_sequence: int | None = None
            last_sequence: int | None = None
            gaps = 0
            ids_seen = [set() for _ in range(ACC_COUNT)]
            statuses_seen = [set() for _ in range(ACC_COUNT)]
            idle_miso_seen = [set() for _ in range(ACC_COUNT)]
            command_rx_seen = [set() for _ in range(ACC_COUNT)]
            spi_errors_seen = [set() for _ in range(ACC_COUNT)]
            ctrl1_seen = [set() for _ in range(ACC_COUNT)]
            ctrl4_seen = [set() for _ in range(ACC_COUNT)]
            last_raw_axes = [[0] * 6 for _ in range(ACC_COUNT)]
            axis_min = [[32767, 32767, 32767] for _ in range(ACC_COUNT)]
            axis_max = [[-32768, -32768, -32768] for _ in range(ACC_COUNT)]

            while args.frames == 0 or valid_frames < args.frames:
                try:
                    sequence, matrix = reader.read_frame()
                except TimeoutError as error:
                    print(f"Warning: {error}", file=sys.stderr)
                    continue

                if first_sequence is None:
                    first_sequence = sequence
                if last_sequence is not None and sequence != ((last_sequence + 1) & 0xFFFF):
                    gaps += 1
                last_sequence = sequence

                selected = (
                    range(ACC_COUNT) if args.sensor is None else [args.sensor - 1]
                )
                if not args.summary_only:
                    print(f"\nframe {sequence}")
                    print("ACC  WHO  STATUS             X       Y       Z")

                for index in range(ACC_COUNT):
                    who, status, x, y, z = sensor_record(matrix[index])
                    ids_seen[index].add(who)
                    statuses_seen[index].add(status)
                    idle_miso_seen[index].add(matrix[index][5])
                    command_rx_seen[index].add(matrix[index][6])
                    spi_errors_seen[index].add(matrix[index][7])
                    ctrl1_seen[index].add(matrix[index][8])
                    ctrl4_seen[index].add(matrix[index][9])
                    last_raw_axes[index] = matrix[index][10:16]
                    for axis, value in enumerate((x, y, z)):
                        axis_min[index][axis] = min(axis_min[index][axis], value)
                        axis_max[index][axis] = max(axis_max[index][axis], value)
                    if index in selected and not args.summary_only:
                        status_name = STATUS_NAMES.get(status, f"UNKNOWN_{status}")
                        print(
                            f"{index + 1:3d}  0x{who:02X}  "
                            f"{status_name:<16} {x:7d} {y:7d} {z:7d}"
                        )

                valid_frames += 1

            elapsed = time.monotonic() - started
            print("\nACC test summary")
            print(
                "ACC  IDs       statuses        MISO  command RX  SPI errors  "
                "CTRL1 CTRL4 raw XL/XH YL/YH ZL/ZH  "
                "X range        Y range        Z range"
            )
            for index in range(ACC_COUNT):
                ids = ",".join(f"0x{value:02X}" for value in sorted(ids_seen[index]))
                statuses = ",".join(
                    STATUS_NAMES.get(value, str(value))
                    for value in sorted(statuses_seen[index])
                )
                idle_miso = ",".join(str(value) for value in sorted(idle_miso_seen[index]))
                command_rx = ",".join(
                    f"0x{value:02X}" for value in sorted(command_rx_seen[index])
                )
                spi_errors = ",".join(
                    f"0x{value:03X}" for value in sorted(spi_errors_seen[index])
                )
                ctrl1 = ",".join(
                    f"0x{value:02X}" for value in sorted(ctrl1_seen[index])
                )
                ctrl4 = ",".join(
                    f"0x{value:02X}" for value in sorted(ctrl4_seen[index])
                )
                raw_axes = "/".join(
                    f"{value:02X}" for value in last_raw_axes[index]
                )
                print(
                    f"{index + 1:3d}  {ids:<9} {statuses:<15} "
                    f"{idle_miso:<5} {command_rx:<11} {spi_errors:<11} "
                    f"{ctrl1:<5} {ctrl4:<5} {raw_axes:<17} "
                    f"{axis_min[index][0]:6d}..{axis_max[index][0]:<6d} "
                    f"{axis_min[index][1]:6d}..{axis_max[index][1]:<6d} "
                    f"{axis_min[index][2]:6d}..{axis_max[index][2]:<6d}"
                )
            print(
                f"frames={valid_frames} sequence={first_sequence}..{last_sequence} "
                f"gaps={gaps} rate={valid_frames / elapsed:.2f} frame/s"
            )
            return 0

    except serial.SerialException as error:
        print(f"Serial error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
