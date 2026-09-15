"""Display a 16 x 16 FSR grid with only the peak and eight neighbours coloured.

The STM32/Teensy transport matrix is [MUX column][ADC row]. This script
transposes it once to the physical [R][C] convention, finds the maximum in the
complete 16 x 16 frame, keeps the full physical layout visible, and masks every
cell except the 3 x 3 physical neighbourhood centred on that maximum.

Examples:
    python -u test_peak_neighborhood.py --port COM9
    python -u test_peak_neighborhood.py --port COM9 --mcu-normalized
"""

from __future__ import annotations

import argparse
import queue
import threading
import time
from dataclasses import dataclass

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import serial
from matplotlib.animation import FuncAnimation
from matplotlib.patches import Rectangle

from read_teensy_fsr import COLS, ROWS, FrameReader


ADC_MAX = 0x0FFF


@dataclass(frozen=True)
class PeakFrame:
    sequence: int
    physical_matrix: np.ndarray
    received_at: float
    sequence_gaps: int


def put_latest(target: queue.Queue[PeakFrame], frame: PeakFrame) -> None:
    try:
        target.put_nowait(frame)
        return
    except queue.Full:
        pass
    try:
        target.get_nowait()
    except queue.Empty:
        pass
    target.put_nowait(frame)


class SerialReader(threading.Thread):
    def __init__(
        self,
        port: str,
        baud: int,
        timeout: float,
        frames: queue.Queue[PeakFrame],
        errors: queue.Queue[str],
        stop: threading.Event,
    ) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.frames = frames
        self.errors = errors
        self.stop = stop

    def run(self) -> None:
        try:
            with serial.Serial(self.port, self.baud, timeout=self.timeout) as port:
                reader = FrameReader(port)
                last_sequence: int | None = None
                sequence_gaps = 0
                while not self.stop.is_set():
                    try:
                        sequence, matrix = reader.read_frame()
                    except TimeoutError:
                        continue
                    if last_sequence is not None:
                        expected = (last_sequence + 1) & 0xFFFF
                        if sequence != expected:
                            sequence_gaps += 1
                    last_sequence = sequence
                    # Transport is [MUX column][ADC row]. Use physical [R][C].
                    physical = np.asarray(matrix, dtype=np.uint16).T.copy()
                    put_latest(
                        self.frames,
                        PeakFrame(
                            sequence=sequence,
                            physical_matrix=physical,
                            received_at=time.monotonic(),
                            sequence_gaps=sequence_gaps,
                        ),
                    )
        except serial.SerialException as error:
            self.errors.put(f"Serial error on {self.port}: {error}")
        except Exception as error:
            self.errors.put(f"Reader error: {error}")


def peak_neighbourhood(
    physical_matrix: np.ndarray,
) -> tuple[int, int, int, np.ndarray, np.ndarray]:
    """Return peak location/value and a fixed 3 x 3 physical neighbourhood."""
    if physical_matrix.shape != (ROWS, COLS):
        raise ValueError(
            f"matrix must be {ROWS} x {COLS}, got {physical_matrix.shape}"
        )
    peak_index = int(np.argmax(physical_matrix))
    peak_row, peak_column = divmod(peak_index, COLS)
    peak_value = int(physical_matrix[peak_row, peak_column])
    values = np.full((3, 3), np.nan, dtype=float)
    valid = np.zeros((3, 3), dtype=bool)
    for local_row, row_offset in enumerate((-1, 0, 1)):
        source_row = peak_row + row_offset
        for local_column, column_offset in enumerate((-1, 0, 1)):
            source_column = peak_column + column_offset
            if 0 <= source_row < ROWS and 0 <= source_column < COLS:
                values[local_row, local_column] = physical_matrix[
                    source_row, source_column
                ]
                valid[local_row, local_column] = True
    return peak_row, peak_column, peak_value, values, valid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Teensy USB port, e.g. COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--timeout", type=float, default=0.5)
    parser.add_argument("--refresh-ms", type=int, default=10)
    parser.add_argument(
        "--mcu-normalized",
        action="store_true",
        help="Interpret 0..4095 as MCU-normalized 0..100%% pressure",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frames: queue.Queue[PeakFrame] = queue.Queue(maxsize=1)
    errors: queue.Queue[str] = queue.Queue()
    stop = threading.Event()
    reader = SerialReader(
        args.port,
        args.baud,
        args.timeout,
        frames,
        errors,
        stop,
    )
    reader.start()

    plt.style.use("dark_background")
    figure, axis = plt.subplots(figsize=(9.0, 8.0))
    colour_map = matplotlib.colormaps["inferno"].copy()
    colour_map.set_bad((0.0, 0.0, 0.0, 1.0))
    image = axis.imshow(
        np.ma.masked_invalid(np.full((ROWS, COLS), np.nan, dtype=float)),
        vmin=0.0,
        vmax=float(ADC_MAX),
        cmap=colour_map,
        interpolation="nearest",
        origin="upper",
    )
    colour_bar = figure.colorbar(image, ax=axis, fraction=0.05, pad=0.04)
    if args.mcu_normalized:
        colour_bar.set_label("MCU-normalized pressure code (0..4095)")
    else:
        colour_bar.set_label("Raw ADC code (0..4095)")

    axis.set_title(f"Waiting for FSR frames from {args.port}...")
    axis.set_xlabel("Physical column")
    axis.set_ylabel("Physical row")
    axis.set_xticks(np.arange(COLS))
    axis.set_yticks(np.arange(ROWS))
    axis.set_xticklabels([f"C{column + 1}" for column in range(COLS)])
    axis.set_yticklabels([f"R{row + 1}" for row in range(ROWS)])
    axis.tick_params(axis="x", labelrotation=45, labelsize=8)
    axis.tick_params(axis="y", labelsize=8)
    axis.set_xticks(np.arange(-0.5, COLS, 1.0), minor=True)
    axis.set_yticks(np.arange(-0.5, ROWS, 1.0), minor=True)
    axis.grid(which="minor", color=(1.0, 1.0, 1.0, 0.24), linewidth=0.55)
    axis.tick_params(which="minor", bottom=False, left=False)
    annotations = [
        axis.text(
            0,
            0,
            "",
            ha="center",
            va="center",
            fontsize=7,
            color="white",
            visible=False,
        )
        for _index in range(9)
    ]
    peak_marker = Rectangle(
        (-0.5, -0.5),
        1.0,
        1.0,
        fill=False,
        edgecolor="cyan",
        linewidth=2.5,
        visible=False,
    )
    axis.add_patch(peak_marker)

    last_frame: PeakFrame | None = None
    displayed_rate = 0.0

    def update(_animation_frame: int) -> None:
        nonlocal last_frame
        nonlocal displayed_rate

        try:
            error = errors.get_nowait()
        except queue.Empty:
            error = None
        if error is not None:
            axis.set_title(error, color="tomato")
            figure.canvas.draw_idle()
            return

        newest: PeakFrame | None = None
        while True:
            try:
                newest = frames.get_nowait()
            except queue.Empty:
                break
        if newest is None:
            return

        if last_frame is not None:
            elapsed = newest.received_at - last_frame.received_at
            if elapsed > 0.0:
                instantaneous_rate = 1.0 / elapsed
                displayed_rate = (
                    instantaneous_rate
                    if displayed_rate == 0.0
                    else 0.9 * displayed_rate + 0.1 * instantaneous_rate
                )
        last_frame = newest

        peak_row, peak_column, peak_value, values, valid = peak_neighbourhood(
            newest.physical_matrix
        )
        masked_full_frame = np.full((ROWS, COLS), np.nan, dtype=float)
        annotation_index = 0
        for local_row in range(3):
            for local_column in range(3):
                annotation = annotations[annotation_index]
                annotation_index += 1
                if not valid[local_row, local_column]:
                    annotation.set_visible(False)
                    continue
                value = int(values[local_row, local_column])
                source_row = peak_row + local_row - 1
                source_column = peak_column + local_column - 1
                masked_full_frame[source_row, source_column] = value
                if args.mcu_normalized:
                    value_text = f"{value}\n{value / ADC_MAX:.0%}"
                else:
                    value_text = str(value)
                annotation.set_position((source_column, source_row))
                annotation.set_text(value_text)
                annotation.set_color(
                    "black" if value > int(0.72 * ADC_MAX) else "white"
                )
                annotation.set_visible(True)

        image.set_data(np.ma.masked_invalid(masked_full_frame))
        peak_marker.set_xy((peak_column - 0.5, peak_row - 0.5))
        peak_marker.set_visible(True)

        peak_description = (
            f"{peak_value / ADC_MAX:.1%} ({peak_value})"
            if args.mcu_normalized
            else str(peak_value)
        )
        axis.set_title(
            f"{args.port}  |  frame {newest.sequence}  |  "
            f"{displayed_rate:5.1f} fps  |  gaps {newest.sequence_gaps}\n"
            f"peak R{peak_row + 1}, C{peak_column + 1} = {peak_description}"
        )
        figure.canvas.draw_idle()

    def on_close(_event: object) -> None:
        stop.set()

    figure.canvas.mpl_connect("close_event", on_close)
    animation = FuncAnimation(
        figure,
        update,
        interval=args.refresh_ms,
        cache_frame_data=False,
    )
    # Keep a live reference for Matplotlib backends that otherwise collect it.
    figure._peak_animation = animation  # type: ignore[attr-defined]
    plt.show()
    stop.set()
    reader.join(timeout=1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
