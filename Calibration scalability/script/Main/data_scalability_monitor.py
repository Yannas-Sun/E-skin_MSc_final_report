"""Monitor and parser for the active data-scalability STM32/Teensy stream.

Supported logical frames:
  ESKF / ESKD / ESK0  - Full and Delta ESK frames
  ESPF / ESPD / ESP0  - Spatial Sparse frames

The active firmware wraps up to four module payloads in one variable-length
MUL1 v2 USB packet. Each module uses the v4 FSR-only ESK protocol with a
1044-byte FULL frame, mask-based DELTA frames, or the compact SPATIAL format.
The parser keeps a separate cache for every module before handing frames to
the existing calibration and visualization functions.
"""

from __future__ import annotations

import argparse
import csv
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import importlib.util
from threading import Lock
import json
import queue
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable
import zlib

import numpy as np

from Utility.portable_paths import portable_path


ROWS = 16
COLS = 16
MODULE_COUNT = 4
FSR_CELLS = ROWS * COLS
HOST_SLOT_BYTES = 1188
ACTIVE_HOST_SLOT_BYTES = 1044
MUL1_HEADER_BYTES = 20
MUL1_TRAILER_BYTES = 4
MUL1_MIN_BYTES = MUL1_HEADER_BYTES + MUL1_TRAILER_BYTES
MUL1_MAX_BYTES = MUL1_HEADER_BYTES + MODULE_COUNT * (4 + ACTIVE_HOST_SLOT_BYTES) + MUL1_TRAILER_BYTES
MUL1_MAGIC = b"MUL1"
MUL1_VERSION = 2
DIAGNOSTIC_PREFIX_BYTES = 16
ACTIVE_ESK_VERSION = 4
LEGACY_ESK_VERSION = 2
ESK_HEADER_BYTES = 16
ESK_TRAILER_BYTES = 4
SPATIAL_PREFIX_BYTES = 142
ACTIVE_SPATIAL_PREFIX_BYTES = 46
SPATIAL_HEARTBEAT_BYTES = 12
ACC_RECORD_BYTES = 16
ACC_COUNT = 9
ACC_STRUCT = struct.Struct("<BBhhhBBHBB")
KNOWN_MARKERS = (MUL1_MAGIC, b"ESKF", b"ESKD", b"ESK0", b"ESPF", b"ESPD", b"ESP0")
CRC_FLAG = 0x10
DELTA_FLAG = 0x20
SPATIAL_FLAG = 0x40
ADC_MAX = 4095
# Nonlinear calibrated display curve.  gamma > 1 compresses low load and
# expands the response near the calibrated full-load endpoint.
CALIBRATION_GAMMA = 4.0
PRESSURE_ANALYSIS_SCRIPT = "plot_pressure_calibration_monotonic.py"
VIEW_DISTRIBUTION_SCRIPT = "analyze_view_distributions.py"
CALIBRATION_LOAD_UNIT = "g"
AVERAGE_CAPTURE_SECONDS = 1.0
NORMALIZED_CALIBRATION_FRAME_COUNT = 200
NORMALIZED_MIN_RESPONSE_SPAN = 50.0
NORMALIZED_MAX_NOISE_RANGE = 50.0
NORMALIZED_SATURATION_CODE = 4090
NEWTONS_PER_GRAM = 0.00980665
VIEW_LABELS = ("All", "FSR1", "FSR2", "ACC")
MODULE_LABELS = ("M0", "M1", "M2", "M3")
NORMALIZED_CORNER_LABELS = (
    "upper-left",
    "upper-right",
    "right",
    "lower-right",
    "lower-left",
    "left",
)
ACC_POSITIONS = (
    (2, 2), (2, 1), (2, 0),
    (1, 2), (1, 1), (1, 0),
    (0, 2), (0, 1), (0, 0),
)


class ProtocolError(ValueError):
    """A malformed frame or a frame that cannot be applied to the cache."""


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
class DecodedFrame:
    marker: str
    family: str
    sequence: int
    base_sequence: int | None
    fsr1: np.ndarray
    fsr2: np.ndarray
    acc: tuple[AccSample, ...]
    changed_count: int = 0
    sampled_count: int = 0
    cache_valid: bool = True
    note: str = ""
    flags: int = 0
    module_id: int | None = None
    packet_sequence: int | None = None
    packet_length: int | None = None
    module_status: int = 0


def save_matrix_csv(path: Path, matrix: np.ndarray, *, layer: str) -> None:
    """Write the displayed FSR values as a labelled 16x16 CSV matrix."""
    if matrix.shape != (ROWS, COLS):
        raise ValueError(f"{layer} matrix shape is {matrix.shape}, expected {(ROWS, COLS)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([layer] + [f"C{COLS - column}" for column in range(COLS)])
        for row in range(ROWS):
            values = []
            for value in matrix[row]:
                if isinstance(value, np.floating):
                    values.append(f"{float(value):.6f}")
                else:
                    values.append(str(int(value)))
            writer.writerow([f"R{row + 1}"] + values)


def fsr_data_directory(output_root: Path, module_id: int, fsr_name: str) -> Path:
    return output_root / "DATA" / f"module_{module_id}" / fsr_name


def save_pressure_sweep(
    output_root: Path,
    *,
    module_id: int,
    fsr_name: str,
    port_name: str,
    baud: int,
    pressure_unit: str,
    started_at: str,
    points: list[dict[str, object]],
    protocol_errors: int,
) -> Path:
    """Save all pressure-labelled full-matrix samples from one GUI session."""
    if not points:
        raise ValueError("no pressure points were recorded")
    for point in points:
        matrix = np.asarray(point.get("raw_adc"), dtype=np.uint16)
        if matrix.shape != (ROWS, COLS):
            raise ValueError(
                f"pressure point matrix shape is {matrix.shape}, "
                f"expected {(ROWS, COLS)}"
            )

    data = {
        "format": "e-skin-fsr-pressure-response-sweep",
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "module_id": module_id,
        "fsr": fsr_name,
        "matrix": {"rows": ROWS, "columns": COLS},
        "response": {
            "type": "raw_adc_code",
            "adc_bits": 12,
            "maximum_code": ADC_MAX,
        },
        "pressure": {
            "unit": pressure_unit,
            "meaning": "operator-entered value; keep the unit consistent",
        },
        "source": {
            "port": port_name,
            "baud": baud,
            "protocol_errors": protocol_errors,
            "points": len(points),
        },
        "points": points,
    }
    raw_dir = fsr_data_directory(output_root, module_id, fsr_name) / "fit" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    path = raw_dir / f"{fsr_name}_pressure_sweep_{stamp}.json"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def save_normalized_calibration(
    output_root: Path,
    *,
    module_id: int,
    fsr_name: str,
    port_name: str,
    baud: int,
    zero_frames: list[np.ndarray],
    corner_frames: dict[str, list[np.ndarray]],
    protocol_errors: int,
    spatial_frames: int,
) -> tuple[Path, int]:
    """Build and save the same two-point JSON used by calibrate_fsr.py."""
    script_path = output_root / "script" / "Main" / "Calibration" / "calibrate_fsr.py"
    spec = importlib.util.spec_from_file_location(
        "e_skin_calibrate_fsr_helpers", script_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load normalisation helper: {script_path}")
    module = sys.modules.get(spec.name)
    if module is None:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    data = module.build_calibration(
        module_id=module_id,
        fsr_name=fsr_name,
        port_name=port_name,
        baud=baud,
        frame_count=NORMALIZED_CALIBRATION_FRAME_COUNT,
        zero_frames=zero_frames,
        corner_frames=corner_frames,
        protocol_errors=protocol_errors,
        spatial_frames=spatial_frames,
        min_span=NORMALIZED_MIN_RESPONSE_SPAN,
        max_noise_range=NORMALIZED_MAX_NOISE_RANGE,
        saturation_code=NORMALIZED_SATURATION_CODE,
    )
    path = module.save_calibration(data, output_root)
    return path, int(data["problem_cell_count"])



def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def parse_acc(data: bytes, offset: int, count: int = ACC_COUNT) -> tuple[AccSample, ...]:
    result: list[AccSample] = []
    for index in range(count):
        start = offset + index * ACC_RECORD_BYTES
        if start + ACC_RECORD_BYTES > len(data):
            break
        result.append(AccSample(*ACC_STRUCT.unpack_from(data, start)))
    return tuple(result)


def validate_esk_crc(data: bytes) -> None:
    if len(data) < ESK_TRAILER_BYTES:
        raise ProtocolError("ESK frame is shorter than its trailer")
    if not (data[5] & CRC_FLAG):
        raise ProtocolError("ESK frame has no CRC flag")
    expected = u32(data, len(data) - ESK_TRAILER_BYTES)
    actual = zlib.crc32(data[:-ESK_TRAILER_BYTES]) & 0xFFFFFFFF
    if expected != actual:
        raise ProtocolError(
            f"CRC32 mismatch: wire={expected:08X}, calculated={actual:08X}"
        )


class StreamFramer:
    """Extract active MUL1 packets and legacy direct frames from USB serial."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def _find_marker(self) -> int:
        positions = [self.buffer.find(marker) for marker in KNOWN_MARKERS]
        valid = [position for position in positions if position >= 0]
        return min(valid) if valid else -1

    def feed(self, chunk: bytes) -> Iterable[bytes]:
        self.buffer.extend(chunk)
        while True:
            position = self._find_marker()
            if position < 0:
                # Keep enough bytes for a marker split across USB reads.
                if len(self.buffer) > 3:
                    del self.buffer[:-3]
                return
            if position:
                del self.buffer[:position]
            if len(self.buffer) < 4:
                return

            marker = bytes(self.buffer[:4])
            if marker == MUL1_MAGIC:
                if len(self.buffer) < MUL1_HEADER_BYTES // 2:
                    return
                if self.buffer[4] != MUL1_VERSION:
                    del self.buffer[0]
                    continue
                length = u16(self.buffer, 8)
                if length < MUL1_MIN_BYTES or length > MUL1_MAX_BYTES:
                    del self.buffer[0]
                    continue
            elif marker in (b"ESKF", b"ESKD", b"ESK0"):
                if len(self.buffer) < ESK_HEADER_BYTES:
                    return
                length = u16(self.buffer, 6)
                if length < ESK_HEADER_BYTES + ESK_TRAILER_BYTES or length > HOST_SLOT_BYTES:
                    del self.buffer[0]
                    continue
            elif marker == b"ESP0":
                length = SPATIAL_HEARTBEAT_BYTES
            else:
                if len(self.buffer) < SPATIAL_PREFIX_BYTES:
                    return
                count = u16(self.buffer, 140)
                length = SPATIAL_PREFIX_BYTES + 4 * count
                if length > HOST_SLOT_BYTES:
                    del self.buffer[0]
                    continue

            if len(self.buffer) < length:
                return
            frame = bytes(self.buffer[:length])
            del self.buffer[:length]
            yield frame


class ProtocolState:
    """Reconstruct FSR caches from Full, Delta, and Spatial Sparse frames."""

    def __init__(self) -> None:
        self.fsr1 = np.zeros((ROWS, COLS), dtype=np.uint16)
        self.fsr2 = np.zeros((ROWS, COLS), dtype=np.uint16)
        self.acc: tuple[AccSample, ...] = ()
        self.esk_cache_valid = False
        self.spatial_cache_valid = False
        self.last_esk_sequence: int | None = None
        self.last_spatial_sequence: int | None = None

    def copy_from(self, other: "ProtocolState") -> None:
        self.fsr1 = other.fsr1.copy()
        self.fsr2 = other.fsr2.copy()
        self.acc = other.acc
        self.esk_cache_valid = other.esk_cache_valid
        self.spatial_cache_valid = other.spatial_cache_valid
        self.last_esk_sequence = other.last_esk_sequence
        self.last_spatial_sequence = other.last_spatial_sequence

    def clone(self) -> "ProtocolState":
        clone = ProtocolState()
        clone.copy_from(self)
        return clone

    def apply(self, data: bytes) -> DecodedFrame:
        marker = data[:4]
        if marker in (b"ESKF", b"ESKD", b"ESK0"):
            return self._apply_esk(data)
        if marker in (b"ESPF", b"ESPD", b"ESP0"):
            return self._apply_spatial(data)
        raise ProtocolError(f"unsupported marker {marker!r}")

    def _apply_esk(self, data: bytes) -> DecodedFrame:
        if len(data) < ESK_HEADER_BYTES:
            raise ProtocolError("ESK frame has an incomplete header")
        marker = data[:4]
        if data[4] == ACTIVE_ESK_VERSION:
            return self._apply_esk_active(data)
        if data[4] != LEGACY_ESK_VERSION:
            raise ProtocolError(f"unsupported ESK version {data[4]}")
        declared = u16(data, 6)
        if declared != len(data):
            raise ProtocolError(f"ESK length {declared} != received {len(data)}")
        validate_esk_crc(data)
        flags = data[5]
        sequence = u32(data, 8)
        base_sequence = u32(data, 12)

        if marker == b"ESKF":
            if len(data) != 1188:
                raise ProtocolError("ESKF must be 1188 bytes")
            self.fsr1 = np.frombuffer(data, dtype="<u2", count=256, offset=16).reshape(
                ROWS, COLS
            ).copy()
            self.fsr2 = np.frombuffer(
                data, dtype="<u2", count=256, offset=16 + 512
            ).reshape(ROWS, COLS).copy()
            self.acc = parse_acc(data, 16 + 1024)
            self.esk_cache_valid = True
            self.last_esk_sequence = sequence
            algorithm = "DELTA" if (flags & DELTA_FLAG) else "FULL"
            note = ("Delta full sync; previous cache was missing or K exceeded "
                    "the variable-frame limit"
                    if algorithm == "DELTA" else "complete cache sync")
            return self._snapshot(
                "ESKF", algorithm, sequence, 0xFFFFFFFF, note=note, flags=flags
            )

        if not self.esk_cache_valid or self.last_esk_sequence != base_sequence:
            self.esk_cache_valid = False
            raise ProtocolError(
                f"Delta base sequence {base_sequence} does not match "
                f"cache {self.last_esk_sequence}"
            )

        if marker == b"ESK0":
            if len(data) != 164:
                raise ProtocolError("ESK0 must be 164 bytes")
            changed = 0
            note = "heartbeat; FSR cache retained"
        else:
            changed = u16(data, 160)
            if len(data) != 166 + 4 * changed:
                raise ProtocolError("ESKD changed_count does not match length")
            offset = 162
            for _ in range(changed):
                layer_row = data[offset]
                column = data[offset + 1]
                value = u16(data, offset + 2)
                layer = (layer_row >> 7) & 1
                row = layer_row & 0x0F
                if row >= ROWS or column >= COLS:
                    raise ProtocolError("ESKD record contains an invalid position")
                target = self.fsr2 if layer else self.fsr1
                target[row, column] = value
                offset += 4
            note = f"{changed} changed cells applied"

        self.acc = parse_acc(data, 16)
        self.last_esk_sequence = sequence
        return self._snapshot(
            marker.decode(), "DELTA", sequence, base_sequence,
            changed_count=changed, note=note, flags=flags,
        )

    def _apply_esk_active(self, data: bytes) -> DecodedFrame:
        """Decode the v4 FSR-only ESK payload used by the active firmware."""
        marker = data[:4]
        declared = u16(data, 6)
        if declared != len(data):
            raise ProtocolError(
                f"active ESK length {declared} != received {len(data)}"
            )
        validate_esk_crc(data)
        flags = data[5]
        sequence = u32(data, 8)
        base_sequence = u32(data, 12)

        if marker == b"ESKF":
            if len(data) != ACTIVE_HOST_SLOT_BYTES:
                raise ProtocolError("active ESKF must be 1044 bytes")
            self.fsr1 = np.frombuffer(
                data, dtype="<u2", count=FSR_CELLS, offset=16
            ).reshape(ROWS, COLS).copy() & 0x0FFF
            self.fsr2 = np.frombuffer(
                data, dtype="<u2", count=FSR_CELLS, offset=16 + 512
            ).reshape(ROWS, COLS).copy() & 0x0FFF
            self.acc = ()
            self.esk_cache_valid = True
            self.last_esk_sequence = sequence
            # An ESKF with the spatial flag is a full-value fallback frame;
            # it still carries both complete FSR matrices and is safe to use.
            if flags & SPATIAL_FLAG:
                note = "spatial fallback carried as a complete FSR frame"
            elif flags & DELTA_FLAG:
                note = "Delta cache resynchronised by a complete FSR frame"
            else:
                note = "complete active FSR cache sync"
            return self._snapshot(
                "ESKF",
                "DELTA" if (flags & DELTA_FLAG) else "FULL",
                sequence,
                0xFFFFFFFF,
                note=note,
                flags=flags,
            )

        if marker != b"ESKD":
            raise ProtocolError(f"unsupported active ESK marker {marker!r}")
        if len(data) < 84:
            raise ProtocolError("active ESKD is shorter than its mask prefix")
        masks = (data[16:48], data[48:80])
        changed = sum(byte.bit_count() for mask in masks for byte in mask)
        expected = 84 + 2 * changed
        if len(data) != expected:
            raise ProtocolError(
                f"active ESKD length {len(data)} != expected {expected} for K={changed}"
            )
        if not self.esk_cache_valid or self.last_esk_sequence != base_sequence:
            self.esk_cache_valid = False
            raise ProtocolError(
                f"Delta base sequence {base_sequence} does not match "
                f"cache {self.last_esk_sequence}"
            )

        offset = 80
        for layer, mask in enumerate(masks):
            for position in range(FSR_CELLS):
                if mask[position // 8] & (1 << (position % 8)):
                    row, column = divmod(position, COLS)
                    target = self.fsr2 if layer else self.fsr1
                    target[row, column] = u16(data, offset) & 0x0FFF
                    offset += 2
        self.acc = ()
        self.last_esk_sequence = sequence
        return self._snapshot(
            "ESKD", "DELTA", sequence, base_sequence,
            changed_count=changed,
            note=f"{changed} mask-selected cells applied",
            flags=flags,
        )

    def _apply_spatial(self, data: bytes) -> DecodedFrame:
        marker = data[:4]
        if marker == b"ESP0":
            if len(data) != SPATIAL_HEARTBEAT_BYTES:
                raise ProtocolError("ESP0 must be 12 bytes")
            sequence = u32(data, 8)
            if not self.spatial_cache_valid:
                raise ProtocolError("ESP0 received before an ESPF cache")
            self.last_spatial_sequence = sequence
            return self._snapshot(
                "ESP0", "SPATIAL", sequence, None,
                note="heartbeat; spatial cache retained", flags=0,
            )

        # Active v4 spatial frames have a 46-byte prefix and no ACC records.
        # Legacy frames remain supported for old recordings and direct tests.
        if (len(data) >= ACTIVE_SPATIAL_PREFIX_BYTES and
                ACTIVE_SPATIAL_PREFIX_BYTES + 4 * u16(data, 44) == len(data)):
            return self._apply_spatial_active(data)

        if len(data) < SPATIAL_PREFIX_BYTES:
            raise ProtocolError("Spatial frame has an incomplete prefix")
        count = u16(data, 140)
        expected = SPATIAL_PREFIX_BYTES + 4 * count
        if expected != len(data) or expected > HOST_SLOT_BYTES:
            raise ProtocolError("Spatial count does not match frame length")
        sequence = u32(data, 8)
        self.acc = parse_acc(data, 12, 6)

        if marker == b"ESPF":
            if count > FSR_CELLS:
                raise ProtocolError("ESPF sampled_count is too large")
            mask = data[108:140]
            offset = SPATIAL_PREFIX_BYTES
            self.fsr1.fill(0)
            self.fsr2.fill(0)
            for position in range(FSR_CELLS):
                if not ((mask[position // 8] >> (position % 8)) & 1):
                    continue
                row, column = divmod(position, COLS)
                self.fsr1[row, column] = u16(data, offset)
                self.fsr2[row, column] = u16(data, offset + 2)
                offset += 4
            self.spatial_cache_valid = True
            self.last_spatial_sequence = sequence
            return self._snapshot(
                "ESPF", "SPATIAL", sequence, None,
                sampled_count=count, note=f"spatial sync with {count} positions",
                flags=0,
            )

        changed = count
        if not self.spatial_cache_valid:
            raise ProtocolError("ESPD received before an ESPF cache")
        offset = SPATIAL_PREFIX_BYTES
        for _ in range(changed):
            layer_row = data[offset]
            column = data[offset + 1]
            value = u16(data, offset + 2)
            layer = (layer_row >> 7) & 1
            row = layer_row & 0x0F
            if row >= ROWS or column >= COLS:
                raise ProtocolError("ESPD record contains an invalid position")
            target = self.fsr2 if layer else self.fsr1
            target[row, column] = value
            offset += 4
        self.last_spatial_sequence = sequence
        return self._snapshot(
            "ESPD", "SPATIAL", sequence, None,
            changed_count=changed, note=f"{changed} spatial changes applied", flags=0,
        )

    def _apply_spatial_active(self, data: bytes) -> DecodedFrame:
        marker = data[:4]
        count = u16(data, 44)
        sequence = u32(data, 8)
        mask = data[12:44]
        if count > FSR_CELLS:
            raise ProtocolError("active spatial count is too large")

        if marker == b"ESPF":
            self.fsr1.fill(0)
            self.fsr2.fill(0)
            offset = ACTIVE_SPATIAL_PREFIX_BYTES
            for position in range(FSR_CELLS):
                if not (mask[position // 8] & (1 << (position % 8))):
                    continue
                self.fsr1.flat[position] = u16(data, offset) & 0x0FFF
                self.fsr2.flat[position] = u16(data, offset + 2) & 0x0FFF
                offset += 4
            if offset != len(data):
                raise ProtocolError("active ESPF mask/value count mismatch")
            self.spatial_cache_valid = True
            self.last_spatial_sequence = sequence
            self.acc = ()
            return self._snapshot(
                "ESPF", "SPATIAL", sequence, None,
                sampled_count=count,
                note=f"active spatial sync with {count} positions",
                flags=SPATIAL_FLAG,
            )

        if marker != b"ESPD":
            raise ProtocolError(f"unsupported active spatial marker {marker!r}")
        if not self.spatial_cache_valid:
            raise ProtocolError("active ESPD received before an ESPF cache")
        if (self.last_spatial_sequence is None or
                sequence != (self.last_spatial_sequence + 1) & 0xFFFFFFFF):
            self.spatial_cache_valid = False
            raise ProtocolError("active spatial sequence does not match cache")
        offset = ACTIVE_SPATIAL_PREFIX_BYTES
        for _ in range(count):
            layer_row = data[offset]
            column = data[offset + 1]
            row = layer_row & 0x0F
            layer = (layer_row >> 7) & 1
            if row >= ROWS or column >= COLS:
                raise ProtocolError("active ESPD record contains an invalid position")
            target = self.fsr2 if layer else self.fsr1
            target[row, column] = u16(data, offset + 2) & 0x0FFF
            offset += 4
        self.last_spatial_sequence = sequence
        self.acc = ()
        return self._snapshot(
            "ESPD", "SPATIAL", sequence, None,
            changed_count=count,
            note=f"{count} active spatial changes applied",
            flags=SPATIAL_FLAG,
        )

    def _snapshot(
        self,
        marker: str,
        family: str,
        sequence: int,
        base_sequence: int | None,
        *,
        changed_count: int = 0,
        sampled_count: int = 0,
        note: str = "",
        flags: int = 0,
    ) -> DecodedFrame:
        return DecodedFrame(
            marker=marker,
            family=family,
            sequence=sequence,
            base_sequence=base_sequence,
            fsr1=self.fsr1.copy(),
            fsr2=self.fsr2.copy(),
            acc=self.acc,
            changed_count=changed_count,
            sampled_count=sampled_count,
            cache_valid=(self.esk_cache_valid
                         if family in ("FULL", "DELTA")
                         else self.spatial_cache_valid),
            note=note,
            flags=flags,
        )


def module_status_name(status: int) -> str:
    """Return the active Teensy status byte in a compact human-readable form."""
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


def parse_mul1_packet(
    data: bytes,
    states: list[ProtocolState],
) -> tuple[list[DecodedFrame], tuple[int, ...], list[str]]:
    """Parse one active MUL1 v2 packet and update four independent caches.

    A malformed module payload does not discard valid payloads from the other
    modules in the same USB packet.  The caller can show the error while the
    healthy modules continue to feed the existing GUI and calibration queues.
    """
    if len(data) < MUL1_MIN_BYTES or data[:4] != MUL1_MAGIC:
        raise ProtocolError("invalid MUL1 packet header")
    if data[4] != MUL1_VERSION:
        raise ProtocolError(f"unsupported MUL1 version {data[4]}")
    if data[5] != MODULE_COUNT:
        raise ProtocolError(f"unexpected MUL1 module count {data[5]}")
    declared = u16(data, 8)
    if declared != len(data) or not (MUL1_MIN_BYTES <= declared <= MUL1_MAX_BYTES):
        raise ProtocolError(
            f"MUL1 length {declared} is invalid for {len(data)} received bytes"
        )
    expected_crc = u32(data, len(data) - MUL1_TRAILER_BYTES)
    actual_crc = zlib.crc32(data[:-MUL1_TRAILER_BYTES]) & 0xFFFFFFFF
    if expected_crc != actual_crc:
        raise ProtocolError(
            f"MUL1 CRC32 mismatch: wire={expected_crc:08X}, calculated={actual_crc:08X}"
        )
    if len(states) != MODULE_COUNT:
        raise ProtocolError("four module protocol states are required")

    working = [state.clone() for state in states]
    statuses: list[int] = []
    decoded: list[DecodedFrame] = []
    errors: list[str] = []
    offset = MUL1_HEADER_BYTES
    end = len(data) - MUL1_TRAILER_BYTES
    packet_sequence = u32(data, 12)
    while len(statuses) < MODULE_COUNT:
        if offset + 4 > end:
            raise ProtocolError("truncated MUL1 module block")
        module_id = data[offset]
        status = data[offset + 1]
        payload_length = u16(data, offset + 2)
        offset += 4
        expected_id = len(statuses)
        if module_id != expected_id:
            raise ProtocolError(
                f"MUL1 module id {module_id} is out of order; expected {expected_id}"
            )
        if offset + payload_length > end:
            raise ProtocolError("MUL1 module payload exceeds packet boundary")
        statuses.append(status)

        if status != 0:
            if payload_length not in (0, DIAGNOSTIC_PREFIX_BYTES):
                raise ProtocolError("invalid failed-module diagnostic length")
            offset += payload_length
            continue
        if payload_length == 0:
            errors.append(f"module {module_id}: healthy status without payload")
            continue

        payload = data[offset:offset + payload_length]
        try:
            frame = working[module_id].apply(payload)
        except ProtocolError as error:
            errors.append(f"module {module_id}: {error}")
        else:
            decoded.append(replace(
                frame,
                module_id=module_id,
                packet_sequence=packet_sequence,
                packet_length=len(data),
                module_status=status,
            ))
        offset += payload_length

    if offset != end:
        raise ProtocolError("trailing bytes after MUL1 module blocks")
    for state, working_state in zip(states, working):
        state.copy_from(working_state)
    return decoded, tuple(statuses), errors


def half_width_at(v: float) -> float:
    """Half-width of the original flat-top hexagonal FSR panel."""
    safe_v = min(1.0, max(0.0, v))
    return 1.0 - abs(safe_v * 2.0 - 1.0) * 0.5


def board_point(u: float, v: float) -> tuple[float, float]:
    """Map a normalised grid coordinate onto the original FSR hexagon."""
    x = (u * 2.0 - 1.0) * half_width_at(v)
    y = 1.0 - v * 2.0
    return x, y


def cell_polygons() -> list[list[tuple[float, float]]]:
    return [
        [
            board_point(col / COLS, row / ROWS),
            board_point((col + 1) / COLS, row / ROWS),
            board_point((col + 1) / COLS, (row + 1) / ROWS),
            board_point(col / COLS, (row + 1) / ROWS),
        ]
        for row in range(ROWS)
        for col in range(COLS)
    ]


def board_outline() -> list[tuple[float, float]]:
    return [
        board_point(0.0, 0.5),
        board_point(0.0, 0.0),
        board_point(1.0, 0.0),
        board_point(1.0, 0.5),
        board_point(1.0, 1.0),
        board_point(0.0, 1.0),
    ]


def oriented_fsr(matrix: np.ndarray) -> np.ndarray:
    """Match the original GUI: transpose, then mirror the display columns."""
    return np.fliplr(matrix.T)


def add_grid_labels(axis, compact: bool) -> None:
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


def build_esk_full(sequence: int = 1, flags: int = 0x14) -> bytes:
    data = bytearray(1188)
    data[:4] = b"ESKF"
    data[4] = 2
    data[5] = flags
    struct.pack_into("<HII", data, 6, 1188, sequence, 0xFFFFFFFF)
    struct.pack_into("<I", data, 1184, zlib.crc32(data[:1184]) & 0xFFFFFFFF)
    return bytes(data)


def build_esk_delta(sequence: int = 2, base_sequence: int = 1) -> bytes:
    data = bytearray(170)
    data[:4] = b"ESKD"
    data[4] = 2
    data[5] = 0x34
    struct.pack_into("<HII", data, 6, 170, sequence, base_sequence)
    struct.pack_into("<H", data, 160, 1)
    data[162:166] = bytes((0, 3, 0xD2, 0x04))
    struct.pack_into("<I", data, 166, zlib.crc32(data[:166]) & 0xFFFFFFFF)
    return bytes(data)


def build_esp_full(sequence: int = 1) -> bytes:
    data = bytearray(146)
    data[:4] = b"ESPF"
    struct.pack_into("<II", data, 4, 100, sequence)
    data[108] = 1  # position 0 in the 32-byte mask
    struct.pack_into("<H", data, 140, 1)
    struct.pack_into("<HH", data, 142, 111, 222)
    return bytes(data)


def build_active_esk_full(sequence: int = 1, base: int = 0) -> bytes:
    """Build a synthetic active v4 1044-byte FULL payload for self-tests."""
    data = bytearray(ACTIVE_HOST_SLOT_BYTES)
    data[:4] = b"ESKF"
    data[4], data[5] = ACTIVE_ESK_VERSION, CRC_FLAG
    struct.pack_into("<HII", data, 6, ACTIVE_HOST_SLOT_BYTES, sequence, 0xFFFFFFFF)
    for position in range(FSR_CELLS):
        struct.pack_into("<H", data, 16 + 2 * position,
                         (base + position) & 0x0FFF)
        struct.pack_into("<H", data, 16 + 512 + 2 * position,
                         (base + 2 * position) & 0x0FFF)
    struct.pack_into(
        "<I", data, ACTIVE_HOST_SLOT_BYTES - ESK_TRAILER_BYTES,
        zlib.crc32(data[:-ESK_TRAILER_BYTES]) & 0xFFFFFFFF,
    )
    return bytes(data)


def build_active_esk_delta(
    sequence: int = 2,
    base_sequence: int = 1,
    changes: list[tuple[int, int, int, int]] | None = None,
) -> bytes:
    """Build a synthetic active mask-based ESKD payload for self-tests."""
    changes = changes or [(0, 0, 3, 1234), (1, 1, 2, 2345)]
    masks = [bytearray(32), bytearray(32)]
    values: list[tuple[int, int]] = []
    for layer, row, column, value in changes:
        if layer not in (0, 1) or not (0 <= row < ROWS) or not (0 <= column < COLS):
            raise ValueError("invalid active Delta test coordinate")
        position = row * COLS + column
        masks[layer][position // 8] |= 1 << (position % 8)
        values.append((layer, position, value & 0x0FFF))
    data = bytearray(84 + 2 * len(values))
    data[:4] = b"ESKD"
    data[4], data[5] = ACTIVE_ESK_VERSION, CRC_FLAG | DELTA_FLAG
    struct.pack_into("<HII", data, 6, len(data), sequence, base_sequence)
    data[16:48] = masks[0]
    data[48:80] = masks[1]
    offset = 80
    for layer in range(2):
        for position in range(FSR_CELLS):
            for value_layer, value_position, value in values:
                if (value_layer, value_position) == (layer, position):
                    struct.pack_into("<H", data, offset, value)
                    offset += 2
    struct.pack_into(
        "<I", data, len(data) - ESK_TRAILER_BYTES,
        zlib.crc32(data[:-ESK_TRAILER_BYTES]) & 0xFFFFFFFF,
    )
    return bytes(data)


def build_active_esp_full(sequence: int = 1, positions: list[int] | None = None) -> bytes:
    positions = positions or [1, 4, 6, 9, 11, 14]
    data = bytearray(ACTIVE_SPATIAL_PREFIX_BYTES + 4 * len(positions))
    data[:4] = b"ESPF"
    struct.pack_into("<II", data, 4, 1234, sequence)
    for position in positions:
        data[12 + position // 8] |= 1 << (position % 8)
    struct.pack_into("<H", data, 44, len(positions))
    offset = ACTIVE_SPATIAL_PREFIX_BYTES
    for position in positions:
        struct.pack_into("<HH", data, offset, position + 100, position + 200)
        offset += 4
    return bytes(data)


def build_active_esp_delta(sequence: int = 2, positions: list[int] | None = None) -> bytes:
    positions = positions or [1]
    data = bytearray(ACTIVE_SPATIAL_PREFIX_BYTES + 4 * len(positions))
    data[:4] = b"ESPD"
    struct.pack_into("<II", data, 4, 1234, sequence)
    struct.pack_into("<H", data, 44, len(positions))
    offset = ACTIVE_SPATIAL_PREFIX_BYTES
    for position in positions:
        row, column = divmod(position, COLS)
        data[offset] = row
        data[offset + 1] = column
        struct.pack_into("<H", data, offset + 2, position + 300)
        offset += 4
    return bytes(data)


def build_active_mul1(frames: list[bytes | None], sequence: int = 1) -> bytes:
    if len(frames) != MODULE_COUNT:
        raise ValueError("active MUL1 self-test requires four module entries")
    packet = bytearray(MUL1_HEADER_BYTES)
    packet[:4] = MUL1_MAGIC
    packet[4], packet[5] = MUL1_VERSION, MODULE_COUNT
    packet[6] = sum((1 << index) for index, frame in enumerate(frames) if frame)
    struct.pack_into("<II", packet, 12, sequence, 99)
    for module_id, frame in enumerate(frames):
        status = 0 if frame is not None else 0x80
        payload = frame or b""
        packet.extend(bytes((module_id, status)))
        packet.extend(struct.pack("<H", len(payload)))
        packet.extend(payload)
    packet.extend(b"\0\0\0\0")
    struct.pack_into("<H", packet, 8, len(packet))
    struct.pack_into(
        "<I", packet, len(packet) - MUL1_TRAILER_BYTES,
        zlib.crc32(packet[:-MUL1_TRAILER_BYTES]) & 0xFFFFFFFF,
    )
    return bytes(packet)


def run_self_test() -> None:
    framer = StreamFramer()
    state = ProtocolState()
    full = build_esk_full()
    delta = build_esk_delta()
    frames = list(framer.feed(b"#DSMODE mode=FULL\r\n" + full[:17]))
    frames.extend(framer.feed(full[17:] + delta))
    assert len(frames) == 2
    state.apply(frames[0])
    decoded_delta = state.apply(frames[1])
    assert decoded_delta.fsr1[0, 3] == 1234
    delta_sync = ProtocolState().apply(build_esk_full(flags=0x34))
    assert delta_sync.family == "DELTA"

    spatial_state = ProtocolState()
    spatial = list(StreamFramer().feed(b"noise\n" + build_esp_full()))
    assert len(spatial) == 1
    decoded_spatial = spatial_state.apply(spatial[0])
    assert decoded_spatial.fsr1[0, 0] == 111
    assert decoded_spatial.fsr2[0, 0] == 222
    orientation_test = np.arange(FSR_CELLS, dtype=np.uint16).reshape(ROWS, COLS)
    assert oriented_fsr(orientation_test)[0, 0] == orientation_test[15, 0]
    assert oriented_fsr(orientation_test)[15, 15] == orientation_test[0, 15]
    assert board_outline() == [(-1.0, 0.0), (-0.5, 1.0),
                               (0.5, 1.0), (1.0, 0.0),
                               (0.5, -1.0), (-0.5, -1.0)]
    active_states = [ProtocolState() for _ in range(MODULE_COUNT)]
    active_full = build_active_esk_full(base=100)
    active_packet = build_active_mul1(
        [active_full, build_active_esk_full(base=200), active_full, active_full]
    )
    active_framer = StreamFramer()
    active_frames = list(active_framer.feed(active_packet[:19]))
    active_frames.extend(active_framer.feed(active_packet[19:]))
    assert len(active_frames) == 1
    decoded, statuses, errors = parse_mul1_packet(active_frames[0], active_states)
    assert not errors and statuses == (0, 0, 0, 0)
    assert {frame.module_id for frame in decoded} == {0, 1, 2, 3}
    assert decoded[0].fsr1[0, 0] == 100
    active_delta = build_active_esk_delta(
        changes=[(0, 0, 3, 1234), (1, 1, 2, 2345)]
    )
    decoded, _, errors = parse_mul1_packet(
        build_active_mul1([active_delta, None, None, None], sequence=2),
        active_states,
    )
    assert not errors and decoded[0].fsr1[0, 3] == 1234
    assert decoded[0].fsr2[1, 2] == 2345
    spatial_state = ProtocolState()
    spatial_full = spatial_state.apply(build_active_esp_full())
    spatial_delta = spatial_state.apply(build_active_esp_delta())
    assert spatial_full.fsr1.flat[1] == 101
    assert spatial_delta.fsr1.flat[1] == 301
    print("data scalability parser self-test: PASS")


@dataclass
class MonitorStats:
    received: int = 0
    displayed: int = 0
    parse_errors: int = 0
    last_error: str = ""
    last_frame_bytes: int = 0
    module_statuses: tuple[int, ...] = (0, 0, 0, 0)
    _rate_samples: deque[tuple[float, int]] = field(default_factory=deque,
                                                     repr=False)
    _rate_lock: Lock = field(default_factory=Lock, repr=False)

    def record_frame(self, length: int) -> None:
        now = time.monotonic()
        with self._rate_lock:
            self.last_frame_bytes = length
            self._rate_samples.append((now, length))
            cutoff = now - 1.0
            while self._rate_samples and self._rate_samples[0][0] < cutoff:
                self._rate_samples.popleft()

    def data_rate(self) -> tuple[float, float]:
        now = time.monotonic()
        with self._rate_lock:
            cutoff = now - 1.0
            while self._rate_samples and self._rate_samples[0][0] < cutoff:
                self._rate_samples.popleft()
            if not self._rate_samples:
                return 0.0, 0.0
            elapsed = max(now - self._rate_samples[0][0], 1e-3)
            total_bytes = sum(length for _, length in self._rate_samples)
            return total_bytes / elapsed, len(self._rate_samples) / elapsed

    def record_module_statuses(self, statuses: tuple[int, ...]) -> None:
        self.module_statuses = statuses


def serial_worker(
    port_name: str,
    baud: int,
    output: queue.Queue[DecodedFrame],
    stats: MonitorStats,
    stop: threading.Event,
    capture_output: queue.Queue[DecodedFrame] | None = None,
    measurement_output: queue.Queue[DecodedFrame] | None = None,
) -> None:
    try:
        import serial
    except ImportError as error:
        stats.last_error = f"pyserial is required: {error}"
        return

    while not stop.is_set():
        try:
            with serial.Serial(port_name, baudrate=baud, timeout=0.1) as port:
                framer = StreamFramer()
                legacy_state = ProtocolState()
                active_states = [ProtocolState() for _ in range(MODULE_COUNT)]

                def publish_frame(decoded: DecodedFrame) -> None:
                    stats.received += 1
                    try:
                        output.put_nowait(decoded)
                    except queue.Full:
                        try:
                            output.get_nowait()
                        except queue.Empty:
                            pass
                        output.put_nowait(decoded)
                    for target in (capture_output, measurement_output):
                        if target is None:
                            continue
                        try:
                            target.put_nowait(decoded)
                        except queue.Full:
                            try:
                                target.get_nowait()
                            except queue.Empty:
                                pass
                            try:
                                target.put_nowait(decoded)
                            except queue.Full:
                                pass

                while not stop.is_set():
                    chunk = port.read(4096)
                    if not chunk:
                        continue
                    for raw in framer.feed(chunk):
                        # Measure the actual logical USB bytes received from
                        # the Teensy, independent of any theoretical formula.
                        stats.record_frame(len(raw))
                        if raw[:4] == MUL1_MAGIC:
                            try:
                                decoded_frames, statuses, errors = parse_mul1_packet(
                                    raw, active_states
                                )
                            except ProtocolError as error:
                                stats.parse_errors += 1
                                stats.last_error = str(error)
                                continue
                            stats.record_module_statuses(statuses)
                            if errors:
                                stats.parse_errors += len(errors)
                                stats.last_error = "; ".join(errors)
                            for decoded in decoded_frames:
                                publish_frame(decoded)
                            continue

                        stats.record_module_statuses((0,) * MODULE_COUNT)
                        try:
                            decoded = legacy_state.apply(raw)
                        except ProtocolError as error:
                            stats.parse_errors += 1
                            stats.last_error = str(error)
                            continue
                        publish_frame(decoded)
        except serial.SerialException as error:
            stats.last_error = f"{port_name}: {error}"
            stop.wait(1.0)


class SquareScalabilityGui:
    """New-protocol monitor using the original hexagonal 16x16 FSR panel."""

    def __init__(
        self,
        frames: queue.Queue[DecodedFrame],
        stats: MonitorStats,
        stop: threading.Event,
        source: str,
        baud: int,
        initial_view: str,
        interval_ms: int,
        module_id: int,
        pyocd_executable: str,
        pyocd_uid: str | None,
        pyocd_target: str | None,
        calibration_frames: queue.Queue[DecodedFrame] | None = None,
        measurement_frames: queue.Queue[DecodedFrame] | None = None,
    ) -> None:
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
        from matplotlib.widgets import Button, RadioButtons, TextBox

        plt.style.use("dark_background")
        self.plt = plt
        self.frames = frames
        self.stats = stats
        self.stop = stop
        self.source = source
        self.baud = baud
        self.mode = {"all": "All", "fsr1": "FSR1", "fsr2": "FSR2", "acc": "ACC"}[initial_view]
        self.latest: DecodedFrame | None = None
        self.latest_by_module: dict[int, DecodedFrame] = {}
        self.content_axes = []
        self.fsr_artists = {}
        self.acc_axis = None
        self.module_id = module_id
        self.calibration_module_id = module_id
        self.calibration_fsr_name: str | None = None
        self.calibration_phase = "idle"
        self.calibration_parse_errors_start = 0
        self.calibration_data: dict[str, dict[str, np.ndarray]] = {}
        self.pressure_model_data: dict[str, dict[str, object]] = {}
        self.pressure_area_model_data: dict[str, dict[str, object]] = {}
        self.calibration_pressure_points: list[dict[str, object]] = []
        self.calibration_started_at: str | None = None
        self.calibration_pressure_box = None
        self.calibration_record_button = None
        self.pressure_submit_consumed = False
        self.calibration_analysis_results: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=4)
        self.display_mode = "RAW"
        self.calibration_gamma = CALIBRATION_GAMMA
        self.frame_save_button = None
        self.frame_save_status = None
        self.pyocd_executable = pyocd_executable
        self.pyocd_uid = pyocd_uid
        self.pyocd_target = pyocd_target
        self.pyocd_busy = False
        self.pyocd_results: queue.Queue[str] = queue.Queue(maxsize=1)
        self.view_distribution_busy = False
        self.view_distribution_collecting = False
        self.view_distribution_started_at = 0.0
        self.view_distribution_layers: tuple[str, ...] = ()
        self.view_distribution_actual_load_g = 0.0
        self.view_distribution_frames: list[DecodedFrame] = []
        self.view_distribution_results: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=2)
        self.calibration_frames = calibration_frames
        self.measurement_frames = measurement_frames
        self.load_capture_busy = False
        self.load_capture_started_at = 0.0
        self.load_capture_layers: tuple[str, ...] = ()
        self.load_capture_frames: list[DecodedFrame] = []
        self.normalized_phase = "idle"
        self.normalized_module_id = module_id
        self.normalized_fsr_name: str | None = None
        self.normalized_started_at: str | None = None
        self.normalized_parse_errors_start = 0
        self.normalized_spatial_frames = 0
        self.normalized_zero_frames: list[np.ndarray] = []
        self.normalized_corner_frames: dict[str, list[np.ndarray]] = {}
        self.normalized_corner_index = 0
        self.normalized_phase_frames: list[np.ndarray] = []

        self.figure = plt.figure(figsize=(14, 9), facecolor="#080a0d")
        try:
            self.figure.canvas.manager.set_window_title("E-SKIN Data Scalability Monitor")
        except AttributeError:
            pass
        self.figure.subplots_adjust(left=0.16, right=0.84, top=0.87, bottom=0.06)
        self.rate_text = self.figure.text(
            0.01, 0.982, "Measured USB data rate: waiting for frames...",
            color="#7dd3fc", family="monospace", fontsize=11,
        )
        self.algorithm_text = self.figure.text(
            0.01, 0.962, "Algorithm: waiting for frames...",
            color="#fbbf24", family="monospace", fontsize=10,
        )
        self.title = self.figure.suptitle(
            f"Waiting for data-scalability frames from {source}...",
            color="white", y=0.945,
        )
        self._Button = Button
        self._panel_headers = {}
        self._panel_bodies = {}
        self._panel_items = {}
        self._sidebar_left = 0.855
        self._sidebar_width = 0.13
        self._panel_left = {"tools": 0.01}
        self._add_control_panel("display", "VIEW & DISPLAY", 0.57, 0.32, True)
        self._add_control_panel("calibration", "CALIBRATION", 0.13, 0.405, True)
        self._add_control_panel("tools", "TOOLS & SAVE", 0.61, 0.28, False)

        view_axis = self._panel_axis("display", (0.86, 0.765, 0.12, 0.080))
        self.radio = RadioButtons(
            view_axis, VIEW_LABELS, active=VIEW_LABELS.index(self.mode),
            activecolor="tab:orange",
        )
        for label in self.radio.labels:
            label.set_color("white")
            label.set_fontsize(8)
        view_axis.set_title("View", color="white", fontsize=9, pad=2)
        self.radio.on_clicked(self._select_view)

        module_axis = self._panel_axis("display", (0.86, 0.690, 0.12, 0.065))
        self.module_radio = RadioButtons(
            module_axis, MODULE_LABELS, active=module_id,
            activecolor="tab:green",
        )
        for label in self.module_radio.labels:
            label.set_color("white")
            label.set_fontsize(8)
        module_axis.set_title("Module", color="white", fontsize=9, pad=2)
        self.module_radio.on_clicked(self._select_module)

        normalized_axis = self._panel_axis("display", (0.86, 0.650, 0.12, 0.028))
        self.normalized_button = Button(
            normalized_axis, "NORM CAL", color="#26324a", hovercolor="#3c4f78"
        )
        self.normalized_button.label.set_color("white")
        self.normalized_button.label.set_fontsize(8)
        self.normalized_button.on_clicked(self._show_normalized_display)
        pressure_display_axis = self._panel_axis("display", (0.86, 0.615, 0.12, 0.028))
        self.pressure_display_button = Button(
            pressure_display_axis, "FIT PRESS", color="#26324a", hovercolor="#3c4f78"
        )
        self.pressure_display_button.label.set_color("white")
        self.pressure_display_button.label.set_fontsize(8)
        self.pressure_display_button.on_clicked(self._show_pressure_display)
        raw_display_axis = self._panel_axis("display", (0.86, 0.580, 0.12, 0.028))
        self.raw_display_button = Button(
            raw_display_axis, "RAW", color="#26324a", hovercolor="#3c4f78"
        )
        self.raw_display_button.label.set_color("white")
        self.raw_display_button.label.set_fontsize(8)
        self.raw_display_button.on_clicked(self._show_raw_display)

        normalized_calibration_axis = self._panel_axis(
            "calibration", (0.86, 0.455, 0.12, 0.035)
        )
        self.normalized_calibration_button = Button(
            normalized_calibration_axis, "Start Norm Cal",
            color="#183328", hovercolor="#2f6b48",
        )
        self.normalized_calibration_button.label.set_color("white")
        self.normalized_calibration_button.label.set_fontsize(8)
        self.normalized_calibration_button.on_clicked(
            self._normalized_calibration_button_clicked
        )
        self.normalized_calibration_status = self._panel_text(
            "calibration", 0.92, 0.442, "Norm Cal: select FSR1/FSR2", fontsize=6.2,
        )

        calibration_axis = self._panel_axis("calibration", (0.86, 0.385, 0.12, 0.035))
        self.calibration_button = Button(
            calibration_axis, "Start Fit Cal", color="#183328", hovercolor="#2f6b48"
        )
        self.calibration_button.label.set_color("white")
        self.calibration_button.label.set_fontsize(8)
        self.calibration_button.on_clicked(self._calibration_button_clicked)
        self.calibration_status = self._panel_text(
            "calibration", 0.92, 0.372, "Fit Cal: select FSR1/FSR2", fontsize=6.2,
        )
        self.calibration_pressure_label = self._panel_text(
            "calibration", 0.92, 0.350, "Load (g)", fontsize=6.2,
        )
        pressure_axis = self._panel_axis("calibration", (0.86, 0.305, 0.12, 0.038))
        self.calibration_pressure_box = TextBox(
            pressure_axis, "", initial="", color="#181b20", hovercolor="#26324a"
        )
        self.calibration_pressure_box.text_disp.set_color("white")
        self.calibration_pressure_box.text_disp.set_fontsize(8)
        self.calibration_pressure_box.on_submit(self._record_pressure_point)
        record_axis = self._panel_axis("calibration", (0.86, 0.255, 0.12, 0.035))
        self.calibration_record_button = Button(
            record_axis, "Record", color="#26324a", hovercolor="#3c4f78"
        )
        self.calibration_record_button.label.set_color("white")
        self.calibration_record_button.label.set_fontsize(8)
        self.calibration_record_button.on_clicked(self._record_pressure_point)
        self.gamma_label = self._panel_text(
            "calibration", 0.92, 0.232, "Gamma (1–10)", fontsize=6.2,
        )
        gamma_axis = self._panel_axis("calibration", (0.86, 0.185, 0.12, 0.035))
        self.gamma_box = TextBox(
            gamma_axis, "", initial=f"{self.calibration_gamma:g}",
            color="#181b20", hovercolor="#26324a",
        )
        self.gamma_box.text_disp.set_color("white")
        self.gamma_box.text_disp.set_fontsize(8)
        self.gamma_box.on_submit(self._gamma_submitted)
        gamma_apply_axis = self._panel_axis("calibration", (0.86, 0.140, 0.12, 0.032))
        self.gamma_apply_button = Button(
            gamma_apply_axis, "Apply", color="#26324a", hovercolor="#3c4f78"
        )
        self.gamma_apply_button.label.set_color("white")
        self.gamma_apply_button.label.set_fontsize(8)
        self.gamma_apply_button.on_clicked(self._apply_gamma)
        self.gamma_status = self._panel_text(
            "calibration", 0.92, 0.130, f"γ={self.calibration_gamma:g}", fontsize=6.2,
        )

        load_axis = self._panel_axis("tools", (0.01, 0.828, 0.13, 0.021))
        self.load_button = Button(
            load_axis, "CURRENT LOAD", color="#26324a", hovercolor="#3c4f78"
        )
        self.load_button.label.set_color("white")
        self.load_button.label.set_fontsize(7)
        self.load_button.on_clicked(self._show_current_load)
        self.load_value_text = self._panel_text(
            "tools", 0.075, 0.821, "— g", fontsize=12.0,
        )
        self.load_value_text.set_color("#f8fafc")
        self.load_value_text.set_fontweight("bold")
        self.load_status = self._panel_text(
            "tools", 0.075, 0.804, "click CURRENT LOAD", fontsize=5.7,
        )

        reset_axis = self._panel_axis("tools", (0.01, 0.773, 0.13, 0.022))
        self.pyocd_button = Button(
            reset_axis, "pyOCD Reset", color="#182235", hovercolor="#334155"
        )
        self.pyocd_button.label.set_color("white")
        self.pyocd_button.label.set_fontsize(8)
        self.pyocd_button.on_clicked(self._start_pyocd_reset)
        self.pyocd_status = self._panel_text(
            "tools", 0.075, 0.765, "pyOCD: ready", fontsize=5.7,
        )
        save_axis = self._panel_axis("tools", (0.01, 0.740, 0.13, 0.022))
        self.frame_save_button = Button(
            save_axis, "Save Frame", color="#26324a", hovercolor="#3c4f78"
        )
        self.frame_save_button.label.set_color("white")
        self.frame_save_button.label.set_fontsize(8)
        self.frame_save_button.on_clicked(self._save_current_frame)
        self.frame_save_status = self._panel_text(
            "tools", 0.075, 0.732, "Frame: waiting", fontsize=5.7,
        )
        self.view_distribution_label = self._panel_text(
            "tools", 0.075, 0.712, "Distribution load (g)", fontsize=6.2,
        )
        distribution_load_axis = self._panel_axis(
            "tools", (0.01, 0.675, 0.13, 0.029)
        )
        self.view_distribution_load_box = TextBox(
            distribution_load_axis, "", initial="", color="#181b20",
            hovercolor="#26324a",
        )
        self.view_distribution_load_box.text_disp.set_color("white")
        self.view_distribution_load_box.text_disp.set_fontsize(8)
        distribution_axis = self._panel_axis(
            "tools", (0.01, 0.640, 0.13, 0.027)
        )
        self.view_distribution_button = Button(
            distribution_axis, "Capture 3 Views",
            color="#26324a", hovercolor="#3c4f78",
        )
        self.view_distribution_button.label.set_color("white")
        self.view_distribution_button.label.set_fontsize(7.5)
        self.view_distribution_button.on_clicked(self._capture_view_distributions)
        self.view_distribution_status = self._panel_text(
            "tools", 0.075, 0.628, "Distribution: ready", fontsize=5.5,
        )
        self._update_display_buttons()
        self._build_view()
        self.figure.canvas.mpl_connect("close_event", lambda _event: self.stop.set())
        self.animation = FuncAnimation(
            self.figure, self._update, interval=max(10, interval_ms),
            cache_frame_data=False,
        )

    def _add_control_panel(
        self, name: str, title: str, y: float, height: float, expanded: bool,
    ) -> None:
        self._panel_items[name] = []
        self._panel_expanded = getattr(self, "_panel_expanded", {})
        self._panel_expanded[name] = expanded
        panel_left = self._panel_left.get(name, self._sidebar_left)
        body = self.figure.add_axes(
            (panel_left, y, self._sidebar_width, height - 0.035),
            facecolor="#111827",
        )
        body.set_zorder(10)
        body.set_visible(expanded)
        body.set_xticks([])
        body.set_yticks([])
        for spine in body.spines.values():
            spine.set_color("#334155")
            spine.set_linewidth(0.6)
        self._panel_bodies[name] = body
        header_axis = self.figure.add_axes(
            (panel_left, y + height - 0.032,
             self._sidebar_width, 0.028)
        )
        header_axis.set_zorder(12)
        header = self._Button(
            header_axis,
            ("▼ " if expanded else "▶ ") + title,
            color="#1e293b",
            hovercolor="#334155",
        )
        header.label.set_color("white")
        header.label.set_fontsize(7.5)
        header.label.set_horizontalalignment("left")
        header.label.set_x(0.06)
        header.on_clicked(lambda _event, panel=name: self._toggle_panel(panel))
        self._panel_headers[name] = (header, title)

    def _panel_axis(self, panel: str, rect: tuple[float, float, float, float]):
        axis = self.figure.add_axes(rect, facecolor="#111827")
        axis.set_zorder(11)
        axis.set_visible(self._panel_expanded[panel])
        self._panel_items[panel].append(axis)
        return axis

    def _panel_text(
        self, panel: str, x: float, y: float, text: str, *, fontsize: float,
    ):
        artist = self.figure.text(
            x, y, text, color="#94a3b8", ha="center", va="top",
            family="monospace", fontsize=fontsize,
        )
        artist.set_zorder(13)
        artist.set_visible(self._panel_expanded[panel])
        self._panel_items[panel].append(artist)
        return artist

    def _toggle_panel(self, panel: str) -> None:
        expanded = not self._panel_expanded[panel]
        self._panel_expanded[panel] = expanded
        body = self._panel_bodies[panel]
        body.set_visible(expanded)
        header, title = self._panel_headers[panel]
        header.label.set_text(("▼ " if expanded else "▶ ") + title)
        for item in self._panel_items[panel]:
            item.set_visible(expanded)
        self.figure.canvas.draw_idle()

    def _start_pyocd_reset(self, _event) -> None:
        if self.pyocd_busy:
            return
        self.pyocd_busy = True
        self.pyocd_button.label.set_text("Resetting...")
        self.pyocd_status.set_text("pyOCD: running")
        self.figure.canvas.draw_idle()
        threading.Thread(target=self._run_pyocd_reset, daemon=True).start()

    def _save_current_frame(self, _event) -> None:
        if self.latest is None:
            self.frame_save_status.set_color("#fca5a5")
            self.frame_save_status.set_text("Frame: no valid frame")
            self.figure.canvas.draw_idle()
            return
        if self.mode == "ACC":
            self.frame_save_status.set_color("#fca5a5")
            self.frame_save_status.set_text("Frame: select FSR view")
            self.figure.canvas.draw_idle()
            return
        frame = self.latest
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        layers = (self.mode,) if self.mode in {"FSR1", "FSR2"} else ("FSR1", "FSR2")
        matrices = {"FSR1": frame.fsr1, "FSR2": frame.fsr2}
        paths = []
        heatmap_path = (
            fsr_data_directory(
                self._calibration_directory(), self.module_id, "FSR1",
            ).parent
            / "heatmap"
            / f"heatmap_M{self.module_id}_{self.mode}_{frame.marker}_"
            f"seq{frame.sequence}_{stamp}.png"
        )
        try:
            for layer in layers:
                path = (
                    fsr_data_directory(
                        self._calibration_directory(), self.module_id, layer,
                    )
                    / "fit"
                    / "raw"
                    / f"frame_M{self.module_id}_{layer}_{frame.marker}_"
                    f"seq{frame.sequence}_{stamp}.csv"
                )
                display_matrix = oriented_fsr(
                    self._display_fsr(layer, matrices[layer])
                )
                save_matrix_csv(path, display_matrix, layer=layer)
                paths.append(path)
            # Render the currently visible GUI figure so the saved PNG matches
            # the active heatmap view (RAW/NORM CAL/FIT PRESS and module).
            heatmap_path.parent.mkdir(parents=True, exist_ok=True)
            self.figure.canvas.draw()
            self.figure.savefig(
                heatmap_path,
                dpi=150,
                facecolor=self.figure.get_facecolor(),
                edgecolor=self.figure.get_edgecolor(),
            )
        except (OSError, ValueError) as error:
            self.frame_save_status.set_color("#fca5a5")
            self.frame_save_status.set_text(f"Frame: failed {str(error)[:52]}")
            self.figure.canvas.draw_idle()
            return
        self.frame_save_status.set_color("#86efac")
        self.frame_save_status.set_text(
            f"Frame: saved {len(paths)} matrix{'es' if len(paths) != 1 else ''} + heatmap"
        )
        self.figure.canvas.draw_idle()
        for path in paths:
            print(f"Saved frame matrix CSV: {path}")
        print(f"Saved heatmap PNG: {heatmap_path}")

    def _clear_view_distribution_input(self) -> None:
        eventson = self.view_distribution_load_box.eventson
        self.view_distribution_load_box.eventson = False
        try:
            self.view_distribution_load_box.set_val("")
        finally:
            self.view_distribution_load_box.eventson = eventson

    def _clear_measurement_frames(self) -> None:
        if self.measurement_frames is None:
            return
        while True:
            try:
                self.measurement_frames.get_nowait()
            except queue.Empty:
                return

    @staticmethod
    def _is_measurement_frame(frame: DecodedFrame) -> bool:
        return (
            frame.cache_valid
            and frame.family in {"FULL", "DELTA"}
            and frame.fsr1.shape == (ROWS, COLS)
            and frame.fsr2.shape == (ROWS, COLS)
        )

    def _consume_measurement_frames(self) -> None:
        """Collect every valid frame during the active one-second window."""
        if self.measurement_frames is not None:
            while True:
                try:
                    frame = self.measurement_frames.get_nowait()
                except queue.Empty:
                    break
                if (frame.module_id is not None and
                        frame.module_id != self.module_id):
                    continue
                if not self._is_measurement_frame(frame):
                    continue
                if self.load_capture_busy:
                    self.load_capture_frames.append(frame)
                if self.view_distribution_collecting:
                    self.view_distribution_frames.append(frame)

        now = time.monotonic()
        if self.load_capture_busy:
            elapsed = now - self.load_capture_started_at
            if elapsed >= AVERAGE_CAPTURE_SECONDS:
                self._finish_current_load_capture()
            else:
                self.load_status.set_color("#fbbf24")
                self.load_status.set_text(
                    f"Load: averaging {elapsed:.1f}/{AVERAGE_CAPTURE_SECONDS:g} s "
                    f"({len(self.load_capture_frames)} frames)"
                )
        if self.view_distribution_collecting:
            elapsed = now - self.view_distribution_started_at
            if elapsed >= AVERAGE_CAPTURE_SECONDS:
                self._finish_view_distribution_capture()
            else:
                self.view_distribution_status.set_color("#fbbf24")
                self.view_distribution_status.set_text(
                    f"Distribution: averaging {elapsed:.1f}/"
                    f"{AVERAGE_CAPTURE_SECONDS:g} s "
                    f"({len(self.view_distribution_frames)} frames)"
                )

    def _capture_view_distributions(self, _event) -> None:
        """Average one second of frames before generating the saved views."""
        if self.view_distribution_busy:
            return
        if self.load_capture_busy:
            self.view_distribution_status.set_color("#fca5a5")
            self.view_distribution_status.set_text(
                "Distribution: wait for Load averaging"
            )
            self.figure.canvas.draw_idle()
            return
        try:
            actual_load_g = float(self.view_distribution_load_box.text.strip())
        except (TypeError, ValueError):
            self.view_distribution_status.set_color("#fca5a5")
            self.view_distribution_status.set_text("Distribution: enter numeric load")
            self.figure.canvas.draw_idle()
            return
        if not np.isfinite(actual_load_g) or actual_load_g < 0.0:
            self.view_distribution_status.set_color("#fca5a5")
            self.view_distribution_status.set_text("Distribution: load must be >= 0")
            self.figure.canvas.draw_idle()
            return
        if self.latest is None or not self.latest.cache_valid:
            self.view_distribution_status.set_color("#fca5a5")
            self.view_distribution_status.set_text("Distribution: waiting for full matrix")
            self.figure.canvas.draw_idle()
            return
        if self.latest.family == "SPATIAL":
            self.view_distribution_status.set_color("#fca5a5")
            self.view_distribution_status.set_text("Distribution: use FULL or DELTA")
            self.figure.canvas.draw_idle()
            return
        if self.mode == "ACC":
            self.view_distribution_status.set_color("#fca5a5")
            self.view_distribution_status.set_text("Distribution: select an FSR view")
            self.figure.canvas.draw_idle()
            return

        layers = (self.mode,) if self.mode in {"FSR1", "FSR2"} else ("FSR1", "FSR2")
        try:
            for layer in layers:
                self._load_calibration(layer)
                self._load_pressure_model(layer)
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as error:
            self.view_distribution_busy = False
            self.view_distribution_button.label.set_text("Capture 3 Views")
            self.view_distribution_status.set_color("#fca5a5")
            self.view_distribution_status.set_text(
                f"Distribution: {str(error)[:54]}"
            )
            self.figure.canvas.draw_idle()
            return

        self._clear_measurement_frames()
        self.view_distribution_busy = True
        self.view_distribution_collecting = True
        self.view_distribution_started_at = time.monotonic()
        self.view_distribution_layers = layers
        self.view_distribution_actual_load_g = actual_load_g
        self.view_distribution_frames = []
        self.view_distribution_button.label.set_text("Averaging...")
        self.view_distribution_status.set_color("#fbbf24")
        self.view_distribution_status.set_text(
            f"Distribution: averaging 0/{AVERAGE_CAPTURE_SECONDS:g} s"
        )
        self._clear_view_distribution_input()
        self.figure.canvas.draw_idle()

    def _finish_view_distribution_capture(self) -> None:
        """Average the captured raw matrices and start distribution analysis."""
        self.view_distribution_collecting = False
        frames = self.view_distribution_frames
        self.view_distribution_frames = []
        layers = self.view_distribution_layers
        actual_load_g = self.view_distribution_actual_load_g
        if not frames:
            self.view_distribution_busy = False
            self.view_distribution_button.label.set_text("Capture 3 Views")
            self.view_distribution_status.set_color("#fca5a5")
            self.view_distribution_status.set_text(
                "Distribution: no valid frames in 1 s"
            )
            self.figure.canvas.draw_idle()
            return

        matrices = {
            "FSR1": np.mean(
                np.stack([frame.fsr1 for frame in frames], axis=0), axis=0
            ),
            "FSR2": np.mean(
                np.stack([frame.fsr2 for frame in frames], axis=0), axis=0
            ),
        }
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        load_token = f"{actual_load_g:g}".replace(".", "p")
        pending: list[tuple[Path, Path, dict[str, object]]] = []
        try:
            for layer in layers:
                # Keep the per-cell arithmetic mean as a float; converting
                # back to uint16 here would discard the one-second averaging.
                raw = np.asarray(matrices[layer], dtype=np.float64)
                if raw.shape != (ROWS, COLS):
                    raise ValueError(f"invalid 16x16 matrix for {layer}")
                calibration_path = self._load_calibration(layer)
                model_path = self._load_pressure_model(layer)
                linear = self._linear_fsr_values(layer, raw)
                normalized = self._normalized_fsr_values(layer, raw)
                fitted = self._fitted_fsr_values(layer, raw)
                fit_unit = str(self.pressure_model_data[layer]["unit"])
                output_dir = (
                    self._calibration_directory()
                    / "DATA"
                    / f"module_{self.module_id}"
                    / layer
                    / "evaluation"
                    / "view_distribution"
                    / f"load_{load_token}g_{stamp}"
                )
                capture_path = output_dir / "view_distribution_capture.json"
                payload: dict[str, object] = {
                    "format": "e-skin-fsr-view-distribution-capture",
                    "version": 2,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "module_id": self.module_id,
                    "fsr": layer,
                    "actual_load": {"value": actual_load_g, "unit": "g"},
                    "source_frames": {
                        "count": len(frames),
                        "sequence_first": int(frames[0].sequence),
                        "sequence_last": int(frames[-1].sequence),
                        "aggregation": (
                            f"per-cell arithmetic mean of valid frames collected "
                            f"for {AVERAGE_CAPTURE_SECONDS:g} s"
                        ),
                    },
                    "source_models": {
                        "normalized_calibration": portable_path(calibration_path),
                        "fitted_response": portable_path(model_path),
                        "linear_formula": "clip((RAW - zero) / (full - zero), 0, 1)",
                        "normalized_gamma": float(self.calibration_gamma),
                    },
                    "views": {
                        "RAW": {"unit": "ADC code", "values": raw.tolist()},
                        "LINEAR": {
                            "unit": "linear two-point normalized full-load ratio",
                            "values": linear.tolist(),
                        },
                        "NORM_CAL": {
                            "unit": "normalized full-load ratio",
                            "values": normalized.tolist(),
                        },
                        "FIT_PRESS": {"unit": fit_unit, "values": fitted.tolist()},
                    },
                }
                pending.append((capture_path, output_dir, payload))
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as error:
            self.view_distribution_busy = False
            self.view_distribution_button.label.set_text("Capture 3 Views")
            self.view_distribution_status.set_color("#fca5a5")
            self.view_distribution_status.set_text(
                f"Distribution: {str(error)[:54]}"
            )
            self.figure.canvas.draw_idle()
            return

        jobs: list[tuple[Path, Path]] = []
        try:
            for capture_path, output_dir, payload in pending:
                output_dir.mkdir(parents=True, exist_ok=False)
                with capture_path.open("x", encoding="utf-8", newline="\n") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                jobs.append((capture_path, output_dir))
                print(f"Saved view-distribution capture: {capture_path}")
        except OSError as error:
            self.view_distribution_busy = False
            self.view_distribution_button.label.set_text("Capture 3 Views")
            self.view_distribution_status.set_color("#fca5a5")
            self.view_distribution_status.set_text(
                f"Distribution save failed: {str(error)[:42]}"
            )
            self.figure.canvas.draw_idle()
            return

        self.view_distribution_busy = True
        self.view_distribution_button.label.set_text("Analyzing...")
        self.view_distribution_status.set_color("#fbbf24")
        self.view_distribution_status.set_text(
            f"Distribution: {'+'.join(layers)} at {actual_load_g:g} g"
        )
        self._clear_view_distribution_input()
        self.figure.canvas.draw_idle()
        threading.Thread(
            target=self._run_view_distribution_analysis,
            args=(jobs, layers, actual_load_g),
            daemon=True,
        ).start()

    def _run_view_distribution_analysis(
        self, jobs: list[tuple[Path, Path]], layers: tuple[str, ...], actual_load_g: float,
    ) -> None:
        script_path = (
            self._calibration_directory()
            / "script"
            / "Main"
            / "Evaluation"
            / VIEW_DISTRIBUTION_SCRIPT
        )
        try:
            for capture_path, output_dir in jobs:
                result = subprocess.run(
                    [
                        sys.executable, str(script_path), "--input", str(capture_path),
                        "--output-dir", str(output_dir),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout).strip().splitlines()
                    suffix = detail[-1][:80] if detail else f"exit {result.returncode}"
                    raise RuntimeError(suffix)
                print(result.stdout.strip())
            message = f"Distribution complete: {'+'.join(layers)} at {actual_load_g:g} g"
            color = "#86efac"
        except subprocess.TimeoutExpired:
            message = "Distribution failed: analysis timed out"
            color = "#fca5a5"
        except (FileNotFoundError, OSError, RuntimeError) as error:
            message = f"Distribution failed: {str(error)[:70]}"
            color = "#fca5a5"
        try:
            self.view_distribution_results.put_nowait((message, color))
        except queue.Full:
            pass

    def _poll_view_distribution_result(self) -> None:
        try:
            message, color = self.view_distribution_results.get_nowait()
        except queue.Empty:
            return
        self.view_distribution_busy = False
        self.view_distribution_button.label.set_text("Capture 3 Views")
        self.view_distribution_status.set_color(color)
        self.view_distribution_status.set_text(message)
        self.figure.canvas.draw_idle()

    def _load_pressure_area_model(self, fsr_name: str) -> Path:
        """Load the newest CAD-area pressure model for one module and FSR."""
        model_root = (
            self._calibration_directory()
            / "DATA"
            / f"module_{self.module_id}"
            / fsr_name
            / "fit"
            / "analysis"
        )
        candidates = [
            model_root / "pressure_code" / "pressure_response_area_model.json",
        ]
        candidates = [path for path in candidates if path.is_file()]
        if not candidates:
            # Backward-compatible read of the pre-fixed-folder layout.
            candidates = list(
                (model_root / "pressure").glob("*/pressure_response_area_model.json")
            )
        if not candidates:
            raise FileNotFoundError(
                f"no area pressure model for M{self.module_id}/{fsr_name}"
            )
        path = max(candidates, key=lambda candidate: candidate.stat().st_mtime_ns)
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("format") != "e-skin-fsr-pressure-response-area-model":
            raise ValueError(f"unsupported area pressure model in {path.name}")
        if data.get("source_module_id") != self.module_id:
            raise ValueError(f"area pressure model module does not match {path.name}")
        if data.get("source_fsr") != fsr_name:
            raise ValueError(f"area pressure model FSR does not match {path.name}")
        matrix = data.get("matrix", {})
        if matrix.get("rows") != ROWS or matrix.get("columns") != COLS:
            raise ValueError(f"area pressure model matrix shape is invalid in {path.name}")
        area_info = data.get("area", {})
        areas = np.asarray(area_info.get("matrix_mm2"), dtype=np.float64)
        if areas.shape != (ROWS, COLS) or not np.all(np.isfinite(areas)) or np.any(areas <= 0.0):
            raise ValueError(f"area matrix is invalid in {path.name}")
        cells = data.get("fit", {}).get("cells")
        if not isinstance(cells, list) or len(cells) != FSR_CELLS:
            raise ValueError(f"area pressure model must contain 256 cells in {path.name}")
        cell_models: list[list[dict[str, np.ndarray] | None]] = [
            [None for _ in range(COLS)] for _ in range(ROWS)
        ]
        for cell in cells:
            try:
                row = int(cell["row"]) - 1
                column = int(cell["column"]) - 1
                inverse = cell["pressure_from_adc"]
                adc_axis = np.asarray(inverse["x"], dtype=np.float64)
                pressure_axis = np.asarray(inverse["y"], dtype=np.float64)
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"invalid area pressure model cell in {path.name}") from error
            if not (0 <= row < ROWS and 0 <= column < COLS):
                raise ValueError(f"area pressure model cell index is invalid in {path.name}")
            if (
                adc_axis.ndim != 1
                or pressure_axis.ndim != 1
                or adc_axis.size == 0
                or adc_axis.size != pressure_axis.size
                or not np.all(np.isfinite(adc_axis))
                or not np.all(np.isfinite(pressure_axis))
            ):
                raise ValueError(f"invalid inverse LUT in {path.name}")
            cell_models[row][column] = {"adc": adc_axis, "pressure": pressure_axis}
        if any(model is None for row in cell_models for model in row):
            raise ValueError(f"area pressure model has missing cells in {path.name}")
        self.pressure_area_model_data[fsr_name] = {
            "cells": cell_models,
            "areas": areas,
            "path": path,
        }
        return path

    def _estimate_load_for_fsr(
        self, fsr_name: str, matrix: np.ndarray,
    ) -> tuple[float, int, Path, int]:
        path = self._load_pressure_area_model(fsr_name)
        model_data = self.pressure_area_model_data[fsr_name]
        areas = np.asarray(model_data["areas"], dtype=np.float64)
        cells = model_data["cells"]
        loads = np.empty((ROWS, COLS), dtype=np.float64)
        clipped = 0
        for row in range(ROWS):
            for column in range(COLS):
                lut = cells[row][column]
                if lut is None:
                    raise ValueError(f"missing inverse LUT for {fsr_name} R{row + 1}C{column + 1}")
                adc_axis = lut["adc"]
                pressure_axis = lut["pressure"]
                adc = float(matrix[row, column])
                if adc < adc_axis[0] or adc > adc_axis[-1]:
                    clipped += 1
                pressure_pa = float(np.interp(adc, adc_axis, pressure_axis))
                force_newton = pressure_pa * areas[row, column] * 1e-6
                loads[row, column] = force_newton / NEWTONS_PER_GRAM
        flat_loads = loads.ravel()
        # Keep the central empirical 95% of cell estimates. This filters
        # outliers in the cells, rather than forming a confidence interval for
        # the mean load itself.
        lower, upper = np.percentile(flat_loads, (2.5, 97.5))
        inlier_mask = (flat_loads >= lower) & (flat_loads <= upper)
        inlier_loads = flat_loads[inlier_mask]
        if inlier_loads.size == 0:
            raise ValueError(f"95% load interval has no valid cells for {fsr_name}")
        excluded = int(flat_loads.size - inlier_loads.size)
        return float(np.mean(inlier_loads)), clipped, path, excluded

    def _show_current_load(self, _event) -> None:
        """Average one second of frames before estimating the current load."""
        if self.load_capture_busy:
            return
        if self.view_distribution_busy:
            self.load_value_text.set_color("#fca5a5")
            self.load_value_text.set_text("— g")
            self.load_status.set_color("#fca5a5")
            self.load_status.set_text("Load: wait for distribution analysis")
            self.figure.canvas.draw_idle()
            return
        if self.latest is None or not self.latest.cache_valid or self.latest.family == "SPATIAL":
            self.load_value_text.set_color("#fca5a5")
            self.load_value_text.set_text("— g")
            self.load_status.set_color("#fca5a5")
            self.load_status.set_text("Load: waiting for FULL/DELTA")
            self.figure.canvas.draw_idle()
            return
        if self.mode == "ACC":
            self.load_value_text.set_color("#fca5a5")
            self.load_value_text.set_text("— g")
            self.load_status.set_color("#fca5a5")
            self.load_status.set_text("Load: select All/FSR1/FSR2")
            self.figure.canvas.draw_idle()
            return
        layers = (self.mode,) if self.mode in {"FSR1", "FSR2"} else ("FSR1", "FSR2")
        try:
            for layer in layers:
                self._load_pressure_area_model(layer)
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as error:
            self.load_value_text.set_color("#fca5a5")
            self.load_value_text.set_text("— g")
            self.load_status.set_color("#fca5a5")
            self.load_status.set_text(f"Load: {str(error)[:58]}")
            self.figure.canvas.draw_idle()
            return

        self._clear_measurement_frames()
        self.load_capture_busy = True
        self.load_capture_started_at = time.monotonic()
        self.load_capture_layers = layers
        self.load_capture_frames = []
        self.load_value_text.set_color("#fbbf24")
        self.load_value_text.set_text("… g")
        self.load_status.set_color("#fbbf24")
        self.load_status.set_text(
            f"Load: averaging 0/{AVERAGE_CAPTURE_SECONDS:g} s"
        )
        self.figure.canvas.draw_idle()

    def _finish_current_load_capture(self) -> None:
        """Calculate Load from the per-cell mean of the one-second sample."""
        self.load_capture_busy = False
        frames = self.load_capture_frames
        self.load_capture_frames = []
        layers = self.load_capture_layers
        if not frames:
            self.load_value_text.set_color("#fca5a5")
            self.load_value_text.set_text("— g")
            self.load_status.set_color("#fca5a5")
            self.load_status.set_text("Load: no valid frames in 1 s")
            self.figure.canvas.draw_idle()
            return

        matrices = {
            "FSR1": np.mean(
                np.stack([frame.fsr1 for frame in frames], axis=0), axis=0
            ),
            "FSR2": np.mean(
                np.stack([frame.fsr2 for frame in frames], axis=0), axis=0
            ),
        }
        results: list[float] = []
        clipped_total = 0
        excluded_total = 0
        loaded: list[str] = []
        try:
            for layer in layers:
                mean_load, clipped, path, excluded = self._estimate_load_for_fsr(
                    layer, matrices[layer]
                )
                results.append(mean_load)
                clipped_total += clipped
                excluded_total += excluded
                loaded.append(layer)
                print(f"Loaded area pressure model for current load: {path}")
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as error:
            self.load_value_text.set_color("#fca5a5")
            self.load_value_text.set_text("— g")
            self.load_status.set_color("#fca5a5")
            self.load_status.set_text(f"Load: {str(error)[:58]}")
            self.figure.canvas.draw_idle()
            return
        mean_load = float(np.mean(results))
        suffix_parts = []
        if excluded_total:
            suffix_parts.append(f"excluded {excluded_total}")
        if clipped_total:
            suffix_parts.append(f"clipped {clipped_total}")
        suffix_parts.append(f"averaged {len(frames)} frames")
        suffix = "; " + ", ".join(suffix_parts) if suffix_parts else ""
        self.load_value_text.set_color("#86efac")
        self.load_value_text.set_text(f"{mean_load:.1f} g")
        self.load_status.set_color("#86efac")
        self.load_status.set_text(f"{'+'.join(loaded)}{suffix}")
        self.figure.canvas.draw_idle()

    def _normalization_matrix(self, frame: DecodedFrame) -> np.ndarray | None:
        if not frame.cache_valid or frame.family == "SPATIAL":
            if frame.family == "SPATIAL":
                self.normalized_spatial_frames += 1
            return None
        matrix = frame.fsr1 if self.normalized_fsr_name == "FSR1" else frame.fsr2
        if matrix.shape != (ROWS, COLS):
            return None
        return np.array(matrix, dtype=np.uint16, copy=True)

    def _normalised_capture_status(self) -> None:
        phase_count = len(self.normalized_phase_frames)
        target = NORMALIZED_CALIBRATION_FRAME_COUNT
        if self.normalized_phase == "zero_capture":
            message = f"Norm Cal: zero load {phase_count}/{target}"
        else:
            corner = NORMALIZED_CORNER_LABELS[self.normalized_corner_index]
            message = f"Norm Cal: {corner} {phase_count}/{target}"
        self.normalized_calibration_status.set_color("#fbbf24")
        self.normalized_calibration_status.set_text(message)

    def _consume_normalized_frame(self, frame: DecodedFrame) -> None:
        if self.normalized_phase not in {"zero_capture", "corner_capture"}:
            return
        matrix = self._normalization_matrix(frame)
        if matrix is None:
            return
        self.normalized_phase_frames.append(matrix)
        count = len(self.normalized_phase_frames)
        if count < NORMALIZED_CALIBRATION_FRAME_COUNT:
            if count == 1 or count % 20 == 0:
                self._normalised_capture_status()
            return

        if self.normalized_phase == "zero_capture":
            self.normalized_zero_frames = self.normalized_phase_frames
            self.normalized_phase_frames = []
            self.normalized_phase = "await_corner"
            self.normalized_corner_index = 0
            corner = NORMALIZED_CORNER_LABELS[0]
            self.normalized_calibration_button.label.set_text(
                f"Capture {corner}"
            )
            self.normalized_calibration_status.set_color("#86efac")
            self.normalized_calibration_status.set_text(
                f"Norm Cal: zero done; apply full load at {corner}"
            )
            self.figure.canvas.draw_idle()
            return

        corner = NORMALIZED_CORNER_LABELS[self.normalized_corner_index]
        self.normalized_corner_frames[corner] = self.normalized_phase_frames
        self.normalized_phase_frames = []
        if self.normalized_corner_index + 1 < len(NORMALIZED_CORNER_LABELS):
            self.normalized_corner_index += 1
            next_corner = NORMALIZED_CORNER_LABELS[self.normalized_corner_index]
            self.normalized_phase = "await_corner"
            self.normalized_calibration_button.label.set_text(
                f"Capture {next_corner}"
            )
            self.normalized_calibration_status.set_color("#86efac")
            self.normalized_calibration_status.set_text(
                f"Norm Cal: move full load to {next_corner}"
            )
            self.figure.canvas.draw_idle()
            return

        self._finish_normalized_calibration()

    def _consume_normalized_frames(self) -> None:
        if self.calibration_frames is None:
            return
        while True:
            try:
                frame = self.calibration_frames.get_nowait()
            except queue.Empty:
                return
            if (frame.module_id is not None and
                    frame.module_id != self.normalized_module_id):
                continue
            self._consume_normalized_frame(frame)

    def _normalized_calibration_button_clicked(self, _event) -> None:
        if self.normalized_phase == "finalizing":
            return
        if self.calibration_frames is None:
            self.normalized_calibration_status.set_color("#fca5a5")
            self.normalized_calibration_status.set_text(
                "Norm Cal unavailable: no capture queue"
            )
            self.figure.canvas.draw_idle()
            return
        if self.calibration_phase != "idle":
            self.normalized_calibration_status.set_color("#fca5a5")
            self.normalized_calibration_status.set_text(
                "Norm Cal: finish Fit Cal first"
            )
            self.figure.canvas.draw_idle()
            return

        if self.normalized_phase == "idle":
            if self.mode not in {"FSR1", "FSR2"}:
                self.normalized_calibration_status.set_color("#fca5a5")
                self.normalized_calibration_status.set_text(
                    "Norm Cal: select FSR1 or FSR2 view"
                )
                self.figure.canvas.draw_idle()
                return
            self.normalized_module_id = self.module_id
            self.normalized_fsr_name = self.mode
            self.normalized_started_at = datetime.now(timezone.utc).isoformat()
            self.normalized_parse_errors_start = self.stats.parse_errors
            self.normalized_spatial_frames = 0
            self.normalized_zero_frames = []
            self.normalized_corner_frames = {}
            self.normalized_corner_index = 0
            self.normalized_phase_frames = []
            self.normalized_phase = "zero_capture"
            self.normalized_calibration_button.label.set_text("Capturing zero...")
            self.normalized_calibration_status.set_color("#fbbf24")
            self.normalized_calibration_status.set_text(
                f"Norm Cal M{self.normalized_module_id}/{self.normalized_fsr_name}: "
                "remove load"
            )
            self.figure.canvas.draw_idle()
            return

        if self.normalized_phase == "await_corner":
            self.normalized_phase = "corner_capture"
            self.normalized_phase_frames = []
            corner = NORMALIZED_CORNER_LABELS[self.normalized_corner_index]
            self.normalized_calibration_button.label.set_text(
                f"Capturing {corner}..."
            )
            self.normalized_calibration_status.set_color("#fbbf24")
            self.normalized_calibration_status.set_text(
                f"Norm Cal: press {corner}; collecting 0/"
                f"{NORMALIZED_CALIBRATION_FRAME_COUNT}"
            )
            self.figure.canvas.draw_idle()
            return

        if self.normalized_phase == "ready_to_save":
            self._finish_normalized_calibration()
            return

        self.normalized_calibration_status.set_color("#fbbf24")
        self.normalized_calibration_status.set_text(
            "Norm Cal: capture in progress"
        )
        self.figure.canvas.draw_idle()

    def _finish_normalized_calibration(self) -> None:
        if (
            self.normalized_fsr_name is None
            or self.normalized_started_at is None
            or len(self.normalized_zero_frames) != NORMALIZED_CALIBRATION_FRAME_COUNT
            or len(self.normalized_corner_frames) != len(NORMALIZED_CORNER_LABELS)
        ):
            self.normalized_phase = "idle"
            self.normalized_calibration_button.label.set_text("Start Norm Cal")
            self.normalized_calibration_status.set_color("#fca5a5")
            self.normalized_calibration_status.set_text(
                "Norm Cal failed: incomplete capture"
            )
            self.figure.canvas.draw_idle()
            return

        self.normalized_phase = "finalizing"
        self.normalized_calibration_button.label.set_text("Saving Norm...")
        try:
            path, problem_count = save_normalized_calibration(
                self._calibration_directory(),
                module_id=self.normalized_module_id,
                fsr_name=self.normalized_fsr_name,
                port_name=self.source,
                baud=self.baud,
                zero_frames=self.normalized_zero_frames,
                corner_frames=self.normalized_corner_frames,
                protocol_errors=max(
                    0, self.stats.parse_errors - self.normalized_parse_errors_start
                ),
                spatial_frames=self.normalized_spatial_frames,
            )
        except Exception as error:
            self.normalized_phase = "ready_to_save"
            self.normalized_calibration_button.label.set_text("Retry Norm Save")
            self.normalized_calibration_status.set_color("#fca5a5")
            self.normalized_calibration_status.set_text(
                f"Norm Cal failed; click retry: {str(error)[:55]}"
            )
            self.figure.canvas.draw_idle()
            return

        self.normalized_phase = "idle"
        self.normalized_calibration_button.label.set_text("Start Norm Cal")
        self.normalized_calibration_status.set_color("#86efac")
        self.normalized_calibration_status.set_text(
            f"Norm Cal saved; problem cells {problem_count}/256"
        )
        if self.display_mode == "NORMALIZED":
            self._load_display_data((self.normalized_fsr_name,))
            self._build_view()
            if self.latest is not None:
                self._render(self.latest)
        print(f"Saved normalised calibration: {path}")
        self.figure.canvas.draw_idle()

    def _run_pyocd_reset(self) -> None:
        command = [self.pyocd_executable, "reset", "--no-wait"]
        if self.pyocd_uid:
            command.extend(("--uid", self.pyocd_uid))
        if self.pyocd_target:
            command.extend(("--target", self.pyocd_target))
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except FileNotFoundError:
            message = f"pyOCD not found: {self.pyocd_executable}"
        except subprocess.TimeoutExpired:
            message = "pyOCD reset timed out"
        except OSError as error:
            message = f"pyOCD error: {error}"
        else:
            if result.returncode == 0:
                message = "pyOCD reset OK"
            else:
                detail = (result.stderr or result.stdout).strip().splitlines()
                suffix = detail[-1][:100] if detail else f"exit {result.returncode}"
                message = f"pyOCD failed: {suffix}"
        try:
            self.pyocd_results.put_nowait(message)
        except queue.Full:
            pass

    def _run_pressure_analysis(
        self, sweep_path: Path, output_dir: Path, load_unit: str,
    ) -> None:
        """Fit the current shared-endpoint sweep and save its model plots."""
        del load_unit
        calibration_dir = self._calibration_directory()
        fit_script_path = (
            calibration_dir / "script" / "Main" / "Model" / PRESSURE_ANALYSIS_SCRIPT
        )
        command = [
            sys.executable, "-B", str(fit_script_path),
            "--input", str(sweep_path),
            "--output-dir", str(output_dir),
            "--protocol", "whole_layer_shared_endpoints_v3",
            "--per-cell-grid",
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=240, check=False
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip().splitlines()
                suffix = detail[-1][:100] if detail else f"exit {result.returncode}"
                message, color = f"Fit failed: {suffix}", "#fca5a5"
            else:
                print(result.stdout.strip())
                message, color = "Current calibration fit and plots saved", "#86efac"
        except (FileNotFoundError, OSError) as error:
            message, color = f"Fit failed: {str(error)[:80]}", "#fca5a5"
        except subprocess.TimeoutExpired:
            message, color = "Fit failed: analysis timed out", "#fca5a5"
        try:
            self.calibration_analysis_results.put_nowait((message, color))
        except queue.Full:
            pass
    def _poll_pressure_analysis_result(self) -> None:
        try:
            message, color = self.calibration_analysis_results.get_nowait()
        except queue.Empty:
            return
        self._set_calibration_status(message, color)

    def _poll_pyocd_result(self) -> None:
        try:
            message = self.pyocd_results.get_nowait()
        except queue.Empty:
            return
        self.pyocd_busy = False
        self.pyocd_button.label.set_text("pyOCD Reset")
        self.pyocd_status.set_text(message)
        self.figure.canvas.draw_idle()

    def _select_module(self, label: str) -> None:
        self.module_id = int(label[1:])
        if self.calibration_phase == "idle":
            self.calibration_status.set_text(
                f"Fit Cal: M{self.module_id}; select FSR1/FSR2"
            )
        if self.display_mode != "RAW":
            try:
                self._load_display_data(self._calibration_fsrs_for_view())
            except (FileNotFoundError, KeyError, OSError, ValueError) as error:
                self.display_mode = "RAW"
                self._update_display_buttons()
                self._set_calibration_status(
                    f"Display reset to source: {str(error)[:70]}", "#fbbf24"
                )
            else:
                self._set_calibration_status(
                    f"Display: {self.display_mode.lower()} M{self.module_id}", "#86efac"
                )
        self._build_view()
        selected_latest = self.latest_by_module.get(self.module_id)
        if selected_latest is not None:
            self.latest = selected_latest
        if self.latest is not None:
            self._render(self.latest)
        self.figure.canvas.draw_idle()

    def _set_calibration_status(self, message: str, color: str = "#94a3b8") -> None:
        self.calibration_status.set_color(color)
        self.calibration_status.set_text(message)
        self.figure.canvas.draw_idle()

    def _calibration_directory(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _load_calibration(self, fsr_name: str, module_id: int | None = None) -> Path:
        selected_module = self.module_id if module_id is None else module_id
        two_point_dir = (
            self._calibration_directory()
            / "DATA"
            / f"module_{selected_module}"
            / fsr_name
            / "two_point"
        )
        candidates = sorted(two_point_dir.glob(f"{fsr_name}_calibration_*.json"))
        if not candidates:
            raise FileNotFoundError(
                f"no {fsr_name} calibration for module M{selected_module}"
            )
        path = candidates[-1]
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("module_id") != selected_module or data.get("fsr") != fsr_name:
            raise ValueError(f"calibration metadata does not match {path.name}")
        calibration = data.get("calibration", {})
        low = np.asarray(calibration["interval_low_zero"], dtype=np.float64)
        high = np.asarray(calibration["interval_high_full"], dtype=np.float64)
        if low.shape != (ROWS, COLS) or high.shape != (ROWS, COLS):
            raise ValueError(f"calibration matrix shape is invalid in {path.name}")
        span = high - low
        self.calibration_data[fsr_name] = {
            "low": low,
            "high": high,
            "span": np.where(span > 0.0, span, 1.0),
        }
        return path

    def _load_pressure_model(self, fsr_name: str, module_id: int | None = None) -> Path:
        """Load the newest per-cell pressure model for one module and FSR."""
        selected_module = self.module_id if module_id is None else module_id
        analysis_dir = (
            self._calibration_directory()
            / "DATA"
            / f"module_{selected_module}"
            / fsr_name
            / "fit"
            / "analysis"
        )
        candidates = [analysis_dir / "load_code" / "pressure_response_model.json"]
        candidates = [path for path in candidates if path.is_file()]
        if not candidates:
            # Backward-compatible read of the pre-fixed-folder layout.
            candidates = sorted(analysis_dir.glob("*/pressure_response_model.json"))
        if not candidates:
            raise FileNotFoundError(
                f"no pressure model for M{selected_module}/{fsr_name}"
            )
        path = candidates[-1]
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        model_format = data.get("format")
        supported_formats = {
            "e-skin-fsr-pressure-response-model",
            "e-skin-fsr-pressure-response-monotonic-model",
        }
        if model_format not in supported_formats:
            raise ValueError(f"unsupported pressure model format in {path.name}")
        if data.get("source_module_id") != selected_module:
            raise ValueError(f"pressure model module does not match {path.name}")
        if data.get("source_fsr") != fsr_name:
            raise ValueError(f"pressure model FSR does not match {path.name}")
        matrix = data.get("matrix", {})
        if matrix.get("rows") != ROWS or matrix.get("columns") != COLS:
            raise ValueError(f"pressure model matrix shape is invalid in {path.name}")

        pressure_range = data.get("pressure_range", {})
        try:
            pressure_min = float(pressure_range["min"])
            pressure_max = float(pressure_range["max"])
        except (KeyError, TypeError, ValueError):
            pressure_min = pressure_max = float("nan")

        fit = data.get("fit", {})
        cells = fit.get("cells")
        if not isinstance(cells, list) or len(cells) != FSR_CELLS:
            raise ValueError(f"pressure model must contain 256 cells in {path.name}")
        if not np.isfinite(pressure_min) or not np.isfinite(pressure_max):
            try:
                first_forward = cells[0]["adc_from_pressure"]
                pressure_min = float(first_forward["x_min"])
                pressure_max = float(first_forward["x_max"])
            except (KeyError, TypeError, ValueError, IndexError) as error:
                raise ValueError(f"pressure range is missing in {path.name}") from error
        if pressure_max <= pressure_min:
            raise ValueError(f"pressure range is invalid in {path.name}")

        cell_models: list[list[dict[str, object] | None]] = [
            [None for _ in range(COLS)] for _ in range(ROWS)
        ]
        for cell in cells:
            try:
                row = int(cell["row"]) - 1
                column = int(cell["column"]) - 1
                model = cell["pressure_from_adc"]
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"invalid pressure model cell in {path.name}") from error
            if not (0 <= row < ROWS and 0 <= column < COLS):
                raise ValueError(f"pressure model cell index is invalid in {path.name}")
            try:
                if model_format == "e-skin-fsr-pressure-response-monotonic-model":
                    adc_axis = np.asarray(model["x"], dtype=np.float64)
                    pressure_axis = np.asarray(model["y"], dtype=np.float64)
                    if (
                        adc_axis.ndim != 1
                        or pressure_axis.ndim != 1
                        or adc_axis.size == 0
                        or adc_axis.size != pressure_axis.size
                        or not np.all(np.isfinite(adc_axis))
                        or not np.all(np.isfinite(pressure_axis))
                        or (
                            adc_axis.size > 1
                            and not np.all(np.diff(adc_axis) > 0.0)
                        )
                    ):
                        raise ValueError("invalid monotonic LUT")
                    cell_models[row][column] = {
                        "type": "linear_lut",
                        "x": adc_axis,
                        "y": pressure_axis,
                        "x_min": float(adc_axis[0]),
                        "x_max": float(adc_axis[-1]),
                    }
                else:
                    coefficients = np.asarray(model["coefficients"], dtype=np.float64)
                    center = float(model["x_center"])
                    scale = float(model["x_scale"])
                    x_min = float(model["x_min"])
                    x_max = float(model["x_max"])
                    if coefficients.ndim != 1 or coefficients.size == 0:
                        raise ValueError("invalid polynomial coefficients")
                    if not np.all(np.isfinite(coefficients)):
                        raise ValueError("polynomial coefficients are non-finite")
                    if not all(np.isfinite(value) for value in (center, scale, x_min, x_max)):
                        raise ValueError("polynomial bounds are invalid")
                    cell_models[row][column] = {
                        "type": "polynomial",
                        "coefficients": coefficients,
                        "x_center": center,
                        "x_scale": max(abs(scale), 1.0),
                        "x_min": min(x_min, x_max),
                        "x_max": max(x_min, x_max),
                    }
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"invalid pressure model cell in {path.name}") from error
        if any(model is None for row in cell_models for model in row):
            raise ValueError(f"pressure model has missing cells in {path.name}")

        pressure_info = data.get("pressure", {})
        unit = pressure_info.get("unit", "user-defined") if isinstance(pressure_info, dict) else "user-defined"
        self.pressure_model_data[fsr_name] = {
            "cells": cell_models,
            "pressure_min": pressure_min,
            "pressure_max": pressure_max,
            "unit": str(unit),
            "path": path,
        }
        return path

    def _load_display_data(self, fsr_names: tuple[str, ...]) -> list[str]:
        loaded: list[str] = []
        for fsr_name in fsr_names:
            if self.display_mode == "PRESSURE":
                self._load_pressure_model(fsr_name)
            else:
                self._load_calibration(fsr_name)
            loaded.append(fsr_name)
        return loaded

    def _calibration_fsrs_for_view(self) -> tuple[str, ...]:
        if self.mode == "FSR1":
            return ("FSR1",)
        if self.mode == "FSR2":
            return ("FSR2",)
        if self.mode == "All":
            return ("FSR1", "FSR2")
        return ()

    def _update_display_buttons(self) -> None:
        """Highlight the selected display source without coupling the modes."""
        buttons = {
            "NORMALIZED": self.normalized_button,
            "PRESSURE": self.pressure_display_button,
            "RAW": self.raw_display_button,
        }
        for mode, button in buttons.items():
            active = mode == self.display_mode
            button.ax.set_facecolor("#28523a" if active else "#26324a")
            button.label.set_color("#86efac" if active else "white")

    def _set_display_mode(self, requested_mode: str) -> None:
        """Select one display/calibration path; never fall back to another path."""
        if requested_mode not in {"RAW", "NORMALIZED", "PRESSURE"}:
            raise ValueError(f"unsupported display mode: {requested_mode}")

        required = self._calibration_fsrs_for_view()
        if requested_mode != "RAW" and not required:
            self._set_calibration_status(
                "Display applies to FSR1/FSR2 views", "#fca5a5"
            )
            return

        previous_mode = self.display_mode
        self.display_mode = requested_mode
        if requested_mode != "RAW":
            try:
                loaded = self._load_display_data(required)
            except (FileNotFoundError, KeyError, OSError, ValueError) as error:
                self.display_mode = previous_mode
                self._update_display_buttons()
                self._set_calibration_status(
                    f"{requested_mode} unavailable M{self.module_id}: "
                    f"{str(error)[:60]}",
                    "#fca5a5",
                )
                return
            label = "normalized" if requested_mode == "NORMALIZED" else "fitted pressure"
            self._set_calibration_status(
                f"Display: {label} M{self.module_id}/" + "+".join(loaded),
                "#86efac",
            )
        else:
            self._set_calibration_status("Display: source ADC data", "#86efac")

        self._update_display_buttons()
        self._build_view()
        if self.latest is not None:
            self._render(self.latest)
        self.figure.canvas.draw_idle()

    def _show_normalized_display(self, _event) -> None:
        self._set_display_mode("NORMALIZED")

    def _show_pressure_display(self, _event) -> None:
        self._set_display_mode("PRESSURE")

    def _show_raw_display(self, _event) -> None:
        self._set_display_mode("RAW")

    def _gamma_submitted(self, _value: str) -> None:
        self._apply_gamma(None)

    def _apply_gamma(self, _event) -> None:
        try:
            gamma = float(self.gamma_box.text.strip())
        except ValueError:
            self.gamma_status.set_color("#fca5a5")
            self.gamma_status.set_text("γ must be 1–10")
            self.figure.canvas.draw_idle()
            return
        if not np.isfinite(gamma) or not 1.0 <= gamma <= 10.0:
            self.gamma_status.set_color("#fca5a5")
            self.gamma_status.set_text("γ must be 1–10")
            self.figure.canvas.draw_idle()
            return
        self.calibration_gamma = gamma
        self.gamma_status.set_color("#86efac")
        self.gamma_status.set_text(f"γ={gamma:g}")
        if self.latest is not None:
            self._render(self.latest)
        self.figure.canvas.draw_idle()

    def _calibration_button_clicked(self, _event) -> None:
        if self.calibration_phase == "finalizing":
            return
        if self.normalized_phase != "idle":
            self._set_calibration_status(
                "Fit Cal: finish Norm Cal first", "#fca5a5"
            )
            return

        if self.calibration_phase == "idle":
            if self.mode not in {"FSR1", "FSR2"}:
                self._set_calibration_status(
                    "Fit Cal: select FSR1 or FSR2 view", "#fca5a5"
                )
                return
            if self.latest is None or not self.latest.cache_valid:
                self._set_calibration_status(
                    "Fit Cal: waiting for a valid full matrix", "#fca5a5"
                )
                return
            if self.latest.family == "SPATIAL":
                self._set_calibration_status(
                    "Fit Cal: use FULL or DELTA, not SPATIAL", "#fca5a5"
                )
                return
            zero_matrix = self.latest.fsr1 if self.mode == "FSR1" else self.latest.fsr2
            if zero_matrix.shape != (ROWS, COLS):
                self._set_calibration_status(
                    "Fit Cal: invalid 16x16 matrix", "#fca5a5"
                )
                return
            self.calibration_module_id = self.module_id
            self.calibration_fsr_name = self.mode
            self.calibration_pressure_points = []
            self.pressure_submit_consumed = False
            self.calibration_started_at = datetime.now(timezone.utc).isoformat()
            self.calibration_parse_errors_start = self.stats.parse_errors
            self.calibration_phase = "pressure_capture"
            self.calibration_button.label.set_text("End Fit Cal")
            self.calibration_record_button.label.set_text("Record")
            self._record_pressure_point("0")
            self.pressure_submit_consumed = False
            self._set_calibration_status(
                f"M{self.calibration_module_id}/{self.calibration_fsr_name}: "
                "0 g recorded; enter the next load"
            )
            return

        if self.calibration_phase == "pressure_capture":
            self._finish_calibration()

    def _record_pressure_point(self, _event=None) -> None:
        if self.calibration_phase != "pressure_capture":
            self._set_calibration_status(
                "Fit Cal: click Start Fit Cal before Record", "#fca5a5"
            )
            return
        entered_value = (
            _event
            if isinstance(_event, str)
            else getattr(self.calibration_pressure_box, "text", "")
        )
        if not str(entered_value).strip() and not isinstance(_event, str):
            # Clicking Record can follow TextBox's focus-loss submit. That
            # first callback has already recorded and cleared the value.
            if self.pressure_submit_consumed:
                self.pressure_submit_consumed = False
                return
        try:
            pressure = float(str(entered_value).strip())
        except (TypeError, ValueError):
            self._set_calibration_status(
                "Fit Cal: enter a numeric pressure value", "#fca5a5"
            )
            return
        if not np.isfinite(pressure):
            self._set_calibration_status(
                "Fit Cal: pressure must be finite", "#fca5a5"
            )
            return
        if self.latest is None or not self.latest.cache_valid:
            self._set_calibration_status(
                "Fit Cal: waiting for a valid full matrix", "#fca5a5"
            )
            return
        if self.latest.family == "SPATIAL":
            self._set_calibration_status(
                "Fit Cal: use FULL or DELTA, not SPATIAL", "#fca5a5"
            )
            return
        matrix = (
            self.latest.fsr1
            if self.calibration_fsr_name == "FSR1"
            else self.latest.fsr2
        )
        if matrix.shape != (ROWS, COLS):
            self._set_calibration_status(
                "Fit Cal: invalid 16x16 matrix", "#fca5a5"
            )
            return
        self.calibration_pressure_points.append(
            {
                "index": len(self.calibration_pressure_points) + 1,
                "pressure": pressure,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "sequence": int(self.latest.sequence),
                "marker": self.latest.marker,
                "family": self.latest.family,
                "raw_adc": np.asarray(matrix, dtype=np.uint16).tolist(),
            }
        )
        self._set_calibration_status(
            f"{self.calibration_fsr_name}: point "
            f"{len(self.calibration_pressure_points)} ({pressure:g} g) recorded, "
            "enter next load",
            "#86efac",
        )
        self.pressure_submit_consumed = isinstance(_event, str)
        self._clear_pressure_input()

    def _clear_pressure_input(self) -> None:
        """Clear TextBox text without recursively submitting an empty value."""
        eventson = self.calibration_pressure_box.eventson
        self.calibration_pressure_box.eventson = False
        try:
            self.calibration_pressure_box.set_val("")
        finally:
            self.calibration_pressure_box.eventson = eventson

    def _finish_calibration(self) -> None:
        pressures = [float(point["pressure"]) for point in self.calibration_pressure_points]
        if len(self.calibration_pressure_points) < 2 or len(set(pressures)) < 2:
            self._set_calibration_status(
                "Fit Cal: record at least 2 different pressures", "#fca5a5"
            )
            return
        if self.calibration_fsr_name is None or self.calibration_started_at is None:
            self.calibration_phase = "idle"
            self.calibration_button.label.set_text("Start Fit Cal")
            self._set_calibration_status(
                "Fit Cal failed: session is incomplete", "#fca5a5"
            )
            return

        self.calibration_phase = "finalizing"
        self.calibration_button.label.set_text("Saving Fit...")
        try:
            calibration_dir = self._calibration_directory()
            path = save_pressure_sweep(
                calibration_dir,
                module_id=self.calibration_module_id,
                fsr_name=self.calibration_fsr_name,
                port_name=self.source,
                baud=self.baud,
                pressure_unit=CALIBRATION_LOAD_UNIT,
                started_at=self.calibration_started_at,
                points=self.calibration_pressure_points,
                protocol_errors=max(
                    0, self.stats.parse_errors - self.calibration_parse_errors_start
                ),
            )
        except Exception as error:
            self.calibration_phase = "pressure_capture"
            self.calibration_button.label.set_text("End Fit Cal")
            self._set_calibration_status(
                f"Fit Cal failed: {str(error)[:80]}", "#fca5a5"
            )
            return

        self.calibration_phase = "idle"
        self.calibration_button.label.set_text("Start Fit Cal")
        self._set_calibration_status(
            f"Saved Fit Cal {self.calibration_fsr_name}: "
            f"{len(self.calibration_pressure_points)} points; analyzing...",
            "#fbbf24",
        )
        print(f"Saved pressure sweep: {path}")
        analysis_dir = (
            path.parent.parent
            / "analysis"
            / "load_code"
        )
        threading.Thread(
            target=self._run_pressure_analysis,
            args=(path, analysis_dir, CALIBRATION_LOAD_UNIT),
            daemon=True,
        ).start()

    def _select_view(self, label: str) -> None:
        self.mode = label
        if self.display_mode != "RAW":
            required = self._calibration_fsrs_for_view()
            try:
                self._load_display_data(required)
            except (FileNotFoundError, KeyError, OSError, ValueError) as error:
                self.display_mode = "RAW"
                self._update_display_buttons()
                self._set_calibration_status(
                    f"Display reset to source: {str(error)[:70]}", "#fbbf24"
                )
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

    def _add_fsr(self, spec, key: str, title: str, compact: bool) -> None:
        from matplotlib.collections import PolyCollection
        from matplotlib.patches import Polygon
        import matplotlib

        axis = self.figure.add_subplot(spec)
        axis.set_facecolor("#080a0d")
        fsr_name = key.upper()
        normalized = (
            self.display_mode == "NORMALIZED"
            and fsr_name in self.calibration_data
        )
        pressure = (
            self.display_mode == "PRESSURE"
            and fsr_name in self.pressure_model_data
        )
        if normalized:
            norm_min, norm_max = 0.0, 1.0
            colourbar_label = "calibrated load / full-load"
        elif pressure:
            model_data = self.pressure_model_data[fsr_name]
            norm_min = float(model_data["pressure_min"])
            norm_max = float(model_data["pressure_max"])
            unit = str(model_data["unit"])
            colourbar_label = f"pressure ({unit})"
        else:
            norm_min, norm_max = 0.0, ADC_MAX
            colourbar_label = "raw ADC / 4095"
        collection = PolyCollection(
            cell_polygons(), array=np.zeros(FSR_CELLS), cmap="inferno",
            norm=matplotlib.colors.Normalize(norm_min, norm_max),
            edgecolors=(1, 1, 1, 0.18), linewidths=0.35 if compact else 0.45,
        )
        axis.add_collection(collection)
        axis.add_patch(Polygon(
            board_outline(), closed=True, fill=False,
            edgecolor=(0.88, 0.92, 1, 0.9), linewidth=1.8,
        ))
        axis.set_xlim(-1.13, 1.13)
        axis.set_ylim(-1.13, 1.13)
        axis.set_aspect("equal")
        axis.axis("off")
        if normalized:
            display_suffix = " / normalized"
        elif pressure:
            display_suffix = " / pressure"
        else:
            display_suffix = " / source"
        axis.set_title(title + display_suffix, color="white", pad=16)
        add_grid_labels(axis, compact)
        colourbar = self.figure.colorbar(collection, ax=axis, fraction=0.038,
                                         pad=0.025, label=colourbar_label)
        self.content_axes.extend((axis, colourbar.ax))
        self.fsr_artists[key] = collection

    def _add_acc_text(self, spec) -> None:
        axis = self.figure.add_subplot(spec)
        axis.set_facecolor("#080a0d")
        axis.axis("off")
        axis.set_title("ACC data / protocol status (text only)", color="white", pad=8)
        self.content_axes.append(axis)
        self.acc_axis = axis

    def _linear_fsr_values(self, fsr_name: str, raw: np.ndarray) -> np.ndarray:
        calibration = self.calibration_data.get(fsr_name)
        if calibration is None:
            raise ValueError(f"no normalized calibration loaded for {fsr_name}")
        value = (raw.astype(np.float64) - calibration["low"]) / calibration["span"]
        return np.clip(value, 0.0, 1.0)

    def _normalized_fsr_values(self, fsr_name: str, raw: np.ndarray) -> np.ndarray:
        calibration = self.calibration_data.get(fsr_name)
        if calibration is None:
            raise ValueError(f"no normalized calibration loaded for {fsr_name}")
        value = (raw.astype(np.float64) - calibration["low"]) / calibration["span"]
        value = np.clip(value, 0.0, 1.0)
        # Keep this identical to the NORM CAL heatmap shown by the GUI.
        return np.power(value, self.calibration_gamma)

    def _fitted_fsr_values(self, fsr_name: str, raw: np.ndarray) -> np.ndarray:
        model_data = self.pressure_model_data.get(fsr_name)
        if model_data is None:
            raise ValueError(f"no fitted response model loaded for {fsr_name}")
        cells = model_data["cells"]
        pressure_min = float(model_data["pressure_min"])
        pressure_max = float(model_data["pressure_max"])
        result = np.empty((ROWS, COLS), dtype=np.float64)
        for row in range(ROWS):
            for column in range(COLS):
                model = cells[row][column]
                if model is None:
                    raise ValueError(f"missing fitted model for {fsr_name}")
                raw_value = float(
                    np.clip(
                        raw[row, column],
                        float(model["x_min"]),
                        float(model["x_max"]),
                    )
                )
                if model.get("type") == "linear_lut":
                    pressure_value = float(
                        np.interp(raw_value, model["x"], model["y"])
                    )
                else:
                    normalised = (
                        raw_value - float(model["x_center"])
                    ) / float(model["x_scale"])
                    pressure_value = float(
                        np.polyval(
                            np.asarray(model["coefficients"], dtype=np.float64),
                            normalised,
                        )
                    )
                if not np.isfinite(pressure_value):
                    raise ValueError(f"non-finite fitted value for {fsr_name}")
                result[row, column] = np.clip(
                    pressure_value, pressure_min, pressure_max,
                )
        return result

    def _display_fsr(self, fsr_name: str, raw: np.ndarray) -> np.ndarray:
        if self.display_mode == "RAW":
            return raw
        try:
            if self.display_mode == "NORMALIZED":
                return self._normalized_fsr_values(fsr_name, raw)
            return self._fitted_fsr_values(fsr_name, raw)
        except (KeyError, TypeError, ValueError):
            return raw

    def _build_view(self) -> None:
        self._remove_content()
        if self.mode == "All":
            grid = self.figure.add_gridspec(
                1, 2, left=0.16, right=0.84, bottom=0.06, top=0.86,
            )
            self._add_fsr(grid[0, 0], "fsr1", "FSR1 / left", True)
            self._add_fsr(grid[0, 1], "fsr2", "FSR2 / right", True)
        elif self.mode == "FSR1":
            grid = self.figure.add_gridspec(1, 1, left=0.16, right=0.84,
                                            bottom=0.06, top=0.86)
            self._add_fsr(grid[0], "fsr1", "FSR1 / left", False)
        elif self.mode == "FSR2":
            grid = self.figure.add_gridspec(1, 1, left=0.16, right=0.84,
                                            bottom=0.06, top=0.86)
            self._add_fsr(grid[0], "fsr2", "FSR2 / right", False)
        else:
            grid = self.figure.add_gridspec(1, 1, left=0.08, right=0.86,
                                            bottom=0.05, top=0.86)
            self._add_acc_text(grid[0])

    def _render_acc_text(self, frame: DecodedFrame) -> int:
        if self.acc_axis is None:
            return sum(sample.valid for sample in frame.acc)
        valid_count = 0
        lines = [
            f"marker: {frame.marker}",
            f"family: {frame.family}",
            f"sequence: {frame.sequence}",
            f"base: {frame.base_sequence}",
            f"changed: {frame.changed_count}",
            f"sampled: {frame.sampled_count}",
            "",
        ]
        if not frame.acc:
            lines.append("ACC: unavailable in active four-module FSR-only firmware")
        for index, sample in enumerate(frame.acc, start=1):
            valid_count += int(sample.valid)
            lines.append(
                f"ACC{index}: WHO=0x{sample.who:02X} status={sample.status} "
                f"({sample.x:5d},{sample.y:5d},{sample.z:5d})"
            )
        self.acc_axis.clear()
        self.acc_axis.axis("off")
        self.acc_axis.set_title("ACC data / protocol status (text only)",
                                color="white", pad=8)
        self.acc_axis.text(0.02, 0.98, "\n".join(lines), va="top",
                           family="monospace", color="white")
        return valid_count

    def _render(self, frame: DecodedFrame) -> None:
        if "fsr1" in self.fsr_artists:
            self.fsr_artists["fsr1"].set_array(
                oriented_fsr(self._display_fsr("FSR1", frame.fsr1)).ravel()
            )
        if "fsr2" in self.fsr_artists:
            self.fsr_artists["fsr2"].set_array(
                oriented_fsr(self._display_fsr("FSR2", frame.fsr2)).ravel()
            )
        valid_count = sum(sample.valid for sample in frame.acc)
        if self.acc_axis is not None:
            self._render_acc_text(frame)
        bytes_per_second, frames_per_second = self.stats.data_rate()
        algorithm = {
            "FULL": "FULL",
            "DELTA": "DELTA",
            "SPATIAL": "SPATIAL SPARSE",
        }.get(frame.family, frame.family)
        if frame.flags & SPATIAL_FLAG and frame.marker == "ESKF":
            algorithm = "SPATIAL FALLBACK (FULL)"
        module_status = self.stats.module_statuses[self.module_id]
        self.algorithm_text.set_text(
            f"Algorithm: {algorithm} | protocol frame: {frame.marker} | "
            f"cache: {'valid' if frame.cache_valid else 'invalid'} | "
            f"M{self.module_id}: {module_status_name(module_status)}"
        )
        self.rate_text.set_text(
            f"Measured USB data rate: {bytes_per_second:,.1f} B/s | "
            f"{bytes_per_second * 8.0 / 1_000_000.0:.4f} Mbit/s | "
            f"{frames_per_second:.1f} USB packets/s | "
            f"last frame {self.stats.last_frame_bytes} B"
        )
        cache = "cache OK" if frame.cache_valid else "cache invalid"
        acc_text = (f"ACC {valid_count}/{len(frame.acc)}"
                    if frame.acc else "ACC unavailable")
        self.title.set_text(
            f"M{self.module_id} | {self.mode} | {frame.marker} | frame {frame.sequence} | "
            f"K {frame.changed_count} | S {frame.sampled_count} | "
            f"{acc_text} | {module_status_name(module_status)} | "
            f"{cache} | {frame.note} | parser errors {self.stats.parse_errors}"
        )

    def _update(self, _index: int) -> None:
        self._poll_pyocd_result()
        self._poll_pressure_analysis_result()
        self._poll_view_distribution_result()
        self._consume_normalized_frames()
        self._consume_measurement_frames()
        newest = None
        while True:
            try:
                frame = self.frames.get_nowait()
            except queue.Empty:
                break
            newest = frame
            if frame.module_id is not None:
                self.latest_by_module[frame.module_id] = frame
        if newest is None and self.module_id in self.latest_by_module:
            newest = self.latest_by_module[self.module_id]
        elif newest is not None and self.module_id in self.latest_by_module:
            newest = self.latest_by_module[self.module_id]
        if newest is None:
            bytes_per_second, frames_per_second = self.stats.data_rate()
            self.rate_text.set_text(
                f"Measured USB data rate: {bytes_per_second:,.1f} B/s | "
                f"{bytes_per_second * 8.0 / 1_000_000.0:.4f} Mbit/s | "
                f"{frames_per_second:.1f} USB packets/s"
            )
            self.algorithm_text.set_text(
                "Algorithm: waiting for a valid frame"
            )
            self.title.set_text(
                f"Waiting for {self.source} | parser errors={self.stats.parse_errors} | "
                f"{self.stats.last_error}"
            )
            return
        self.latest = newest
        self.stats.displayed += 1
        self._render(newest)
        self.figure.canvas.draw_idle()

    def show(self) -> None:
        self.plt.show()


def run_gui(
    port_name: str,
    baud: int,
    view: str,
    module_id: int,
    pyocd_executable: str,
    pyocd_uid: str | None,
    pyocd_target: str | None,
) -> None:
    # A single MUL1 packet can produce one decoded frame per module.  Keep
    # enough room for the complete round so the selected module is not lost.
    frames: queue.Queue[DecodedFrame] = queue.Queue(maxsize=MODULE_COUNT * 2)
    calibration_frames: queue.Queue[DecodedFrame] = queue.Queue(maxsize=2048)
    measurement_frames: queue.Queue[DecodedFrame] = queue.Queue(maxsize=4096)
    stats = MonitorStats()
    stop = threading.Event()
    worker = threading.Thread(
        target=serial_worker,
        args=(
            port_name, baud, frames, stats, stop, calibration_frames,
            measurement_frames,
        ),
        daemon=True,
    )
    worker.start()
    from calibration_shared_endpoints import make_calibration_gui
    gui_type = make_calibration_gui(SquareScalabilityGui)
    gui = gui_type(
        frames, stats, stop, port_name, baud, view, 30,
        module_id,
        pyocd_executable, pyocd_uid, pyocd_target,
        calibration_frames,
        measurement_frames,
    )
    try:
        gui.show()
    finally:
        stop.set()
        worker.join(timeout=1.5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9", help="Teensy USB serial port")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument(
        "--view", choices=("all", "fsr1", "fsr2", "acc"), default="all"
    )
    parser.add_argument(
        "--module", type=int, choices=range(4), default=0,
        help="module ID used to classify calibration output (0-3)",
    )
    parser.add_argument(
        "--pyocd", default="pyocd",
        help="pyOCD executable used by the GUI reset button",
    )
    parser.add_argument(
        "--pyocd-uid", default=None,
        help="optional pyOCD probe UID when multiple probes are connected",
    )
    parser.add_argument(
        "--pyocd-target", default=None,
        help="optional pyOCD target name, for example stm32g474re",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    run_gui(
        args.port, args.baud, args.view, args.module,
        args.pyocd, args.pyocd_uid, args.pyocd_target,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

