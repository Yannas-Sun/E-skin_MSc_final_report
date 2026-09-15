"""Monitor the fixed ACC1/ACC5 WHO_AM_I isolation test over Teensy USB."""

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


READS = 100
A1_OFFSET = 0
A5_OFFSET = 100
SUMMARY_OFFSET = 200
TEST_MAGIC = 0xA15
EXPECTED_ID = 0x33


def flatten(matrix: list[list[int]]) -> list[int]:
    return [value for row in matrix for value in row]


def result_name(value: int) -> str:
    if value == EXPECTED_ID:
        return "PASS"
    if value == 0x00:
        return "0x00"
    if value == 0xFF:
        return "0xFF"
    if 0x100 <= value <= 0x10F:
        return f"SPI_ERROR_{value & 0xF}"
    return f"0x{value:03X}"


def compact_counts(values: list[int]) -> str:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return ", ".join(
        f"{result_name(value)}={count}" for value, count in sorted(counts.items())
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--frames", type=int, default=0, help="0 runs continuously")
    parser.add_argument(
        "--show-samples",
        action="store_true",
        help="Print all 100 raw values for ACC1 and ACC5",
    )
    args = parser.parse_args()

    try:
        with serial.Serial(args.port, args.baud, timeout=args.timeout) as port:
            reader = FrameReader(port)
            print(f"Listening on {args.port}; frame size {FRAME_SIZE} bytes")
            count = 0
            started = time.monotonic()
            while args.frames == 0 or count < args.frames:
                try:
                    sequence, matrix = reader.read_frame()
                except TimeoutError as error:
                    print(f"Warning: {error}", file=sys.stderr)
                    continue

                words = flatten(matrix)
                if words[SUMMARY_OFFSET] != TEST_MAGIC:
                    print(
                        f"frame {sequence}: wrong firmware/magic "
                        f"0x{words[SUMMARY_OFFSET]:03X}; expected 0x{TEST_MAGIC:03X}"
                    )
                    continue

                a1 = words[A1_OFFSET : A1_OFFSET + READS]
                a5 = words[A5_OFFSET : A5_OFFSET + READS]
                summary = words[SUMMARY_OFFSET : SUMMARY_OFFSET + 16]
                print(
                    f"frame {sequence:5d} | A1 {compact_counts(a1)} | "
                    f"A5 {compact_counts(a5)} | "
                    f"MISO A1/A5={summary[11]}/{summary[12]} | "
                    f"commandRX=0x{summary[13]:02X}/0x{summary[14]:02X} | "
                    f"SPIerr=0x{summary[15]:03X}"
                )
                if args.show_samples:
                    print("A1:", " ".join(f"{value:03X}" for value in a1))
                    print("A5:", " ".join(f"{value:03X}" for value in a5))
                count += 1

            elapsed = time.monotonic() - started
            print(f"Received {count} valid test frames in {elapsed:.2f} s")
            return 0
    except serial.SerialException as error:
        print(f"Serial error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
