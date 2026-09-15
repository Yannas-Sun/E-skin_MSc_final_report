"""Live 3D monitor for the 9-accelerometer E-SKIN array.

The live mode reads the existing 515-byte STM32 -> Teensy USB frames. Demo
mode generates synthetic vectors so the GUI can be tested before every ACC
passes firmware initialization.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import sys
import threading
import time

import matplotlib.pyplot as plt
from matplotlib import colors
from matplotlib.animation import FuncAnimation
import numpy as np
import serial


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
BRIDGE_DIRECTORY = (
    SCRIPT_DIRECTORY.parents[1] / "applications" / "ESKIN_SPI_USB_BRIDGE"
)
sys.path.insert(0, str(BRIDGE_DIRECTORY))

from read_teensy_fsr import FrameReader  # noqa: E402


ACC_COUNT = 9
TRANSPORT_ROWS = 16
# Original logical positions before the requested left-right display mirror.
ACC_POSITIONS = (
    (2, 2), (2, 1), (2, 0),
    (1, 2), (1, 1), (1, 0),
    (0, 2), (0, 1), (0, 0),
)
ACC_COLUMN_MAX = 2
MIRROR_LEFT_RIGHT = True
WHO_AM_I_EXPECTED = 0x33
STATUS_NAMES = {
    0: "OK",
    1: "BAD_ID",
    2: "ID_SPI_ERROR",
    3: "CONFIG_ERROR",
    4: "DATA_SPI_ERROR",
}


def signed_12(value: int) -> int:
    value &= 0x0FFF
    return value - 0x1000 if value & 0x0800 else value


def display_column(column: int) -> int:
    """Mirror the complete ACC layout across its centre column."""
    return ACC_COLUMN_MAX - column if MIRROR_LEFT_RIGHT else column


@dataclass(frozen=True)
class AccSample:
    who_am_i: int
    status: int
    x_mg: int
    y_mg: int
    z_mg: int

    @property
    def valid(self) -> bool:
        return self.who_am_i == WHO_AM_I_EXPECTED and self.status == 0

    @property
    def magnitude_g(self) -> float:
        return math.sqrt(
            self.x_mg * self.x_mg
            + self.y_mg * self.y_mg
            + self.z_mg * self.z_mg
        ) / 1000.0


@dataclass(frozen=True)
class AccFrame:
    sequence: int
    samples: tuple[AccSample, ...]
    received_at: float
    frame_rate: float
    gaps: int


def decode_acc_matrix(
    sequence: int,
    matrix: list[list[int]],
    frame_rate: float = 0.0,
    gaps: int = 0,
) -> AccFrame:
    if len(matrix) != TRANSPORT_ROWS or any(len(row) < 5 for row in matrix):
        raise ValueError("ACC transport matrix must contain 16 rows and 16 columns")
    samples = tuple(
        AccSample(
            who_am_i=row[0],
            status=row[1],
            x_mg=signed_12(row[2]),
            y_mg=signed_12(row[3]),
            z_mg=signed_12(row[4]),
        )
        for row in matrix[:ACC_COUNT]
    )
    return AccFrame(sequence, samples, time.monotonic(), frame_rate, gaps)


class SharedFrame:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: AccFrame | None = None
        self._message = "Starting"

    def set(self, frame: AccFrame) -> None:
        with self._lock:
            self._frame = frame
            self._message = "Live"

    def set_message(self, message: str) -> None:
        with self._lock:
            self._message = message

    def get(self) -> tuple[AccFrame | None, str]:
        with self._lock:
            return self._frame, self._message


class SerialWorker(threading.Thread):
    def __init__(
        self,
        shared: SharedFrame,
        stop_event: threading.Event,
        port: str,
        baud: int,
    ) -> None:
        super().__init__(daemon=True)
        self.shared = shared
        self.stop_event = stop_event
        self.port = port
        self.baud = baud

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.shared.set_message(f"Connecting to {self.port}")
                with serial.Serial(self.port, self.baud, timeout=1.0) as usb:
                    usb.reset_input_buffer()
                    reader = FrameReader(usb)
                    first_time = time.monotonic()
                    frame_count = 0
                    last_sequence: int | None = None
                    gaps = 0
                    while not self.stop_event.is_set():
                        try:
                            sequence, matrix = reader.read_frame()
                        except TimeoutError:
                            self.shared.set_message(
                                f"Waiting for ACC frames from {self.port}"
                            )
                            continue
                        if (
                            last_sequence is not None
                            and sequence != ((last_sequence + 1) & 0xFFFF)
                        ):
                            gaps += 1
                        last_sequence = sequence
                        frame_count += 1
                        elapsed = max(time.monotonic() - first_time, 1e-6)
                        self.shared.set(
                            decode_acc_matrix(
                                sequence,
                                matrix,
                                frame_rate=frame_count / elapsed,
                                gaps=gaps,
                            )
                        )
            except serial.SerialException as error:
                self.shared.set_message(f"Serial error on {self.port}: {error}")
                self.stop_event.wait(1.0)


class DemoWorker(threading.Thread):
    def __init__(
        self, shared: SharedFrame, stop_event: threading.Event, rate_hz: float
    ) -> None:
        super().__init__(daemon=True)
        self.shared = shared
        self.stop_event = stop_event
        self.rate_hz = rate_hz

    def run(self) -> None:
        sequence = 0
        started = time.monotonic()
        period = 1.0 / self.rate_hz
        while not self.stop_event.is_set():
            phase = time.monotonic() - started
            samples = []
            for index in range(ACC_COUNT):
                angle = phase * 0.8 + index * math.tau / ACC_COUNT
                tilt = 0.35 * math.sin(phase * 0.55 + index * 0.41)
                samples.append(
                    AccSample(
                        who_am_i=WHO_AM_I_EXPECTED,
                        status=0,
                        x_mg=round(1000.0 * math.sin(tilt) * math.cos(angle)),
                        y_mg=round(1000.0 * math.sin(tilt) * math.sin(angle)),
                        z_mg=round(1000.0 * math.cos(tilt)),
                    )
                )
            self.shared.set(
                AccFrame(
                    sequence=sequence,
                    samples=tuple(samples),
                    received_at=time.monotonic(),
                    frame_rate=self.rate_hz,
                    gaps=0,
                )
            )
            sequence = (sequence + 1) & 0xFFFF
            self.stop_event.wait(period)


class Acc3DGui:
    def __init__(
        self,
        shared: SharedFrame,
        stop_event: threading.Event,
        source_name: str,
        interval_ms: int,
        vector_scale: float,
    ) -> None:
        self.shared = shared
        self.stop_event = stop_event
        self.source_name = source_name
        self.interval_ms = interval_ms
        self.vector_scale = vector_scale
        self.selected = 0
        self.last_sequence: int | None = None

        self.figure = plt.figure(figsize=(12.5, 8.2))
        self.axis = self.figure.add_subplot(111, projection="3d")
        self.figure.canvas.manager.set_window_title("E-SKIN ACC 3D Monitor")
        self.figure.canvas.mpl_connect("close_event", self._on_close)
        self.figure.canvas.mpl_connect("pick_event", self._on_pick)
        self.animation = FuncAnimation(
            self.figure,
            self._update,
            interval=self.interval_ms,
            cache_frame_data=False,
        )

    def _on_close(self, _event: object) -> None:
        self.stop_event.set()

    def _on_pick(self, event: object) -> None:
        artist = getattr(event, "artist", None)
        sensor_index = getattr(artist, "_acc_index", None)
        if sensor_index is not None:
            self.selected = int(sensor_index)

    def _configure_axes(self) -> None:
        self.axis.set_xlim(-0.8, 2.8)
        self.axis.set_ylim(-0.8, 2.8)
        self.axis.set_zlim(-1.5, 1.5)
        self.axis.set_xticks(range(3), ["Left", "Centre", "Right"])
        self.axis.set_yticks(range(3), ["Lower", "Middle", "Upper"])
        self.axis.set_zticks([-1.0, 0.0, 1.0], ["-1 g", "0", "+1 g"])
        self.axis.set_xlabel("Logical ACC column")
        self.axis.set_ylabel("Logical ACC row")
        self.axis.set_zlabel("Z acceleration")
        self.axis.view_init(elev=28, azim=-56)
        self.axis.set_box_aspect((1.0, 1.0, 0.72))

    def _update(self, _frame_number: int) -> tuple[()]:
        frame, message = self.shared.get()
        self.axis.clear()
        self._configure_axes()

        for value in range(3):
            self.axis.plot(
                [-0.35, 2.35],
                [value, value],
                [0, 0],
                color="0.65",
                linewidth=0.6,
                alpha=0.45,
            )
            self.axis.plot(
                [value, value],
                [-0.35, 2.35],
                [0, 0],
                color="0.65",
                linewidth=0.6,
                alpha=0.45,
            )

        if frame is None:
            self.axis.set_title(f"{message}\n{self.source_name}")
            return ()

        norm = colors.Normalize(vmin=0.0, vmax=2.0)
        colour_map = plt.get_cmap("viridis")
        valid_count = 0

        for index, sample in enumerate(frame.samples):
            source_column, row = ACC_POSITIONS[index]
            column = display_column(source_column)
            is_selected = index == self.selected
            if sample.valid:
                valid_count += 1
                magnitude = sample.magnitude_g
                vector = np.asarray(
                    [sample.x_mg, sample.y_mg, sample.z_mg], dtype=float
                ) / 1000.0
                display_vector = np.clip(vector, -2.0, 2.0) * self.vector_scale
                if MIRROR_LEFT_RIGHT:
                    display_vector[0] *= -1.0
                colour = colour_map(norm(min(magnitude, 2.0)))
                self.axis.quiver(
                    column,
                    row,
                    0.0,
                    display_vector[0],
                    display_vector[1],
                    display_vector[2],
                    color=colour,
                    linewidth=2.8 if is_selected else 1.8,
                    arrow_length_ratio=0.22,
                )
                marker = self.axis.scatter(
                    [column],
                    [row],
                    [0],
                    s=95 if is_selected else 48,
                    c=[colour],
                    marker="o",
                    edgecolors="white" if is_selected else "none",
                    linewidths=1.4,
                    picker=8,
                )
            else:
                marker = self.axis.scatter(
                    [column],
                    [row],
                    [0],
                    s=105 if is_selected else 68,
                    c=["tab:red"],
                    marker="x",
                    linewidths=2.5 if is_selected else 1.8,
                    picker=8,
                )
            marker._acc_index = index
            self.axis.text(
                column,
                row,
                -0.13,
                f"A{index + 1}",
                ha="center",
                va="top",
                fontsize=8,
            )

        selected = frame.samples[self.selected]
        selected_status = STATUS_NAMES.get(
            selected.status, f"UNKNOWN_{selected.status}"
        )
        age = max(0.0, time.monotonic() - frame.received_at)
        self.axis.set_title(
            f"{self.source_name}  |  frame {frame.sequence}  |  "
            f"{frame.frame_rate:.1f} fps  |  gaps {frame.gaps}  |  "
            f"valid {valid_count}/{ACC_COUNT}  |  age {age:.2f} s\n"
            f"Selected A{self.selected + 1}: ID 0x{selected.who_am_i:02X}, "
            f"{selected_status}, X {selected.x_mg:+d} mg, "
            f"Y {selected.y_mg:+d} mg, Z {selected.z_mg:+d} mg, "
            f"|a| {selected.magnitude_g:.3f} g"
        )
        self.last_sequence = frame.sequence
        return ()

    def show(self) -> None:
        plt.tight_layout()
        plt.show()


def run_self_test() -> None:
    assert signed_12(0x000) == 0
    assert signed_12(0x7FF) == 2047
    assert signed_12(0x800) == -2048
    assert signed_12(0xFFF) == -1
    assert display_column(0) == 2
    assert display_column(1) == 1
    assert display_column(2) == 0
    matrix = [[0] * 16 for _ in range(16)]
    matrix[0][0:5] = [0x33, 0, 0x064, 0xF9C, 0x3E8]
    frame = decode_acc_matrix(7, matrix)
    assert frame.samples[0] == AccSample(0x33, 0, 100, -100, 1000)
    assert frame.samples[0].valid
    assert not frame.samples[1].valid
    print("ACC 3D GUI self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--interval-ms", type=int, default=40)
    parser.add_argument(
        "--vector-scale",
        type=float,
        default=0.9,
        help="Displayed grid units per g",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Show generated 3D vectors without opening a serial port",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return 0

    shared = SharedFrame()
    stop_event = threading.Event()
    if args.demo:
        worker: threading.Thread = DemoWorker(shared, stop_event, 25.0)
        source_name = "Demo data"
    else:
        worker = SerialWorker(shared, stop_event, args.port, args.baud)
        source_name = args.port
    worker.start()

    gui = Acc3DGui(
        shared,
        stop_event,
        source_name,
        interval_ms=max(20, args.interval_ms),
        vector_scale=max(0.05, args.vector_scale),
    )
    try:
        gui.show()
    finally:
        stop_event.set()
        worker.join(timeout=2.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
