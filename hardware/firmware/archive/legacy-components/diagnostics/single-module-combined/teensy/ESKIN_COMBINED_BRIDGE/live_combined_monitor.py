"""Live selectable monitor for combined E-SKIN FSR1, FSR2 and ACC data.

The window can show FSR1, FSR2, the nine accelerometers, or all sensors.
FSR panels use the established hexagonal PCB geometry and physical mapping;
the ACC panel uses the established mirrored 3 x 3 physical layout.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import queue
import struct
import threading
import time
import zlib

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.collections import PolyCollection
from matplotlib.patches import Polygon
from matplotlib.widgets import RadioButtons
import numpy as np
import serial

MAGIC = b"ESK1"
LEGACY_VERSION = 1
VERSION = 2
SUPPORTED_VERSIONS = (LEGACY_VERSION, VERSION)
CRC_PRESENT_FLAG = 0x10
FSR_UPDATED_FLAG = 0x40
ACC_UPDATED_FLAG = 0x80
CRC_FRAME_INTERVAL = 32
FRAME_BYTES = 1188
HEADER_BYTES = 16
FSR_WORDS = 256
ROWS = 16
COLS = 16
ACC_COUNT = 9
ACC_RECORD_BYTES = 16
ADC_MAX = 4095
VIEW_LABELS = ("All", "FSR1", "FSR2", "ACC")
VIEW_KEYS = {label.lower(): label for label in VIEW_LABELS}
ACC_POSITIONS = (
    (2, 2), (2, 1), (2, 0),
    (1, 2), (1, 1), (1, 0),
    (0, 2), (0, 1), (0, 0),
)


@dataclass(frozen=True)
class AccSample:
    who: int
    status: int
    x: int
    y: int
    z: int
    ctrl1: int
    ctrl4: int
    spi_error: int
    idle_miso: int
    command_rx: int

    @property
    def valid(self) -> bool:
        return self.who == 0x33 and self.status == 0


@dataclass(frozen=True)
class CombinedFrame:
    flags: int
    sequence: int
    stm32_ms: int
    fsr1: np.ndarray
    fsr2: np.ndarray
    acc: tuple[AccSample, ...]
    updated_mux_address: int = 0xFF
    mux_addresses_updated: int = 16
    profile_us: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0)
    version: int = VERSION
    crc_checked: bool = True


def parse_frame(data: bytes) -> CombinedFrame:
    if len(data) != FRAME_BYTES:
        raise ValueError(f"frame length {len(data)} != {FRAME_BYTES}")
    if data[:4] != MAGIC or data[4] not in SUPPORTED_VERSIONS:
        raise ValueError("bad magic or protocol version")
    declared = struct.unpack_from("<H", data, 6)[0]
    if declared != FRAME_BYTES:
        raise ValueError(f"declared frame length {declared} is invalid")
    flags = data[5]
    sequence, stm32_ms = struct.unpack_from("<II", data, 8)
    version = data[4]
    crc_checked = version == LEGACY_VERSION or bool(flags & CRC_PRESENT_FLAG)
    if version == VERSION and crc_checked != (sequence % CRC_FRAME_INTERVAL == 0):
        raise ValueError("CRC flag does not match the protocol-v2 sampling cadence")
    expected_crc = struct.unpack_from("<I", data, FRAME_BYTES - 4)[0]
    if crc_checked:
        actual_crc = zlib.crc32(data[:-4]) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("CRC32 mismatch")
    elif expected_crc != 0:
        raise ValueError("protocol-v2 frame without CRC flag has a nonzero trailer")
    offset = HEADER_BYTES
    fsr1 = np.frombuffer(data, dtype="<u2", count=FSR_WORDS, offset=offset).copy()
    offset += FSR_WORDS * 2
    fsr2 = np.frombuffer(data, dtype="<u2", count=FSR_WORDS, offset=offset).copy()
    offset += FSR_WORDS * 2
    samples: list[AccSample] = []
    reserved: list[tuple[int, int]] = []
    for _ in range(ACC_COUNT):
        values = struct.unpack_from("<BBhhhBBHBB", data, offset)
        samples.append(AccSample(*values))
        reserved.append((data[offset + 14], data[offset + 15]))
        offset += ACC_RECORD_BYTES
    profiles = tuple((low | (high << 8)) for low, high in reserved[1:6])
    return CombinedFrame(flags, sequence, stm32_ms, fsr1.reshape(ROWS, COLS),
                         fsr2.reshape(ROWS, COLS), tuple(samples),
                         reserved[0][0], reserved[0][1], profiles,
                         version, crc_checked)


def read_exact(port: serial.Serial, count: int) -> bytes:
    result = bytearray()
    while len(result) < count:
        part = port.read(count - len(result))
        if not part:
            raise TimeoutError("serial timeout")
        result.extend(part)
    return bytes(result)


def read_stream_frame(port: serial.Serial) -> CombinedFrame:
    matched = 0
    while matched < len(MAGIC):
        byte = read_exact(port, 1)[0]
        if byte == MAGIC[matched]:
            matched += 1
        else:
            matched = 1 if byte == MAGIC[0] else 0
    return parse_frame(MAGIC + read_exact(port, FRAME_BYTES - len(MAGIC)))


def put_latest(target: queue.Queue[CombinedFrame], frame: CombinedFrame) -> None:
    try:
        target.put_nowait(frame)
    except queue.Full:
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        target.put_nowait(frame)


def serial_worker(port_name: str, baud: int, target: queue.Queue[CombinedFrame],
                  stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with serial.Serial(port_name, baud, timeout=1.0) as port:
                port.reset_input_buffer()
                while not stop.is_set():
                    try:
                        put_latest(target, read_stream_frame(port))
                    except (TimeoutError, ValueError):
                        continue
        except serial.SerialException:
            stop.wait(1.0)


def demo_worker(target: queue.Queue[CombinedFrame], stop: threading.Event) -> None:
    sequence = 0
    grid_y, grid_x = np.mgrid[0:ROWS, 0:COLS]
    while not stop.is_set():
        phase = sequence / 8.0
        a = np.exp(-((grid_x - (7.5 + 5*np.sin(phase)))**2 +
                     (grid_y - (7.5 + 5*np.cos(phase)))**2) / 10.0) * ADC_MAX
        b = np.exp(-((grid_x - (7.5 - 5*np.sin(phase)))**2 +
                     (grid_y - (7.5 - 5*np.cos(phase)))**2) / 10.0) * ADC_MAX
        acc = tuple(AccSample(0x33, 0, int(300*np.sin(phase+i)),
                              int(300*np.cos(phase+i)), 980,
                              0x57, 0x88, 0, 1, 0xFF) for i in range(ACC_COUNT))
        put_latest(target, CombinedFrame(7 | CRC_PRESENT_FLAG,
                                         sequence, sequence * 100,
                                         a.astype(np.uint16),
                                         b.astype(np.uint16), acc))
        sequence += 1
        stop.wait(0.1)


def half_width_at(v: float) -> float:
    safe_v = min(1.0, max(0.0, v))
    return 1.0 - abs(safe_v * 2.0 - 1.0) * 0.5


def board_point(u: float, v: float) -> tuple[float, float]:
    return (u * 2.0 - 1.0) * half_width_at(v), 1.0 - v * 2.0


def cell_polygons() -> list[list[tuple[float, float]]]:
    return [[board_point(col / COLS, row / ROWS),
             board_point((col + 1) / COLS, row / ROWS),
             board_point((col + 1) / COLS, (row + 1) / ROWS),
             board_point(col / COLS, (row + 1) / ROWS)]
            for row in range(ROWS) for col in range(COLS)]


def board_outline() -> list[tuple[float, float]]:
    return [board_point(0, 0.5), board_point(0, 0), board_point(1, 0),
            board_point(1, 0.5), board_point(1, 1), board_point(0, 1)]


def oriented_fsr(matrix: np.ndarray) -> np.ndarray:
    """Match the proven FSR GUI: MUX columns horizontal, mirrored physically."""
    return np.fliplr(matrix.T)


def add_hex_labels(axis: matplotlib.axes.Axes, compact: bool) -> None:
    size = 4.7 if compact else 6.0
    colour = "0.75"
    for display_col in range(COLS):
        raw_col = COLS - display_col
        u = (display_col + 0.5) / COLS
        for v, offset, va in ((0.0, 0.032, "bottom"), (1.0, -0.032, "top")):
            x, y = board_point(u, v)
            axis.text(x, y + offset, f"C{raw_col}", ha="center", va=va,
                      fontsize=size, color=colour)
    for display_row in range(ROWS):
        v = (display_row + 0.5) / ROWS
        for u, offset, ha in ((0.0, -0.028, "right"), (1.0, 0.028, "left")):
            x, y = board_point(u, v)
            axis.text(x + offset, y, f"R{display_row + 1}", ha=ha, va="center",
                      fontsize=size, color=colour)


class CombinedGui:
    def __init__(self, frames: queue.Queue[CombinedFrame], stop: threading.Event,
                 source: str, initial_view: str, interval_ms: int) -> None:
        plt.style.use("dark_background")
        self.frames = frames
        self.stop = stop
        self.source = source
        self.mode = VIEW_KEYS[initial_view]
        self.latest: CombinedFrame | None = None
        self.last_wall = time.monotonic()
        self.render_fps = 0.0
        self.last_sequence: int | None = None
        self.last_stm32_ms: int | None = None
        self.source_fps = 0.0
        self.content_axes: list[matplotlib.axes.Axes] = []
        self.fsr_artists: dict[str, PolyCollection] = {}
        self.acc_axis: matplotlib.axes.Axes | None = None
        self.acc_artists: list[object] = []

        self.figure = plt.figure(figsize=(14, 9), facecolor="#080a0d")
        self.figure.canvas.manager.set_window_title("E-SKIN Combined Monitor")
        self.figure.subplots_adjust(left=0.05, right=0.89, top=0.91, bottom=0.06)
        self.title = self.figure.suptitle(
            f"Waiting for combined frames from {source}...", color="white")
        radio_axis = self.figure.add_axes((0.905, 0.72, 0.085, 0.18),
                                          facecolor="#181b20")
        self.radio = RadioButtons(radio_axis, VIEW_LABELS,
                                  active=VIEW_LABELS.index(self.mode),
                                  activecolor="tab:orange")
        for label in self.radio.labels:
            label.set_color("white")
            label.set_fontsize(10)
        radio_axis.set_title("View", color="white", fontsize=10)
        self.radio.on_clicked(self._select_view)
        self._build_view()
        self.figure.canvas.mpl_connect("close_event", lambda _event: self.stop.set())
        self.animation = FuncAnimation(self.figure, self._update,
                                       interval=max(10, interval_ms),
                                       cache_frame_data=False)

    def _select_view(self, label: str) -> None:
        self.mode = label
        self._build_view()
        if self.latest is not None:
            self._render(self.latest)
        self.figure.canvas.draw_idle()

    def _remove_content(self) -> None:
        for axis in self.content_axes:
            axis.remove()
        self.content_axes.clear()
        self.fsr_artists.clear()
        self.acc_axis = None
        self.acc_artists.clear()

    def _add_fsr(self, spec: object, key: str, title: str,
                 compact: bool) -> None:
        axis = self.figure.add_subplot(spec)
        axis.set_facecolor("#080a0d")
        collection = PolyCollection(
            cell_polygons(), array=np.zeros(ROWS * COLS), cmap="inferno",
            norm=matplotlib.colors.Normalize(0, ADC_MAX),
            edgecolors=(1, 1, 1, 0.18), linewidths=0.35 if compact else 0.45)
        axis.add_collection(collection)
        axis.add_patch(Polygon(board_outline(), closed=True, fill=False,
                               edgecolor=(0.88, 0.92, 1, 0.9), linewidth=1.8))
        axis.set_xlim(-1.13, 1.13)
        axis.set_ylim(-1.12, 1.10)
        axis.set_aspect("equal")
        axis.axis("off")
        axis.set_title(title, color="white", pad=16)
        add_hex_labels(axis, compact)
        self.figure.colorbar(collection, ax=axis, fraction=0.038, pad=0.025,
                             label="raw ADC / 4095")
        self.content_axes.extend([axis, collection.colorbar.ax])
        self.fsr_artists[key] = collection

    def _add_acc(self, spec: object, compact: bool) -> None:
        axis = self.figure.add_subplot(spec, projection="3d")
        axis.set_facecolor("#080a0d")
        axis.set_xlim(-0.8, 2.8)
        axis.set_ylim(-0.8, 2.8)
        axis.set_zlim(-1.5, 1.5)
        axis.set_xticks(range(3), ["Left", "Centre", "Right"])
        axis.set_yticks(range(3), ["Lower", "Middle", "Upper"])
        axis.set_zticks([-1, 0, 1], ["-1 g", "0", "+1 g"])
        axis.set_xlabel("Logical ACC column")
        axis.set_ylabel("Logical ACC row")
        axis.set_zlabel("Z acceleration")
        axis.set_title("Nine accelerometers — physical mirrored view",
                       color="white", pad=8)
        axis.view_init(elev=28, azim=-56)
        axis.set_box_aspect((1, 1, 0.72))
        if compact:
            axis.tick_params(labelsize=7)
        for value in range(3):
            axis.plot([-0.35, 2.35], [value, value], [0, 0],
                      color="0.65", linewidth=0.6, alpha=0.45)
            axis.plot([value, value], [-0.35, 2.35], [0, 0],
                      color="0.65", linewidth=0.6, alpha=0.45)
        self.content_axes.append(axis)
        self.acc_axis = axis

    def _build_view(self) -> None:
        self._remove_content()
        if self.mode == "All":
            grid = self.figure.add_gridspec(2, 2, left=0.04, right=0.88,
                                            bottom=0.05, top=0.88,
                                            height_ratios=(1.0, 1.2))
            self._add_fsr(grid[0, 0], "fsr1", "FSR1 / left", True)
            self._add_fsr(grid[0, 1], "fsr2", "FSR2 / right", True)
            self._add_acc(grid[1, :], True)
        elif self.mode == "FSR1":
            grid = self.figure.add_gridspec(1, 1, left=0.12, right=0.84,
                                            bottom=0.06, top=0.88)
            self._add_fsr(grid[0], "fsr1", "FSR1 / left", False)
        elif self.mode == "FSR2":
            grid = self.figure.add_gridspec(1, 1, left=0.12, right=0.84,
                                            bottom=0.06, top=0.88)
            self._add_fsr(grid[0], "fsr2", "FSR2 / right", False)
        else:
            grid = self.figure.add_gridspec(1, 1, left=0.08, right=0.86,
                                            bottom=0.05, top=0.88)
            self._add_acc(grid[0], False)

    def _render_acc(self, frame: CombinedFrame) -> int:
        if self.acc_axis is None:
            return sum(sample.valid for sample in frame.acc)
        for artist in self.acc_artists:
            try:
                artist.remove()
            except (ValueError, AttributeError):
                pass
        self.acc_artists.clear()
        valid_count = 0
        for index, sample in enumerate(frame.acc):
            source_column, row = ACC_POSITIONS[index]
            column = 2 - source_column
            if sample.valid:
                valid_count += 1
                vector = np.clip(np.asarray([sample.x, sample.y, sample.z],
                                            dtype=float) / 1000.0, -2, 2)
                vector[0] *= -1
                arrow = self.acc_axis.quiver(column, row, 0, *vector,
                                             color="teal", linewidth=2,
                                             arrow_length_ratio=0.2)
                point = self.acc_axis.scatter([column], [row], [0],
                                              color="teal", s=45)
                self.acc_artists.extend((arrow, point))
            else:
                mark = self.acc_axis.scatter([column], [row], [0], color="red",
                                             marker="x", s=70, linewidths=2)
                self.acc_artists.append(mark)
            label = self.acc_axis.text(column, row, -0.13, f"A{index + 1}",
                                       ha="center", va="top", fontsize=8)
            self.acc_artists.append(label)
        return valid_count

    def _render(self, frame: CombinedFrame) -> None:
        if "fsr1" in self.fsr_artists:
            self.fsr_artists["fsr1"].set_array(oriented_fsr(frame.fsr1).ravel())
        if "fsr2" in self.fsr_artists:
            self.fsr_artists["fsr2"].set_array(oriented_fsr(frame.fsr2).ravel())
        valid_count = self._render_acc(frame)
        fsr_update = "new" if (frame.flags & FSR_UPDATED_FLAG) else "hold"
        acc_update = "new" if (frame.flags & ACC_UPDATED_FLAG) else "hold"
        self.title.set_text(
            f"{self.mode} | frame {frame.sequence} | source {self.source_fps:.1f} fps | "
            f"display {self.render_fps:.1f} fps | FSR flags {frame.flags & 3:02b} | "
            f"FSR {fsr_update} | ACC {acc_update} | "
            f"ACC {valid_count}/9 | MUX {frame.updated_mux_address} "
            f"(+{frame.mux_addresses_updated}) | "
            f"{'CRC OK' if frame.crc_checked else 'CRC NOT PRESENT / UNVERIFIED'}")

    def _update(self, _index: int) -> None:
        newest = None
        while True:
            try:
                newest = self.frames.get_nowait()
            except queue.Empty:
                break
        if newest is None:
            return
        now = time.monotonic()
        wall_delta = max(now - self.last_wall, 1e-6)
        instant_render = 1.0 / wall_delta
        self.render_fps = (instant_render if self.render_fps == 0 else
                           0.85 * self.render_fps + 0.15 * instant_render)
        if self.last_sequence is not None and self.last_stm32_ms is not None:
            seq_delta = (newest.sequence - self.last_sequence) & 0xFFFFFFFF
            ms_delta = (newest.stm32_ms - self.last_stm32_ms) & 0xFFFFFFFF
            if ms_delta and seq_delta:
                instant_source = seq_delta * 1000.0 / ms_delta
                self.source_fps = (instant_source if self.source_fps == 0 else
                                   0.85 * self.source_fps + 0.15 * instant_source)
        self.last_wall = now
        self.last_sequence = newest.sequence
        self.last_stm32_ms = newest.stm32_ms
        self.latest = newest
        self._render(newest)

    def show(self) -> None:
        plt.show()


def self_test() -> None:
    data = bytearray(FRAME_BYTES)
    data[:4] = MAGIC
    data[4] = VERSION
    data[5] = 7 | CRC_PRESENT_FLAG
    struct.pack_into("<HII", data, 6, FRAME_BYTES, 128, 456)
    offset = HEADER_BYTES
    for value in range(512):
        struct.pack_into("<H", data, offset, value)
        offset += 2
    for index in range(ACC_COUNT):
        reserved_low = 5 if index == 0 else 0
        reserved_high = 1 if index == 0 else 0
        if 1 <= index <= 5:
            reserved_value = 100 + index
            reserved_low = reserved_value & 0xFF
            reserved_high = reserved_value >> 8
        struct.pack_into("<BBhhhBBHBB", data, offset, 0x33, 0,
                         index, -index, 1000, 0x57, 0x88, 0, 1, 0xFF)
        data[offset + 14] = reserved_low
        data[offset + 15] = reserved_high
        offset += ACC_RECORD_BYTES
    struct.pack_into("<I", data, FRAME_BYTES - 4, zlib.crc32(data[:-4]))
    frame = parse_frame(bytes(data))
    assert frame.sequence == 128 and frame.fsr1[0, 0] == 0
    assert frame.fsr2[-1, -1] == 511 and frame.acc[8].y == -8
    assert frame.updated_mux_address == 5 and frame.mux_addresses_updated == 1
    assert frame.profile_us == (101, 102, 103, 104, 105)
    assert frame.version == VERSION and frame.crc_checked
    test = np.arange(256).reshape(16, 16)
    assert oriented_fsr(test)[0, 0] == test[15, 0]
    assert oriented_fsr(test)[15, 15] == test[0, 15]
    damaged = bytearray(data)
    damaged[100] ^= 1
    try:
        parse_frame(bytes(damaged))
    except ValueError:
        pass
    else:
        raise AssertionError("CRC test failed")
    unchecked = bytearray(data)
    unchecked[5] &= ~CRC_PRESENT_FLAG
    struct.pack_into("<I", unchecked, 8, 129)
    struct.pack_into("<I", unchecked, FRAME_BYTES - 4, 0)
    unchecked_frame = parse_frame(bytes(unchecked))
    assert unchecked_frame.version == VERSION and not unchecked_frame.crc_checked
    bad_trailer = bytearray(unchecked)
    struct.pack_into("<I", bad_trailer, FRAME_BYTES - 4, 1)
    try:
        parse_frame(bytes(bad_trailer))
    except ValueError:
        pass
    else:
        raise AssertionError("skipped-CRC trailer test failed")
    legacy = bytearray(data)
    legacy[4] = LEGACY_VERSION
    legacy[5] &= ~CRC_PRESENT_FLAG
    struct.pack_into("<I", legacy, FRAME_BYTES - 4, zlib.crc32(legacy[:-4]))
    legacy_frame = parse_frame(bytes(legacy))
    assert legacy_frame.version == LEGACY_VERSION and legacy_frame.crc_checked
    print("combined protocol and GUI mapping self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--view", choices=tuple(VIEW_KEYS), default="all",
                        help="Initial panel: fsr1, fsr2, acc, or all")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--interval-ms", type=int, default=30)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    frames: queue.Queue[CombinedFrame] = queue.Queue(maxsize=1)
    stop = threading.Event()
    source = "demo" if args.demo else args.port
    worker = threading.Thread(target=(demo_worker if args.demo else serial_worker),
                              args=((frames, stop) if args.demo else
                                    (args.port, args.baud, frames, stop)), daemon=True)
    worker.start()
    gui = CombinedGui(frames, stop, source, args.view, args.interval_ms)
    try:
        gui.show()
    finally:
        stop.set()
        worker.join(timeout=1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
