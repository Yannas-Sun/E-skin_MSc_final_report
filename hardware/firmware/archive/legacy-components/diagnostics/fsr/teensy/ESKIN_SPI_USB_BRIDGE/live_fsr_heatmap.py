"""Display raw Teensy 16 x 16 FSR ADC frames on a PCB-shaped heatmap.

The incoming protocol is shared with ``read_teensy_fsr.py``:

    0xA5 + uint16 sequence + 256 little-endian uint16 ADC samples

Examples:

    python -u live_fsr_heatmap.py --port COM9 --region fsr1
    python -u live_fsr_heatmap.py --port COM9 --region fsr2
    python -u live_fsr_heatmap.py --demo

Dependencies:

    python -m pip install pyserial numpy matplotlib
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
import queue
import sys
import threading
import time

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.collections import PolyCollection
from matplotlib.patches import Polygon
from matplotlib.ticker import ScalarFormatter
from matplotlib.widgets import Button
import numpy as np
import serial

# Allow the script to be started from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_teensy_fsr import COLS, ROWS, FrameReader  # noqa: E402


ADC_MAX = 0x0FFF
MIN_EXPECTED_FPS = 10.0
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_DATA_DIRECTORY = SCRIPT_DIRECTORY / "data"
DEFAULT_RAW_OUTPUT_DIRECTORY = DEFAULT_DATA_DIRECTORY / "raw_frames"


@dataclass(frozen=True)
class Frame:
    sequence: int
    matrix: np.ndarray
    received_at: float
    sequence_gaps: int


def save_raw_frame(output_directory: Path, frame: Frame) -> Path:
    """Save one raw hardware frame as physical rows R and columns C."""
    matrix = np.asarray(frame.matrix)
    if matrix.shape != (ROWS, COLS):
        raise ValueError(
            f"Raw frame must be {ROWS} x {COLS}, got {matrix.shape}"
        )

    # The transport matrix is [MUX column][ADC row]. CSV users expect a
    # conventional table whose rows are physical R1..R16 and whose columns are
    # physical C1..C16, so transpose once here. GUI orientation is irrelevant.
    physical_matrix = matrix.T
    captured_at = datetime.now(timezone.utc)
    timestamp = captured_at.strftime("%Y%m%dT%H%M%S_%fZ")
    output_directory.mkdir(parents=True, exist_ok=True)
    path = output_directory / (
        f"fsr_raw_frame_{frame.sequence:05d}_{timestamp}.csv"
    )
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["row", *(f"C{column}" for column in range(1, COLS + 1))])
        for row_index, values in enumerate(physical_matrix, start=1):
            writer.writerow([f"R{row_index}", *(int(value) for value in values)])
    temporary.replace(path)
    return path


def put_latest(target: queue.Queue[Frame], frame: Frame) -> None:
    """Keep only the newest frame so rendering never delays acquisition."""
    try:
        target.put_nowait(frame)
    except queue.Full:
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
        frames: queue.Queue[Frame],
        errors: queue.Queue[str],
        stop: threading.Event,
    ) -> None:
        super().__init__(name="teensy-fsr-reader", daemon=True)
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.frames = frames
        self.errors = errors
        self.stop = stop

    def run(self) -> None:
        last_sequence: int | None = None
        sequence_gaps = 0
        try:
            with serial.Serial(self.port, self.baud, timeout=self.timeout) as device:
                frame_reader = FrameReader(device)
                while not self.stop.is_set():
                    try:
                        sequence, matrix = frame_reader.read_frame()
                    except TimeoutError:
                        continue

                    if last_sequence is not None:
                        expected = (last_sequence + 1) & 0xFFFF
                        if sequence != expected:
                            sequence_gaps += 1
                    last_sequence = sequence
                    put_latest(
                        self.frames,
                        Frame(
                            sequence=sequence,
                            matrix=np.asarray(matrix, dtype=np.uint16),
                            received_at=time.monotonic(),
                            sequence_gaps=sequence_gaps,
                        ),
                    )
        except serial.SerialException as error:
            self.errors.put(f"Serial error on {self.port}: {error}")
        except Exception as error:  # Keep GUI errors visible instead of exiting silently.
            self.errors.put(f"Reader error: {error}")


class DemoReader(threading.Thread):
    """Generate moving test pressure so the geometry can be checked offline."""

    def __init__(
        self,
        frames: queue.Queue[Frame],
        stop: threading.Event,
        rate_hz: float = 25.0,
    ) -> None:
        super().__init__(name="fsr-demo-reader", daemon=True)
        self.frames = frames
        self.stop = stop
        self.rate_hz = rate_hz

    def run(self) -> None:
        sequence = 0
        started = time.monotonic()
        row_grid, col_grid = np.mgrid[0:ROWS, 0:COLS]
        rng = np.random.default_rng(70025)
        while not self.stop.is_set():
            phase = time.monotonic() - started
            center_row = 7.5 + 5.0 * math.sin(phase * 0.65)
            center_col = 7.5 + 5.0 * math.cos(phase * 0.48)
            radius = (
                (row_grid - center_row) ** 2
                + (col_grid - center_col) ** 2
            )
            values = 30.0 + 3600.0 * np.exp(-radius / 7.0)
            values += rng.normal(0.0, 12.0, size=(ROWS, COLS))
            matrix = np.clip(values, 0, ADC_MAX).astype(np.uint16)
            put_latest(
                self.frames,
                Frame(
                    sequence=sequence,
                    matrix=matrix,
                    received_at=time.monotonic(),
                    sequence_gaps=0,
                ),
            )
            sequence = (sequence + 1) & 0xFFFF
            self.stop.wait(1.0 / self.rate_hz)


def half_width_at(v: float) -> float:
    """Half-width of the hexagonal PCB outline at normalized vertical v."""
    safe_v = min(1.0, max(0.0, v))
    return 1.0 - abs(safe_v * 2.0 - 1.0) * 0.5


def board_point(u: float, v: float) -> tuple[float, float]:
    """Map normalized grid coordinates into the hexagonal PCB outline."""
    x = (u * 2.0 - 1.0) * half_width_at(v)
    y = 1.0 - v * 2.0
    return x, y


def cell_polygons() -> list[list[tuple[float, float]]]:
    polygons: list[list[tuple[float, float]]] = []
    for row in range(ROWS):
        for col in range(COLS):
            u0 = col / COLS
            u1 = (col + 1) / COLS
            v0 = row / ROWS
            v1 = (row + 1) / ROWS
            polygons.append(
                [
                    board_point(u0, v0),
                    board_point(u1, v0),
                    board_point(u1, v1),
                    board_point(u0, v1),
                ]
            )
    return polygons


def board_outline() -> list[tuple[float, float]]:
    return [
        board_point(0.0, 0.5),
        board_point(0.0, 0.0),
        board_point(1.0, 0.0),
        board_point(1.0, 0.5),
        board_point(1.0, 1.0),
        board_point(0.0, 1.0),
    ]


def oriented_matrix(
    matrix: np.ndarray,
    transpose: bool,
    flip_rows: bool,
    flip_columns: bool,
) -> np.ndarray:
    displayed = matrix.T if transpose else matrix
    if flip_rows:
        displayed = np.flip(displayed, axis=0)
    if flip_columns:
        displayed = np.flip(displayed, axis=1)
    return displayed


def raw_coordinate(
    display_row: int,
    display_col: int,
    transpose: bool,
    flip_rows: bool,
    flip_columns: bool,
) -> tuple[int, int]:
    oriented_row = ROWS - 1 - display_row if flip_rows else display_row
    oriented_col = COLS - 1 - display_col if flip_columns else display_col
    if transpose:
        return oriented_col, oriented_row
    return oriented_row, oriented_col


def add_grid_labels(
    axis: matplotlib.axes.Axes,
    transpose: bool,
    flip_rows: bool,
    flip_columns: bool,
) -> list[matplotlib.text.Text]:
    """Label displayed rows and columns with their raw matrix indices."""
    labels: list[matplotlib.text.Text] = []
    colour = (0.82, 0.84, 0.88, 1.0)

    for display_col in range(COLS):
        raw_index = COLS - 1 - display_col if flip_columns else display_col
        # Raw matrix axis 0 is the MUX-selected physical column. After a
        # transpose it becomes the horizontal display axis.
        label = f"C{raw_index + 1}" if transpose else f"R{raw_index + 1}"
        u = (display_col + 0.5) / COLS
        top_x, top_y = board_point(u, 0.0)
        bottom_x, bottom_y = board_point(u, 1.0)
        labels.append(
            axis.text(
                top_x,
                top_y + 0.032,
                label,
                ha="center",
                va="bottom",
                fontsize=5.5,
                color=colour,
                zorder=5,
            )
        )
        labels.append(
            axis.text(
                bottom_x,
                bottom_y - 0.032,
                label,
                ha="center",
                va="top",
                fontsize=5.5,
                color=colour,
                zorder=5,
            )
        )

    for display_row in range(ROWS):
        raw_index = ROWS - 1 - display_row if flip_rows else display_row
        # Raw matrix axis 1 is the ADC physical row. After a transpose it
        # becomes the vertical display axis.
        label = f"R{raw_index + 1}" if transpose else f"C{raw_index + 1}"
        v = (display_row + 0.5) / ROWS
        left_x, left_y = board_point(0.0, v)
        right_x, right_y = board_point(1.0, v)
        labels.append(
            axis.text(
                left_x - 0.028,
                left_y,
                label,
                ha="right",
                va="center",
                fontsize=5.5,
                color=colour,
                zorder=5,
            )
        )
        labels.append(
            axis.text(
                right_x + 0.028,
                right_y,
                label,
                ha="left",
                va="center",
                fontsize=5.5,
                color=colour,
                zorder=5,
            )
        )

    return labels


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Teensy USB serial port, for example COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--timeout", type=float, default=0.5)
    parser.add_argument(
        "--refresh-ms",
        type=int,
        default=10,
        help=(
            "How often the GUI checks for a new hardware frame. The heatmap "
            "redraws only when a new frame arrives, so its visible rate follows "
            "the acquisition rate."
        ),
    )
    parser.add_argument("--vmin", type=float, default=0.0)
    parser.add_argument("--vmax", type=float, default=float(ADC_MAX))
    parser.add_argument(
        "--region",
        choices=("fsr1", "fsr2"),
        default="fsr1",
        help=(
            "Select the automatic raw-data output folder and physical mapping "
            "(default: fsr1)"
        ),
    )
    parser.add_argument(
        "--raw-output-directory",
        type=Path,
        help=(
            "Override the automatic data/raw_frames/<region>/ directory used "
            "by the Save raw frame button"
        ),
    )
    parser.add_argument(
        "--autoscale",
        action="store_true",
        help="Scale colours to the minimum and maximum of each live frame",
    )
    transpose_group = parser.add_mutually_exclusive_group()
    transpose_group.add_argument(
        "--transpose",
        dest="transpose",
        action="store_true",
        default=True,
        help="Map MUX columns to the horizontal axis (enabled by default)",
    )
    transpose_group.add_argument(
        "--no-transpose",
        dest="transpose",
        action="store_false",
        help="Display the raw matrix without exchanging its axes",
    )
    parser.add_argument(
        "--flip-rows",
        action="store_true",
        help="Reverse the displayed row direction without changing raw labels",
    )
    column_flip_group = parser.add_mutually_exclusive_group()
    column_flip_group.add_argument(
        "--flip-columns",
        dest="flip_columns",
        action="store_true",
        default=True,
        help="Reverse the displayed column direction (enabled by default)",
    )
    column_flip_group.add_argument(
        "--no-flip-columns",
        dest="flip_columns",
        action="store_false",
        help="Disable the default left-right mirror",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use an animated synthetic pressure point instead of a serial port",
    )
    args = parser.parse_args()
    if not args.demo and not args.port:
        parser.error("--port is required unless --demo is used")
    if args.vmax <= args.vmin:
        parser.error("--vmax must be greater than --vmin")
    if args.raw_output_directory is None:
        args.raw_output_directory = DEFAULT_RAW_OUTPUT_DIRECTORY / args.region
    return args


def main() -> int:
    args = parse_args()
    raw_output_directory = args.raw_output_directory.resolve()

    frame_queue: queue.Queue[Frame] = queue.Queue(maxsize=1)
    error_queue: queue.Queue[str] = queue.Queue()
    stop = threading.Event()

    reader: threading.Thread
    if args.demo:
        reader = DemoReader(frame_queue, stop)
        source_label = "demo"
    else:
        reader = SerialReader(
            args.port,
            args.baud,
            args.timeout,
            frame_queue,
            error_queue,
            stop,
        )
        source_label = str(args.port)
    reader.start()

    plt.style.use("dark_background")
    figure, axis = plt.subplots(figsize=(9.2, 8.2))
    figure.subplots_adjust(left=0.05, right=0.87, top=0.92, bottom=0.16)
    normalizer = matplotlib.colors.Normalize(vmin=args.vmin, vmax=args.vmax)
    colour_map = matplotlib.colormaps["inferno"].copy()
    colour_map.set_bad((0.22, 0.22, 0.22, 1.0))
    cells = PolyCollection(
        cell_polygons(),
        array=np.zeros(ROWS * COLS),
        cmap=colour_map,
        norm=normalizer,
        edgecolors=(1.0, 1.0, 1.0, 0.18),
        linewidths=0.45,
    )
    axis.add_collection(cells)
    axis.add_patch(
        Polygon(
            board_outline(),
            closed=True,
            fill=False,
            edgecolor=(0.88, 0.92, 1.0, 0.9),
            linewidth=2.0,
        )
    )
    axis.set_xlim(-1.12, 1.12)
    axis.set_ylim(-1.15, 1.10)
    axis.set_aspect("equal")
    axis.axis("off")
    add_grid_labels(axis, args.transpose, args.flip_rows, args.flip_columns)

    title = axis.set_title(f"Waiting for FSR frames from {source_label}...")
    hover_text = axis.text(
        0.0,
        -1.10,
        "Move the pointer over a cell to inspect its raw row, column and ADC code.",
        ha="center",
        va="center",
        color=(0.82, 0.84, 0.88, 1.0),
    )
    colorbar = figure.colorbar(cells, ax=axis, fraction=0.046, pad=0.04)
    colorbar.set_label("ADC code (12-bit)")
    colorbar.ax.yaxis.set_major_formatter(ScalarFormatter())

    save_button_axis = figure.add_axes([0.39, 0.035, 0.22, 0.055])
    save_button = Button(save_button_axis, "Save raw frame")
    raw_status = figure.text(
        0.465,
        0.112,
        "",
        ha="center",
        va="center",
        color=(0.82, 0.84, 0.88, 1.0),
    )

    latest_matrix: np.ndarray | None = None
    last_sequence: int | None = None
    last_received_at: float | None = None
    displayed_rate = 0.0
    shown_error: str | None = None
    first_display_reported = False

    raw_status.set_text(
        "Raw ADC mode: displaying unmodified STM32 values from 0 to 4095"
    )

    cells.set_norm(matplotlib.colors.Normalize(vmin=args.vmin, vmax=args.vmax))
    colorbar.update_normal(cells)
    colorbar.set_label("Raw ADC code (12-bit)")
    colorbar.ax.yaxis.set_major_formatter(ScalarFormatter())

    def save_latest_raw_frame(_event: object) -> None:
        if latest_matrix is None or last_sequence is None:
            raw_status.set_text(
                "Waiting for a live STM32 frame; no raw data was saved"
            )
            figure.canvas.draw_idle()
            return
        frame = Frame(
            sequence=last_sequence,
            matrix=latest_matrix.copy(),
            received_at=last_received_at or time.monotonic(),
            sequence_gaps=0,
        )
        try:
            saved_path = save_raw_frame(raw_output_directory, frame)
            raw_status.set_text(
                f"Raw frame {last_sequence} saved: {saved_path}"
            )
        except (OSError, ValueError) as error:
            raw_status.set_text(f"Raw frame save failed: {error}")
        figure.canvas.draw_idle()

    save_button.on_clicked(save_latest_raw_frame)

    def update() -> None:
        nonlocal latest_matrix
        nonlocal last_sequence
        nonlocal last_received_at
        nonlocal displayed_rate
        nonlocal shown_error
        nonlocal first_display_reported

        try:
            error = error_queue.get_nowait()
        except queue.Empty:
            error = None
        if error and error != shown_error:
            shown_error = error
            title.set_text(error)
            title.set_color("tomato")
            print(error, file=sys.stderr)

        newest: Frame | None = None
        while True:
            try:
                newest = frame_queue.get_nowait()
            except queue.Empty:
                break
        if newest is None:
            return

        if last_sequence is not None and last_received_at is not None:
            elapsed = newest.received_at - last_received_at
            sequence_step = (newest.sequence - last_sequence) & 0xFFFF
            if elapsed > 0.0 and sequence_step > 0:
                instantaneous_rate = sequence_step / elapsed
                displayed_rate = (
                    instantaneous_rate
                    if displayed_rate == 0.0
                    else displayed_rate * 0.8 + instantaneous_rate * 0.2
                )
        last_sequence = newest.sequence
        last_received_at = newest.received_at
        latest_matrix = newest.matrix
        if not first_display_reported:
            print(
                f"Heatmap synchronized on {source_label}: "
                f"frame {newest.sequence}, {ROWS}x{COLS}",
                flush=True,
            )
            first_display_reported = True

        source_matrix = latest_matrix.astype(float)

        displayed = oriented_matrix(
            source_matrix,
            args.transpose,
            args.flip_rows,
            args.flip_columns,
        )
        flat = displayed.reshape(-1)
        cells.set_array(flat)
        if args.autoscale:
            frame_min = float(np.min(flat))
            frame_max = float(np.max(flat))
            if frame_max <= frame_min:
                frame_max = frame_min + 1.0
            cells.set_clim(frame_min, frame_max)
            colorbar.update_normal(cells)

        title.set_color(matplotlib.rcParams["text.color"])
        rate_warning = (
            "  |  SLOW LINK: reset STM32"
            if displayed_rate > 0.0 and displayed_rate < MIN_EXPECTED_FPS
            else ""
        )
        max_index = int(np.argmax(latest_matrix))
        max_row, max_col = divmod(max_index, COLS)
        max_value = int(latest_matrix[max_row, max_col])
        frame_min = int(np.min(latest_matrix))
        title.set_text(
            f"{source_label}  |  frame {newest.sequence}  |  "
            f"{displayed_rate:5.1f} fps  |  gaps {newest.sequence_gaps}  |  "
            f"raw range {frame_min}..{max_value}  |  "
            f"peak R{max_col + 1}, C{max_row + 1}{rate_warning}"
        )
        figure.canvas.draw_idle()

    def on_motion(event: matplotlib.backend_bases.MouseEvent) -> None:
        if latest_matrix is None or event.inaxes is not axis:
            return
        if event.xdata is None or event.ydata is None:
            return
        v = (1.0 - event.ydata) * 0.5
        if not 0.0 <= v <= 1.0:
            return
        half_width = half_width_at(v)
        if abs(event.xdata) > half_width:
            return
        u = (event.xdata / half_width + 1.0) * 0.5
        display_row = min(ROWS - 1, max(0, int(v * ROWS)))
        display_col = min(COLS - 1, max(0, int(u * COLS)))
        row, col = raw_coordinate(
            display_row,
            display_col,
            args.transpose,
            args.flip_rows,
            args.flip_columns,
        )
        value = int(latest_matrix[row, col])
        hover_text.set_text(
            f"R{col + 1}, C{row + 1}  |  raw ADC {value} / {ADC_MAX}  |  "
            f"MUX I{row} / column FPC pin {row + 1}, "
            f"AIN{col} / row FPC pin {col + 1}"
        )
        figure.canvas.draw_idle()

    def on_close(_event: object) -> None:
        stop.set()

    figure.canvas.mpl_connect("motion_notify_event", on_motion)
    figure.canvas.mpl_connect("close_event", on_close)
    # FuncAnimation starts its event source only after the GUI canvas has been
    # drawn. This is more reliable on Windows than starting a backend timer
    # before plt.show(), which could leave the window permanently on Waiting.
    animation = FuncAnimation(
        figure,
        lambda _frame_index: update(),
        interval=max(10, args.refresh_ms),
        cache_frame_data=False,
    )

    try:
        plt.show()
    except KeyboardInterrupt:
        pass
    finally:
        # Retain a live reference for the entire GUI session.
        _ = animation
        stop.set()
        reader.join(timeout=max(1.0, args.timeout + 0.5))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
