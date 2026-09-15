"""FULL/DELTA monitor for the four-module variable-SPI firmware."""
from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import queue
import struct
import sys
import threading
import time
import uuid
import zlib

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.collections import PolyCollection
from matplotlib.colors import Normalize
from matplotlib.patches import Polygon
from matplotlib.widgets import Button, TextBox
import numpy as np

ROWS = 16
COLS = 16
MODULE_COUNT = 4
HOST_SLOT_BYTES = 1044
DIAGNOSTIC_PREFIX_BYTES = 16
MUL_MAGIC = b"MUL1"
MUL_VERSION = 2
ESK_PROTOCOL_VERSION = 4
DELTA_MASK_BYTES = 32
DELTA_MASK_TOTAL_BYTES = 2 * DELTA_MASK_BYTES
DELTA_MASK_PREFIX_BYTES = 16 + DELTA_MASK_TOTAL_BYTES
DELTA_MASK_MIN_FRAME_BYTES = DELTA_MASK_PREFIX_BYTES + 4
RATE_WINDOW_SECONDS = 1.0
UINT32_MASK = 0xFFFFFFFF
RECORD_SECONDS = 40.0
RECORDING_PROGRESS_INTERVAL = 0.5
PROJECT_ROOT = Path(__file__).resolve().parents[6]
FIRMWARE_DIR = Path(__file__).resolve().parents[1]
RECORD_DATA_DIR = PROJECT_ROOT / "docs" / "Final" / "data scalability" / "data"
DEFAULT_SCHEDULE = PROJECT_ROOT / "docs" / "Final" / "new_firmware_experiment_plan" / "halfday_schedule.csv"
# Keep direct importlib loading (used by protocol regression) working.
PC_DIR = str(Path(__file__).resolve().parent)
if PC_DIR not in sys.path:
    sys.path.insert(0, PC_DIR)
from experiment_recording import ExperimentRecorder, RecordingConfig, RecordingStatus
from experiment_controls import ExperimentControls
from module_detection import ModuleDetector, require_ready
from recording_plot_jobs import launch_recording_plots


@dataclass
class ParserCounters:
    """Cumulative transport and parser checks shown by the GUI."""

    candidate_packets: int = 0
    valid_packets: int = 0
    outer_crc_errors: int = 0
    sequence_gap_events: int = 0
    lost_frames: int = 0
    duplicate_frames: int = 0
    out_of_order_frames: int = 0
    format_errors: int = 0
    inner_crc_errors: int = 0
    delta_base_mismatches: int = 0
    last_mul1_sequence: int | None = None

    def observe_sequence(self, sequence: int) -> None:
        if self.last_mul1_sequence is None:
            self.last_mul1_sequence = sequence
            return
        delta = (sequence - self.last_mul1_sequence) & UINT32_MASK
        if delta == 0:
            self.duplicate_frames += 1
        elif delta < 0x80000000:
            if delta > 1:
                self.sequence_gap_events += 1
                self.lost_frames += delta - 1
        else:
            self.out_of_order_frames += 1
        self.last_mul1_sequence = sequence

    def snapshot(self) -> "ParserCounters":
        return ParserCounters(
            candidate_packets=self.candidate_packets,
            valid_packets=self.valid_packets,
            outer_crc_errors=self.outer_crc_errors,
            sequence_gap_events=self.sequence_gap_events,
            lost_frames=self.lost_frames,
            duplicate_frames=self.duplicate_frames,
            out_of_order_frames=self.out_of_order_frames,
            format_errors=self.format_errors,
            inner_crc_errors=self.inner_crc_errors,
            delta_base_mismatches=self.delta_base_mismatches,
            last_mul1_sequence=self.last_mul1_sequence,
        )

    def summary(self) -> str:
        return (
            f"CRC err={self.outer_crc_errors + self.inner_crc_errors} "
            f"(outer={self.outer_crc_errors}, inner={self.inner_crc_errors}) | "
            f"seq gaps={self.sequence_gap_events} | missing MUL1={self.lost_frames} | "
            f"parse err={self.format_errors} | "
            f"Delta base={self.delta_base_mismatches}"
        )


def half_width_at(v: float) -> float:
    return 1.0 - abs(v * 2.0 - 1.0) * 0.5


def board_point(u: float, v: float) -> tuple[float, float]:
    return (u * 2.0 - 1.0) * half_width_at(v), 1.0 - v * 2.0


def cell_polygons() -> list[list[tuple[float, float]]]:
    return [
        [
            board_point(c / COLS, r / ROWS),
            board_point((c + 1) / COLS, r / ROWS),
            board_point((c + 1) / COLS, (r + 1) / ROWS),
            board_point(c / COLS, (r + 1) / ROWS),
        ]
        for r in range(ROWS)
        for c in range(COLS)
    ]


def board_outline() -> list[tuple[float, float]]:
    return [
        board_point(0.0, 0.5), board_point(0.0, 0.0),
        board_point(1.0, 0.0), board_point(1.0, 0.5),
        board_point(1.0, 1.0), board_point(0.0, 1.0),
    ]


def oriented_fsr(matrix: np.ndarray) -> np.ndarray:
    """Keep the established GUI orientation: transpose then mirror columns."""
    return np.fliplr(matrix.T)


def add_grid_labels(axis) -> None:
    for display_col in range(COLS):
        raw_col = COLS - display_col
        u = (display_col + 0.5) / COLS
        x, _ = board_point(u, 0.0)
        axis.text(x, 1.04, f"C{raw_col}", ha="center", va="bottom",
                  fontsize=5.5, color="0.55", rotation=90)
    for display_row in range(ROWS):
        v = (display_row + 0.5) / ROWS
        _, y = board_point(0.0, v)
        axis.text(-1.04, y, f"R{display_row + 1}", ha="right", va="center",
                  fontsize=5, color="0.75")


def read_u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def crc_ok(data: bytes) -> bool:
    return zlib.crc32(data[:-4]) & 0xFFFFFFFF == read_u32(data, len(data) - 4)


def marker(data: bytes) -> bytes:
    return data[:4]


class ProtocolState:
    """Reconstructs one module's FSR matrices from FULL/DELTA frames."""

    def __init__(self) -> None:
        self.fsr1 = np.zeros((ROWS, COLS), dtype=np.uint16)
        self.fsr2 = np.zeros((ROWS, COLS), dtype=np.uint16)
        self.last_sequence: int | None = None
        self.delta_valid = False
        self.last_frame_type = "NONE"

    def _set_cell(self, layer: int, row: int, col: int, value: int) -> None:
        if not (0 <= row < ROWS and 0 <= col < COLS):
            raise ValueError("cell coordinate out of range")
        target = self.fsr1 if layer == 0 else self.fsr2
        target[row, col] = value & 0x0FFF

    def copy_from(self, other: "ProtocolState") -> None:
        self.fsr1[:, :] = other.fsr1
        self.fsr2[:, :] = other.fsr2
        self.last_sequence = other.last_sequence
        self.delta_valid = other.delta_valid
        self.last_frame_type = other.last_frame_type

    def clone(self) -> "ProtocolState":
        clone = ProtocolState()
        clone.copy_from(self)
        return clone

    def apply(self, data: bytes) -> str:
        kind = marker(data)
        if kind in (b"ESKF", b"ESKD"):
            return self._apply_esk(data, kind)
        raise ValueError(f"unknown inner marker {kind!r}")

    def _apply_esk(self, data: bytes, kind: bytes) -> str:
        if (len(data) < 22 or data[4] != ESK_PROTOCOL_VERSION or
                read_u16(data, 6) != len(data)):
            raise ValueError("invalid ESK header")
        if not crc_ok(data):
            raise ValueError("inner ESK CRC32 mismatch")
        # Low bits carry acquisition status (normally 0x03). Only the top
        # two bits are reserved; CRC and DELTA flags match the bridge rules.
        flags = data[5]
        if ((flags & 0xC0) or not (flags & 0x10) or
                (kind == b"ESKD" and not (flags & 0x20))):
            raise ValueError("unsupported ESK flags")
        sequence = read_u32(data, 8)
        if kind == b"ESKF":
            if len(data) != HOST_SLOT_BYTES:
                raise ValueError("invalid ESKF length")
            values = np.frombuffer(data, dtype="<u2", count=ROWS * COLS,
                                   offset=16).reshape((ROWS, COLS))
            self.fsr1[:, :] = values & 0x0FFF
            values = np.frombuffer(data, dtype="<u2", count=ROWS * COLS,
                                   offset=528).reshape((ROWS, COLS))
            self.fsr2[:, :] = values & 0x0FFF
            self.delta_valid = True
            self.last_sequence = sequence
            self.last_frame_type = "ESKF"
            if flags & 0x20:
                return "DELTA_SYNC"
            return "FULL"
        base = read_u32(data, 12)
        if kind != b"ESKD" or len(data) < DELTA_MASK_MIN_FRAME_BYTES:
            raise ValueError("invalid mask Delta frame")
        masks = (data[16:48], data[48:80])
        changed = sum(byte.bit_count() for mask in masks for byte in mask)
        expected_length = DELTA_MASK_MIN_FRAME_BYTES + 2 * changed
        if len(data) != expected_length:
            raise ValueError("invalid mask Delta length")
        if not self.delta_valid or self.last_sequence != base:
            raise ValueError(f"Delta base sequence {base} does not match cache "
                             f"{self.last_sequence}")
        offset = DELTA_MASK_PREFIX_BYTES
        for layer, mask in enumerate(masks):
            for position in range(ROWS * COLS):
                if mask[position // 8] & (1 << (position % 8)):
                    if offset + 2 > len(data) - 4:
                        raise ValueError("mask/value mismatch")
                    row, col = divmod(position, COLS)
                    self._set_cell(layer, row, col, read_u16(data, offset))
                    offset += 2
        if offset != len(data) - 4:
            raise ValueError("mask/value count mismatch")
        self.last_sequence = sequence
        self.last_frame_type = "ESKD"
        return "DELTA"



@dataclass
class MultiModulePacket:
    sequence: int
    host_ms: int
    updated_mask: int
    states: tuple[ProtocolState, ...]
    algorithms: tuple[str | None, ...]
    statuses: tuple[int, ...]
    packet_bytes: int = 0
    usb_rate: float = 0.0
    round_rate: float = 0.0
    counters: ParserCounters | None = None
    errors: tuple[str | None, ...] = ()
    detection: dict | None = None
    received_monotonic: float = 0.0


@dataclass
class SerialError:
    message: str


@dataclass
class ParserWarning:
    message: str
    counters: ParserCounters | None = None


def module_status_name(status: int) -> str:
    if status == 0:
        return "OK"
    if (status & 0x80) == 0:
        return f"ERROR_{status}"
    names = {
        0: "NOT_UPDATED",
        1: "BAD_FRAME",
        2: "BAD_CRC",
        3: "NO_IRQ",
        4: "TIMEOUT",
        5: "MODE_TRANSITION",
        6: "RESYNC_NEEDED",
        7: "BAD_VERSION",
    }
    return names.get(status & 0x0F, f"NOT_UPDATED_{status & 0x0F}")


def parse_multi_packet(data: bytes, states: list[ProtocolState] | None = None,
                       usb_rate: float = 0.0,
                       round_rate: float = 0.0,
                       allow_partial: bool = False) -> MultiModulePacket:
    if len(data) < 24 or data[:4] != MUL_MAGIC or data[4] != MUL_VERSION:
        raise ValueError("bad MUL1 header")
    if data[5] != MODULE_COUNT:
        raise ValueError("unexpected module count")
    declared = read_u16(data, 8)
    if declared != len(data) or declared < 24:
        raise ValueError("invalid MUL1 length")
    if zlib.crc32(data[:-4]) & 0xFFFFFFFF != read_u32(data, len(data) - 4):
        raise ValueError("MUL1 CRC32 mismatch")
    if states is None:
        states = [ProtocolState() for _ in range(MODULE_COUNT)]
    if len(states) != MODULE_COUNT:
        raise ValueError("four module states required")
    working_states = [state.clone() for state in states]
    offset = 20
    algorithms: list[str | None] = []
    statuses: list[int] = []
    end = len(data) - 4
    parser_error: str | None = None
    errors: list[str | None] = [None] * MODULE_COUNT
    for expected_id in range(MODULE_COUNT):
        if offset + 4 > end:
            raise ValueError("truncated module block")
        module_id, status = data[offset], data[offset + 1]
        payload_len = read_u16(data, offset + 2)
        offset += 4
        if module_id != expected_id or offset + payload_len > end:
            raise ValueError("invalid module block")
        statuses.append(status)
        if status != 0:
            if payload_len not in (0, DIAGNOSTIC_PREFIX_BYTES):
                raise ValueError("invalid failed-module diagnostic payload")
            offset += payload_len
            algorithms.append(None)
            continue
        if payload_len == 0:
            raise ValueError("healthy module has no payload")
        try:
            algorithms.append(working_states[module_id].apply(
                data[offset:offset + payload_len]))
        except ValueError as exc:
            # Preserve valid module caches from this MUL1 packet. A broken
            # incremental chain in one module must not roll back the others.
            algorithms.append(None)
            working_states[module_id].delta_valid = False
            errors[module_id] = str(exc)
            if parser_error is None:
                parser_error = f"module {module_id}: {exc}"
        offset += payload_len
    if offset != end:
        raise ValueError("trailing MUL1 bytes")
    for state, working in zip(states, working_states):
        state.copy_from(working)
    if parser_error is not None and not allow_partial:
        raise ValueError(parser_error)
    return MultiModulePacket(read_u32(data, 12), read_u32(data, 16), data[6],
                             tuple(state.clone() for state in states), tuple(algorithms), tuple(statuses),
                             len(data), usb_rate, round_rate, errors=tuple(errors))


def make_full_frame(sequence: int, base: int, flags: int = 0x10) -> bytes:
    frame = bytearray(HOST_SLOT_BYTES)
    frame[:4] = b"ESKF"
    frame[4], frame[5] = ESK_PROTOCOL_VERSION, flags
    struct.pack_into("<HII", frame, 6, HOST_SLOT_BYTES, sequence, 0xFFFFFFFF)
    for i in range(ROWS * COLS):
        struct.pack_into("<H", frame, 16 + 2 * i, (base + i) & 0x0FFF)
        struct.pack_into("<H", frame, 528 + 2 * i, (base + 2 * i) & 0x0FFF)
    struct.pack_into("<I", frame, HOST_SLOT_BYTES - 4,
                     zlib.crc32(frame[:-4]) & 0xFFFFFFFF)
    return bytes(frame)


def make_esk_delta(sequence: int, base_sequence: int,
                   changes: list[tuple[int, int, int, int]]) -> bytes:
    values: dict[tuple[int, int, int], int] = {}
    masks = [bytearray(DELTA_MASK_BYTES), bytearray(DELTA_MASK_BYTES)]
    for layer, row, col, value in changes:
        if layer not in (0, 1) or not (0 <= row < ROWS) or not (0 <= col < COLS):
            raise ValueError("invalid Delta test coordinate")
        key = (layer, row, col)
        if key in values:
            raise ValueError("duplicate Delta test coordinate")
        values[key] = value & 0x0FFF
        position = row * COLS + col
        masks[layer][position // 8] |= 1 << (position % 8)
    frame = bytearray(DELTA_MASK_MIN_FRAME_BYTES + 2 * len(values))
    frame[:4] = b"ESKD"
    frame[4], frame[5] = ESK_PROTOCOL_VERSION, 0x30
    struct.pack_into("<HII", frame, 6, len(frame), sequence, base_sequence)
    frame[16:48] = masks[0]
    frame[48:80] = masks[1]
    offset = DELTA_MASK_PREFIX_BYTES
    for layer in range(2):
        for position in range(ROWS * COLS):
            row, col = divmod(position, COLS)
            if (layer, row, col) in values:
                struct.pack_into("<H", frame, offset, values[(layer, row, col)])
                offset += 2
    struct.pack_into("<I", frame, len(frame) - 4,
                     zlib.crc32(frame[:-4]) & 0xFFFFFFFF)
    return bytes(frame)






def make_packet(frames: list[bytes], sequence: int = 1) -> bytes:
    packet = bytearray(20)
    packet[:4], packet[4], packet[5], packet[6] = MUL_MAGIC, 2, MODULE_COUNT, 0x0F
    struct.pack_into("<II", packet, 12, sequence, 99)
    for module, frame in enumerate(frames):
        packet.extend(bytes((module, 0)))
        packet.extend(struct.pack("<H", len(frame)))
        packet.extend(frame)
    packet.extend(b"\0\0\0\0")
    struct.pack_into("<H", packet, 8, len(packet))
    struct.pack_into("<I", packet, len(packet) - 4,
                     zlib.crc32(packet[:-4]) & 0xFFFFFFFF)
    return bytes(packet)


def make_diagnostic_packet(prefix: bytes, sequence: int = 9) -> bytes:
    if len(prefix) != DIAGNOSTIC_PREFIX_BYTES:
        raise ValueError("diagnostic prefix must be 16 bytes")
    packet = bytearray(20)
    packet[:4], packet[4], packet[5], packet[6] = MUL_MAGIC, 2, MODULE_COUNT, 0
    struct.pack_into("<II", packet, 12, sequence, 99)
    for module in range(MODULE_COUNT):
        if module == 0:
            packet.extend(bytes((module, 0x81)))
            packet.extend(struct.pack("<H", len(prefix)))
            packet.extend(prefix)
        else:
            packet.extend(bytes((module, 0x83, 0, 0)))
    packet.extend(b"\0\0\0\0")
    struct.pack_into("<H", packet, 8, len(packet))
    struct.pack_into("<I", packet, len(packet) - 4,
                     zlib.crc32(packet[:-4]) & 0xFFFFFFFF)
    return bytes(packet)


def self_test() -> None:
    # Exercise the actual STM32 acquisition bits, including partial scans.
    for status in range(4):
        state = ProtocolState()
        assert state.apply(make_full_frame(40, 20, flags=0x10 | status)) == "FULL"
        assert state.apply(make_full_frame(41, 20, flags=0x30 | status)) == "DELTA_SYNC"
        status_delta = bytearray(make_esk_delta(42, 41, [(0, 3, 4, 3000)]))
        status_delta[5] |= status
        struct.pack_into("<I", status_delta, len(status_delta) - 4,
                         zlib.crc32(status_delta[:-4]) & 0xFFFFFFFF)
        assert state.apply(bytes(status_delta)) == "DELTA"
        assert int(state.fsr1[3, 4]) == 3000
    states = [ProtocolState() for _ in range(MODULE_COUNT)]
    full = make_full_frame(10, 20)
    packet = make_packet([full] * MODULE_COUNT)
    parsed = parse_multi_packet(packet, states)
    assert parsed.algorithms == ("FULL",) * MODULE_COUNT
    delta = make_esk_delta(11, 10, [(0, 3, 4, 3000), (1, 1, 2, 3500)])
    parsed = parse_multi_packet(make_packet([delta] + [full] * 3, 2), states)
    assert parsed.algorithms[0] == "DELTA"
    assert int(states[0].fsr1[3, 4]) == 3000
    assert int(states[0].fsr2[1, 2]) == 3500
    zero_delta = make_esk_delta(12, 11, [])
    parsed = parse_multi_packet(make_packet([zero_delta] + [full] * 3, 3), states)
    assert parsed.algorithms[0] == "DELTA"
    assert len(zero_delta) == DELTA_MASK_MIN_FRAME_BYTES
    dropped_delta = make_esk_delta(14, 11, [(0, 4, 5, 3200)])
    try:
        parse_multi_packet(make_packet([dropped_delta] + [full] * 3, 4), states)
    except ValueError:
        pass
    else:
        raise AssertionError("Delta base mismatch was not rejected")
    assert states[0].last_sequence == 12
    resync = make_full_frame(15, 20, flags=0x30)
    parsed = parse_multi_packet(make_packet([resync] + [full] * 3, 5), states)
    assert parsed.algorithms[0] == "DELTA_SYNC"
    unsupported = bytearray(full)
    unsupported[:4] = b"NOPE"
    for invalid_frame in (bytes(unsupported),
                          make_full_frame(16, 20, flags=0x50),
                          make_full_frame(16, 20, flags=0x90),
                          make_full_frame(16, 20, flags=0x03)):
        try:
            ProtocolState().apply(invalid_frame)
        except ValueError:
            pass
        else:
            raise AssertionError("Unsupported inner frame was not rejected")
    assert states[0].last_frame_type == "ESKF"
    damaged = bytearray(packet)
    damaged[25] ^= 1
    try:
        parse_multi_packet(bytes(damaged), [ProtocolState() for _ in range(4)])
    except ValueError:
        pass
    else:
        raise AssertionError("MUL1 CRC self-test failed")
    diagnostic_states = [ProtocolState() for _ in range(MODULE_COUNT)]
    diagnostic = make_diagnostic_packet(b"\x00\x00ESKF\x03\x10\x14\x04\x00\x00\x00\x00\x00\x00")
    parsed = parse_multi_packet(diagnostic, diagnostic_states)
    assert parsed.statuses == (0x81, 0x83, 0x83, 0x83)
    assert parsed.algorithms == (None, None, None, None)
    print("four-module FSR-only parser self-test: PASS")


class PacketFramer:
    """Incremental framing; offsets address the complete received byte stream."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.buffer = bytearray()
        self.offset = 0
        self.discarded_bytes = 0

    def feed(self, chunk: bytes) -> list[tuple[int, bytes]]:
        self.buffer.extend(chunk)
        packets = []
        while True:
            start = self.buffer.find(MUL_MAGIC)
            if start < 0:
                skip = max(0, len(self.buffer) - 3)
                self.discarded_bytes += skip
                self.offset += skip
                del self.buffer[:skip]
                break
            if start:
                self.discarded_bytes += start
                self.offset += start
                del self.buffer[:start]
            if len(self.buffer) < 20:
                break
            length = read_u16(self.buffer, 8)
            if not 40 <= length <= 5000:
                self.discarded_bytes += 1
                self.offset += 1
                del self.buffer[:1]
                continue
            if len(self.buffer) < length:
                break
            packets.append((self.offset, bytes(self.buffer[:length])))
            del self.buffer[:length]
            self.offset += length
        return packets


def read_exact(port, length: int) -> bytes:
    chunks: list[bytes] = []
    received = 0
    while received < length:
        chunk = port.read(length - received)
        if not chunk:
            raise TimeoutError("serial read timeout")
        chunks.append(chunk)
        received += len(chunk)
    return b"".join(chunks)


def read_packet(port) -> bytes:
    window = bytearray()
    while True:
        window += read_exact(port, 1)
        if len(window) > 4:
            del window[:-4]
        if bytes(window) == MUL_MAGIC:
            rest = read_exact(port, 16)
            header = bytes(window) + rest
            length = read_u16(header, 8)
            if 24 <= length <= 5000:
                return header + read_exact(port, length - 20)


def publish_serial_error(packets: queue.Queue, message: str) -> None:
    event = SerialError(message)
    try:
        packets.put_nowait(event)
    except queue.Full:
        try:
            packets.get_nowait()
        except queue.Empty:
            pass
        packets.put_nowait(event)


def publish_parser_warning(packets: queue.Queue, message: str,
                           counters: ParserCounters | None = None) -> None:
    try:
        packets.put_nowait(ParserWarning(message, counters.snapshot()
                                          if counters is not None else None))
    except queue.Full:
        pass


def publish_recording_status(events: queue.Queue,
                             status: str | RecordingStatus) -> None:
    if isinstance(status, str):
        status = RecordingStatus(status)
    try:
        events.put_nowait(status)
    except queue.Full:
        try:
            events.get_nowait()
        except queue.Empty:
            pass
        try:
            events.put_nowait(status)
        except queue.Full:
            pass


def serial_worker(port_name: str, baud: int, packets: queue.Queue,
                  commands: queue.Queue, recording_events: queue.Queue,
                  stop: threading.Event) -> None:
    import serial

    states = [ProtocolState() for _ in range(MODULE_COUNT)]
    framer = PacketFramer()
    detector = ModuleDetector()
    counters = ParserCounters()
    recorder: ExperimentRecorder | None = None
    stream_bytes_received = 0
    recording_stream_start = 0
    window_start = time.monotonic()
    window_bytes = window_packets = 0
    last_usb_rate = last_round_rate = 0.0
    last_warning = last_progress = last_resync = 0.0
    recent_commands: list[dict] = []
    batch_config: RecordingConfig | None = None
    batch_total = 1
    batch_index = 0
    batch_id = None
    batch_pending = False
    pending_plot_runs: list[Path] = []

    def submit_pending_plots() -> str:
        if not pending_plot_runs:
            return ""
        paths = list(pending_plot_runs)
        pending_plot_runs.clear()
        try:
            launch_recording_plots(paths)
            return f"Plots queued ({len(paths)} runs; see plot_status.json / plot_generation.log)"
        except OSError as exc:
            # Plot failures must never invalidate saved data or cancel a capture.
            return f"Data saved; automatic plots could not start: {exc}"

    def publish_capture(status: RecordingStatus) -> None:
        if batch_total > 1:
            status.message = f"Repeat {batch_index}/{batch_total} | {status.message}"
        publish_recording_status(recording_events, status)

    def clear_batch() -> None:
        nonlocal batch_config, batch_pending
        batch_config, batch_pending = None, False

    def finish(reason: str) -> None:
        nonlocal batch_pending
        if reason != "capture duration reached":
            clear_batch()
        if recorder is None or not recorder.active:
            if batch_config is None:
                plot_message = submit_pending_plots()
                if plot_message:
                    publish_recording_status(recording_events,
                        RecordingStatus(plot_message, phase="complete"))
            return
        try:
            status = recorder.finish(counters, reason)
            if recorder.target_mode == "DELTA":
                pending_plot_runs.append(recorder.run_dir)
            if reason == "capture duration reached" and batch_config is not None and batch_index < batch_total:
                batch_pending = True
                if status:
                    status.phase = "between"
            else:
                clear_batch()
            if batch_config is None:
                plot_message = submit_pending_plots()
                if status and plot_message:
                    status.message = f"{plot_message} | {status.message}"
            if status:
                publish_capture(status)
        except OSError as exc:
            recorder.active = False
            clear_batch()
            plot_message = submit_pending_plots()
            publish_recording_status(recording_events,
                RecordingStatus(f"Recording write error: {exc} | {plot_message}", phase="unavailable"))

    def begin_capture() -> None:
        nonlocal recorder, batch_index, batch_pending, last_progress, recording_stream_start
        if batch_config is None:
            return
        try:
            config = deepcopy(batch_config)
            if batch_total > 1:
                config.metadata.update(
                    repeat=str(batch_index + 1), batch_id=batch_id,
                    batch_repeat_index=batch_index + 1, batch_repeat_count=batch_total,
                    batch_recording_method="consecutive_capture_windows_same_setup",
                    batch_interpretation="Temporal repeats under one setup; not independent setup blocks or automatic reloading",
                    batch_initial_observations="GUI at_record fields describe the initial batch request; each run measures its own statistics",
                    module_detection_at_repeat_start=detector.snapshot(time.monotonic()))
            if batch_index == 0 and config.metadata.get("module_selection_source") == "automatic":
                detected = require_ready(detector.snapshot(time.monotonic()), time.monotonic())
                if (detected["modules"] != config.metadata["target_modules"] or
                        detected["mode"] != config.metadata["target_mode"]):
                    raise ValueError('Module/mode detection changed before Record; wait and retry')
                config.metadata["module_detection_at_worker_start"] = detected
            config.metadata["pre_record_commands"] = deepcopy(recent_commands[-4:])
            recording_stream_start = stream_bytes_received
            config.metadata["stream_start_offset"] = recording_stream_start
            config.metadata["live_parser_buffer_bytes_at_start"] = len(framer.buffer)
            config.metadata["live_parser_continuous_across_recordings"] = True
            recorder = ExperimentRecorder(port_name, baud, config)
            status = recorder.start(counters)
            batch_index += 1
            batch_pending = False
            last_progress = time.monotonic()
            publish_capture(status)
        except (ValueError, OSError) as exc:
            clear_batch()
            plot_message = submit_pending_plots()
            publish_recording_status(recording_events,
                RecordingStatus(f"Recording unavailable: {exc}; remaining repeats cancelled | {plot_message}", phase="unavailable"))

    def count_error(message: str) -> None:
        if "inner ESK CRC32 mismatch" in message:
            counters.inner_crc_errors += 1
        elif "Delta base sequence" in message:
            counters.delta_base_mismatches += 1
        elif "MUL1 CRC32 mismatch" not in message:
            counters.format_errors += 1

    try:
        port = serial.Serial(port_name, baudrate=baud, timeout=0.05)
    except serial.SerialException as exc:
        publish_serial_error(packets, f"Could not open {port_name}: {exc}")
        return
    try:
        with port:
            while not stop.is_set():
                if recorder is not None and recorder.expired():
                    finish("capture duration reached")
                while True:
                    try:
                        command = commands.get_nowait()
                    except queue.Empty:
                        break
                    command_source = "user"
                    if isinstance(command, dict):
                        action = command.get("action")
                        if action == "START_RECORDING":
                            if batch_config is not None or (recorder is not None and recorder.active):
                                publish_recording_status(recording_events, "Recording already active")
                                continue
                            try:
                                repeats = command.get("repeats", 1)
                                if repeats not in (1, 3):
                                    raise ValueError('Record supports one legacy capture or three consecutive captures')
                                batch_config = deepcopy(command["config"])
                                batch_total, batch_index = repeats, 0
                                batch_id = f"BATCH_{uuid.uuid4().hex}"
                                batch_pending = True
                            except (ValueError, OSError) as exc:
                                clear_batch()
                                publish_recording_status(recording_events,
                                    RecordingStatus(f"Recording unavailable: {exc}", phase="unavailable"))
                            continue
                        if action == "MARK_EVENT":
                            if recorder is not None and recorder.active:
                                recorder.note_command(str(command.get("text", "manual marker")), source="event")
                            continue
                        if action == "SEND_COMMAND":
                            command_source = str(command.get("source", "user"))
                            command = str(command["command"])
                        else:
                            continue
                    if command == "STOP_RECORDING":
                        was_pending = batch_pending
                        finish("operator stopped capture")
                        if was_pending:
                            publish_recording_status(recording_events,
                                RecordingStatus(f"Batch stopped after {batch_index}/{batch_total}; remaining repeats cancelled", phase="complete"))
                        continue
                    if command == "START_RECORDING":
                        publish_recording_status(recording_events, "Use Record with experiment settings")
                        continue
                    if recorder is not None and recorder.active:
                        recorder.note_command(command, source=command_source)
                    port.write((command + "\n").encode("ascii"))
                    port.flush()
                    recent_commands.append({"command": command, "source": command_source,
                                            "sent_at": datetime.now().astimezone().isoformat()})
                    del recent_commands[:-4]
                # STOP is processed before a scheduled next repeat. This runs even
                # when the heatmap/settings UI is paused or its event queue is full.
                if batch_pending and not stop.is_set():
                    begin_capture()
                chunk = port.read(min(max(getattr(port, "in_waiting", 0), 1), 65536))
                now = time.monotonic()
                if not chunk:
                    if recorder is not None and recorder.expired():
                        finish("capture duration reached")
                    if recorder is not None and recorder.active and now - last_progress >= RECORDING_PROGRESS_INTERVAL:
                        publish_capture(recorder.progress_status())
                        last_progress = now
                    continue
                received_at = datetime.now().astimezone()
                stream_bytes_received += len(chunk)
                if recorder is not None and recorder.active:
                    recorder.record_raw(chunk, elapsed_s=now - recorder.started_monotonic)
                window_bytes += len(chunk)
                for offset, data in framer.feed(chunk):
                    counters.candidate_packets += 1
                    window_packets += 1
                    packet = None
                    error = None
                    if crc_ok(data):
                        counters.observe_sequence(read_u32(data, 12))
                    else:
                        counters.outer_crc_errors += 1
                    try:
                        packet = parse_multi_packet(data, states, last_usb_rate,
                                                    last_round_rate, allow_partial=True)
                        errors = [f"M{i}: {value}" for i, value in enumerate(packet.errors) if value]
                        if errors:
                            error = "; ".join(errors)
                            for value in errors:
                                count_error(value)
                        else:
                            counters.valid_packets += 1
                    except ValueError as exc:
                        error = str(exc)
                        count_error(error)
                    if error:
                        if "Delta" in error and now - last_resync >= 0.25:
                            commands.put({"action": "SEND_COMMAND", "command": "RESYNC DELTA",
                                          "source": "automatic_parser_resync"})
                            last_resync = now
                        if now - last_warning >= 1.0:
                            publish_parser_warning(packets, f"Parser: {error}", counters)
                            last_warning = now
                    if recorder is not None and recorder.active:
                        raw_offset = offset - recording_stream_start
                        if raw_offset < 0:
                            # The packet began before Record, but its suffix was
                            # received in this file. Keep parsing the live stream;
                            # separately account for the captured boundary fragment.
                            recorder.record_start_boundary(data, raw_offset=raw_offset,
                                elapsed_s=now - recorder.started_monotonic,
                                error=error, counters=counters)
                        else:
                            recorder.record_packet(data, packet, error, raw_offset=raw_offset,
                                elapsed_s=now - recorder.started_monotonic,
                                packet_started_at=received_at, counters=counters)
                    if packet is not None:
                        packet.counters = counters.snapshot()
                        packet.received_monotonic = now
                        packet.detection = detector.observe(packet, now)
                        try:
                            packets.put_nowait(packet)
                        except queue.Full:
                            try:
                                packets.get_nowait()
                            except queue.Empty:
                                pass
                            packets.put_nowait(packet)
                elapsed = now - window_start
                if elapsed >= RATE_WINDOW_SECONDS:
                    last_usb_rate = window_bytes / elapsed
                    last_round_rate = window_packets / elapsed
                    window_bytes = window_packets = 0
                    window_start = now
                if recorder is not None and recorder.expired():
                    finish("capture duration reached")
                elif recorder is not None and recorder.active and now - last_progress >= RECORDING_PROGRESS_INTERVAL:
                    publish_capture(recorder.progress_status())
                    last_progress = now
    except serial.SerialException as exc:
        finish("serial port disconnected")
        publish_serial_error(packets, f"Serial {port_name} disconnected: {exc}")
    except OSError as exc:
        finish("recording IO error")
        publish_serial_error(packets, f"Recording IO error: {exc}")
    finally:
        finish("monitor stopped")



def demo_worker(packets: queue.Queue, stop: threading.Event) -> None:
    states = [ProtocolState() for _ in range(MODULE_COUNT)]
    detector = ModuleDetector()
    sequence = 1
    while not stop.is_set():
        frames = [make_full_frame(sequence, 100 * m + sequence) for m in range(MODULE_COUNT)]
        packet = parse_multi_packet(make_packet(frames, sequence), states,
                                    0.0)
        packet.received_monotonic = time.monotonic()
        packet.detection = detector.observe(packet, packet.received_monotonic)
        try:
            packets.put_nowait(packet)
        except queue.Full:
            try:
                packets.get_nowait()
            except queue.Empty:
                pass
            packets.put_nowait(packet)
        sequence += 1
        time.sleep(0.05)


class FsrGui:
    def __init__(self, packets: queue.Queue, commands: queue.Queue,
                 recording_events: queue.Queue, stop: threading.Event,
                 source: str, output_dir: Path = RECORD_DATA_DIR,
                 schedule_path: Path = DEFAULT_SCHEDULE) -> None:
        self.packets = packets
        self.commands = commands
        self.recording_events = recording_events
        self.stop = stop
        self.source = source
        self.last_packet: MultiModulePacket | None = None
        self.serial_error: str | None = None
        self.parser_warning: str | None = None
        self.parser_counters = ParserCounters()
        self.target_scan_hz = 200
        self.recording_active = False
        self.recording_repeat_label = "1/3"
        self.display_paused = False
        self._requested_mode = None
        self.target_scan_hz_source = "GUI default 200 Hz; not firmware readback"
        self.experiment = ExperimentControls(FIRMWARE_DIR, output_dir, schedule_path,
                                             on_change=self._refresh_experiment,
                                             on_open=self._pause_display,
                                             on_close=self._resume_display)
        self.fig, axes = plt.subplots(2, MODULE_COUNT, figsize=(16, 9),
                                      constrained_layout=False)
        self.fig.subplots_adjust(left=0.02, right=0.98, bottom=0.04,
                                 top=0.62, wspace=0.08, hspace=0.20)
        self.axes = np.asarray(axes).reshape((2, MODULE_COUNT))
        self.mode_buttons: list[Button] = []
        self.apply_button: Button | None = None
        self.record_button: Button | None = None
        self.recording_time_status = None
        polygons = cell_polygons()
        self.collections: list[PolyCollection] = []
        for module in range(MODULE_COUNT):
            for layer in range(2):
                axis = self.axes[layer, module]
                axis.set_aspect("equal")
                axis.set_xlim(-1.16, 1.16)
                axis.set_ylim(-1.16, 1.16)
                axis.axis("off")
                axis.add_patch(Polygon(board_outline(), closed=True, fill=False,
                                       edgecolor="0.8", linewidth=1.5))
                values = np.zeros(ROWS * COLS, dtype=np.uint16)
                collection = PolyCollection(polygons, array=values, cmap="inferno",
                                           edgecolors="0.15", linewidths=0.2,
                                           norm=Normalize(vmin=0, vmax=4095))
                axis.add_collection(collection)
                add_grid_labels(axis)
                self.collections.append(collection)
            self.axes[0, module].set_title(f"Module {module} / FSR1")
            self.axes[1, module].set_title(f"Module {module} / FSR2")
        self._add_controls()
        self.live_status = self.fig.text(
            0.02, 0.715,
            "Algorithm: waiting | measured MUL1 rate: -- Hz | target: 200 Hz",
            fontsize=10, va="center", color="#1f5f9e")
        self.integrity_status = self.fig.text(
            0.02, 0.685,
            "Checks: CRC err=0 | seq gaps=0 | missing MUL1=0 | parse err=0 | Delta base=0",
            fontsize=8.5, va="center", color="#555555")
        self.fig.suptitle(f"FSR-only monitor | {source}", fontsize=14)
        self.animation = FuncAnimation(self.fig, self.update, interval=100,
                                       cache_frame_data=False)
        self.fig.canvas.mpl_connect("close_event", self._close_gui)

    def _add_controls(self) -> None:
        self.extra_buttons = []
        for index, mode in enumerate(("FULL", "DELTA")):
            button = Button(self.fig.add_axes([0.02 + index * 0.07, 0.895, 0.065, 0.045]), mode)
            button.on_clicked(lambda _event, value=mode: self._send_command(f"MODE {value}"))
            self.mode_buttons.append(button)
        self.rate_box = TextBox(self.fig.add_axes([0.24, 0.895, 0.07, 0.045]), "Scan Hz: ", initial="200")
        self.apply_button = Button(self.fig.add_axes([0.32, 0.895, 0.065, 0.045]), "Apply")
        self.apply_button.on_clicked(self._apply_scan_rate)
        self.record_button = Button(self.fig.add_axes([0.40, 0.895, 0.08, 0.045]), "Record x3")
        self.record_button.on_clicked(self._start_recording)
        for x, title, callback in (
            (0.49, "Stop", lambda _e: self.commands.put("STOP_RECORDING")),
            (0.58, "Settings", self._open_settings),
            (0.67, "Resync", lambda _e: self._send_command("RESYNC DELTA")),
        ):
            button = Button(self.fig.add_axes([x, 0.895, 0.08, 0.045]), title)
            button.on_clicked(callback)
            self.extra_buttons.append(button)
        self.control_status = self.fig.text(0.02, 0.865, "Record x3: three separate captures. Stop cancels the remaining repeats.", fontsize=9, va="center", color="#2d7f4f")
        self.recording_time_status = self.fig.text(0.02, 0.838, "Record time: idle", fontsize=9, va="center")
        self.plan_box = TextBox(self.fig.add_axes([0.08, 0.78, 0.07, 0.04]), "Plan row: ", initial="1")
        for x, title, callback in (
            (0.16, "Use row", self._use_plan),
            (0.25, "Next", self._next_plan),
        ):
            button = Button(self.fig.add_axes([x, 0.78, 0.08, 0.04]), title)
            button.on_clicked(callback)
            self.extra_buttons.append(button)
        self.event_box = TextBox(self.fig.add_axes([0.43, 0.78, 0.36, 0.04]), "Event: ", initial="")
        marker_button = Button(self.fig.add_axes([0.80, 0.78, 0.08, 0.04]), "Mark")
        marker_button.on_clicked(self._mark_event)
        self.extra_buttons.append(marker_button)
        self.experiment_status = self.fig.text(0.02, 0.752, self.experiment.description(), fontsize=8.5, va="center")
        self.fig.text(0.78, 0.916, "Threshold 8 | SPI 10 MHz", fontsize=9, va="center")

    def _refresh_experiment(self) -> None:
        if hasattr(self, "experiment_status"):
            self.experiment_status.set_text(self.experiment.description())
            if not self.display_paused:
                self.fig.canvas.draw_idle()

    def _open_settings(self, _event=None) -> None:
        self._consume_pending()
        self.experiment.show()

    def _pause_display(self) -> None:
        self.display_paused = True
        if hasattr(self, "animation") and self.animation.event_source is not None:
            self.animation.event_source.stop()

    def _resume_display(self) -> None:
        self.display_paused = False
        if self.stop.is_set():
            return
        self.update(None, force_draw=True)
        if self.experiment.last_error:
            self.control_status.set_text(f"Settings not saved: {self.experiment.last_error}")
            self.control_status.set_color("#b00020")
            self.fig.canvas.draw_idle()
        if hasattr(self, "animation") and self.animation.event_source is not None:
            self.animation.event_source.start()

    def _close_gui(self, _event=None) -> None:
        self.stop.set()
        self.experiment.close_settings()

    def _use_plan(self, _event=None) -> None:
        if self.recording_active:
            self.control_status.set_text("Stop the current recording before changing plan row")
            return
        try:
            self.experiment.select_row(int(self.plan_box.text))
        except (ValueError, OSError) as exc:
            self.control_status.set_text(str(exc))
            self.control_status.set_color("#b00020")
            return
        self.rate_box.set_val(str(self.experiment.metadata["target_hz"]))
        self._send_command(f"SCAN_HZ {self.experiment.metadata['target_hz']}")
        self._send_command(f"MODE {self.experiment.metadata['target_mode']}")
        self.target_scan_hz = self.experiment.metadata["target_hz"]
        self.target_scan_hz_source = "experiment schedule SCAN_HZ command; not readback"
        self._refresh_experiment()

    def _next_plan(self, _event=None) -> None:
        if not self.recording_active:
            self.plan_box.set_val(str(self.experiment.row_index + 2))
            self._use_plan()

    def _mark_event(self, _event=None) -> None:
        if self.source != "demo":
            self.commands.put({"action": "MARK_EVENT", "text": self.event_box.text.strip() or "manual marker"})
            self.control_status.set_text("Event marker queued (PC timestamp)")
            self.fig.canvas.draw_idle()

    def _send_command(self, command: str) -> None:
        if self.source == "demo":
            self.control_status.set_text("Demo mode: no serial command")
            self.control_status.set_color("#a06a00")
            return
        if self.recording_active and command.startswith(("MODE ", "SCAN_HZ ")):
            self.control_status.set_text("Stop the three-repeat batch before changing mode or scan rate")
            self.control_status.set_color("#b00020")
            self.fig.canvas.draw_idle()
            return
        if command.startswith("MODE ") and not self.recording_active:
            self._requested_mode = command.split()[1]
            self.experiment.metadata["target_mode"] = self._requested_mode
            self._refresh_experiment()
        self.commands.put(command)
        self.control_status.set_text(f"Queued: {command}")
        self.control_status.set_color("#2d7f4f")
        self.fig.canvas.draw_idle()

    def _apply_scan_rate(self, _event=None) -> None:
        if self.recording_active:
            self.control_status.set_text("Stop the three-repeat batch before changing scan rate")
            return
        try:
            rate = int(self.rate_box.text.strip())
            if not 0 <= rate <= 1000:
                raise ValueError
        except ValueError:
            self.control_status.set_text("Scan Hz must be an integer 0..1000")
            self.control_status.set_color("#b00020")
            return
        self.target_scan_hz = rate
        self.target_scan_hz_source = "GUI SCAN_HZ command; not firmware readback"
        if not self.recording_active:
            self.experiment.metadata["target_hz"] = rate
        self._send_command(f"SCAN_HZ {rate}")

    def _start_recording(self, _event=None) -> None:
        if self.source == "demo":
            self.control_status.set_text("Demo mode: no recording")
            return
        if self.recording_active:
            return
        if self.display_paused:
            self.control_status.set_text("Close Settings before Record")
            return
        self._consume_pending()
        try:
            if self.serial_error:
                raise ValueError(self.serial_error)
            detected = require_ready(self.last_packet.detection if self.last_packet else None, time.monotonic())
            if self._requested_mode and detected["mode"] != self._requested_mode:
                raise ValueError(f"Waiting for modules to switch to {self._requested_mode}")
            self._requested_mode = None
            metadata = self.experiment.metadata
            if metadata.get("module_selection_source") == "automatic":
                metadata["target_modules"] = list(detected["modules"])
                metadata["target_mode"] = detected["mode"]
            metadata["target_hz"] = self.target_scan_hz
            metadata["target_hz_source"] = self.target_scan_hz_source
            metadata["module_detection_at_record"] = detected
            metadata["observed_mode_at_record"] = detected["mode"]
            metadata["observed_mul1_rate_at_record_Hz"] = self.last_packet.round_rate
            metadata["spi_setting_source"] = "local firmware configuration; not measured or read back"
            metadata["delta_threshold_source"] = "local firmware configuration; not measured or read back"
            metadata["module_identity_source"] = "CS/IRQ slot; protocol carries no unique board identity"
            config = self.experiment.make_config()
        except (ValueError, OSError) as exc:
            self.control_status.set_text(str(exc))
            self.control_status.set_color("#b00020")
            return
        # Capture the current stream without changing its mode or scan timing.
        self.commands.put({"action": "START_RECORDING", "config": config, "repeats": 3})
        self.recording_active = True
        self.recording_repeat_label = "1/3"
        self.record_button.label.set_text("Armed 1/3")
        self.control_status.set_text(
            f"Queued: 3 x {config.duration_seconds:g}s = {3 * config.duration_seconds:g}s; "
            f"each has {config.settle_seconds:g}s prefix; separate files")
        self.fig.canvas.draw_idle()

    def _handle_recording_status(self, event: RecordingStatus) -> None:
        self.control_status.set_text(event.message if len(event.message) <= 170 else event.message[:167] + "...")
        self.control_status.set_color("#b00020" if event.phase == "unavailable" else "#2d7f4f")
        self.recording_active = event.phase in ("armed", "recording", "between") or (self.recording_active and event.phase == "info")
        if event.message.startswith("Repeat "):
            self.recording_repeat_label = event.message.split(" | ", 1)[0].removeprefix("Repeat ")
        if event.phase in ("complete", "unavailable"):
            self.record_button.label.set_text("Record x3")
        elif event.phase == "recording":
            self.record_button.label.set_text(f"Rec {self.recording_repeat_label}")
        elif event.phase == "between":
            self.record_button.label.set_text("Next repeat")
        if event.elapsed_seconds is not None:
            self.recording_time_status.set_text(
                f"Repeat {self.recording_repeat_label} | recorded {event.elapsed_seconds:.2f}s | "
                f"remaining this repeat {(event.remaining_seconds or 0):.2f}s"
            )
        self.fig.canvas.draw_idle()

    def _consume_pending(self) -> bool:
        new_packet = False
        try:
            while True:
                self._handle_recording_status(
                    self.recording_events.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                event = self.packets.get_nowait()
                if isinstance(event, SerialError):
                    self.serial_error = event.message
                elif isinstance(event, RecordingStatus):
                    self._handle_recording_status(event)
                elif isinstance(event, ParserWarning):
                    self.parser_warning = event.message
                    if event.counters is not None:
                        self.parser_counters = event.counters
                    self.control_status.set_text(event.message)
                    self.control_status.set_color("#b06a00")
                else:
                    self.last_packet = event
                    if event.counters is not None:
                        self.parser_counters = event.counters
                    new_packet = True
        except queue.Empty:
            pass
        if new_packet and self.last_packet.detection:
            detected = self.last_packet.detection
            slots = '+'.join(f'M{m}' for m in detected['modules']) or 'waiting'
            self.experiment.auto_summary = (
                f"Detected slots: {slots} | mode: {detected['mode'] or 'waiting'} | "
                f"MUL1: {self.last_packet.round_rate:.1f} Hz | target: {self.target_scan_hz} Hz (control value)")
            if (not self.recording_active and
                    self.experiment.metadata.get('module_selection_source') == 'automatic'):
                self.experiment.metadata['target_modules'] = list(detected['modules'])
                if detected['mode']:
                    self.experiment.metadata['target_mode'] = detected['mode']
            if hasattr(self, 'experiment_status'):
                self.experiment_status.set_text(self.experiment.description())
        return new_packet

    def update(self, _frame, force_draw=False) -> None:
        if self.display_paused:
            return
        new_packet = self._consume_pending()
        if self.serial_error is not None:
            self.fig.suptitle(
                f"FSR-only monitor | ERROR: {self.serial_error}",
                fontsize=14, color="#ff7777")
            self.fig.canvas.draw_idle()
            return
        if self.last_packet is None or (not new_packet and not force_draw):
            self.integrity_status.set_text(
                f"Checks: {self.parser_counters.summary()}")
            return
        for module, state in enumerate(self.last_packet.states):
            self.collections[2 * module].set_array(
                oriented_fsr(state.fsr1).reshape(-1))
            self.collections[2 * module + 1].set_array(
                oriented_fsr(state.fsr2).reshape(-1))
        algorithms = {value for value in self.last_packet.algorithms if value}
        algorithm = "/".join(sorted(algorithms)) if algorithms else "waiting"
        rate = self.last_packet.usb_rate
        measured_rate = self.last_packet.round_rate
        active_modules = ",".join(
            str(module) for module in range(MODULE_COUNT)
            if self.last_packet.updated_mask & (1 << module))
        module_status = ", ".join(
            f"M{module}:{module_status_name(status)}"
            for module, status in enumerate(self.last_packet.statuses)
            if status != 0
        )
        target = "uncapped" if self.target_scan_hz == 0 else f"{self.target_scan_hz} Hz"
        self.live_status.set_text(
            f"Algorithm: {algorithm} | measured MUL1 rate: "
            f"{measured_rate:,.1f} Hz | target: {target} | "
            f"active modules: {active_modules or 'none'}" +
            (f" | {module_status}" if module_status else ""))
        errors = "; ".join(f"M{i}: {e}" for i, e in enumerate(self.last_packet.errors) if e)
        self.integrity_status.set_text(
            f"Session checks: {self.parser_counters.summary()}" + (f" | {errors}" if errors else ""))
        self.fig.suptitle(
            f"FSR-only monitor | algorithm={algorithm} | "
            f"measured USB={rate:,.1f} B/s ({rate * 8 / 1e6:.4f} Mbit/s) | "
            f"MUL1 seq={self.last_packet.sequence}", fontsize=14)
        self.fig.canvas.draw_idle()

    def show(self) -> None:
        try:
            plt.show()
        finally:
            self.stop.set()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--output-dir", type=Path, default=RECORD_DATA_DIR)
    parser.add_argument("--schedule", type=Path, default=DEFAULT_SCHEDULE)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    packets: queue.Queue = queue.Queue(maxsize=1)
    recording_events: queue.Queue = queue.Queue(maxsize=32)
    commands: queue.Queue = queue.Queue()
    stop = threading.Event()
    if args.demo:
        worker = threading.Thread(target=demo_worker, args=(packets, stop), daemon=True)
        source = "demo"
    else:
        worker = threading.Thread(target=serial_worker,
                                  args=(args.port, args.baud, packets, commands,
                                        recording_events, stop), daemon=True)
        source = args.port
    worker.start()
    FsrGui(packets, commands, recording_events, stop, source,
           output_dir=args.output_dir, schedule_path=args.schedule).show()
    worker.join(timeout=1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
