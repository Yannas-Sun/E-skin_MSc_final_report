"""Fit current whole-layer FSR responses with monotonic regression and LUTs.

The script keeps the measured data, first aggregates repeated pressure points, then fits
each cell independently with:

    measured ADC -> isotonic (non-decreasing) ADC -> PCHIP ADC=f(pressure)
    ADC=f(pressure) -> linear lookup table for pressure=f^-1(ADC)

Outputs are written to the selected analysis directory. The explicit
whole_layer_shared_endpoints_v3
protocol evaluates 0..U g, where U is the sweep's final and maximum load,
and preserves prior captures/models in place,
using a separate model-run directory. The measured input JSON is not modified.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


CALIBRATION_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CALIBRATION_ROOT))
SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))
sys.path.insert(0, str(SCRIPT_ROOT / "Utility"))
from Utility.portable_paths import portable_path  # noqa: E402
from figure_style import DEEP_TEAL, PUBLICATION_STYLE, SLATE_BLUE, TEAL_CYAN  # noqa: E402

plt.rcParams.update(PUBLICATION_STYLE)

try:
    from scipy.interpolate import PchipInterpolator
except ImportError as error:  # pragma: no cover - depends on the local runtime
    PchipInterpolator = None
    SCIPY_IMPORT_ERROR = error
else:
    SCIPY_IMPORT_ERROR = None

from saturation_regions import mark_saturation_regions


ROWS = 16
COLS = 16
FSR_CELLS = ROWS * COLS
DEFAULT_CURVE_POINTS = 400
NEW_PROTOCOL = "whole_layer_shared_endpoints_v3"


def load_pressure_sweep(path: Path) -> tuple[dict, np.ndarray, np.ndarray]:
    """Load and validate one saved whole-layer sweep."""
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("format") != "e-skin-fsr-pressure-response-sweep":
        raise ValueError("input is not a pressure-response sweep JSON")
    points = data.get("points")
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("the sweep must contain at least two pressure points")
    pressures, matrices = [], []
    for index, point in enumerate(points, start=1):
        try:
            pressure = float(point["pressure"])
            matrix = np.asarray(point["raw_adc"], dtype=np.float64)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid pressure point {index}: {error}") from error
        if not np.isfinite(pressure) or matrix.shape != (ROWS, COLS) or not np.all(np.isfinite(matrix)):
            raise ValueError(f"invalid pressure point {index}")
        pressures.append(pressure)
        matrices.append(matrix)
    pressure_array = np.asarray(pressures, dtype=np.float64)
    raw_array = np.stack(matrices, axis=0)
    if np.unique(pressure_array).size < 2:
        raise ValueError("the sweep must contain at least two different pressures")
    return data, pressure_array, raw_array


def fit_dir_for_input(input_path: Path) -> Path:
    if input_path.parent.name.lower() == "raw" and input_path.parent.parent.name.lower() == "fit":
        return input_path.parent.parent
    if input_path.parent.name.lower() == "fit":
        return input_path.parent
    return input_path.parent


def default_output_dir(input_path: Path, source: dict) -> Path:
    del source
    return fit_dir_for_input(input_path) / "analysis" / "load_code"


def archive_previous_calibration(input_path: Path, output_dir: Path, source: dict) -> tuple[Path | None, int]:
    """Compatibility hook; current protocol never archives or mutates old runs."""
    del input_path, output_dir, source
    return None, 0


def validate_protocol(source: dict, pressures: np.ndarray, raw: np.ndarray, protocol: str) -> None:
    """Reject relabelling a historical sweep as the new acquisition protocol."""
    if protocol == "legacy":
        if source.get("protocol_id") == NEW_PROTOCOL:
            raise ValueError(f"new-protocol sweeps require --protocol {NEW_PROTOCOL}")
        return
    if protocol != NEW_PROTOCOL:
        raise ValueError(f"unsupported protocol: {protocol}")
    if source.get("protocol_id") != NEW_PROTOCOL or source.get("version") != 3:
        raise ValueError(f"new fitting requires a version 3 sweep acquired and tagged {NEW_PROTOCOL}")
    if source.get("pressure", {}).get("unit") != "g":
        raise ValueError("new-protocol sweep input unit must be g")
    if source.get("module_id") not in range(4) or source.get("fsr") not in {"FSR1", "FSR2"}:
        raise ValueError("new-protocol sweep must identify module_id 0..3 and FSR1 or FSR2")
    if pressures.size == 0 or not np.all(np.isfinite(pressures)) or np.any(pressures < 0):
        raise ValueError("new-protocol sweep requires finite nonnegative loads")
    upper = float(np.max(pressures))
    if upper <= 0 or pressures[-1] != upper:
        raise ValueError("the last captured load must equal the positive maximum load U")
    if source.get("load_range_g") != [0, upper]:
        raise ValueError("new-protocol sweep must declare load_range_g [0, U] matching its actual maximum")
    if not np.any(pressures == 0):
        raise ValueError("new-protocol sweep requires a measured zero-load endpoint")
    if len(np.unique(pressures)) < 3:
        raise ValueError("multi-point calibration requires at least one interior load")
    if not np.all(np.isfinite(raw)) or np.any(raw < 0) or np.any(raw > 4095):
        raise ValueError("new-protocol ADC values must be finite and within 0..4095")


def style_load_axis(axis, protocol: str) -> None:
    if protocol == NEW_PROTOCOL:
        axis.set_xlabel("Applied whole-layer calibration mass (g)")
        axis.set_xlim(0, axis.dataLim.xmax)
    else:
        mark_saturation_regions(axis)


def isotonic_increasing(values: np.ndarray) -> np.ndarray:
    """Return the closest non-decreasing sequence using the PAVA algorithm."""
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return values.copy()

    means: list[float] = []
    weights: list[int] = []
    starts: list[int] = []
    ends: list[int] = []
    for index, value in enumerate(values):
        means.append(float(value))
        weights.append(1)
        starts.append(index)
        ends.append(index)
        while len(means) >= 2 and means[-2] > means[-1]:
            right_mean = means.pop()
            right_weight = weights.pop()
            right_start = starts.pop()
            right_end = ends.pop()
            left_mean = means.pop()
            left_weight = weights.pop()
            left_start = starts.pop()
            left_end = ends.pop()
            total_weight = left_weight + right_weight
            means.append(
                (left_mean * left_weight + right_mean * right_weight)
                / total_weight
            )
            weights.append(total_weight)
            starts.append(left_start)
            ends.append(right_end)

    result = np.empty_like(values)
    for mean, start, end in zip(means, starts, ends):
        result[start:end + 1] = mean
    return result


def aggregate_pressure_points(
    pressures: np.ndarray, raw: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Sort pressure points and median repeated measurements at each pressure."""
    pressures = np.asarray(pressures, dtype=np.float64)
    raw = np.asarray(raw, dtype=np.float64)
    unique_pressures = np.unique(pressures)
    aggregated = np.empty(
        (len(unique_pressures), ROWS, COLS), dtype=np.float64,
    )
    for index, pressure in enumerate(unique_pressures):
        aggregated[index] = np.median(raw[pressures == pressure], axis=0)
    return unique_pressures, aggregated


def collapse_equal_x(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Collapse repeated inverse ADC values using the midpoint pressure."""
    order = np.argsort(x, kind="stable")
    sorted_x = np.asarray(x, dtype=np.float64)[order]
    sorted_y = np.asarray(y, dtype=np.float64)[order]
    unique_x, first = np.unique(sorted_x, return_index=True)
    last = np.r_[first[1:], len(sorted_x)]
    midpoint_y = np.asarray(
        [(float(np.min(sorted_y[start:stop])) + float(np.max(sorted_y[start:stop]))) / 2.0
         for start, stop in zip(first, last)],
        dtype=np.float64,
    )
    return unique_x, midpoint_y


def r2_score(observed: np.ndarray, predicted: np.ndarray) -> float:
    residual = np.asarray(observed) - np.asarray(predicted)
    ss_res = float(np.sum(residual ** 2))
    centred = np.asarray(observed) - float(np.mean(observed))
    ss_tot = float(np.sum(centred ** 2))
    return float("nan") if ss_tot == 0.0 else 1.0 - ss_res / ss_tot


def evaluate_pchip(model: dict, x: np.ndarray) -> np.ndarray:
    x_values = np.asarray(model["x"], dtype=np.float64)
    y_values = np.asarray(model["y"], dtype=np.float64)
    if len(x_values) < 2:
        return np.full_like(np.asarray(x, dtype=np.float64), y_values[0])
    interpolator = PchipInterpolator(x_values, y_values, extrapolate=False)
    clipped = np.clip(np.asarray(x, dtype=np.float64), x_values[0], x_values[-1])
    return np.asarray(interpolator(clipped), dtype=np.float64)


def evaluate_lut(model: dict, x: np.ndarray) -> np.ndarray:
    x_values = np.asarray(model["x"], dtype=np.float64)
    y_values = np.asarray(model["y"], dtype=np.float64)
    values = np.asarray(x, dtype=np.float64)
    if len(x_values) < 2:
        return np.full_like(values, y_values[0])
    return np.interp(values, x_values, y_values)


def fit_monotonic_response(
    pressures: np.ndarray, adc_values: np.ndarray,
    *, load_range_g: tuple[float, float] = (0, 3000),
) -> dict:
    """Fit one cell's forward PCHIP and inverse linear-LUT response."""
    pressures = np.asarray(pressures, dtype=np.float64)
    adc_values = np.asarray(adc_values, dtype=np.float64)
    isotonic_adc = isotonic_increasing(adc_values)
    inverse_adc, inverse_pressure = collapse_equal_x(isotonic_adc, pressures)

    forward = {
        "type": "pchip",
        "x_name": "pressure",
        "y_name": "adc",
        "x": pressures.tolist(),
        "y": isotonic_adc.tolist(),
        "x_min": float(pressures[0]),
        "x_max": float(pressures[-1]),
        "y_min": float(isotonic_adc[0]),
        "y_max": float(isotonic_adc[-1]),
    }
    inverse = {
        "type": "linear_lut",
        "x_name": "adc",
        "y_name": "pressure",
        "x": inverse_adc.tolist(),
        "y": inverse_pressure.tolist(),
        "x_min": float(inverse_adc[0]),
        "x_max": float(inverse_adc[-1]),
        "y_min": float(np.min(inverse_pressure)),
        "y_max": float(np.max(inverse_pressure)),
        "plateau_count": int(len(isotonic_adc) - len(inverse_adc)),
    }
    fitted_adc = evaluate_pchip(forward, pressures)
    fitted_pressure = evaluate_lut(inverse, adc_values)
    metric_mask = (pressures >= load_range_g[0]) & (pressures <= load_range_g[1])
    observed_adc, predicted_adc = adc_values[metric_mask], fitted_adc[metric_mask]
    observed_load, predicted_load = pressures[metric_mask], fitted_pressure[metric_mask]
    return {
        "adc_from_pressure": forward,
        "pressure_from_adc": inverse,
        "metrics": {
            "statistical_load_range_g": list(load_range_g),
            "included_points": int(metric_mask.sum()),
            "excluded_saturated_points": int((pressures > load_range_g[1]).sum()),
            "excluded_outside_range_points": int((~metric_mask).sum()),
            "metric_scope": "training_knots_after_replicate_median; not independent validation",
            "adc_rmse": float(np.sqrt(np.mean((observed_adc - predicted_adc) ** 2))),
            "adc_r2": r2_score(observed_adc, predicted_adc),
            "pressure_rmse": float(
                np.sqrt(np.mean((observed_load - predicted_load) ** 2))
            ),
            "pressure_r2": r2_score(observed_load, predicted_load),
            "measured_adc_min": float(np.min(adc_values)),
            "measured_adc_max": float(np.max(adc_values)),
            "isotonic_adc_min": float(np.min(isotonic_adc)),
            "isotonic_adc_max": float(np.max(isotonic_adc)),
        },
    }


def build_models(
    pressures: np.ndarray, raw: np.ndarray,
    *, load_range_g: tuple[float, float] = (0, 3000),
) -> tuple[list[dict], dict]:
    cells: list[dict] = []
    for row in range(ROWS):
        for column in range(COLS):
            response = fit_monotonic_response(pressures, raw[:, row, column], load_range_g=load_range_g)
            cells.append({
                "row": row + 1,
                "column": column + 1,
                **response,
            })

    mean_adc = np.mean(raw, axis=(1, 2))
    return cells, fit_monotonic_response(pressures, mean_adc, load_range_g=load_range_g)


def json_safe(value):
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def save_model(
    output_dir: Path,
    source: dict,
    pressures: np.ndarray,
    raw: np.ndarray,
    cells: list[dict],
    mean_model: dict,
    *, protocol: str = "legacy", input_path: Path | None = None,
) -> None:
    model = {
        "format": "e-skin-fsr-pressure-response-monotonic-model",
        "version": 1,
        "method": {
            "name": "isotonic_regression_pchip_lut",
            "description": (
                "PAVA monotonic regression, PCHIP forward interpolation, "
                "and linear inverse lookup table"
            ),
        },
        "source_format": source.get("format"),
        "source_module_id": source.get("module_id"),
        "source_fsr": source.get("fsr"),
        "matrix": {"rows": ROWS, "columns": COLS},
        "pressure": source.get("pressure", {"unit": "user-defined"}),
        "pressure_range": {
            "min": float(np.min(pressures)),
            "max": float(np.max(pressures)),
        },
        "evaluation_policy": {
            "statistical_load_range_g": [0, 3000],
            "soft_saturation_g": [1200, 3000],
            "above_3000g": "retained for full-response display and model knots; excluded from reported fit-error statistics",
        },
        "fit": {
            "pressure_points_after_median": int(len(pressures)),
            "raw_adc_min": float(np.min(raw)),
            "raw_adc_max": float(np.max(raw)),
            "cells": cells,
            "mean_cell": mean_model,
        },
    }
    if protocol == NEW_PROTOCOL:
        upper = float(np.max(pressures))
        model.update({
            "version": 3,
            "protocol_id": NEW_PROTOCOL,
            "load_range_g": [0, upper],
            "shared_endpoints_adc": {"zero": raw[0].tolist(), "full": raw[-1].tolist(),
                                     "aggregation": "median across captures at each repeated load"},
            "source_created_at": source.get("created_at"),
            "source_acquisition": source.get("acquisition"),
            "evaluation_policy": {
                "protocol_id": NEW_PROTOCOL,
                "statistical_load_range_g": [0, upper],
                "output_load_range_g": [0, upper],
                "metric_scope": "training_knots_after_replicate_median; not independent validation",
                "inverse_evaluation": "piecewise-linear ADC-to-load LUT with endpoint clamping; not an exact inverse of PCHIP",
                "plateau_policy": "merge equal isotonic ADC knots at midpoint of corresponding load interval; no endpoint re-anchoring",
                "saturation_policy": "no assumed 3000 g cutoff; measured ADC saturation and plateaus remain visible",
            },
        })
        if input_path is not None:
            model["source_file"] = portable_path(input_path)
            model["source_sha256"] = hashlib.sha256(input_path.read_bytes()).hexdigest()
    path = output_dir / "pressure_response_model.json"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(json_safe(model), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def save_parameters_csv(output_dir: Path, cells: list[dict]) -> None:
    path = output_dir / "per_cell_fit_parameters.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "row", "column", "method", "adc_rmse", "adc_r2",
            "pressure_rmse", "pressure_r2", "lut_points", "plateau_count",
            "measured_adc_min", "measured_adc_max",
        ])
        for cell in cells:
            metrics = cell["metrics"]
            inverse = cell["pressure_from_adc"]
            writer.writerow([
                cell["row"], cell["column"], "isotonic+pchip+lut",
                f"{metrics['adc_rmse']:.6f}",
                f"{metrics['adc_r2']:.6f}" if np.isfinite(metrics["adc_r2"]) else "",
                f"{metrics['pressure_rmse']:.6f}",
                f"{metrics['pressure_r2']:.6f}"
                if np.isfinite(metrics["pressure_r2"]) else "",
                len(inverse["x"]), inverse["plateau_count"],
                f"{metrics['measured_adc_min']:.3f}",
                f"{metrics['measured_adc_max']:.3f}",
            ])


def plot_all_cells_raw(output_dir: Path, pressures: np.ndarray, raw: np.ndarray, *, protocol: str = "legacy") -> None:
    order = np.argsort(pressures)
    fig, axis = plt.subplots(figsize=(11, 7))
    for row in range(ROWS):
        for column in range(COLS):
            axis.plot(
                pressures[order], raw[order, row, column],
                color=SLATE_BLUE, alpha=0.16, linewidth=0.55,
            )
    mean_adc = np.mean(raw, axis=(1, 2))
    axis.plot(
        pressures[order], mean_adc[order], color=TEAL_CYAN, linewidth=2.2,
        marker="o", markersize=2.2, label="mean of 256 cells",
    )
    axis.set_title("All 256 FSR cells: measured response")
    axis.set_xlabel("Pressure value (input unit)")
    axis.set_ylabel("Raw ADC code")
    axis.set_ylim(bottom=0)
    axis.grid(alpha=0.25)
    style_load_axis(axis, protocol)
    axis.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "all_cells_raw_lines.png", dpi=300, facecolor="white", transparent=False)
    plt.close(fig)


def plot_all_cells_fits(
    output_dir: Path, pressure_curve: np.ndarray,
    cells: list[dict], mean_model: dict,
    *, protocol: str = "legacy",
) -> None:
    fig, axis = plt.subplots(figsize=(11, 7))
    for cell in cells:
        axis.plot(
            pressure_curve,
            evaluate_pchip(cell["adc_from_pressure"], pressure_curve),
            color=SLATE_BLUE, alpha=0.16, linewidth=0.55,
        )
    axis.plot(
        pressure_curve,
        evaluate_pchip(mean_model["adc_from_pressure"], pressure_curve),
        color=SLATE_BLUE, linewidth=2.2, label="monotonic fit of mean response",
    )
    axis.set_title("All 256 FSR cells: monotonic fitted response curves")
    axis.set_xlabel("Pressure value (input unit)")
    axis.set_ylabel("Fitted raw ADC code")
    axis.set_ylim(bottom=0)
    axis.grid(alpha=0.25)
    style_load_axis(axis, protocol)
    axis.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "all_cells_fitted_curves.png", dpi=300, facecolor="white", transparent=False)
    plt.close(fig)


def plot_mean_response(
    output_dir: Path, pressures: np.ndarray, raw: np.ndarray,
    pressure_curve: np.ndarray, mean_model: dict,
    *, protocol: str = "legacy",
) -> None:
    order = np.argsort(pressures)
    mean_adc = np.mean(raw, axis=(1, 2))
    fig, axis = plt.subplots(figsize=(10, 6))
    axis.plot(
        pressures[order], mean_adc[order], "o-", color=TEAL_CYAN,
        linewidth=1.5, markersize=2.4,
    )
    axis.set_title("Mean response of all 256 cells: measured line")
    axis.set_xlabel("Pressure value (input unit)")
    axis.set_ylabel("Mean raw ADC code")
    axis.set_ylim(bottom=0)
    axis.grid(alpha=0.25)
    style_load_axis(axis, protocol)
    axis.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "mean_response_line.png", dpi=300, facecolor="white", transparent=False)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(10, 6))
    axis.plot(
        pressure_curve,
        evaluate_pchip(mean_model["adc_from_pressure"], pressure_curve),
        color=SLATE_BLUE, linewidth=2.2,
    )
    axis.scatter(pressures, mean_adc, color=TEAL_CYAN, s=7, label="measured mean")
    axis.set_title("Mean response of all 256 cells: isotonic + PCHIP curve")
    axis.set_xlabel("Pressure value (input unit)")
    axis.set_ylabel("Fitted raw ADC code")
    axis.set_ylim(bottom=0)
    axis.grid(alpha=0.25)
    style_load_axis(axis, protocol)
    axis.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "mean_response_fitted_curve.png", dpi=300, facecolor="white", transparent=False)
    plt.close(fig)


def plot_per_cell_grid(
    output_dir: Path, pressures: np.ndarray, raw: np.ndarray,
    pressure_curve: np.ndarray, cells: list[dict],
    *, protocol: str = "legacy",
) -> None:
    order = np.argsort(pressures)
    fig, axes = plt.subplots(
        ROWS, COLS, figsize=(18, 18), sharex=True, sharey=True,
    )
    for cell, axis in zip(cells, axes.flat):
        row = cell["row"] - 1
        column = cell["column"] - 1
        axis.plot(
            pressures[order], raw[order, row, column],
            ".-", color=TEAL_CYAN, markersize=1.8, linewidth=0.45,
        )
        axis.plot(
            pressure_curve,
            evaluate_pchip(cell["adc_from_pressure"], pressure_curve),
            color=SLATE_BLUE, linewidth=0.65,
        )
        axis.set_title(f"R{cell['row']}C{cell['column']}", fontsize=5)
        axis.tick_params(labelsize=4)
        axis.grid(alpha=0.15)
        style_load_axis(axis, protocol)
        axis.set_xlabel("")
    fig.supxlabel("Applied whole-layer calibration mass (g)" if protocol == NEW_PROTOCOL else "Pressure value (input unit)")
    fig.supylabel("Raw ADC code")
    fig.suptitle("Per-cell measured lines and monotonic fitted curves", y=0.995)
    fig.tight_layout(rect=(0.02, 0.02, 1.0, 0.985))
    fig.savefig(output_dir / "per_cell_response_grid.png", dpi=300, facecolor="white", transparent=False)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="pressure sweep JSON")
    parser.add_argument(
        "--protocol", choices=(NEW_PROTOCOL,), default=NEW_PROTOCOL,
        help="current whole-layer shared-endpoint protocol",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="output directory; default is fit/analysis/load_code",
    )
    parser.add_argument(
        "--per-cell-grid", dest="per_cell_grid", action="store_true", default=True,
        help="generate the detailed 16x16 measured/fitted grid (default)",
    )
    parser.add_argument(
        "--no-per-cell-grid", dest="per_cell_grid", action="store_false",
        help="skip the detailed 16x16 measured/fitted grid",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if PchipInterpolator is None:
        raise SystemExit(
            "scipy is required for PCHIP interpolation; "
            f"import error: {SCIPY_IMPORT_ERROR}"
        )
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise SystemExit(f"input file not found: {input_path}")
    source, pressures, raw = load_pressure_sweep(input_path)
    validate_protocol(source, pressures, raw, args.protocol)
    pressures, raw = aggregate_pressure_points(pressures, raw)
    if len(pressures) < 2:
        raise SystemExit("at least two unique pressure points are required")
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else default_output_dir(input_path, source)
    )
    if args.protocol == NEW_PROTOCOL:
        # New experiment records are immutable inputs. Preserve prior sweeps
        # and model runs so every validation result remains traceable.
        if args.output_dir is None:
            output_dir = output_dir.parent / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        if (output_dir / "pressure_response_model.json").exists():
            raise ValueError("new-protocol model output already exists; choose a fresh output directory")
        archive_root, archived_count = None, 0
    else:
        archive_root, archived_count = archive_previous_calibration(
            input_path, output_dir, source,
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    metric_range = (0, float(np.max(pressures))) if args.protocol == NEW_PROTOCOL else (0, 3000)
    cells, mean_model = build_models(pressures, raw, load_range_g=metric_range)
    pressure_curve = np.linspace(
        float(np.min(pressures)), float(np.max(pressures)), DEFAULT_CURVE_POINTS,
    )
    save_model(output_dir, source, pressures, raw, cells, mean_model, protocol=args.protocol, input_path=input_path)
    save_parameters_csv(output_dir, cells)
    plot_all_cells_raw(output_dir, pressures, raw, protocol=args.protocol)
    plot_all_cells_fits(output_dir, pressure_curve, cells, mean_model, protocol=args.protocol)
    plot_mean_response(output_dir, pressures, raw, pressure_curve, mean_model, protocol=args.protocol)
    if args.per_cell_grid:
        plot_per_cell_grid(output_dir, pressures, raw, pressure_curve, cells, protocol=args.protocol)

    print(f"Input: {input_path}")
    print(f"Output: {output_dir}")
    print(f"Pressure points: {len(pressures)}")
    print("Method: isotonic regression + PCHIP forward curve + inverse linear LUT")
    print("Generated: pressure_response_model.json")
    print("Generated: per_cell_fit_parameters.csv")
    print("Generated: all_cells_raw_lines.png")
    print("Generated: all_cells_fitted_curves.png")
    print("Generated: mean_response_line.png")
    print("Generated: mean_response_fitted_curve.png")
    if args.per_cell_grid:
        print("Generated: per_cell_response_grid.png")
    if archive_root is not None:
        print(f"Archived {archived_count} older calibration item(s): {archive_root}")
    else:
        print("Archived: no older same-module/FSR calibration data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
