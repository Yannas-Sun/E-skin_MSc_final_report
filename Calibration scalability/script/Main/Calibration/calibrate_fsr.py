"""Derive linear/gamma endpoints from the exact saved multi-point sweep.

Use --sweep PATH. U is the final and maximum measured load. Endpoints share
200-frame per-capture medians and repeated-load aggregation with the fitted model.
No independent endpoint capture is used.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
import numpy as np

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
from Utility.portable_paths import portable_path

ROWS = 16
COLS = 16
ADC_MAX = 4095
DEFAULT_FRAME_COUNT = 200
DEFAULT_GAMMA = 4.0
SHARED_PROTOCOL_ID = "whole_layer_shared_endpoints_v3"


def matrix_stats(matrices: list[np.ndarray]) -> dict[str, np.ndarray]:
    stack = np.stack(matrices).astype(np.float64)
    return {
        "median": np.median(stack, axis=0),
        "p05": np.percentile(stack, 5, axis=0),
        "p95": np.percentile(stack, 95, axis=0),
        "minimum": np.min(stack, axis=0),
        "maximum": np.max(stack, axis=0),
    }


def as_matrix(value: np.ndarray) -> list[list[float | int]]:
    array = np.asarray(value)
    if np.issubdtype(array.dtype, np.integer):
        return array.astype(int).tolist()
    return np.round(array.astype(np.float64), 3).tolist()


def _validated_capture(
    frames: list[np.ndarray], frame_count: int, label: str,
) -> np.ndarray:
    """Reject missing frames, wrong shapes and non-raw ADC input before fitting."""
    if len(frames) != frame_count:
        raise ValueError(f"{label} has {len(frames)} frames; expected {frame_count}")
    stack = np.asarray(frames)
    if stack.shape != (frame_count, ROWS, COLS):
        raise ValueError(f"{label} shape {stack.shape}; expected {(frame_count, ROWS, COLS)}")
    if (not np.issubdtype(stack.dtype, np.number)
            or not np.all(np.isfinite(stack))
            or np.any(stack < 0) or np.any(stack > ADC_MAX)
            or np.any(stack != np.floor(stack))):
        raise ValueError(f"{label} must contain finite integer ADC codes in [0, {ADC_MAX}]")
    return stack.astype(np.uint16)


def build_from_sweep(sweep_path: Path, gamma: float = DEFAULT_GAMMA) -> dict[str, Any]:
    """Derive both endpoints from the exact multi-point capture and its SHA.

    Aggregate 200 raw frames by per-cell median for each capture, then take
    the median of capture matrices for repeated loads, matching the fit input.
    """
    if not np.isfinite(gamma) or gamma <= 0:
        raise ValueError("gamma must be finite and positive")
    path = Path(sweep_path).resolve()
    contents = path.read_bytes()
    sweep = json.loads(contents)
    if (sweep.get("protocol_id") != SHARED_PROTOCOL_ID or sweep.get("version") != 3
            or sweep.get("pressure", {}).get("unit") != "g"):
        raise ValueError("shared endpoints require a version 3 shared-protocol sweep in g")
    if sweep.get("module_id") not in range(4) or sweep.get("fsr") not in {"FSR1", "FSR2"}:
        raise ValueError("sweep must identify module_id 0--3 and FSR1 or FSR2")
    points = sweep.get("points", [])
    if len(points) < 3:
        raise ValueError("at least 3 distinct loads are required")
    loads = np.asarray([point["pressure"] for point in points], float)
    if not np.all(np.isfinite(loads)) or np.any(loads < 0):
        raise ValueError("loads must be finite and nonnegative")
    upper = float(np.max(loads))
    if upper <= 0 or loads[-1] != upper or 0 not in loads or len(np.unique(loads)) < 3:
        raise ValueError("include zero and an interior load; last load must equal maximum U")
    if sweep.get("load_range_g") != [0, upper]:
        raise ValueError("load_range_g must match [0, last and maximum load U]")
    captures = []
    for index, point in enumerate(points):
        raw = _validated_capture(point.get("raw_frames", []), DEFAULT_FRAME_COUNT,
                                 f"points[{index}].raw_frames")
        median = np.median(raw, axis=0)
        saved = np.asarray(point.get("raw_adc"), float)
        if saved.shape != (ROWS, COLS) or not np.array_equal(saved, median):
            raise ValueError(f"point {index} raw_adc must equal the median of its 200 raw_frames")
        captures.append((raw, median))
    zero_indices = np.flatnonzero(loads == 0).tolist()
    full_indices = np.flatnonzero(loads == upper).tolist()
    source = sweep.get("source", {})
    result = {
        "format": "e-skin-fsr-two-point-calibration",
        "version": 3, "protocol_id": SHARED_PROTOCOL_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "module_id": sweep["module_id"], "fsr": sweep["fsr"],
        "matrix": {"rows": ROWS, "columns": COLS},
        "adc": {"bits": 12, "maximum_code": ADC_MAX},
        "load_range_g": [0, upper], "capture_scope": "whole_layer",
        "measurand": "equivalent whole-layer calibration mass in g",
        "loading_geometry": "shared with the source multi-point sweep",
        "source": {
            "port": source.get("port", "saved sweep"),
            "baud": source.get("baud", 2000000),
            "frames_per_phase": DEFAULT_FRAME_COUNT,
            "acquisition_mode": "FULL",
            "protocol_errors": source.get("protocol_errors", 0),
        },
        "calibration": {
            "output_unit": "g",
            "gamma": float(gamma),
            "gamma_source": "operator-selected; not fitted from endpoints",
            "invalid_response_policy": "NaN when response_span <= 0; retain QC flags",
            "outside_endpoint_policy": "clip controlled outputs; separately log out-of-range ADC",
            "thresholds": {"minimum_response_span": 50.0,
                           "maximum_p05_p95_noise_range": 50.0, "saturation_code": 4090},
        },
        "qc_flag_counts": dict.fromkeys(("NO_RESPONSE_OR_REVERSED", "LOW_RESPONSE",
                                          "ZERO_UNSTABLE", "FULL_UNSTABLE", "SATURATED"), 0),
    }
    for key, indices, mass in (("zero_load", zero_indices, 0.0),
                               ("full_load", full_indices, upper)):
        stacks = [captures[i][0] for i in indices]
        combined = np.concatenate(stacks, axis=0)
        stats = matrix_stats(combined)
        median = np.median(np.stack([captures[i][1] for i in indices]), axis=0)
        noise = np.maximum.reduce([
            np.percentile(stack, 95, axis=0) - np.percentile(stack, 5, axis=0)
            for stack in stacks
        ])
        result[key] = {
            "load_g": mass, "capture_scope": "whole_layer", "capture_count": len(indices),
            "frame_count": len(combined), "frames_per_capture": DEFAULT_FRAME_COUNT,
            "aggregation": "per-cell median per 200-frame capture, then median across captures at this load",
            **{name: as_matrix(value) for name, value in stats.items()},
            "median": as_matrix(median),
            "interval_p05_p95": as_matrix(stats["p95"] - stats["p05"]),
            "stability_range_max_over_captures": as_matrix(noise),
            "raw_frames": combined.astype(int).tolist(),
            "source_point_indices_zero_based": indices,
            "source_captures": [points[i] for i in indices],
        }
    low = np.asarray(result["zero_load"]["median"], float)
    high = np.asarray(result["full_load"]["median"], float)
    span = high - low
    zero_noise = np.asarray(result["zero_load"]["stability_range_max_over_captures"], float)
    full_noise = np.asarray(result["full_load"]["stability_range_max_over_captures"], float)
    full_max = np.asarray(result["full_load"]["maximum"], float)
    problems = []
    for row in range(ROWS):
        for col in range(COLS):
            flags = []
            if span[row, col] <= 0:
                flags.append("NO_RESPONSE_OR_REVERSED")
            elif span[row, col] < 50:
                flags.append("LOW_RESPONSE")
            if zero_noise[row, col] > 50:
                flags.append("ZERO_UNSTABLE")
            if full_noise[row, col] > 50:
                flags.append("FULL_UNSTABLE")
            if full_max[row, col] >= 4090:
                flags.append("SATURATED")
            if flags:
                problems.append({"row": row + 1, "column": col + 1, "flags": flags,
                                 "zero_median": float(low[row, col]),
                                 "full_median": float(high[row, col]),
                                 "response_span": float(span[row, col]),
                                 "zero_p05_p95_range": float(zero_noise[row, col]),
                                 "full_p05_p95_range": float(full_noise[row, col])})
    result.update(version=3, protocol_id=SHARED_PROTOCOL_ID, load_range_g=[0, upper],
                  source_file=portable_path(path), source_sha256=hashlib.sha256(contents).hexdigest(),
                  problem_cells=problems, problem_cell_count=len(problems))
    result["calibration"].update(
        interval_low_zero=as_matrix(low), interval_high_full=as_matrix(high),
        response_span=as_matrix(span), valid_response_mask=(span > 0).tolist(),
        linear_load_g="U * clip((raw-zero_median)/response_span,0,1)",
        gamma_load_g="U * clip((raw-zero_median)/response_span,0,1)**gamma", upper_load_g=upper,
    )
    result["source"].update(
        endpoint_aggregation="per-cell median per 200-frame capture, then median across captures at each load",
        zero_frames_captured=result["zero_load"]["frame_count"],
        full_frames_captured=result["full_load"]["frame_count"],
        shared_with_fit=True,
        source_file=portable_path(path), source_sha256=result["source_sha256"],
    )
    result["qc_flag_counts"] = {flag: sum(flag in p["flags"] for p in problems)
                                for flag in result["qc_flag_counts"]}
    return result


def save_calibration(data: dict[str, Any], output_root: Path) -> Path:
    fsr_dir = (
        output_root
        / "DATA"
        / f"module_{data['module_id']}"
        / str(data["fsr"])
        / "two_point"
    )
    fsr_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = fsr_dir / f"{data['fsr']}_calibration_{stamp}.json"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Derive shared linear/gamma endpoints from a saved multi-point sweep")
    parser.add_argument("--sweep", required=True, type=Path,
                        help="version 3 shared-protocol sweep JSON; no serial acquisition")
    parser.add_argument("--gamma", type=float, default=DEFAULT_GAMMA)
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[3])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = build_from_sweep(args.sweep, gamma=args.gamma)
        path = save_calibration(result, args.output_root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"Saved shared endpoints: {path}")
    print(f"Range: 0--{result['load_range_g'][1]:g} g; gamma={args.gamma:g}")
    print(f"QC-flagged cells: {result['problem_cell_count']}/256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
