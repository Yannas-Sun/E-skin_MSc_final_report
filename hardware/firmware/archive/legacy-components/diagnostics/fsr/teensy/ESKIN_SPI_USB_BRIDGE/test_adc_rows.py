"""End-to-end response test for selected physical FSR rows.

The wire protocol stores samples as matrix[mux_column][adc_row]. Therefore:

    R1  = MAX11633 AIN0
    R12 = MAX11633 AIN11
    R13 = MAX11633 AIN12
    R14 = MAX11633 AIN13

This test first captures an unloaded baseline. It then asks the operator to
press each requested physical row in turn and compares the raw ADC values with
the baseline. No Heatmap calibration is used.

Example:

    python test_adc_rows.py --port COM9
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import serial

from read_teensy_fsr import COLS, ROWS, FrameReader


DEFAULT_ROWS = (1, 12, 13, 14)
DEFAULT_OUTPUT_DIRECTORY = Path(__file__).resolve().parent / "data" / "row_tests"


@dataclass
class Capture:
    median: np.ndarray
    minimum: np.ndarray
    maximum: np.ndarray
    first_sequence: int
    last_sequence: int
    sequence_gaps: int
    frames: int
    elapsed_seconds: float


@dataclass
class RowResult:
    physical_row: int
    adc_input: int
    response_detected: bool
    maximum_absolute_delta: float
    strongest_column: int
    signed_delta_at_strongest_column: float
    strongest_row_anywhere: int
    strongest_row_delta: float
    sequence_gaps: int
    frame_rate: float


def parse_rows(value: str) -> tuple[int, ...]:
    rows: list[int] = []
    for item in value.split(","):
        try:
            row = int(item.strip())
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"Invalid row number: {item!r}") from error
        if not 1 <= row <= ROWS:
            raise argparse.ArgumentTypeError(
                f"Row {row} is outside the valid range 1..{ROWS}"
            )
        if row not in rows:
            rows.append(row)
    if not rows:
        raise argparse.ArgumentTypeError("At least one row is required")
    return tuple(rows)


def capture_frames(reader: FrameReader, frame_count: int) -> Capture:
    matrices: list[np.ndarray] = []
    first_sequence: int | None = None
    previous_sequence: int | None = None
    sequence_gaps = 0
    started = time.monotonic()

    while len(matrices) < frame_count:
        sequence, matrix = reader.read_frame()
        if first_sequence is None:
            first_sequence = sequence
        if previous_sequence is not None:
            expected = (previous_sequence + 1) & 0xFFFF
            if sequence != expected:
                sequence_gaps += (sequence - expected) & 0xFFFF
        previous_sequence = sequence
        matrices.append(np.asarray(matrix, dtype=np.float64))

        count = len(matrices)
        if count == 1 or count % 25 == 0 or count == frame_count:
            print(f"\r  captured {count}/{frame_count} frames", end="", flush=True)

    print()
    elapsed = time.monotonic() - started
    stack = np.stack(matrices)
    assert first_sequence is not None
    assert previous_sequence is not None
    return Capture(
        median=np.median(stack, axis=0),
        minimum=np.min(stack, axis=0),
        maximum=np.max(stack, axis=0),
        first_sequence=first_sequence,
        last_sequence=previous_sequence,
        sequence_gaps=sequence_gaps,
        frames=frame_count,
        elapsed_seconds=elapsed,
    )


def analyse_row(
    baseline: Capture,
    pressed: Capture,
    physical_row: int,
    threshold: float,
) -> RowResult:
    # Raw matrix axis 0 is MUX/physical column; axis 1 is ADC/physical row.
    delta = pressed.median - baseline.median
    row_index = physical_row - 1
    target_delta = delta[:, row_index]
    strongest_column_index = int(np.argmax(np.abs(target_delta)))
    maximum_absolute_delta = float(abs(target_delta[strongest_column_index]))

    per_row_delta = np.max(np.abs(delta), axis=0)
    strongest_row_index = int(np.argmax(per_row_delta))

    return RowResult(
        physical_row=physical_row,
        adc_input=row_index,
        response_detected=maximum_absolute_delta >= threshold,
        maximum_absolute_delta=maximum_absolute_delta,
        strongest_column=strongest_column_index + 1,
        signed_delta_at_strongest_column=float(target_delta[strongest_column_index]),
        strongest_row_anywhere=strongest_row_index + 1,
        strongest_row_delta=float(per_row_delta[strongest_row_index]),
        sequence_gaps=pressed.sequence_gaps,
        frame_rate=pressed.frames / pressed.elapsed_seconds,
    )


def print_result(result: RowResult, threshold: float) -> None:
    status = "PASS: RESPONSE DETECTED" if result.response_detected else "FAIL: NO RESPONSE"
    direction = "increase" if result.signed_delta_at_strongest_column >= 0 else "decrease"
    print(
        f"\nR{result.physical_row} / AIN{result.adc_input}: {status}\n"
        f"  strongest target cell: R{result.physical_row}, C{result.strongest_column}\n"
        f"  target change: {result.maximum_absolute_delta:.1f} ADC counts "
        f"({direction})\n"
        f"  threshold: {threshold:.1f} ADC counts\n"
        f"  strongest row anywhere during this press: "
        f"R{result.strongest_row_anywhere} "
        f"({result.strongest_row_delta:.1f} counts)\n"
        f"  capture rate: {result.frame_rate:.2f} frame/s, "
        f"sequence gaps: {result.sequence_gaps}"
    )
    if (
        not result.response_detected
        and result.strongest_row_delta >= threshold
        and result.strongest_row_anywhere != result.physical_row
    ):
        print(
            "  NOTE: another ADC row responded. Check physical row numbering or "
            "AIN-to-row mapping."
        )


def capture_to_json(capture: Capture) -> dict[str, object]:
    return {
        "first_sequence": capture.first_sequence,
        "last_sequence": capture.last_sequence,
        "sequence_gaps": capture.sequence_gaps,
        "frames": capture.frames,
        "elapsed_seconds": capture.elapsed_seconds,
        "median": capture.median.tolist(),
        "minimum": capture.minimum.tolist(),
        "maximum": capture.maximum.tolist(),
    }


def run_self_test(threshold: float) -> int:
    baseline_matrix = np.full((ROWS, COLS), 100.0)
    baseline = Capture(
        median=baseline_matrix,
        minimum=baseline_matrix,
        maximum=baseline_matrix,
        first_sequence=0,
        last_sequence=49,
        sequence_gaps=0,
        frames=50,
        elapsed_seconds=2.0,
    )
    pressed_matrix = baseline_matrix.copy()
    pressed_matrix[6, 11] += threshold + 25.0  # C7, R12/AIN11.
    pressed = Capture(
        median=pressed_matrix,
        minimum=pressed_matrix,
        maximum=pressed_matrix,
        first_sequence=50,
        last_sequence=99,
        sequence_gaps=0,
        frames=50,
        elapsed_seconds=2.0,
    )
    result = analyse_row(baseline, pressed, physical_row=12, threshold=threshold)
    assert result.response_detected
    assert result.adc_input == 11
    assert result.strongest_column == 7
    assert result.strongest_row_anywhere == 12

    no_response = analyse_row(baseline, baseline, physical_row=13, threshold=threshold)
    assert not no_response.response_detected
    print("Self-test PASS: raw matrix[MUX column][ADC row] indexing is correct.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Teensy USB serial port, for example COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument(
        "--rows",
        type=parse_rows,
        default=DEFAULT_ROWS,
        help="One-based physical rows to test (default: 1,12,13,14)",
    )
    parser.add_argument(
        "--baseline-frames",
        type=int,
        default=50,
        help="Unloaded frames used for the baseline (default: 50)",
    )
    parser.add_argument(
        "--test-frames",
        type=int,
        default=75,
        help="Frames captured while each row is pressed (default: 75)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=50.0,
        help="Minimum absolute median change counted as a response (default: 50)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Optional JSON output path; defaults to "
            "data/row_tests/adc_row_test_<timestamp>.json"
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run an offline indexing/decision test without serial hardware",
    )
    args = parser.parse_args()

    if args.self_test:
        return run_self_test(args.threshold)
    if not args.port:
        parser.error("--port is required unless --self-test is used")
    if args.baseline_frames < 1 or args.test_frames < 1:
        parser.error("Frame counts must be at least 1")
    if args.threshold <= 0:
        parser.error("--threshold must be greater than zero")

    output_path = args.output
    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = DEFAULT_OUTPUT_DIRECTORY / f"adc_row_test_{stamp}.json"

    print("Target mapping:")
    for row in args.rows:
        print(f"  physical R{row} -> MAX11633 AIN{row - 1}")
    print(
        "\nClose the Heatmap and Arduino Serial Monitor before continuing. "
        "Remove all pressure from the FSR surface."
    )
    input("Press Enter to capture the unloaded baseline...")

    try:
        with serial.Serial(args.port, args.baud, timeout=args.timeout) as device:
            device.reset_input_buffer()
            frame_reader = FrameReader(device)
            print("\nCapturing unloaded baseline:")
            baseline = capture_frames(frame_reader, args.baseline_frames)
            print(
                f"Baseline captured at "
                f"{baseline.frames / baseline.elapsed_seconds:.2f} frame/s; "
                f"sequence gaps={baseline.sequence_gaps}."
            )

            results: list[RowResult] = []
            captures: dict[str, object] = {}
            for physical_row in args.rows:
                print(
                    f"\nPress and hold one or more cells on physical R{physical_row}. "
                    "Use firm, steady pressure and do not press another row."
                )
                input("Press Enter while holding the pressure...")
                device.reset_input_buffer()
                frame_reader.reset_lock()
                pressed = capture_frames(frame_reader, args.test_frames)
                result = analyse_row(
                    baseline,
                    pressed,
                    physical_row=physical_row,
                    threshold=args.threshold,
                )
                results.append(result)
                captures[f"R{physical_row}"] = capture_to_json(pressed)
                print_result(result, args.threshold)
                input("Release the pressure, then press Enter to continue...")

    except serial.SerialException as error:
        print(f"Serial error: {error}", file=sys.stderr)
        return 1
    except TimeoutError as error:
        print(f"Frame timeout: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nTest cancelled.")
        return 130

    payload = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "port": args.port,
        "threshold": args.threshold,
        "rows": list(args.rows),
        "baseline": capture_to_json(baseline),
        "pressed_captures": captures,
        "results": [asdict(result) for result in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    passed = sum(result.response_detected for result in results)
    print(
        f"\nCompleted: {passed}/{len(results)} target rows responded. "
        f"Raw result saved to {output_path.resolve()}"
    )
    return 0 if passed == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
