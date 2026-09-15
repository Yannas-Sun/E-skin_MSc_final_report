"""Read the binary 16x16 FSR frames emitted by the Teensy USB bridge.

Install the only dependency with:
    py -m pip install pyserial

Example:
    py read_teensy_fsr.py --port COM7
    py read_teensy_fsr.py --port COM7 --print-matrix
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
import weakref

import serial


ROWS = 16
COLS = 16
FRAME_MAGIC = 0xA5
FRAME_SIZE = 1 + 2 + ROWS * COLS * 2
LOCK_FRAMES = 3


def decode_frame(raw: bytes | bytearray | memoryview) -> tuple[int, list[list[int]]] | None:
    """Decode one frame only when its marker and all 12-bit samples are valid."""
    if len(raw) != FRAME_SIZE or raw[0] != FRAME_MAGIC:
        return None
    sequence = struct.unpack_from("<H", raw, 1)[0]
    values = struct.unpack_from("<256H", raw, 3)
    if any(value > 0x0FFF for value in values):
        return None
    matrix = [list(values[row * COLS:(row + 1) * COLS]) for row in range(ROWS)]
    return sequence, matrix


class FrameReader:
    """Maintain a verified fixed-width frame lock on a continuous byte stream.

    A payload byte can legitimately equal the one-byte 0xA5 marker. Searching
    for one marker before every frame can therefore lock to an ADC sample. This
    reader accepts a boundary only after LOCK_FRAMES complete frames, exactly
    FRAME_SIZE bytes apart, have valid 12-bit payloads and consecutive sequence
    numbers. Once locked it reads only at fixed FRAME_SIZE boundaries.
    """

    def __init__(self, port: serial.Serial, lock_frames: int = LOCK_FRAMES) -> None:
        if lock_frames < 2:
            raise ValueError("lock_frames must be at least 2")
        self.port = port
        self.lock_frames = lock_frames
        self.buffer = bytearray()
        self.locked = False
        self.expected_sequence: int | None = None
        self.lock_count = 0
        self.lock_loss_count = 0

    def reset_lock(self) -> None:
        """Discard buffered bytes and require a fresh multi-frame lock."""
        self.buffer.clear()
        self.locked = False
        self.expected_sequence = None

    def _fill(self, minimum_size: int) -> None:
        while len(self.buffer) < minimum_size:
            chunk = self.port.read(max(FRAME_SIZE, minimum_size - len(self.buffer)))
            if not chunk:
                raise TimeoutError("Timed out while waiting for a complete frame")
            self.buffer.extend(chunk)

    def _candidate(self, offset: int) -> tuple[int, list[list[int]]] | None:
        end = offset + FRAME_SIZE
        if end > len(self.buffer):
            return None
        return decode_frame(memoryview(self.buffer)[offset:end])

    def _acquire_lock(self) -> None:
        required = self.lock_frames * FRAME_SIZE
        # One additional frame allows a full-width search even if reading began
        # in the middle of a frame or after an ASCII diagnostic line.
        window_size = required + FRAME_SIZE

        while not self.locked:
            self._fill(window_size)
            last_offset = len(self.buffer) - required

            for offset in range(last_offset + 1):
                if self.buffer[offset] != FRAME_MAGIC:
                    continue
                first = self._candidate(offset)
                if first is None:
                    continue
                first_sequence = first[0]
                valid = True
                for index in range(1, self.lock_frames):
                    candidate = self._candidate(offset + index * FRAME_SIZE)
                    expected = (first_sequence + index) & 0xFFFF
                    if candidate is None or candidate[0] != expected:
                        valid = False
                        break
                if valid:
                    del self.buffer[:offset]
                    self.locked = True
                    self.expected_sequence = first_sequence
                    self.lock_count += 1
                    return

            # Preserve enough trailing data to contain a lock candidate that
            # was incomplete at the end of this search window.
            keep = required - 1
            if len(self.buffer) > keep:
                del self.buffer[: len(self.buffer) - keep]

    def read_frame(self) -> tuple[int, list[list[int]]]:
        while True:
            if not self.locked:
                self._acquire_lock()

            self._fill(FRAME_SIZE)
            decoded = self._candidate(0)
            if (
                decoded is None
                or self.expected_sequence is None
                or decoded[0] != self.expected_sequence
            ):
                self.lock_loss_count += 1
                self.locked = False
                self.expected_sequence = None
                # Advance by one byte so the rejected marker cannot be selected
                # immediately as the same candidate.
                if self.buffer:
                    del self.buffer[0]
                continue

            del self.buffer[:FRAME_SIZE]
            self.expected_sequence = (decoded[0] + 1) & 0xFFFF
            return decoded


_READERS: "weakref.WeakKeyDictionary[serial.Serial, FrameReader]" = (
    weakref.WeakKeyDictionary()
)


def read_frame(port: serial.Serial) -> tuple[int, list[list[int]]]:
    """Backward-compatible wrapper using a persistent verified FrameReader."""
    reader = _READERS.get(port)
    if reader is None:
        reader = FrameReader(port)
        _READERS[port] = reader
    return reader.read_frame()


def print_matrix(matrix: list[list[int]]) -> None:
    for row in matrix:
        print(" ".join(f"{value:4d}" for value in row))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Teensy USB serial port, e.g. COM7")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--print-matrix", action="store_true")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Suppress per-frame output and print aggregate test statistics",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=0,
        help="Stop after this many valid frames; 0 runs continuously",
    )
    parser.add_argument(
        "--max-time",
        type=float,
        default=0.0,
        help="Stop after this many seconds; 0 disables the time limit",
    )
    args = parser.parse_args()

    try:
        with serial.Serial(args.port, args.baud, timeout=args.timeout) as port:
            print(f"Listening on {args.port}; expecting {FRAME_SIZE} bytes per frame")
            last_sequence: int | None = None
            first_sequence: int | None = None
            valid_frames = 0
            sequence_gaps = 0
            global_min = 0x0FFF
            global_max = 0
            started = time.monotonic()

            while True:
                if args.max_time > 0.0 and (time.monotonic() - started) >= args.max_time:
                    break
                try:
                    sequence, matrix = read_frame(port)
                except TimeoutError as error:
                    if not args.summary_only:
                        print(f"Warning: {error}", file=sys.stderr)
                    continue

                if first_sequence is None:
                    first_sequence = sequence
                if last_sequence is not None:
                    expected = (last_sequence + 1) & 0xFFFF
                    if sequence != expected:
                        sequence_gaps += 1
                        print(
                            f"Warning: sequence gap, expected {expected}, got {sequence}",
                            file=sys.stderr,
                        )
                last_sequence = sequence

                flat = [value for row in matrix for value in row]
                frame_min = min(flat)
                frame_max = max(flat)
                global_min = min(global_min, frame_min)
                global_max = max(global_max, frame_max)
                if not args.summary_only:
                    print(
                        f"frame={sequence:5d} min={frame_min:4d} "
                        f"max={frame_max:4d} first={flat[0]:4d} last={flat[-1]:4d}"
                    )
                if args.print_matrix:
                    print_matrix(matrix)
                    print()

                valid_frames += 1
                if args.frames > 0 and valid_frames >= args.frames:
                    break

            elapsed = time.monotonic() - started
            print(f"Captured {valid_frames} valid frame(s).")
            if valid_frames > 0:
                print(
                    f"Summary: sequence={first_sequence}..{last_sequence} "
                    f"gaps={sequence_gaps} samples={global_min}..{global_max} "
                    f"elapsed={elapsed:.3f}s rate={valid_frames / elapsed:.2f} frame/s"
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
