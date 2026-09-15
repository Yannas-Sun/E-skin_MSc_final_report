"""Capture one raw FSR1 fixed-MUX ADC channel test frame from Teensy.

The binary payload contains AIN0 through AIN15 in channel-major order, with
100 consecutive raw 12-bit conversions for each channel. No calibration,
normalisation, averaging, filtering, or coordinate transformation is applied.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import statistics
import struct
import time

import serial


MAGIC = 0xA6
CHANNELS = 16
REPEATS = 100
HEADER_BYTES = 6
FRAME_BYTES = HEADER_BYTES + CHANNELS * REPEATS * 2
DEFAULT_OUTPUT_DIRECTORY = (
    Path(__file__).resolve().parent / "data" / "channel_tests" / "fsr1"
)


def decode_frame(raw: bytes) -> tuple[int, int, list[list[int]]] | None:
    if len(raw) != FRAME_BYTES or raw[0] != MAGIC:
        return None

    sequence = struct.unpack_from("<H", raw, 1)[0]
    mux_channel = raw[3]
    if raw[4] != CHANNELS or raw[5] != REPEATS:
        return None

    values = struct.unpack_from(f"<{CHANNELS * REPEATS}H", raw, HEADER_BYTES)
    if any(value > 0x0FFF for value in values):
        return None

    samples = [
        list(values[channel * REPEATS : (channel + 1) * REPEATS])
        for channel in range(CHANNELS)
    ]
    return sequence, mux_channel, samples


def read_frame(port: serial.Serial, timeout: float) -> tuple[int, int, list[list[int]]]:
    deadline = time.monotonic() + timeout
    buffer = bytearray()

    while time.monotonic() < deadline:
        chunk = port.read(max(FRAME_BYTES, port.in_waiting))
        if chunk:
            buffer.extend(chunk)

        search_from = 0
        while True:
            try:
                offset = buffer.index(MAGIC, search_from)
            except ValueError:
                if len(buffer) > FRAME_BYTES - 1:
                    del buffer[: -(FRAME_BYTES - 1)]
                break

            end = offset + FRAME_BYTES
            if end > len(buffer):
                if offset:
                    del buffer[:offset]
                break

            decoded = decode_frame(bytes(buffer[offset:end]))
            if decoded is not None:
                return decoded
            search_from = offset + 1

    raise TimeoutError(f"No valid {FRAME_BYTES}-byte ADC test frame received")


def save_csv(
    output_directory: Path,
    sequence: int,
    mux_channel: int,
    samples: list[list[int]],
) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    path = output_directory / (
        f"fsr1_mux{mux_channel:02d}_adc_test_seq{sequence:05d}_{timestamp}.csv"
    )

    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["repeat", *(f"AIN{channel}" for channel in range(CHANNELS))])
        for repeat in range(REPEATS):
            writer.writerow(
                [repeat + 1, *(samples[channel][repeat] for channel in range(CHANNELS))]
            )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
    )
    args = parser.parse_args()

    with serial.Serial(args.port, args.baud, timeout=0.2) as port:
        sequence, mux_channel, samples = read_frame(port, args.timeout)

    path = save_csv(args.output_directory, sequence, mux_channel, samples)
    print(
        f"Captured sequence {sequence}, fixed MUX1 channel {mux_channel}, "
        f"{CHANNELS} AIN channels x {REPEATS} raw samples"
    )
    for channel, values in enumerate(samples):
        print(
            f"AIN{channel:02d}: min={min(values):4d} "
            f"max={max(values):4d} "
            f"mean={statistics.fmean(values):8.2f} "
            f"stdev={statistics.pstdev(values):7.2f}"
        )
    print(f"Saved raw CSV: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
