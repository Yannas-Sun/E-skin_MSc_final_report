"""Capture and qualify the isolated MAX11633 internal-clock FIFO-DMA test."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import numpy as np
import serial


MAGIC = b"ESK1"
FRAME_BYTES = 1188
HEADER_BYTES = 16
FSR_WORDS = 256
CRC_FLAG = 0x10
FSR_UPDATED_FLAG = 0x40
CRC_INTERVAL = 32
WINDOW_FRAMES = 200
BOUNDARY_CODES = np.asarray(
    (0, 1, 3, 7, 15, 31, 63, 127, 255, 511, 1023, 2047, 4095),
    dtype=np.uint16,
)


def read_exact(port: serial.Serial, count: int) -> bytes:
    result = bytearray()
    while len(result) < count:
        part = port.read(count - len(result))
        if not part:
            raise TimeoutError("serial timeout")
        result.extend(part)
    return bytes(result)


def read_wire_frame(port: serial.Serial) -> bytes:
    matched = 0
    while matched < len(MAGIC):
        value = read_exact(port, 1)[0]
        if value == MAGIC[matched]:
            matched += 1
        else:
            matched = 1 if value == MAGIC[0] else 0
    return MAGIC + read_exact(port, FRAME_BYTES - len(MAGIC))


def decode_frame(data: bytes) -> dict[str, object]:
    if len(data) != FRAME_BYTES or data[:4] != MAGIC:
        raise ValueError("bad frame boundary")
    version = data[4]
    flags = data[5]
    if version not in (1, 2):
        raise ValueError(f"unsupported protocol version {version}")
    if struct.unpack_from("<H", data, 6)[0] != FRAME_BYTES:
        raise ValueError("bad declared frame length")
    sequence, stm32_ms = struct.unpack_from("<II", data, 8)
    crc_checked = version == 1 or bool(flags & CRC_FLAG)
    if version == 2 and crc_checked != (sequence % CRC_INTERVAL == 0):
        raise ValueError("CRC cadence mismatch")
    trailer = struct.unpack_from("<I", data, FRAME_BYTES - 4)[0]
    if crc_checked:
        if (zlib.crc32(data[:-4]) & 0xFFFFFFFF) != trailer:
            raise ValueError("CRC mismatch")
    elif trailer != 0:
        raise ValueError("unexpected nonzero trailer")

    fsr1 = np.frombuffer(
        data, dtype="<u2", count=FSR_WORDS, offset=HEADER_BYTES
    ).copy()
    fsr2 = np.frombuffer(
        data,
        dtype="<u2",
        count=FSR_WORDS,
        offset=HEADER_BYTES + (FSR_WORDS * 2),
    ).copy()
    acc_offset = HEADER_BYTES + (2 * FSR_WORDS * 2)
    last_mux = data[acc_offset + 14]
    mux_count = data[acc_offset + 15]
    fsr_profile_offset = acc_offset + 16 + 14
    fsr_us = struct.unpack_from("<H", data, fsr_profile_offset)[0]
    return {
        "flags": flags,
        "sequence": sequence,
        "stm32_ms": stm32_ms,
        "fsr1": fsr1,
        "fsr2": fsr2,
        "last_mux": last_mux,
        "mux_count": mux_count,
        "fsr_us": fsr_us,
    }


def layer_metrics(samples: np.ndarray) -> dict[str, object]:
    windows: list[dict[str, float | int | bool]] = []
    usable = (samples.shape[0] // WINDOW_FRAMES) * WINDOW_FRAMES
    for start in range(0, usable, WINDOW_FRAMES):
        window = samples[start : start + WINDOW_FRAMES]
        unique_per_cell = np.asarray(
            [np.unique(window[:, cell]).size for cell in range(FSR_WORDS)]
        )
        changed_percent = float(
            np.mean(window[1:] != window[:-1]) * 100.0
        )
        metrics = {
            "boundary_percent": float(
                np.mean(np.isin(window, BOUNDARY_CODES)) * 100.0
            ),
            "unique_median": float(np.median(unique_per_cell)),
            "frozen_percent": float(np.mean(unique_per_cell == 1) * 100.0),
            "low_unique_percent": float(
                np.mean(unique_per_cell <= 3) * 100.0
            ),
            "changed_percent": changed_percent,
            "global_unique_codes": int(np.unique(window).size),
        }
        metrics["pass"] = bool(
            metrics["boundary_percent"] < 65.0
            and metrics["unique_median"] >= 4.0
            and metrics["frozen_percent"] <= 5.0
            and metrics["low_unique_percent"] <= 20.0
            and metrics["changed_percent"] >= 40.0
        )
        windows.append(metrics)

    def span(key: str) -> list[float]:
        values = [float(window[key]) for window in windows]
        return [min(values), max(values)] if values else []

    if samples.size:
        flat = samples.reshape(-1)
        max_flat_index = int(np.argmax(samples))
        max_frame, max_cell = np.unravel_index(max_flat_index, samples.shape)
        high_code_counts = {
            str(threshold): int(np.count_nonzero(flat >= threshold))
            for threshold in (1024, 2048, 3072)
        }
        high_code_percent = {
            threshold: (count * 100.0 / flat.size)
            for threshold, count in high_code_counts.items()
        }
        percentiles = {
            "p99": float(np.percentile(flat, 99.0)),
            "p99_9": float(np.percentile(flat, 99.9)),
            "p99_99": float(np.percentile(flat, 99.99)),
        }
        maximum_location = {
            "frame_index": int(max_frame),
            "cell_index": int(max_cell),
            "row": int(max_cell // 16) + 1,
            "column": int(max_cell % 16) + 1,
            "value": int(samples[max_frame, max_cell]),
        }
    else:
        high_code_counts = {}
        high_code_percent = {}
        percentiles = {}
        maximum_location = {}

    return {
        "raw_range": [int(samples.min()), int(samples.max())]
        if samples.size
        else [],
        "windows": len(windows),
        "windows_passed": sum(bool(window["pass"]) for window in windows),
        "all_windows_pass": bool(windows) and all(
            bool(window["pass"]) for window in windows
        ),
        "boundary_percent_range": span("boundary_percent"),
        "unique_median_range": span("unique_median"),
        "frozen_percent_range": span("frozen_percent"),
        "low_unique_percent_range": span("low_unique_percent"),
        "changed_percent_range": span("changed_percent"),
        "global_unique_codes_range": span("global_unique_codes"),
        "percentiles": percentiles,
        "samples_at_or_above": high_code_counts,
        "percent_at_or_above": high_code_percent,
        "maximum_location": maximum_location,
        "early_read_signature": bool(
            samples.size and high_code_counts["3072"] > 0
        ),
    }


def format_span(values: list[float], digits: int = 3) -> str:
    if not values:
        return "n/a"
    return f"{values[0]:.{digits}f}..{values[1]:.{digits}f}"


def capture(args: argparse.Namespace) -> tuple[dict[str, object], Path, Path]:
    frames: list[dict[str, object]] = []
    frame_times: list[float] = []
    parse_errors = 0
    with serial.Serial(args.port, args.baud, timeout=0.25) as port:
        port.reset_input_buffer()
        warmup_deadline = time.monotonic() + args.warmup
        while time.monotonic() < warmup_deadline:
            port.read(max(1, port.in_waiting))
        port.reset_input_buffer()
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            try:
                decoded = decode_frame(read_wire_frame(port))
            except (TimeoutError, ValueError):
                parse_errors += 1
                continue
            frames.append(decoded)
            frame_times.append(time.monotonic())

    sequence_errors = 0
    for previous, current in zip(frames, frames[1:]):
        expected = (int(previous["sequence"]) + 1) & 0xFFFFFFFF
        if int(current["sequence"]) != expected:
            sequence_errors += 1

    complete = [
        frame
        for frame in frames
        if (int(frame["flags"]) & 0x03) == 0x03
        and (
            args.stable_eoc
            or (int(frame["flags"]) & FSR_UPDATED_FLAG) != 0
        )
        and int(frame["mux_count"]) == 16
    ]
    fsr_us_values = [int(frame["fsr_us"]) for frame in complete if frame["fsr_us"]]
    measured_seconds = (
        frame_times[-1] - frame_times[0] if len(frame_times) >= 2 else 0.0
    )
    output_rate = (
        (len(frame_times) - 1) / measured_seconds if measured_seconds > 0 else 0.0
    )
    median_fsr_us = float(np.median(fsr_us_values)) if fsr_us_values else 0.0
    profile_fsr_hz = 1_000_000.0 / median_fsr_us if median_fsr_us else 0.0

    fsr1_samples = np.stack([frame["fsr1"] for frame in complete]) if complete else np.empty((0, FSR_WORDS), dtype=np.uint16)
    fsr2_samples = np.stack([frame["fsr2"] for frame in complete]) if complete else np.empty((0, FSR_WORDS), dtype=np.uint16)
    fsr1_quality = layer_metrics(fsr1_samples)
    fsr2_quality = layer_metrics(fsr2_samples)
    transport_pass = bool(
        len(complete) >= WINDOW_FRAMES
        and parse_errors == 0
        and sequence_errors == 0
        and len(complete) == len(frames)
    )
    result_pass = bool(
        transport_pass
        and fsr1_quality["all_windows_pass"]
        and fsr2_quality["all_windows_pass"]
    )
    early_read_detected = bool(
        fsr1_quality["early_read_signature"]
        or fsr2_quality["early_read_signature"]
    )
    if args.stable_eoc:
        readout_status = "EOC_QUALIFIED" if transport_pass else "TRANSPORT_FAIL"
    elif not transport_pass:
        readout_status = "TRANSPORT_FAIL"
    elif early_read_detected:
        readout_status = "EARLY_READ_SIGNATURE"
    else:
        readout_status = "DIGITALLY_CREDIBLE_UNLOADED"

    result: dict[str, object] = {
        "configuration": {
            "port": args.port,
            "baud": args.baud,
            "duration_seconds": args.duration,
            "warmup_seconds": args.warmup,
            "module": args.module,
            "acquisition_strategy": (
                "stable_internal_clock_eoc" if args.stable_eoc
                else "internal_clock_fixed_gap_dma"
            ),
            "stable_eoc": args.stable_eoc,
            "command_to_fifo_gap_us": args.gap_us,
            "mux_settle_us": args.mux_us,
            "max11633_setup": "0x64",
            "fifo_data_sclk_hz": 10_000_000,
            "stm32_sysclk_hz": 160_000_000,
        },
        "parsed_frames": len(frames),
        "complete_fsr_frames": len(complete),
        "parse_errors": parse_errors,
        "sequence_errors": sequence_errors,
        "measured_output_rate_hz": output_rate,
        "median_complete_fsr_scan_us": median_fsr_us,
        "profile_complete_fsr_scan_hz": profile_fsr_hz,
        "transport_pass": transport_pass,
        "readout_status": readout_status,
        "fsr1": fsr1_quality,
        "fsr2": fsr2_quality,
        "result": "PASS" if result_pass else "FAIL",
    }

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    stem = f"{stamp}_internal_fifo_gap{args.gap_us}_mux{args.mux_us}"
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = [
        "MAX11633 internal-clock FIFO-DMA capture",
        f"module={args.module}",
        f"gap_us={args.gap_us}",
        f"mux_settle_us={args.mux_us}",
        f"parsed_frames={len(frames)}",
        f"complete_fsr_frames={len(complete)}",
        f"parse_errors={parse_errors}",
        f"sequence_errors={sequence_errors}",
        f"measured_output_rate_hz={output_rate:.3f}",
        f"median_complete_fsr_scan_us={median_fsr_us:.3f}",
        f"profile_complete_fsr_scan_hz={profile_fsr_hz:.3f}",
        f"transport_pass={transport_pass}",
    ]
    for name, quality in (("fsr1", fsr1_quality), ("fsr2", fsr2_quality)):
        lines.extend(
            (
                "",
                f"{name}:",
                f"raw_range={quality['raw_range']}",
                f"percentiles={quality['percentiles']}",
                f"samples_at_or_above={quality['samples_at_or_above']}",
                f"percent_at_or_above={quality['percent_at_or_above']}",
                f"maximum_location={quality['maximum_location']}",
                f"early_read_signature={quality['early_read_signature']}",
                f"windows={quality['windows']}",
                f"windows_passed={quality['windows_passed']}",
                "boundary_percent="
                + format_span(quality["boundary_percent_range"]),
                "unique_median="
                + format_span(quality["unique_median_range"]),
                "frozen_percent="
                + format_span(quality["frozen_percent_range"]),
                "low_unique_percent="
                + format_span(quality["low_unique_percent_range"]),
                "changed_percent="
                + format_span(quality["changed_percent_range"]),
                "global_unique_codes="
                + format_span(quality["global_unique_codes_range"], 0),
                f"all_windows_pass={quality['all_windows_pass']}",
            )
        )
    lines.extend(
        (
            "",
            f"readout_status={readout_status}",
            f"result={result['result']}",
            "scope=Unloaded short-run digital validity only; controlled pressure is still required.",
        )
    )
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result, json_path, text_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--warmup", type=float, default=2.5)
    parser.add_argument("--module", type=int, default=1)
    parser.add_argument("--gap-us", type=int, required=True)
    parser.add_argument("--mux-us", type=int, default=0)
    parser.add_argument(
        "--stable-eoc",
        action="store_true",
        help="Accept complete frames from the stable EOC-qualified firmware.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "test_results",
    )
    return parser.parse_args()


def main() -> None:
    result, json_path, text_path = capture(parse_args())
    print(f"result={result['result']}")
    print(f"measured_output_rate_hz={result['measured_output_rate_hz']:.3f}")
    print(
        "profile_complete_fsr_scan_hz="
        f"{result['profile_complete_fsr_scan_hz']:.3f}"
    )
    print(f"json_file={json_path}")
    print(f"text_file={text_path}")


if __name__ == "__main__":
    main()
