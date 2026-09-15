"""Historical four-module E-SKIN monitor for the old FSR+ACC stream.

The default view shows four columns (one per physical module), with FSR1 and
FSR2 on the first two rows and the nine-accelerometer view on the third row.
The ``fsr`` and ``acc`` views are available when a larger single sensor view is
more useful.
The active launcher uses ``four-module-fsr-monitor.py`` instead.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import queue
import struct
import sys
import threading
import time
import zlib

FIRMWARE_ROOT = Path(__file__).resolve().parents[3]
BRIDGE_DIR = FIRMWARE_ROOT / "diagnostics" / "single-module-combined" / "teensy" / "ESKIN_COMBINED_BRIDGE"
sys.path.insert(0, str(BRIDGE_DIR))

from live_combined_monitor import (  # noqa: E402
    ACC_COUNT,
    ACC_POSITIONS,
    ADC_MAX,
    COLS,
    CRC_PRESENT_FLAG,
    AccSample,
    CombinedFrame,
    ROWS,
    add_hex_labels,
    board_outline,
    cell_polygons,
    oriented_fsr,
    parse_frame,
)

import matplotlib  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.animation import FuncAnimation  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402
from matplotlib.widgets import Button  # noqa: E402
from matplotlib.widgets import RadioButtons  # noqa: E402
import numpy as np  # noqa: E402
import serial  # noqa: E402


MODULE_COUNT = 4
MUL_MAGIC = b"MUL1"
MUL_VERSION = 1
FRAME_BYTES = 1188
PACKET_HEADER_BYTES = 20
BLOCK_BYTES = 4 + FRAME_BYTES
PACKET_BYTES = PACKET_HEADER_BYTES + MODULE_COUNT * BLOCK_BYTES + 4
VIEW_LABELS = ("All", "FSR", "ACC")
VIEW_KEYS = {label.lower(): label for label in VIEW_LABELS}
MODULE_LABELS = ("All Modules", "Module 0", "Module 1", "Module 2", "Module 3")


@dataclass(frozen=True)
class MultiModulePacket:
    sequence: int
    host_ms: int
    updated_mask: int
    modules: tuple[CombinedFrame | None, ...]
    statuses: tuple[int, ...]


def parse_multi_packet(data: bytes) -> MultiModulePacket:
    if len(data) < PACKET_HEADER_BYTES + 4:
        raise ValueError("MUL1 packet is too short")
    if data[:4] != MUL_MAGIC or data[4] != MUL_VERSION:
        raise ValueError("bad MUL1 header")
    if data[5] != MODULE_COUNT:
        raise ValueError("unexpected module count")
    declared, block_bytes = struct.unpack_from("<HH", data, 8)
    if declared != len(data) or declared != PACKET_BYTES:
        raise ValueError("invalid MUL1 packet length")
    if block_bytes != BLOCK_BYTES:
        raise ValueError("invalid MUL1 block length")
    expected_crc = struct.unpack_from("<I", data, len(data) - 4)[0]
    if zlib.crc32(data[:-4]) & 0xFFFFFFFF != expected_crc:
        raise ValueError("MUL1 CRC32 mismatch")

    sequence, host_ms = struct.unpack_from("<II", data, 12)
    modules: list[CombinedFrame | None] = []
    statuses: list[int] = []
    for module in range(MODULE_COUNT):
        offset = PACKET_HEADER_BYTES + module * BLOCK_BYTES
        module_id, status = data[offset], data[offset + 1]
        if module_id != module:
            raise ValueError("MUL1 module order mismatch")
        statuses.append(status)
        if status == 0:
            modules.append(parse_frame(data[offset + 4:offset + 4 + FRAME_BYTES]))
        else:
            modules.append(None)
    return MultiModulePacket(sequence, host_ms, data[6], tuple(modules),
                             tuple(statuses))


def read_exact(port: serial.Serial, count: int) -> bytes:
    result = bytearray()
    while len(result) < count:
        part = port.read(count - len(result))
        if not part:
            raise TimeoutError("serial timeout")
        result.extend(part)
    return bytes(result)


def read_stream_packet(port: serial.Serial) -> MultiModulePacket:
    matched = 0
    while matched < len(MUL_MAGIC):
        byte = read_exact(port, 1)[0]
        if byte == MUL_MAGIC[matched]:
            matched += 1
        else:
            matched = 1 if byte == MUL_MAGIC[0] else 0
    header_tail = read_exact(port, PACKET_HEADER_BYTES - len(MUL_MAGIC))
    declared = struct.unpack_from("<H", header_tail, 4)[0]
    if declared < PACKET_HEADER_BYTES + 4 or declared > 65535:
        raise ValueError("invalid MUL1 declared length")
    return parse_multi_packet(MUL_MAGIC + header_tail +
                              read_exact(port, declared - PACKET_HEADER_BYTES))


def put_latest(target: queue.Queue[MultiModulePacket], packet: MultiModulePacket) -> None:
    try:
        target.put_nowait(packet)
    except queue.Full:
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        target.put_nowait(packet)


def serial_worker(port_name: str, baud: int,
                  target: queue.Queue[MultiModulePacket],
                  stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with serial.Serial(port_name, baud, timeout=1.0) as port:
                port.reset_input_buffer()
                while not stop.is_set():
                    try:
                        put_latest(target, read_stream_packet(port))
                    except (TimeoutError, ValueError):
                        continue
        except serial.SerialException:
            stop.wait(1.0)


def make_demo_frame(module: int, sequence: int) -> CombinedFrame:
    grid_y, grid_x = np.mgrid[0:ROWS, 0:COLS]
    phase = sequence / 8.0 + module * 0.9
    fsr1 = np.exp(-((grid_x - (7.5 + 4.5 * np.sin(phase))) ** 2 +
                    (grid_y - (7.5 + 4.5 * np.cos(phase))) ** 2) / 12.0)
    fsr2 = np.exp(-((grid_x - (7.5 - 4.5 * np.sin(phase))) ** 2 +
                    (grid_y - (7.5 - 4.5 * np.cos(phase))) ** 2) / 12.0)
    acc = tuple(AccSample(0x33, 0, int(300 * np.sin(phase + i)),
                          int(300 * np.cos(phase + i)), 980, 0x57, 0x88,
                          0, 1, 0xFF) for i in range(ACC_COUNT))
    return CombinedFrame(7 | CRC_PRESENT_FLAG, sequence, sequence * 100,
                         (fsr1 * ADC_MAX).astype(np.uint16),
                         (fsr2 * ADC_MAX).astype(np.uint16), acc)


def demo_worker(target: queue.Queue[MultiModulePacket], stop: threading.Event) -> None:
    sequence = 0
    while not stop.is_set():
        frames = tuple(make_demo_frame(module, sequence)
                       for module in range(MODULE_COUNT))
        put_latest(target, MultiModulePacket(sequence, sequence * 100,
                                             0x0F, frames, (0, 0, 0, 0)))
        sequence += 1
        stop.wait(0.1)


class MultiModuleGui:
    def __init__(self, packets: queue.Queue[MultiModulePacket],
                 stop: threading.Event, source: str, initial_view: str,
                 interval_ms: int) -> None:
        plt.style.use("dark_background")
        self.packets = packets
        self.stop = stop
        self.source = source
        self.mode = VIEW_KEYS[initial_view]
        self.module_filter: int | None = None
        self.latest: MultiModulePacket | None = None
        self.last_wall = time.monotonic()
        self.render_fps = 0.0
        self.source_fps = 0.0
        self.last_sequence: int | None = None
        self.last_host_ms: int | None = None
        self.content_axes: list[object] = []
        self.fsr_artists: dict[tuple[int, str], PolyCollection] = {}
        self.fsr_axes: dict[tuple[int, str], object] = {}
        self.acc_axes: dict[int, object] = {}
        self.acc_artists: dict[int, list[object]] = {}

        self.figure = plt.figure(figsize=(20, 13), facecolor="#080a0d")
        self.figure.canvas.manager.set_window_title(
            "E-SKIN Four-Module Monitor")
        self.figure.subplots_adjust(left=0.02, right=0.94, top=0.87,
                                    bottom=0.04)
        self.title = self.figure.suptitle(
            f"Waiting for MUL1 packets from {source}...", color="white")
        self.module_buttons: list[Button] = []
        self._build_module_selector()
        radio_axis = self.figure.add_axes((0.95, 0.76, 0.045, 0.14),
                                          facecolor="#181b20")
        self.radio = RadioButtons(radio_axis, VIEW_LABELS,
                                  active=VIEW_LABELS.index(self.mode),
                                  activecolor="tab:orange")
        for label in self.radio.labels:
            label.set_color("white")
            label.set_fontsize(8)
        radio_axis.set_title("View", color="white", fontsize=9)
        self.radio.on_clicked(self._select_view)
        self._build_view()
        self.figure.canvas.mpl_connect("close_event",
                                       lambda _event: self.stop.set())
        self.animation = FuncAnimation(self.figure, self._update,
                                       interval=max(10, interval_ms),
                                       cache_frame_data=False)

    def _build_module_selector(self) -> None:
        self.figure.text(0.02, 0.952, "Module:", color="white",
                         fontsize=9, va="center")
        start_x = 0.075
        width = 0.105
        gap = 0.008
        for index, label in enumerate(MODULE_LABELS):
            axis = self.figure.add_axes((start_x + index * (width + gap),
                                         0.932, width, 0.038))
            button = Button(axis, label, color="#252a31",
                            hovercolor="#46515e")
            button.label.set_color("white")
            button.label.set_fontsize(8)
            button.on_clicked(lambda _event, selected=index:
                              self._select_module(selected))
            self.module_buttons.append(button)
        self._update_module_button_colors()

    def _update_module_button_colors(self) -> None:
        selected = 0 if self.module_filter is None else self.module_filter + 1
        for index, button in enumerate(self.module_buttons):
            colour = "#b85c16" if index == selected else "#252a31"
            button.ax.set_facecolor(colour)
            button.label.set_color("white")
        self.figure.canvas.draw_idle()

    def _displayed_modules(self) -> tuple[int, ...]:
        if self.module_filter is None:
            return tuple(range(MODULE_COUNT))
        return (self.module_filter,)

    def _select_module(self, selected: int) -> None:
        self.module_filter = None if selected == 0 else selected - 1
        self._update_module_button_colors()
        self._build_view()
        if self.latest is not None:
            self._render(self.latest)
        self.figure.canvas.draw_idle()

    def _select_view(self, label: str) -> None:
        self.mode = label
        self._build_view()
        if self.latest is not None:
            self._render(self.latest)
        self.figure.canvas.draw_idle()

    def _remove_content(self) -> None:
        for axis in self.content_axes:
            try:
                axis.remove()
            except (ValueError, AttributeError):
                pass
        self.content_axes.clear()
        self.fsr_artists.clear()
        self.fsr_axes.clear()
        self.acc_axes.clear()
        self.acc_artists.clear()

    def _add_fsr(self, spec: object, module: int, sensor: str) -> None:
        axis = self.figure.add_subplot(spec)
        axis.set_facecolor("#080a0d")
        collection = PolyCollection(
            cell_polygons(), array=np.zeros(ROWS * COLS), cmap="inferno",
            norm=matplotlib.colors.Normalize(0, ADC_MAX),
            edgecolors=(1, 1, 1, 0.18), linewidths=0.25)
        axis.add_collection(collection)
        axis.add_patch(Polygon(board_outline(), closed=True, fill=False,
                               edgecolor=(0.88, 0.92, 1, 0.9), linewidth=1.2))
        axis.set_xlim(-1.13, 1.13)
        axis.set_ylim(-1.12, 1.10)
        axis.set_aspect("equal")
        axis.axis("off")
        axis.set_title(f"M{module} {sensor}", color="white", fontsize=9,
                       pad=3)
        add_hex_labels(axis, True)
        self.content_axes.append(axis)
        key = (module, sensor.lower())
        self.fsr_artists[key] = collection
        self.fsr_axes[key] = axis

    def _add_acc(self, spec: object, module: int) -> None:
        axis = self.figure.add_subplot(spec, projection="3d")
        axis.set_facecolor("#080a0d")
        axis.set_xlim(-0.8, 2.8)
        axis.set_ylim(-0.8, 2.8)
        axis.set_zlim(-1.5, 1.5)
        axis.set_xticks(range(3), ["L", "C", "R"])
        axis.set_yticks(range(3), ["Lo", "M", "Up"])
        axis.set_zticks([-1, 0, 1], ["-1g", "0", "+1g"])
        axis.set_xlabel("X", fontsize=7)
        axis.set_ylabel("Y", fontsize=7)
        axis.set_zlabel("Z", fontsize=7)
        axis.set_title(f"M{module} ACC", color="white", fontsize=9, pad=3)
        axis.view_init(elev=28, azim=-56)
        axis.set_box_aspect((1, 1, 0.72))
        for value in range(3):
            axis.plot([-0.35, 2.35], [value, value], [0, 0],
                      color="0.65", linewidth=0.4, alpha=0.45)
            axis.plot([value, value], [-0.35, 2.35], [0, 0],
                      color="0.65", linewidth=0.4, alpha=0.45)
        self.content_axes.append(axis)
        self.acc_axes[module] = axis
        self.acc_artists[module] = []

    def _build_view(self) -> None:
        self._remove_content()
        modules = self._displayed_modules()
        columns = len(modules)
        if self.mode == "All":
            grid = self.figure.add_gridspec(4, columns, left=0.02, right=0.94,
                                            bottom=0.04, top=0.86,
                                            hspace=0.18, wspace=0.12)
            for column, module in enumerate(modules):
                self._add_fsr(grid[0, column], module, "FSR1")
                self._add_fsr(grid[1, column], module, "FSR2")
                self._add_acc(grid[2:, column], module)
        elif self.mode == "FSR":
            grid = self.figure.add_gridspec(2, columns, left=0.02, right=0.94,
                                            bottom=0.06, top=0.86,
                                            hspace=0.20, wspace=0.12)
            for column, module in enumerate(modules):
                self._add_fsr(grid[0, column], module, "FSR1")
                self._add_fsr(grid[1, column], module, "FSR2")
        else:
            grid = self.figure.add_gridspec(1, columns, left=0.02, right=0.94,
                                            bottom=0.06, top=0.86,
                                            wspace=0.12)
            for column, module in enumerate(modules):
                self._add_acc(grid[0, column], module)

    def _render_acc(self, module: int, frame: CombinedFrame | None) -> int:
        axis = self.acc_axes.get(module)
        if axis is None:
            return 0 if frame is None else sum(s.valid for s in frame.acc)
        for artist in self.acc_artists[module]:
            try:
                artist.remove()
            except (ValueError, AttributeError):
                pass
        self.acc_artists[module].clear()
        if frame is None:
            for index, (source_column, row) in enumerate(ACC_POSITIONS):
                column = 2 - source_column
                mark = axis.scatter([column], [row], [0], color="0.45",
                                    marker="x", s=35, linewidths=1)
                self.acc_artists[module].append(mark)
            axis.set_title(f"M{module} ACC | waiting", color="white",
                           fontsize=9, pad=3)
            return 0
        valid_count = 0
        for index, sample in enumerate(frame.acc):
            source_column, row = ACC_POSITIONS[index]
            column = 2 - source_column
            if sample.valid:
                valid_count += 1
                vector = np.clip(np.asarray([sample.x, sample.y, sample.z],
                                            dtype=float) / 1000.0, -2, 2)
                vector[0] *= -1
                arrow = axis.quiver(column, row, 0, *vector,
                                    color="teal", linewidth=1.2,
                                    arrow_length_ratio=0.2)
                point = axis.scatter([column], [row], [0], color="teal", s=22)
                self.acc_artists[module].extend((arrow, point))
            else:
                mark = axis.scatter([column], [row], [0], color="red",
                                    marker="x", s=45, linewidths=1.5)
                self.acc_artists[module].append(mark)
            label = axis.text(column, row, -0.13, f"A{index + 1}",
                              ha="center", va="top", fontsize=6)
            self.acc_artists[module].append(label)
        axis.set_title(f"M{module} ACC | {valid_count}/9 | seq {frame.sequence}",
                       color="white", fontsize=9, pad=3)
        return valid_count

    def _render(self, packet: MultiModulePacket) -> None:
        visible_modules = set(self._displayed_modules())
        valid_modules = 0
        valid_acc = 0
        for module, frame in enumerate(packet.modules):
            if module not in visible_modules:
                continue
            if frame is not None:
                valid_modules += 1
                fsr1_artist = self.fsr_artists.get((module, "fsr1"))
                if fsr1_artist is not None:
                    fsr1_artist.set_array(oriented_fsr(frame.fsr1).ravel())
                fsr2_artist = self.fsr_artists.get((module, "fsr2"))
                if fsr2_artist is not None:
                    fsr2_artist.set_array(oriented_fsr(frame.fsr2).ravel())
                valid_acc += self._render_acc(module, frame)
                for sensor in ("fsr1", "fsr2"):
                    axis = self.fsr_axes.get((module, sensor))
                    if axis is not None:
                        axis.set_title(
                            f"M{module} {sensor.upper()} | seq {frame.sequence}",
                            color="white", fontsize=9, pad=3)
            else:
                for sensor in ("fsr1", "fsr2"):
                    artist = self.fsr_artists.get((module, sensor))
                    if artist is not None:
                        artist.set_array(np.zeros(ROWS * COLS))
                    axis = self.fsr_axes.get((module, sensor))
                    if axis is not None:
                        axis.set_title(f"M{module} {sensor.upper()} | waiting",
                                       color="white", fontsize=9, pad=3)
                self._render_acc(module, None)

        updated = ",".join(str(i) for i in range(MODULE_COUNT)
                            if i in visible_modules and
                            packet.updated_mask & (1 << i)) or "none"
        module_text = ("all modules" if self.module_filter is None else
                       f"Module {self.module_filter}")
        self.title.set_text(
            f"MUL1 | packet {packet.sequence} | source {self.source_fps:.1f} "
            f"packets/s | display {self.render_fps:.1f} fps | "
            f"view {module_text} | modules {valid_modules}/{len(visible_modules)} | "
            f"ACC {valid_acc}/{9 * len(visible_modules)} | "
            f"updated M{updated} | outer CRC OK")

    def _update(self, _index: int) -> None:
        newest = None
        while True:
            try:
                newest = self.packets.get_nowait()
            except queue.Empty:
                break
        if newest is None:
            return
        now = time.monotonic()
        wall_delta = max(now - self.last_wall, 1e-6)
        instant_render = 1.0 / wall_delta
        self.render_fps = (instant_render if self.render_fps == 0 else
                           0.85 * self.render_fps + 0.15 * instant_render)
        if self.last_sequence is not None and self.last_host_ms is not None:
            seq_delta = (newest.sequence - self.last_sequence) & 0xFFFFFFFF
            ms_delta = (newest.host_ms - self.last_host_ms) & 0xFFFFFFFF
            if ms_delta and seq_delta:
                instant_source = seq_delta * 1000.0 / ms_delta
                self.source_fps = (instant_source if self.source_fps == 0 else
                                   0.85 * self.source_fps + 0.15 * instant_source)
        self.last_wall = now
        self.last_sequence = newest.sequence
        self.last_host_ms = newest.host_ms
        self.latest = newest
        self._render(newest)

    def show(self) -> None:
        plt.show()


def _make_test_inner(sequence: int) -> bytes:
    data = bytearray(FRAME_BYTES)
    data[:4] = b"ESK1"
    data[4] = 2
    data[5] = 7 | CRC_PRESENT_FLAG
    struct.pack_into("<HII", data, 6, FRAME_BYTES, sequence, 1234)
    offset = 16
    for value in range(512):
        struct.pack_into("<H", data, offset, value)
        offset += 2
    for index in range(ACC_COUNT):
        struct.pack_into("<BBhhhBBHBB", data, offset, 0x33, 0, index,
                         -index, 1000, 0x57, 0x88, 0, 1, 0xFF)
        offset += 16
    struct.pack_into("<I", data, FRAME_BYTES - 4,
                     zlib.crc32(data[:-4]) & 0xFFFFFFFF)
    return bytes(data)


def self_test() -> None:
    packet = bytearray(PACKET_BYTES)
    packet[:4] = MUL_MAGIC
    packet[4] = MUL_VERSION
    packet[5] = MODULE_COUNT
    packet[6] = 0x0F
    struct.pack_into("<HHII", packet, 8, PACKET_BYTES, BLOCK_BYTES, 7, 99)
    for module in range(MODULE_COUNT):
        offset = PACKET_HEADER_BYTES + module * BLOCK_BYTES
        packet[offset] = module
        packet[offset + 1] = 0
        packet[offset + 4:offset + 4 + FRAME_BYTES] = _make_test_inner(32)
    struct.pack_into("<I", packet, PACKET_BYTES - 4,
                     zlib.crc32(packet[:-4]) & 0xFFFFFFFF)
    parsed = parse_multi_packet(bytes(packet))
    assert parsed.sequence == 7 and len(parsed.modules) == MODULE_COUNT
    assert all(frame is not None for frame in parsed.modules)
    assert parsed.modules[3] is not None
    assert parsed.modules[3].fsr2[-1, -1] == 511
    damaged = bytearray(packet)
    damaged[100] ^= 1
    try:
        parse_multi_packet(bytes(damaged))
    except ValueError:
        pass
    else:
        raise AssertionError("MUL1 outer CRC test failed")
    print("four-module MUL1 parser self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--view", choices=tuple(VIEW_KEYS), default="all")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--interval-ms", type=int, default=50)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    packets: queue.Queue[MultiModulePacket] = queue.Queue(maxsize=1)
    stop = threading.Event()
    source = "demo" if args.demo else args.port
    worker = threading.Thread(
        target=(demo_worker if args.demo else serial_worker),
        args=((packets, stop) if args.demo else
              (args.port, args.baud, packets, stop)), daemon=True)
    worker.start()
    gui = MultiModuleGui(packets, stop, source, args.view, args.interval_ms)
    try:
        gui.show()
    finally:
        stop.set()
        worker.join(timeout=1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
