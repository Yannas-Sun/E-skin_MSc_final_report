"""Capture and inspect the current four-module MUL1 v2 USB byte stream."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import struct
import sys
import time
import zlib

try:
    import serial
except ImportError as exc:  # pragma: no cover - environment diagnostic
    raise SystemExit("pyserial is required: python -m pip install pyserial") from exc


MAGIC = b"MUL1"
MUL_VERSION = 2
MODULE_COUNT = 4
HEADER_BYTES = 20
TRAILER_BYTES = 4
STATUS_NAMES = {
    0: "OK",
    1: "BAD_FRAME",
    2: "BAD_CRC",
    3: "NO_IRQ",
    4: "TIMEOUT",
    5: "MODE_TRANSITION",
    6: "RESYNC_NEEDED",
    7: "BAD_VERSION",
}


def status_name(status: int) -> str:
    if status == 0:
        return "OK"
    if status & 0x80:
        return STATUS_NAMES.get(status & 0x0F, f"NOT_UPDATED_{status & 0x0F}")
    return STATUS_NAMES.get(status, f"ERROR_{status}")


def describe_packet(packet: bytes) -> list[str]:
    if len(packet) < HEADER_BYTES + TRAILER_BYTES:
        return [f"INVALID short_packet bytes={len(packet)}"]

    version = packet[4]
    modules = packet[5]
    updated_mask = packet[6]
    declared = struct.unpack_from("<H", packet, 8)[0]
    sequence, host_ms = struct.unpack_from("<II", packet, 12)
    wire_crc = struct.unpack_from("<I", packet, len(packet) - TRAILER_BYTES)[0]
    calculated_crc = zlib.crc32(packet[:-TRAILER_BYTES]) & 0xFFFFFFFF
    crc_state = "OK" if wire_crc == calculated_crc else (
        f"BAD wire=0x{wire_crc:08x} calc=0x{calculated_crc:08x}"
    )

    lines = [
        f"MUL1 version={version} length={len(packet)} declared={declared} "
        f"modules={modules} updated=0x{updated_mask:02x} seq={sequence} "
        f"host_ms={host_ms} outer_crc={crc_state}",
    ]

    offset = HEADER_BYTES
    payload_end = len(packet) - TRAILER_BYTES
    for expected_id in range(MODULE_COUNT):
        if offset + 4 > payload_end:
            lines.append(f"  M{expected_id}: TRUNCATED block_header offset={offset}")
            break
        module_id, status = packet[offset], packet[offset + 1]
        payload_len = struct.unpack_from("<H", packet, offset + 2)[0]
        offset += 4
        marker = "----"
        inner_version = "-"
        if offset + payload_len <= payload_end and payload_len >= 5:
            marker = packet[offset:offset + 4].decode("ascii", errors="replace")
            inner_version = str(packet[offset + 4])
        raw_prefix = ""
        if status != 0 and offset + payload_len <= payload_end and payload_len:
            raw_prefix = f" raw_prefix={packet[offset:offset + payload_len].hex(' ')}"
        lines.append(
            f"  M{module_id}: status={status_name(status)}(0x{status:02x}) "
            f"payload={payload_len} marker={marker} esk_version={inner_version}"
            f"{raw_prefix}"
        )
        offset += payload_len

    if offset != payload_end:
        lines.append(f"  packet_layout: trailing_bytes={payload_end - offset}")
    return lines


def capture(port_name: str, baud: int, seconds: float, output_dir: Path,
            hex_bytes: int, max_packets: int) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = output_dir / f"{stamp}_usb_mul1_raw.bin"
    text_path = output_dir / f"{stamp}_usb_mul1_dump.txt"
    stream_buffer = bytearray()
    packet_count = 0
    crc_errors = 0
    sync_drops = 0
    raw_bytes = 0
    lines: list[str] = [
        f"port={port_name}",
        f"baud={baud}",
        f"duration_seconds={seconds}",
        f"raw_file={raw_path}",
        "--- packets ---",
    ]

    print(f"Opening {port_name} at {baud} baud for {seconds:g} seconds.")
    print("Close the GUI and every other serial monitor before starting.")
    print(f"Raw bytes will be saved to: {raw_path}")

    deadline = time.monotonic() + seconds
    try:
        with serial.Serial(port_name, baudrate=baud, timeout=0.1,
                           bytesize=serial.EIGHTBITS,
                           parity=serial.PARITY_NONE,
                           stopbits=serial.STOPBITS_ONE,
                           dsrdtr=True, rtscts=False) as port, \
                raw_path.open("wb") as raw_file:
            while time.monotonic() < deadline:
                chunk = port.read(4096)
                if not chunk:
                    continue
                raw_file.write(chunk)
                raw_bytes += len(chunk)
                stream_buffer.extend(chunk)

                while True:
                    start = stream_buffer.find(MAGIC)
                    if start < 0:
                        sync_drops += max(0, len(stream_buffer) - 3)
                        del stream_buffer[:-3]
                        break
                    if start > 0:
                        sync_drops += start
                        del stream_buffer[:start]
                    if len(stream_buffer) < HEADER_BYTES:
                        break

                    declared = struct.unpack_from("<H", stream_buffer, 8)[0]
                    if (declared < HEADER_BYTES + TRAILER_BYTES or
                            declared > 65535):
                        sync_drops += 1
                        del stream_buffer[:1]
                        continue
                    if len(stream_buffer) < declared:
                        break

                    packet = bytes(stream_buffer[:declared])
                    del stream_buffer[:declared]
                    packet_count += 1
                    packet_lines = describe_packet(packet)
                    if "outer_crc=OK" not in packet_lines[0]:
                        crc_errors += 1
                    lines.extend(packet_lines)
                    lines.append(f"  first_{min(hex_bytes, len(packet))}_bytes="
                                 f"{packet[:hex_bytes].hex(' ')}")
                    print("\n".join(packet_lines))
                    print(f"  first_{min(hex_bytes, len(packet))}_bytes="
                          f"{packet[:hex_bytes].hex(' ')}")
                    if max_packets and packet_count >= max_packets:
                        deadline = time.monotonic()
                        break
    except serial.SerialException as exc:
        print(f"Serial error: {exc}", file=sys.stderr)
        return 2

    summary = [
        "--- summary ---",
        f"raw_bytes={raw_bytes}",
        f"mul1_packets={packet_count}",
        f"outer_crc_errors={crc_errors}",
        f"sync_bytes_discarded={sync_drops}",
        f"raw_file={raw_path}",
        f"text_file={text_path}",
    ]
    lines.extend(summary)
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(summary))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture and inspect raw MUL1 v2 USB packets.")
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "docs" / "test_results",
    )
    parser.add_argument("--hex-bytes", type=int, default=32)
    parser.add_argument("--max-packets", type=int, default=0,
                        help="stop after this many packets; 0 means time limit")
    args = parser.parse_args()
    if args.seconds <= 0 or args.hex_bytes < 0:
        parser.error("--seconds must be positive and --hex-bytes cannot be negative")
    return capture(args.port, args.baud, args.seconds, args.output_dir,
                   args.hex_bytes, args.max_packets)


if __name__ == "__main__":
    raise SystemExit(main())
