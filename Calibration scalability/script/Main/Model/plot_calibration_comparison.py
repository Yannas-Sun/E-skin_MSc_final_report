"""Compare new-protocol LINEAR, GAMMA and multi-point calibration functions.

This is a model-function plot, not an independent accuracy evaluation. Both
inputs must originate from one whole_layer_shared_endpoints_v3 sweep for the
same module and layer. Its final maximum load U sets the common range 0..U.
Historical six-corner maxima and separately captured endpoints are rejected.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Utility.portable_paths import portable_path, resolve_recorded_path  # noqa: E402
from plot_pressure_calibration_monotonic import (
    NEW_PROTOCOL, evaluate_lut, evaluate_pchip, load_pressure_sweep,
    validate_protocol, aggregate_pressure_points, fit_monotonic_response,
)

COLORS = {"LINEAR": "#277c8e", "GAMMA": "#d48428", "MULTI-POINT": "#765ba3"}
CALIBRATION_ROOT = Path(__file__).resolve().parents[3]


def _resolve_project_recorded_path(value: str | Path) -> Path:
    """Resolve model provenance relative to this package, independent of CWD."""
    raw = Path(value)
    if not raw.is_absolute():
        candidate = (CALIBRATION_ROOT / raw).resolve()
        if candidate.exists():
            return candidate
    return resolve_recorded_path(raw, CALIBRATION_ROOT / "__path_anchor__.json", root=CALIBRATION_ROOT)


def _portable_existing_or_original(value: str | Path, resolved: Path) -> str:
    """Serialize in-project provenance paths relative to the package root."""
    try:
        resolved.relative_to(CALIBRATION_ROOT)
    except ValueError:
        return Path(str(value)).as_posix()
    return portable_path(resolved, root=CALIBRATION_ROOT)


def positive_gamma(value: str | float) -> float:
    gamma = float(value)
    if not np.isfinite(gamma) or gamma <= 0:
        raise ValueError("gamma must be finite and greater than zero")
    return gamma


def matrix(value, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (16, 16) or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a finite 16x16 matrix")
    return result


def validate_inputs(two_point: dict, model: dict) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    if two_point.get("format") != "e-skin-fsr-two-point-calibration":
        raise ValueError("two-point input has an unsupported format")
    if model.get("format") != "e-skin-fsr-pressure-response-monotonic-model":
        raise ValueError("multi-point input must be the monotonic response model")
    for name, source in (("two-point", two_point), ("multi-point", model)):
        if source.get("version") != 3 or source.get("protocol_id") != NEW_PROTOCOL:
            raise ValueError(f"{name} input is not shared-endpoint protocol v3; historical calibration cannot be relabelled")
        bounds = source.get("load_range_g")
        if not isinstance(bounds, list) or len(bounds) != 2 or bounds[0] != 0 or not np.isfinite(bounds[1]) or bounds[1] <= 0:
            raise ValueError(f"{name} input must have finite load_range_g [0, U], U > 0")
    upper = float(two_point["load_range_g"][1])
    if model["load_range_g"] != [0, upper]:
        raise ValueError("the two models declare different load ranges")
    if two_point.get("module_id") not in range(4) or two_point.get("fsr") not in {"FSR1", "FSR2"}:
        raise ValueError("two-point input must identify a valid module and FSR layer")
    if (two_point["module_id"], two_point["fsr"]) != (model.get("source_module_id"), model.get("source_fsr")):
        raise ValueError("module or FSR differs between the two calibration inputs")
    policy = model.get("evaluation_policy", {})
    if policy.get("protocol_id") != NEW_PROTOCOL or policy.get("statistical_load_range_g") != [0, upper]:
        raise ValueError("multi-point model does not declare the common 0..U evaluation policy")
    # Match actual source bytes, not just a similar date or module label.
    paths = []
    for source in (two_point, model):
        paths.append(_resolve_project_recorded_path(source["source_file"]))
    if not all(path.is_file() for path in paths):
        raise FileNotFoundError("one or both model source sweeps cannot be resolved")
    if paths[0] != paths[1]:
        raise ValueError("two-point and multi-point models must reference the same sweep path")
    source_hash = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    if any(source.get("source_sha256") != source_hash for source in (two_point, model)):
        raise ValueError("source sweep SHA-256 differs from one or both model records")
    sweep, loads, raw = load_pressure_sweep(paths[0])
    validate_protocol(sweep, loads, raw, NEW_PROTOCOL)
    if (sweep.get("module_id"), sweep.get("fsr")) != (two_point["module_id"], two_point["fsr"]) or sweep["load_range_g"] != [0, upper]:
        raise ValueError("sweep identity or range differs from its derived models")
    loads, raw = aggregate_pressure_points(loads, raw)
    zero = matrix(two_point["calibration"]["interval_low_zero"], "zero endpoint")
    full = matrix(two_point["calibration"]["interval_high_full"], "U g endpoint")
    if not np.array_equal(zero, matrix(two_point["zero_load"]["median"], "zero median")):
        raise ValueError("zero endpoint does not match the captured median")
    if not np.array_equal(full, matrix(two_point["full_load"]["median"], "U g median")):
        raise ValueError("full endpoint does not match the captured median")
    if "maximum_over_all_corners" in two_point["full_load"]:
        raise ValueError("six-corner maxima are not shared whole-layer sweep endpoints")
    if not np.array_equal(zero, raw[0]) or not np.array_equal(full, raw[-1]):
        raise ValueError("two-point endpoints do not match the sweep's median-aggregated raw endpoints")
    shared = model.get("shared_endpoints_adc", {})
    if not np.array_equal(zero, matrix(shared.get("zero"), "model shared zero")) or not np.array_equal(full, matrix(shared.get("full"), "model shared full")):
        raise ValueError("multi-point model's shared raw endpoints do not match the same sweep")
    if np.any(zero < 0) or np.any(zero > 4095) or np.any(full < 0) or np.any(full > 4095):
        raise ValueError("endpoint ADC values must lie in 0..4095")
    cells = model.get("fit", {}).get("cells", [])
    coordinates = [(cell.get("row"), cell.get("column")) for cell in cells]
    if len(cells) != 256 or set(coordinates) != {(r, c) for r in range(1, 17) for c in range(1, 17)}:
        raise ValueError("multi-point model must contain all 256 distinct cell models")
    cells = sorted(cells, key=lambda cell: (cell["row"], cell["column"]))
    for cell in cells:
        forward, inverse = cell["adc_from_pressure"], cell["pressure_from_adc"]
        for label, curve in (("forward", forward), ("inverse", inverse)):
            x, y = np.asarray(curve["x"], dtype=float), np.asarray(curve["y"], dtype=float)
            if x.ndim != 1 or y.ndim != 1 or not len(x) or len(x) != len(y) or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
                raise ValueError(f"malformed {label} knots")
            if np.any(np.diff(x) <= 0) or np.any(np.diff(y) < 0):
                raise ValueError(f"non-monotonic {label} knots")
        if forward.get("type") != "pchip" or inverse.get("type") != "linear_lut":
            raise ValueError("expected PCHIP forward and piecewise-linear inverse LUT")
        if forward["x"][0] != 0 or forward["x"][-1] != upper:
            raise ValueError("multi-point forward model must cover the measured endpoints")
        if min(inverse["y"]) < 0 or max(inverse["y"]) > upper:
            raise ValueError("multi-point inverse values exceed the common output range")
        # Verify model knots remain derived from these exact source statistics.
        expected = fit_monotonic_response(loads, raw[:, cell["row"] - 1, cell["column"] - 1], load_range_g=(0, upper))
        for direction in ("adc_from_pressure", "pressure_from_adc"):
            for coordinate in ("x", "y"):
                if not np.array_equal(cell[direction][coordinate], expected[direction][coordinate]):
                    raise ValueError("multi-point knots differ from the declared source sweep")
    return zero, full, cells


def estimate_curves(zero: np.ndarray, full: np.ndarray, cells: list[dict], gamma: float,
                    adc: np.ndarray) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Evaluate every method and cell at the same physical ADC-code coordinates.

    Endpoint fractions are internal to the linear/gamma formula only. The
    shared x axis is ADC code, not a cell-specific transformed input. A mean
    across these functions is not a mean measurement at a known applied load.
    Nonpositive-span cells are NaN for every method, yielding one common mask.
    """
    gamma = positive_gamma(gamma)
    upper = float(cells[0]["adc_from_pressure"]["x"][-1])
    adc = np.asarray(adc, dtype=float)
    if adc.ndim != 1 or not adc.size or not np.all(np.isfinite(adc)) or np.any(adc < 0) or np.any(adc > 4095):
        raise ValueError("ADC axis must be a finite, nonempty 1-D array within 0..4095")
    span = (full - zero).ravel()
    valid = span > 0
    outputs = {name: np.full((256, len(adc)), np.nan) for name in COLORS}
    for index, cell in enumerate(cells):
        if not valid[index]:
            continue
        u = np.clip((adc - zero.ravel()[index]) / span[index], 0, 1)
        outputs["LINEAR"][index] = upper * u
        outputs["GAMMA"][index] = upper * u ** gamma
        outputs["MULTI-POINT"][index] = np.clip(evaluate_lut(cell["pressure_from_adc"], adc), 0, upper)
    return outputs, valid


def generate_comparison(two_point_path: Path, model_path: Path, output_dir: Path,
                        gamma: float = 4.0, cell: tuple[int, int] = (8, 8)) -> dict:
    gamma = positive_gamma(gamma)
    if len(cell) != 2 or any(not 1 <= value <= 16 for value in cell):
        raise ValueError("representative cell must be row,column within 1..16")
    two_point_path, model_path = two_point_path.resolve(), model_path.resolve()
    two_point = json.loads(two_point_path.read_text(encoding="utf-8"))
    model = json.loads(model_path.read_text(encoding="utf-8"))
    zero, full, cells = validate_inputs(two_point, model)
    source_sweep_path = _resolve_project_recorded_path(model["source_file"])
    upper = float(two_point["load_range_g"][1])
    index = (cell[0] - 1) * 16 + cell[1] - 1
    representative = cells[index]
    z, f = float(zero.ravel()[index]), float(full.ravel()[index])
    if f <= 0:
        raise ValueError("the selected cell's measured ADC at U must be positive to define the inverse plot axis")
    load_fraction = np.linspace(0, 1, 501)
    loads = upper * load_fraction
    adc_axis = np.linspace(0, f, 1025)
    estimates, valid = estimate_curves(zero, full, cells, gamma, adc_axis)
    if not np.any(valid):
        raise ValueError("no positive endpoint spans; no common valid cell set")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.8))
    if valid[index]:
        axes[0].plot(loads, z + (f - z) * load_fraction, color=COLORS["LINEAR"], label="LINEAR forward")
        axes[0].plot(loads, z + (f - z) * load_fraction ** (1 / gamma), color=COLORS["GAMMA"], label=f"GAMMA forward (gamma={gamma:g})")
        axes[0].scatter([0, upper], [z, f], marker="s", color="#222222", s=26, label="Shared sweep endpoint medians", zorder=4)
    else:
        axes[0].text(.04, .95, "Two-point span <= 0: LINEAR/GAMMA unavailable", va="top", transform=axes[0].transAxes, fontsize=9)
    forward = representative["adc_from_pressure"]
    axes[0].plot(loads, evaluate_pchip(forward, loads), color=COLORS["MULTI-POINT"], label="Multi-point PCHIP forward")
    axes[0].scatter(forward["x"], forward["y"], color=COLORS["MULTI-POINT"], s=16, label="Isotonic knots (may form plateaus)")
    axes[0].set(xlabel="Applied whole-layer calibration mass (g)", ylabel="ADC code", xlim=(0, upper), ylim=(0, 4095), title=f"Representative cell R{cell[0]}C{cell[1]}: forward response")
    for name in COLORS:
        if valid[index]:
            axes[1].plot(adc_axis, estimates[name][index], color=COLORS[name], label=name)
    if not valid[index]:
        axes[1].text(.1, .5, "Representative endpoint span <= 0;\nall three comparison curves omitted", transform=axes[1].transAxes)
    axes[1].set(xlabel="ADC code", ylabel="Estimated equivalent whole-layer mass (g)", xlim=(0, f), ylim=(0, upper))
    axes[1].set_title(f"R{cell[0]}C{cell[1]}: actual estimation functions")
    for axis in axes:
        axis.grid(alpha=.22)
        if axis.get_legend_handles_labels()[0]:
            axis.legend(fontsize=8, loc="best")
    note = (f"Same RAW endpoints; output range 0-{upper:g} g. Right ADC axis: 0-{f:g}, ending at this cell's measured endpoint at U.\n"
            "Multi-point uses a linear inverse LUT, not an exact PCHIP inverse; plateaus and endpoint offsets remain.\n"
            "GAMMA is prescribed. Endpoint clamping is retained; separation of these functions is not evidence of accuracy.")
    synthetic = bool(two_point.get("synthetic_test_only") or model.get("synthetic_test_only"))
    title = f"M{two_point['module_id']} / {two_point['fsr']} - calibration-function comparison (gamma={gamma:g})"
    if synthetic:
        title = "SYNTHETIC SOFTWARE TEST - " + title
    fig.suptitle(title, fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, .94))
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    png = output_dir / "calibration_comparison.png"
    pdf = output_dir / "calibration_comparison.pdf"
    fig.savefig(png, dpi=180, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    plt.close(fig)
    manifest = {
        "format": "e-skin-calibration-function-comparison", "version": 3,
        "created_at": datetime.now(timezone.utc).isoformat(), "protocol_id": NEW_PROTOCOL,
        "module_id": two_point["module_id"], "fsr": two_point["fsr"], "load_range_g": [0, upper],
        "source_sweep": {"path": _portable_existing_or_original(model["source_file"], source_sweep_path),
                         "sha256": model["source_sha256"]},
        "gamma": gamma, "gamma_policy": "prescribed; cannot be identified from only two endpoints",
        "panels": ["representative_cell_load_to_adc", "representative_cell_adc_to_load"],
        "inverse_input_axis": {
            "quantity": "raw_adc_code", "range": [0, f],
            "upper_bound_source": "selected cell's shared measured RAW ADC endpoint at the maximum calibration load U",
            "upper_bound_load_g": upper,
        },
        "representative_cell": {"row": cell[0], "column": cell[1]},
        "common_cell_policy": "all finite positive two-point endpoint spans; no error-dependent cell filtering",
        "plotted_cells": int(valid[index]), "available_positive_span_cells": int(valid.sum()),
        "excluded_nonpositive_span_cells": int((~valid).sum()),
        "two_point_problem_cell_count": two_point.get("problem_cell_count"),
        "limitations": note.split("\n"), "synthetic_test_only": synthetic,
        "sources": [{"path": portable_path(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in (two_point_path, model_path)],
        "outputs": [portable_path(png), portable_path(pdf)],
    }
    (output_dir / "comparison_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_cell(text: str) -> tuple[int, int]:
    try:
        values = tuple(int(part.strip()) for part in text.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("cell must be row,column") from error
    if len(values) != 2 or any(not 1 <= value <= 16 for value in values):
        raise argparse.ArgumentTypeError("cell must be row,column within 1..16")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--two-point", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--gamma", type=float, default=4.0)
    parser.add_argument("--cell", type=parse_cell, default=(8, 8))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = generate_comparison(args.two_point, args.model, args.output_dir, args.gamma, args.cell)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
