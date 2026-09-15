"""Four-module FSR-only monitor for the variable-length MUL1 stream."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import threading
import time
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
RECORD_SECONDS = 30.0
RECORDING_PROGRESS_INTERVAL = 0.5
PROJECT_ROOT = Path(__file__).resolve().parents[4]
RECORD_DATA_DIR = PROJECT_ROOT / "docs" / "Final" / "data scalability" / "data"


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
            f"seq gaps={self.sequence_gap_events} | lost={self.lost_frames} | "
            f"parse err={self.format_errors} | "
            f"Delta base={self.delta_base_mismatches}"
        )


@dataclass
class RecordingStatus:
    message: str
    phase: str = "info"
    elapsed_seconds: float | None = None
    remaining_seconds: float | None = None


class ExperimentRecorder:
    """Stores one automatic 30-second USB experiment run."""

    def __init__(self, port_name: str, baud: int,
                 selected_algorithm: str = "FULL",
                 target_scan_hz: int = 200,
                 duration_seconds: float = RECORD_SECONDS) -> None:
        self.port_name = port_name
        self.baud = baud
        self.selected_algorithm = selected_algorithm
        self.target_scan_hz = target_scan_hz
        self.duration_seconds = duration_seconds
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.started_at = datetime.now().astimezone()
        self.started_monotonic: float | None = None
        self.active = False
        self.finished = False
        self.start_error: str | None = None
        self.run_dir = RECORD_DATA_DIR / self.run_id
        self.raw_path = self.run_dir / "mul1_raw.bin"
        self.csv_path = self.run_dir / "packet_log.csv"
        self.summary_path = self.run_dir / "summary.json"
        self.log_path = self.run_dir / "experiment_log.md"
        self.raw_file = None
        self.csv_file = None
        self.csv_writer = None
        self.commands: list[str] = []
        self.observed_algorithms: set[str] = set()
        self.packet_rows = 0
        self.complete_mul_count = 0
        self.total_bytes = 0
        self.raw_offset = 0
        self.first_mul_time: datetime | None = None
        self.last_mul_time: datetime | None = None
        self.active_module_ids: set[int] = set()

    def start(self, started_at: datetime | None = None,
              started_monotonic: float | None = None) -> RecordingStatus:
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.raw_file = self.raw_path.open("wb")
            self.csv_file = self.csv_path.open("w", newline="", encoding="utf-8")
            self.csv_writer = csv.DictWriter(
                self.csv_file,
                fieldnames=(
                    "elapsed_s", "mul_start_time", "raw_offset", "packet_sequence", "declared_length",
                    "received_bytes", "outer_crc_ok", "parse_ok",
                    "updated_mask", "module_statuses", "algorithms", "error"),
            )
            self.csv_writer.writeheader()
            self.started_at = started_at or datetime.now().astimezone()
            self.started_monotonic = started_monotonic or time.monotonic()
            self.commands.append("START_RECORDING (GUI button)")
            self.active = True
            return RecordingStatus(
                f"Recording 30 s from next complete MUL1 | data: {self.raw_path.name} | "
                f"log: {self.log_path.name}",
                phase="recording",
                elapsed_seconds=0.0,
                remaining_seconds=self.duration_seconds,
            )
        except OSError as exc:
            self.start_error = str(exc)
            self._close_files()
            return RecordingStatus(f"Recording unavailable: {exc}",
                                   phase="unavailable")

    def note_command(self, command: str) -> None:
        if self.active:
            self.commands.append(command)

    def launch_delta_plot(self) -> bool:
        """Start the local plotter after a DELTA recording has been closed."""

        # Use the selected mode as a fallback as well as observed parsed
        # algorithms. This keeps plotting reliable when a recording contains
        # a transient parser/status row but still has a usable packet log.
        is_delta = (
            self.selected_algorithm == "DELTA" or
            any(value.startswith("DELTA") for value in self.observed_algorithms)
        )
        if not is_delta or not self.csv_path.is_file():
            return False
        plot_script = Path(__file__).with_name("plot_delta_mul_length.py")
        if not plot_script.is_file():
            return False

        log_path = self.run_dir / "plot_generation.log"
        try:
            log_handle = log_path.open("w", encoding="utf-8")
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                [
                    sys.executable,
                    str(plot_script),
                    "--input",
                    str(self.run_dir),
                ],
                cwd=str(plot_script.parent),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags if os.name == "nt" else 0,
            )
            log_handle.close()
        except OSError:
            try:
                log_handle.close()
            except (UnboundLocalError, AttributeError):
                pass
            return False
        return True

    def expired(self) -> bool:
        return (self.active and self.started_monotonic is not None and
                time.monotonic() - self.started_monotonic >= self.duration_seconds)

    def progress_status(self) -> RecordingStatus:
        elapsed = min(
            self.duration_seconds,
            max(0.0, time.monotonic() - (self.started_monotonic or time.monotonic())),
        )
        return RecordingStatus(
            f"Recording: {elapsed:.1f}/{self.duration_seconds:.0f} s elapsed | "
            f"{max(0.0, self.duration_seconds - elapsed):.1f} s remaining",
            phase="recording",
            elapsed_seconds=elapsed,
            remaining_seconds=max(0.0, self.duration_seconds - elapsed),
        )

    def record(self, data: bytes, packet: "MultiModulePacket | None",
               error: str | None = None,
               packet_started_at: datetime | None = None) -> None:
        if not self.active or self.started_monotonic is None:
            return
        elapsed = time.monotonic() - self.started_monotonic
        packet_started_at = packet_started_at or datetime.now().astimezone()
        if self.first_mul_time is None:
            self.first_mul_time = packet_started_at
        self.last_mul_time = packet_started_at
        raw_offset = self.raw_offset
        self.raw_file.write(data)
        self.total_bytes += len(data)
        self.raw_offset += len(data)
        sequence = (read_u32(data, 12)
                    if len(data) >= 16 and data[:4] == MUL_MAGIC else None)
        declared = read_u16(data, 8) if len(data) >= 10 else None
        outer_ok = len(data) >= 24 and crc_ok(data)
        if (len(data) >= DIAGNOSTIC_PREFIX_BYTES + 4 and
                data[:4] == MUL_MAGIC and declared == len(data) and outer_ok):
            self.complete_mul_count += 1
        updated_mask = ""
        statuses = ""
        algorithms = ""
        if packet is not None:
            updated_mask = f"0x{packet.updated_mask:02X}"
            self.active_module_ids.update(
                module_id for module_id in range(MODULE_COUNT)
                if packet.updated_mask & (1 << module_id)
            )
            statuses = ",".join(module_status_name(value)
                                for value in packet.statuses)
            algorithms = ",".join(value or "NONE"
                                   for value in packet.algorithms)
            self.observed_algorithms.update(
                value for value in packet.algorithms if value)
        self.csv_writer.writerow({
            "elapsed_s": f"{elapsed:.6f}",
            "mul_start_time": packet_started_at.isoformat(timespec="milliseconds"),
            "raw_offset": raw_offset,
            "packet_sequence": "" if sequence is None else sequence,
            "declared_length": "" if declared is None else declared,
            "received_bytes": len(data),
            "outer_crc_ok": outer_ok,
            "parse_ok": packet is not None,
            "updated_mask": updated_mask,
            "module_statuses": statuses,
            "algorithms": algorithms,
            "error": error or "",
        })
        self.csv_file.flush()
        self.raw_file.flush()
        self.packet_rows += 1

    def _close_files(self) -> None:
        if self.csv_file is not None:
            self.csv_file.close()
        if self.raw_file is not None:
            self.raw_file.close()
        self.csv_file = None
        self.raw_file = None

    def finish(self, counters: ParserCounters, reason: str) -> RecordingStatus | None:
        if not self.active or self.started_monotonic is None:
            return None
        elapsed = time.monotonic() - self.started_monotonic
        snapshot = counters.snapshot()
        average_usb_rate = self.total_bytes / elapsed if elapsed > 0 else 0.0
        average_packet_rate = (self.packet_rows / elapsed
                               if elapsed > 0 else 0.0)
        self._close_files()
        self.active = False
        self.finished = True
        passed = (snapshot.candidate_packets > 0 and
                  snapshot.outer_crc_errors == 0 and
                  snapshot.inner_crc_errors == 0 and
                  snapshot.sequence_gap_events == 0 and
                  snapshot.lost_frames == 0 and
                  snapshot.duplicate_frames == 0 and
                  snapshot.out_of_order_frames == 0 and
                  snapshot.format_errors == 0 and
                  snapshot.delta_base_mismatches == 0)
        result = "PASS: no recorded transport/parser/cache error" if passed else \
            "CHECK REQUIRED: one or more transport/parser/cache counters are non-zero"
        active_module_ids = [f"M{module_id}"
                             for module_id in sorted(self.active_module_ids)]
        observed_algorithm = next(
            (value for value in sorted(self.observed_algorithms)
             if value.startswith("DELTA")),
            next(
                (value for value in sorted(self.observed_algorithms)
                 if value in ("FULL", "SPATIAL")),
                self.selected_algorithm,
            ),
        )
        if observed_algorithm == "DELTA_SYNC":
            observed_algorithm = "DELTA"
        test_condition = {
            "algorithm": observed_algorithm,
            "requested_algorithm": self.selected_algorithm,
            "target_scan_rate_hz": self.target_scan_hz,
            "scan_rate_hz": self.target_scan_hz,
            "active_module_ids": active_module_ids,
            "module_count": len(active_module_ids),
            "module_scope": (
                "no active modules" if not active_module_ids else
                f"{len(active_module_ids)} module(s)"
            ),
        }
        summary = {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "duration_seconds": elapsed,
            "requested_duration_seconds": self.duration_seconds,
            "reason": reason,
            "port": self.port_name,
            "baud": self.baud,
            "test_condition": test_condition,
            "commands": self.commands,
            "observed_algorithms": sorted(self.observed_algorithms),
            "recorded_candidate_rows": self.packet_rows,
            "complete_mul_count": self.complete_mul_count,
            "recorded_bytes": self.total_bytes,
            "first_mul_start_time": (self.first_mul_time.isoformat(timespec="milliseconds")
                                      if self.first_mul_time else None),
            "last_mul_start_time": (self.last_mul_time.isoformat(timespec="milliseconds")
                                     if self.last_mul_time else None),
            "average_usb_rate_Bps": average_usb_rate,
            "average_usb_rate_Mbitps": average_usb_rate * 8.0 / 1e6,
            "average_packet_rate_Hz": average_packet_rate,
            "result": result,
            "counters": snapshot.__dict__,
            "files": {
                "raw_usb": str(self.raw_path),
                "packet_log": str(self.csv_path),
                "summary": str(self.summary_path),
                "experiment_log": str(self.log_path),
            },
        }
        self.summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        log = "\n".join([
            f"# Data Scalability Experiment {self.run_id}",
            "",
            "## 记录内容",
            "",
            f"- 端口：`{self.port_name}`；波特率：`{self.baud}`。",
            f"- 活动模块：{', '.join(active_module_ids) or '无'}。",
            f"- 模块数量 N：{len(active_module_ids)}。",
            f"- 目标扫描频率：{'不限速' if self.target_scan_hz == 0 else f'{self.target_scan_hz} Hz'}。",
            f"- 记录开始时选择的算法：`{self.selected_algorithm}`；实际观测算法见下方。",
            f"- 本次记录时长：{elapsed:.2f} s（目标 {self.duration_seconds:.0f} s）。",
            "- 记录 USB 接收到的原始 MUL1 字节流。",
            "- 从按钮触发后的下一个完整 MUL1 开始计时；记录每个候选 MUL1 包的开始时间、原始数据偏移、序号、长度、CRC、解析结果、模块状态和算法。",
            (f"- 首个 MUL1 开始时间：{self.first_mul_time.isoformat(timespec='milliseconds')}。"
             if self.first_mul_time else "- 未收到完整 MUL1 包。"),
            f"- 观测到的算法：{', '.join(sorted(self.observed_algorithms)) or '无有效数据'}。",
            "",
            "## 结果",
            "",
            f"- 结论：**{result}**",
            f"- 候选包：{snapshot.candidate_packets}；有效包：{snapshot.valid_packets}。",
            f"- 完整 MUL1 数量：{self.complete_mul_count}。",
            f"- 记录字节：{self.total_bytes} B；平均 USB 数据率：{average_usb_rate:.2f} B/s "
            f"({average_usb_rate * 8.0 / 1e6:.6f} Mbit/s)；平均候选包率：{average_packet_rate:.2f} Hz。",
            f"- CRC 错误：外层 {snapshot.outer_crc_errors}，内层 {snapshot.inner_crc_errors}。",
            f"- 序号间断：{snapshot.sequence_gap_events}；推断丢帧：{snapshot.lost_frames}。",
            f"- 重复帧：{snapshot.duplicate_frames}；乱序帧：{snapshot.out_of_order_frames}。",
            f"- 协议格式错误：{snapshot.format_errors}；Delta 基础序号失配：{snapshot.delta_base_mismatches}。",
            "",
            "## 输出文件",
            "",
            f"- 原始数据：`{self.raw_path}`",
            f"- 逐包记录：`{self.csv_path}`",
            f"- 机器可读总结：`{self.summary_path}`",
        ])
        self.log_path.write_text(log + "\n", encoding="utf-8")
        plot_started = self.launch_delta_plot()
        plot_message = " | plot started" if plot_started else ""
        return RecordingStatus(
            f"Recording complete: {result} | complete MUL1={self.complete_mul_count} | "
            f"log={self.log_path.name}{plot_message}",
            phase="complete",
            elapsed_seconds=elapsed,
            remaining_seconds=0.0,
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
                  fontsize=5, color="0.75")
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
    """Reconstructs one module's FSR matrices from FULL/DELTA/SPATIAL frames."""

    def __init__(self) -> None:
        self.fsr1 = np.zeros((ROWS, COLS), dtype=np.uint16)
        self.fsr2 = np.zeros((ROWS, COLS), dtype=np.uint16)
        self.last_sequence: int | None = None
        self.delta_valid = False
        self.spatial_valid = False
        self.last_frame_type = "NONE"
        self.last_spatial_count = 0

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
        self.spatial_valid = other.spatial_valid
        self.last_frame_type = other.last_frame_type
        self.last_spatial_count = other.last_spatial_count

    def clone(self) -> "ProtocolState":
        clone = ProtocolState()
        clone.copy_from(self)
        return clone

    def apply(self, data: bytes) -> str:
        kind = marker(data)
        if kind in (b"ESKF", b"ESKD"):
            return self._apply_esk(data, kind)
        if kind in (b"ESPF", b"ESPD", b"ESP0"):
            return self._apply_esp(data, kind)
        raise ValueError(f"unknown inner marker {kind!r}")

    def _apply_esk(self, data: bytes, kind: bytes) -> str:
        if (len(data) < 22 or data[4] != ESK_PROTOCOL_VERSION or
                read_u16(data, 6) != len(data)):
            raise ValueError("invalid ESK header")
        if not crc_ok(data):
            raise ValueError("inner ESK CRC32 mismatch")
        sequence = read_u32(data, 8)
        if kind == b"ESKF":
            if len(data) != HOST_SLOT_BYTES:
                raise ValueError("invalid ESKF length")
            flags = data[5]
            values = np.frombuffer(data, dtype="<u2", count=ROWS * COLS,
                                   offset=16).reshape((ROWS, COLS))
            self.fsr1[:, :] = values & 0x0FFF
            values = np.frombuffer(data, dtype="<u2", count=ROWS * COLS,
                                   offset=528).reshape((ROWS, COLS))
            self.fsr2[:, :] = values & 0x0FFF
            self.delta_valid = True
            self.spatial_valid = bool(flags & 0x40)
            self.last_sequence = sequence
            if flags & 0x40:
                self.last_frame_type = "ESKF"
                self.last_spatial_count = ROWS * COLS
                return "SPATIAL_FALLBACK"
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
        self.last_spatial_count = 0
        return "DELTA"

    def _apply_esp(self, data: bytes, kind: bytes) -> str:
        sequence = read_u32(data, 8)
        if kind == b"ESP0":
            if len(data) != 12:
                raise ValueError("invalid ESP0 heartbeat")
            if (not self.spatial_valid or self.last_sequence is None or
                    sequence != self.last_sequence + 1):
                self.spatial_valid = False
                raise ValueError("Spatial heartbeat sequence does not match cache")
            self.spatial_valid = True
            self.last_sequence = sequence
            self.last_frame_type = "ESP0"
            self.last_spatial_count = 0
            return "SPATIAL"
        if len(data) < 46:
            raise ValueError("short ESP frame")
        count = read_u16(data, 44)
        if len(data) != 46 + 4 * count:
            raise ValueError("invalid ESP length")
        mask = data[12:44]
        self.last_frame_type = kind.decode("ascii")
        self.last_spatial_count = count
        if kind == b"ESPF":
            self.fsr1.fill(0)
            self.fsr2.fill(0)
            offset = 46
            for position in range(ROWS * COLS):
                if mask[position // 8] & (1 << (position % 8)):
                    if offset + 4 > len(data):
                        raise ValueError("ESP mask/value mismatch")
                    row, column = divmod(position, COLS)
                    self.fsr1[row, column] = read_u16(data, offset) & 0x0FFF
                    self.fsr2[row, column] = read_u16(data, offset + 2) & 0x0FFF
                    offset += 4
            if offset != len(data):
                raise ValueError("ESP sampled count mismatch")
            self.spatial_valid = True
        else:
            if not self.spatial_valid:
                raise ValueError("Spatial delta received without a spatial base")
            if (self.last_sequence is None or
                    sequence != self.last_sequence + 1):
                self.spatial_valid = False
                raise ValueError("Spatial delta sequence does not match cache")
            offset = 46
            for _ in range(count):
                address, col, value = data[offset], data[offset + 1], read_u16(data, offset + 2)
                self._set_cell((address >> 7) & 1, address & 0x7F, col, value)
                offset += 4
        self.last_sequence = sequence
        return "SPATIAL"


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
                       round_rate: float = 0.0) -> MultiModulePacket:
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
            if parser_error is None:
                parser_error = f"module {module_id}: {exc}"
        offset += payload_len
    if offset != end:
        raise ValueError("trailing MUL1 bytes")
    for state, working in zip(states, working_states):
        state.copy_from(working)
    if parser_error is not None:
        raise ValueError(parser_error)
    return MultiModulePacket(read_u32(data, 12), read_u32(data, 16), data[6],
                             tuple(states), tuple(algorithms), tuple(statuses),
                             len(data), usb_rate, round_rate)


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


def make_spatial_full(sequence: int, positions: list[int]) -> bytes:
    frame = bytearray(46 + 4 * len(positions))
    frame[:4] = b"ESPF"
    struct.pack_into("<II", frame, 4, 1234, sequence)
    mask = bytearray(32)
    for position in positions:
        mask[position // 8] |= 1 << (position % 8)
    frame[12:44] = mask
    struct.pack_into("<H", frame, 44, len(positions))
    offset = 46
    for position in positions:
        struct.pack_into("<HH", frame, offset, position + 100,
                         position + 200)
        offset += 4
    return bytes(frame)


def make_spatial_delta(sequence: int, positions: list[int]) -> bytes:
    frame = bytearray(46 + 4 * len(positions))
    frame[:4] = b"ESPD"
    struct.pack_into("<II", frame, 4, 1234, sequence)
    mask = bytearray(32)
    for position in positions:
        mask[position // 8] |= 1 << (position % 8)
    frame[12:44] = mask
    struct.pack_into("<H", frame, 44, len(positions))
    offset = 46
    for position in positions:
        row, col = divmod(position, COLS)
        frame[offset:offset + 2] = bytes((row, col))
        struct.pack_into("<H", frame, offset + 2, position + 300)
        offset += 4
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
    spatial_states = [ProtocolState() for _ in range(MODULE_COUNT)]
    sentinels = (1, 4, 6, 9, 11, 14)
    sentinel_positions = [
        row * COLS + column
        for row in range(ROWS)
        for column in range(COLS)
        if row in sentinels or column in sentinels
    ]
    spatial = make_spatial_full(20, sentinel_positions)
    parsed = parse_multi_packet(make_packet([spatial] * MODULE_COUNT, 3),
                                spatial_states)
    assert parsed.algorithms == ("SPATIAL",) * MODULE_COUNT
    assert int(spatial_states[0].fsr1[1, 4]) == 120
    assert int(spatial_states[0].fsr2[1, 4]) == 220
    assert spatial_states[0].last_frame_type == "ESPF"
    assert spatial_states[0].last_spatial_count == 156
    spatial_delta = make_spatial_delta(21, [4])
    parsed = parse_multi_packet(
        make_packet([spatial_delta] + [spatial] * 3, 6), spatial_states)
    assert parsed.algorithms[0] == "SPATIAL"
    try:
        parse_multi_packet(
            make_packet([make_spatial_delta(23, [4])] + [spatial] * 3, 7),
            spatial_states)
    except ValueError:
        pass
    else:
        raise AssertionError("Spatial sequence gap was not rejected")
    spatial_resync = make_spatial_full(24, sentinel_positions)
    parsed = parse_multi_packet(
        make_packet([spatial_resync] + [spatial] * 3, 8), spatial_states)
    assert parsed.algorithms[0] == "SPATIAL"
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
    window_start = time.monotonic()
    window_bytes = 0
    window_packets = 0
    last_usb_rate = 0.0
    last_round_rate = 0.0
    last_parse_warning = 0.0
    counters = ParserCounters()
    recorder: ExperimentRecorder | None = None
    recording_requested = False
    selected_algorithm = "FULL"
    target_scan_hz = 200
    last_recording_progress = 0.0
    last_resync_request = {"DELTA": 0.0, "SPATIAL": 0.0}
    try:
        port = serial.Serial(port_name, baudrate=baud, timeout=0.25)
    except serial.SerialException as exc:
        publish_serial_error(packets, f"Could not open {port_name}: {exc}")
        return
    with port:
        while not stop.is_set():
            if recorder is not None and recorder.expired():
                result = recorder.finish(counters, "30-second capture complete")
                if result is not None:
                    publish_recording_status(recording_events, result)
            elif (recorder is not None and recorder.active and
                  time.monotonic() - last_recording_progress >=
                  RECORDING_PROGRESS_INTERVAL):
                publish_recording_status(recording_events,
                                         recorder.progress_status())
                last_recording_progress = time.monotonic()
            while True:
                try:
                    command = commands.get_nowait()
                except queue.Empty:
                    break
                if command == "START_RECORDING":
                    if recorder is not None and recorder.active:
                        publish_recording_status(
                            recording_events, "Recording already active")
                    elif recording_requested:
                        publish_recording_status(
                            recording_events, "Recording already armed")
                    else:
                        recording_requested = True
                        publish_recording_status(
                            recording_events,
                            RecordingStatus(
                                "Recording armed: next complete MUL1 | 30 s",
                                phase="armed"))
                    continue
                if command.startswith("MODE "):
                    requested_algorithm = command[5:].strip().upper()
                    if requested_algorithm in ("FULL", "DELTA", "SPATIAL"):
                        selected_algorithm = requested_algorithm
                elif command.startswith("SCAN_HZ "):
                    try:
                        target_scan_hz = max(0, min(1000, int(command[9:].strip())))
                    except ValueError:
                        pass
                if recorder is not None:
                    recorder.note_command(command)
                port.write((command + "\n").encode("ascii"))
                port.flush()
            data: bytes | None = None
            packet_started_at = datetime.now().astimezone()
            packet_started_monotonic = time.monotonic()
            try:
                data = read_packet(port)
                now = time.monotonic()
                counters.candidate_packets += 1
                if (len(data) >= 20 and data[:4] == MUL_MAGIC and
                        data[4] == MUL_VERSION):
                    counters.observe_sequence(read_u32(data, 12))
                    if not crc_ok(data):
                        counters.outer_crc_errors += 1
                window_bytes += len(data)
                window_packets += 1
                elapsed = now - window_start
                if elapsed >= RATE_WINDOW_SECONDS:
                    last_usb_rate = window_bytes / elapsed
                    last_round_rate = window_packets / elapsed
                    window_start = now
                    window_bytes = 0
                    window_packets = 0
                if recording_requested:
                    recorder = ExperimentRecorder(
                        port_name,
                        baud,
                        selected_algorithm=selected_algorithm,
                        target_scan_hz=target_scan_hz,
                    )
                    publish_recording_status(
                        recording_events,
                        recorder.start(packet_started_at,
                                       packet_started_monotonic))
                    last_recording_progress = packet_started_monotonic
                    recording_requested = False
                packet = parse_multi_packet(data, states, last_usb_rate,
                                            last_round_rate)
                counters.valid_packets += 1
                packet.counters = counters.snapshot()
                if recorder is not None:
                    recorder.record(data, packet,
                                    packet_started_at=packet_started_at)
            except serial.SerialException as exc:
                if recorder is not None:
                    result = recorder.finish(counters, "serial port disconnected")
                    if result is not None:
                        publish_recording_status(recording_events, result)
                publish_serial_error(packets, f"Serial {port_name} disconnected: {exc}")
                return
            except (TimeoutError, ValueError) as exc:
                if isinstance(exc, ValueError):
                    error_text = str(exc)
                    if "inner ESK CRC32 mismatch" in error_text:
                        counters.inner_crc_errors += 1
                    elif "Delta base sequence" in error_text:
                        counters.delta_base_mismatches += 1
                    elif "MUL1 CRC32 mismatch" not in error_text:
                        counters.format_errors += 1
                    resync_mode = None
                    if "Delta" in error_text:
                        resync_mode = "DELTA"
                    elif "Spatial" in error_text:
                        resync_mode = "SPATIAL"
                    if (resync_mode is not None and
                            time.monotonic() - last_resync_request[resync_mode] >= 0.25):
                        commands.put(f"RESYNC {resync_mode}")
                        last_resync_request[resync_mode] = time.monotonic()
                    warning_time = time.monotonic()
                    if warning_time - last_parse_warning >= 1.0:
                        publish_parser_warning(
                            packets,
                            f"Parser rejected frame: {exc} | "
                            f"{counters.summary()}", counters)
                        last_parse_warning = warning_time
                if data is not None and recorder is not None:
                    recorder.record(data, None, str(exc), packet_started_at)
                continue
            if recorder is not None and recorder.expired():
                result = recorder.finish(counters, "30-second capture complete")
                if result is not None:
                    publish_recording_status(recording_events, result)
            try:
                packets.put_nowait(packet)
            except queue.Full:
                try:
                    packets.get_nowait()
                except queue.Empty:
                    pass
                packets.put_nowait(packet)
        if recorder is not None:
            result = recorder.finish(counters, "monitor stopped before 30 seconds")
            if result is not None:
                publish_recording_status(recording_events, result)


def demo_worker(packets: queue.Queue, stop: threading.Event) -> None:
    states = [ProtocolState() for _ in range(MODULE_COUNT)]
    sequence = 1
    while not stop.is_set():
        frames = [make_full_frame(sequence, 100 * m + sequence) for m in range(MODULE_COUNT)]
        packet = parse_multi_packet(make_packet(frames, sequence), states,
                                    0.0)
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
                 source: str) -> None:
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
        self.fig, axes = plt.subplots(2, MODULE_COUNT, figsize=(14, 7),
                                      constrained_layout=False)
        self.fig.subplots_adjust(left=0.02, right=0.98, bottom=0.04,
                                 top=0.77, wspace=0.08, hspace=0.16)
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
            0.02, 0.825,
            "Algorithm: waiting | measured MUL1 rate: -- Hz | target: 200 Hz",
            fontsize=10, va="center", color="#1f5f9e")
        self.integrity_status = self.fig.text(
            0.02, 0.795,
            "Checks: CRC err=0 | seq gaps=0 | lost=0 | parse err=0 | Delta base=0",
            fontsize=8.5, va="center", color="#555555")
        self.fig.suptitle(f"FSR-only monitor | {source}", fontsize=14)
        self.animation = FuncAnimation(self.fig, self.update, interval=100,
                                       cache_frame_data=False)

    def _add_controls(self) -> None:
        self.fig.text(0.02, 0.925, "Mode:", fontsize=10, va="center")
        for index, mode in enumerate(("FULL", "DELTA", "SPATIAL")):
            axis = self.fig.add_axes([0.065 + index * 0.07, 0.895, 0.06, 0.05])
            button = Button(axis, mode)
            button.on_clicked(lambda _event, value=mode:
                              self._send_command(f"MODE {value}"))
            self.mode_buttons.append(button)

        rate_axis = self.fig.add_axes([0.31, 0.895, 0.13, 0.05])
        self.rate_box = TextBox(rate_axis, "Scan Hz: ", initial="200")
        apply_axis = self.fig.add_axes([0.45, 0.895, 0.08, 0.05])
        self.apply_button = Button(apply_axis, "Apply")
        self.apply_button.on_clicked(self._apply_scan_rate)
        record_axis = self.fig.add_axes([0.54, 0.895, 0.10, 0.05])
        self.record_button = Button(record_axis, "Save 30 s")
        self.record_button.on_clicked(self._start_recording)
        self.control_status = self.fig.text(0.66, 0.925, "Ready",
                                             fontsize=10, va="center",
                                             color="#2d7f4f")
        self.recording_time_status = self.fig.text(
            0.66, 0.895, "Record time: idle", fontsize=8.5, va="center",
            color="#555555")

    def _send_command(self, command: str) -> None:
        if self.source == "demo":
            self.control_status.set_text("Demo mode: no serial command")
            self.control_status.set_color("#a06a00")
            return
        self.commands.put(command)
        status = f"Queued: {command}"
        if command.startswith("MODE "):
            status += " | 1 s coordinated switch"
        self.control_status.set_text(status)
        self.control_status.set_color("#2d7f4f")
        self.fig.canvas.draw_idle()

    def _apply_scan_rate(self, _event) -> None:
        try:
            scan_hz = int(self.rate_box.text.strip())
        except ValueError:
            self.control_status.set_text("Scan Hz must be an integer 0-1000")
            self.control_status.set_color("#b00020")
            self.fig.canvas.draw_idle()
            return
        if not 0 <= scan_hz <= 1000:
            self.control_status.set_text("Scan Hz must be in range 0-1000")
            self.control_status.set_color("#b00020")
            self.fig.canvas.draw_idle()
            return
        self._send_command(f"SCAN_HZ {scan_hz}")
        self.target_scan_hz = scan_hz

    def _start_recording(self, _event) -> None:
        if self.source == "demo":
            self.control_status.set_text("Demo mode: no recording")
            self.control_status.set_color("#a06a00")
            self.fig.canvas.draw_idle()
            return
        self.commands.put("START_RECORDING")
        if self.record_button is not None:
            self.record_button.label.set_text("Armed")
        self.control_status.set_text("Armed: next complete MUL1 | 30 s")
        self.control_status.set_color("#2d7f4f")
        self.fig.canvas.draw_idle()

    def _handle_recording_status(self, event: RecordingStatus) -> None:
        self.control_status.set_text(event.message)
        self.control_status.set_color("#2d7f4f" if
                                      event.phase != "unavailable" else
                                      "#b00020")
        if self.record_button is not None:
            if event.phase in ("complete", "unavailable"):
                self.record_button.label.set_text("Save 30 s")
            elif event.phase == "armed":
                self.record_button.label.set_text("Armed")
            elif event.phase == "recording":
                self.record_button.label.set_text("Recording")
        if self.recording_time_status is None:
            return
        if event.phase == "armed":
            self.recording_time_status.set_text(
                "Record time: waiting for next complete MUL1")
        elif event.phase == "recording" and event.elapsed_seconds is not None:
            remaining = event.remaining_seconds or 0.0
            self.recording_time_status.set_text(
                f"Record time: {event.elapsed_seconds:.1f}/30.0 s elapsed | "
                f"{remaining:.1f} s remaining")
        elif event.phase == "complete" and event.elapsed_seconds is not None:
            self.recording_time_status.set_text(
                f"Record time: complete | {event.elapsed_seconds:.2f} s recorded")
        elif event.phase == "unavailable":
            self.recording_time_status.set_text("Record time: unavailable")

    def update(self, _frame) -> None:
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
        if self.serial_error is not None:
            self.fig.suptitle(
                f"FSR-only monitor | ERROR: {self.serial_error}",
                fontsize=14, color="#ff7777")
            self.fig.canvas.draw_idle()
            return
        if self.last_packet is None or not new_packet:
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
        spatial_details = []
        if any(value and value.startswith("SPATIAL")
               for value in self.last_packet.algorithms):
            for module, state in enumerate(self.last_packet.states):
                if state.last_frame_type in ("ESP0", "ESPD", "ESPF", "ESKF"):
                    count_label = (f"K={state.last_spatial_count}" if
                                   state.last_frame_type == "ESPD" else
                                   f"S={state.last_spatial_count}")
                    spatial_details.append(
                        f"M{module}:{state.last_frame_type},"
                        f"{count_label}")
        rate = self.last_packet.usb_rate
        measured_rate = self.last_packet.round_rate
        active_modules = ",".join(
            str(module) for module in range(MODULE_COUNT)
            if self.last_packet.updated_mask & (1 << module))
        active_module_count = sum(
            1 for module in range(MODULE_COUNT)
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
            f"active modules: {active_modules or 'none'} (N={active_module_count})" +
            (f" | {module_status}" if module_status else "") +
            (f" | {'; '.join(spatial_details)}" if spatial_details else ""))
        self.integrity_status.set_text(
            f"Checks: {self.parser_counters.summary()}")
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
    FsrGui(packets, commands, recording_events, stop, source).show()
    worker.join(timeout=1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
