"""Matched-cell evaluation for shared-endpoint whole-layer calibration.

The legacy evaluation entry points dispatch here only for explicitly marked
captures. Source captures and calibration models are never rewritten.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT / "Utility"))
from portable_paths import calibration_root, portable_path, resolve_recorded_path  # noqa: E402

PROTOCOL_ID = "whole_layer_shared_endpoints_v3"
LEGACY_ID = "legacy_0_3000"
METHODS = ("LINEAR", "GAMMA", "FIT_PRESS")
SHARED_LUT_METHOD = "GLOBAL_LUT"
CAPTURE_NAME = "view_distribution_capture.json"


def validated_range(bounds: Any) -> tuple[float, float]:
    try:
        if len(bounds) != 2:
            raise ValueError
        low, high = map(float, bounds)
    except (TypeError, ValueError) as error:
        raise ValueError("Shared-endpoint range must be [0, U], with finite U > 0") from error
    if low != 0 or not np.isfinite(high) or high <= 0:
        raise ValueError("Shared-endpoint range must be [0, U], with finite U > 0")
    return low, high


def protocol_key(data: dict[str, Any]) -> tuple[str, float, float]:
    """Require explicit new-protocol limits; unmarked old captures stay old."""
    protocol = data.get("protocol_id")
    declared = data.get("evaluation_policy", {})
    bounds = declared.get("statistical_load_range_g", declared.get("range_g", declared.get("range", declared.get("load_range_g"))))
    top_bounds = data.get("load_range_g")
    if top_bounds is not None and bounds is not None and list(top_bounds) != list(bounds):
        raise ValueError("Capture contains conflicting load ranges")
    if protocol in (None, LEGACY_ID):
        if int(data.get("version", 0)) >= 3:
            raise ValueError("Version 3 calibration captures require an explicit new protocol_id")
        if (bounds is not None and list(bounds) != [0, 3000]) or (top_bounds is not None and list(top_bounds) != [0, 3000]):
            raise ValueError("Unmarked legacy capture cannot declare a different evaluation range")
        return LEGACY_ID, 0.0, 3000.0
    if protocol != PROTOCOL_ID:
        raise ValueError(f"Unsupported calibration protocol: {protocol!r}")
    low, high = validated_range(bounds)
    if int(data.get("version", 0)) < 3:
        raise ValueError("New calibration captures require version >= 3")
    return PROTOCOL_ID, low, high


def capture_paths(evaluation_dir: Path) -> list[Path]:
    paths = sorted(evaluation_dir.rglob(CAPTURE_NAME))
    if not paths:
        raise ValueError(f"No {CAPTURE_NAME} under {evaluation_dir}")
    return paths


def selected_capture_paths(evaluation_dir: Path, selected: list[Path] | None) -> list[Path]:
    if selected is None:
        return capture_paths(evaluation_dir)
    paths = [Path(path).resolve() for path in selected]
    if not paths:
        raise ValueError("Explicit capture_paths must contain at least one capture")
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate capture paths cannot be counted as independent repeats")
    return paths


def batch_protocol(paths: list[Path]) -> tuple[str, float, float]:
    keys = {protocol_key(json.loads(path.read_text(encoding="utf-8"))) for path in paths}
    if len(keys) != 1:
        raise ValueError("Mixed calibration protocols/ranges: analyze each protocol separately")
    return keys.pop()


def completion_issue(data: dict[str, Any]) -> str | None:
    status = str(data.get("status", "COMPLETE")).upper()
    if status != "COMPLETE":
        return f"capture_status_{status.lower()}"
    frames = data.get("source_frames", {})
    if "count" in frames and frames["count"] != 200:
        return "incomplete_frame_count"
    if "target_count" in frames and frames["target_count"] != 200:
        return "unsupported_target_frame_count"
    return None


def partition_completed(paths: list[Path]) -> tuple[list[Path], list[dict[str, Any]]]:
    completed, excluded = [], []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        issue = completion_issue(data)
        if issue is None:
            completed.append(path)
        else:
            excluded.append({"source_capture": portable_path(path), "status": data.get("status"),
                             "frame_count": data.get("source_frames", {}).get("count"),
                             "target_frame_count": data.get("source_frames", {}).get("target_count", 200),
                             "exclusion_reason": issue})
    return completed, excluded


def _matrix(value: Any, label: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (16, 16):
        raise ValueError(f"{label} must contain a 16x16 matrix")
    return result


def recorded_predictions_g(data: dict[str, Any], upper: float) -> dict[str, np.ndarray]:
    """Interpret units by the capture schema, never by numerical magnitudes."""
    version = int(data.get("version", 0))
    if version == 3:
        sources = {"LINEAR": ("LINEAR", "ratio", upper),
                   "GAMMA": ("NORM_CAL", "ratio", upper),
                   "FIT_PRESS": ("FIT_PRESS", "g", 1.0)}
    elif version == 4:
        if data.get("prediction_units") != "g":
            raise ValueError("Version 4 captures require prediction_units='g'")
        sources = {name: (name, "g", 1.0) for name in METHODS}
    else:
        raise ValueError(f"Unsupported shared-endpoint prediction schema version {version}")
    views = data.get("views", {})
    result = {}
    for target, (source, unit, factor) in sources.items():
        view = views.get(source)
        if not isinstance(view, dict) or view.get("unit") != unit:
            raise ValueError(f"Version {version} {source} must be captured in {unit} units")
        result[target] = _matrix(view.get("values"), source) * factor
    raw_view = views.get("RAW", {})
    if raw_view.get("unit") not in {"ADC code", "ADC"}:
        raise ValueError("RAW must be captured in ADC code units")
    _matrix(raw_view.get("values"), "RAW")
    return result


def _resolve_recorded_path(value: Any, capture_path: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("New capture must identify the exact recorded model path")
    return resolve_recorded_path(value, capture_path)


def _portable_recorded_sources(value: Any, capture_path: Path, key: str = "") -> Any:
    """Make path-bearing provenance metadata portable without changing evidence."""
    if isinstance(value, dict):
        return {name: _portable_recorded_sources(item, capture_path, str(name))
                for name, item in value.items()}
    if isinstance(value, list):
        return [_portable_recorded_sources(item, capture_path, key) for item in value]
    if isinstance(value, str) and (
        "path" in key.lower() or key.lower().endswith("_original")
        or key.lower() in {"two_point", "fitted_response", "fit", "source"}
    ):
        try:
            resolved = _resolve_recorded_path(value, capture_path)
            # External test fixtures may live outside this calibration tree;
            # keep those references lossless while normalizing project files.
            try:
                resolved.relative_to(calibration_root())
            except ValueError:
                return Path(value).as_posix()
            return portable_path(resolved)
        except (OSError, ValueError, TypeError):
            return Path(value).as_posix()
    return value


def recorded_two_point(data: dict[str, Any], capture_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use the capture's frozen snapshot, or its exact hash-checked model file."""
    sources = data.get("source_models", {})
    source = sources.get("two_point", sources.get("two_point_calibration", sources.get("normalized_calibration")))
    if isinstance(source, str):
        source = {"path": source}
    if not isinstance(source, dict):
        raise ValueError("New capture is missing source_models.two_point provenance")
    source = dict(source)
    source.setdefault("sha256", sources.get("two_point_sha256", sources.get("normalized_calibration_sha256")))
    path = _resolve_recorded_path(source.get("path"), capture_path)
    snapshot = source.get("snapshot", sources.get("two_point_snapshot", data.get("calibration_snapshot", sources.get("calibration_snapshot"))))
    if snapshot is not None:
        if not isinstance(snapshot, dict):
            raise ValueError("Invalid embedded two-point snapshot")
        model = snapshot
        used = "embedded_snapshot"
    else:
        raw = path.read_bytes()
        expected = source.get("sha256")
        if not expected:
            raise ValueError("Exact two-point file requires sha256 or an embedded snapshot")
        if hashlib.sha256(raw).hexdigest().lower() != str(expected).lower():
            raise ValueError("Recorded two-point model hash mismatch; refusing changed model")
        model = json.loads(raw)
        used = "recorded_path_sha256_verified"
    if model.get("protocol_id") != PROTOCOL_ID:
        raise ValueError("Recorded endpoint model is not the shared-endpoint protocol")
    if validated_range(model.get("load_range_g")) != protocol_key(data)[1:]:
        raise ValueError("Recorded two-point model range differs from capture")
    if model.get("source_path") and _resolve_recorded_path(model["source_path"], capture_path) != path:
        raise ValueError("Two-point snapshot source path differs from capture provenance")
    for key in ("module_id", "fsr"):
        if key in model and str(model[key]) != str(data.get(key)):
            raise ValueError(f"Recorded two-point model {key} differs from capture")
    fit = sources.get("fit", sources.get("fit_model", sources.get("fit_pressure", sources.get("fitted_response"))))
    if isinstance(fit, str):
        fit = {"path": fit}
    if not isinstance(fit, dict) or not fit.get("path"):
        raise ValueError("New capture is missing the exact recorded FIT model path")
    fit = dict(fit)
    fit.setdefault("sha256", sources.get("fitted_response_sha256"))
    gamma = sources.get("gamma", sources.get("normalized_gamma", data.get("gamma", source.get("gamma"))))
    if gamma is None:
        gamma = data.get("views", {}).get("NORM_CAL", {}).get("gamma")
    try:
        gamma = float(gamma)
    except (TypeError, ValueError) as error:
        raise ValueError("Recorded gamma is required") from error
    if not np.isfinite(gamma) or gamma <= 0:
        raise ValueError("Recorded gamma must be finite and positive")
    endpoint_sha = source.get("sha256")
    if endpoint_sha:
        endpoint_identity = "sha256:" + str(endpoint_sha).strip().lower()
    else:
        # Synthetic/older exported captures may embed endpoints without a file
        # hash. Ignore the copy location when hashing the frozen model content.
        model_content = dict(model)
        model_content.pop("source_path", None)
        canonical = json.dumps(model_content, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode("utf-8")
        endpoint_identity = "snapshot_sha256:" + hashlib.sha256(canonical).hexdigest()
    fit_path = _resolve_recorded_path(fit["path"], capture_path)
    fit_identity = ("sha256:" + str(fit["sha256"]).strip().lower() if fit.get("sha256")
                    else "recorded_path_without_sha256:" + str(fit_path))
    provenance = {"two_point": portable_path(path), "two_point_source": used,
                  "two_point_sha256": source.get("sha256"),
                  "fit": portable_path(fit_path),
                  "fit_sha256": fit.get("sha256"), "gamma": gamma,
                  "comparison_condition": {"gamma": gamma, "endpoint_identity": endpoint_identity,
                                           "fit_identity": fit_identity},
                  "fit_sha256_basis": "recorded at capture; predictions are read from capture, not refitted",
                  "recorded_source_models": _portable_recorded_sources(sources, capture_path),
                  "endpoint_model_source": model.get("source", {})}
    return model, provenance


def prepare_matched(data: dict[str, Any], capture_path: Path) -> dict[str, Any]:
    protocol, lower, upper = protocol_key(data)
    if protocol != PROTOCOL_ID:
        raise ValueError("Matched shared-endpoint evaluator only accepts the new protocol")
    issue = completion_issue(data)
    if issue is not None:
        raise ValueError(f"Cannot evaluate incomplete capture: {issue}")
    actual = float(data["actual_load"]["value"])
    if not np.isfinite(actual):
        raise ValueError("Actual load must be finite")
    model, provenance = recorded_two_point(data, capture_path)
    if "interval_low_zero" in model:
        zero = _matrix(model["interval_low_zero"], "zero endpoint")
        full = _matrix(model["interval_high_full"], f"{upper:g} g endpoint")
    else:
        zero = _matrix(model["zero_load"]["median"], "zero endpoint")
        full = _matrix(model["full_load"]["median"], f"{upper:g} g endpoint")
    raw = _matrix(data["views"]["RAW"]["values"], "RAW")
    estimates = recorded_predictions_g(data, upper)
    endpoint_valid = np.isfinite(zero) & np.isfinite(full) & (full > zero)
    common = np.isfinite(raw) & endpoint_valid
    for matrix in estimates.values():
        common &= np.isfinite(matrix)
    reasons = np.full((16, 16), "ok", dtype=object)
    reasons[~np.isfinite(raw)] = "nonfinite_raw"
    reasons[~endpoint_valid] = "invalid_two_point_endpoint_or_span"
    finite_all = np.logical_and.reduce([np.isfinite(matrix) for matrix in estimates.values()])
    reasons[~finite_all & endpoint_valid & np.isfinite(raw)] = "nonfinite_method_prediction"
    # Stability/saturation warnings describe cells, but do not remove them.
    flags = model.get("problem_cells", model.get("quality", model.get("quality_flags", model.get("cell_flags", {}))))
    return {"source": portable_path(capture_path), "module_id": data.get("module_id"),
            "fsr": data.get("fsr"), "actual_load_g": actual,
            "included": lower <= actual <= upper, "load_range_g": [lower, upper], "raw": raw, "estimates_g": estimates,
            "record_common_mask": common.copy(), "mask": common.copy(),
            "status": reasons, "model_quality_flags": flags,
            "provenance": provenance, "source_frames": data.get("source_frames", {}),
            "capture_metadata": data.get("experiment_metadata", data.get("metadata", {}))}


def load_matched_batch(paths: list[Path]) -> list[dict[str, Any]]:
    from evaluation_plotting import load_capture
    if batch_protocol(paths)[0] != PROTOCOL_ID:
        raise ValueError("New evaluator cannot process legacy captures")
    paths, _excluded = partition_completed(paths)
    if not paths:
        raise ValueError("No complete 200-frame calibration captures to evaluate")
    records = [prepare_matched(load_capture(path), path) for path in paths]
    if len({(r["module_id"], r["fsr"]) for r in records}) != 1:
        raise ValueError("Analyze one module/FSR at a time")
    conditions = {
        tuple(record["provenance"]["comparison_condition"][key]
              for key in ("gamma", "endpoint_identity", "fit_identity"))
        for record in records
    }
    if len(conditions) != 1:
        raise ValueError("Mixed calibration models or gamma values: group captures by endpoint model, FIT model and gamma before analysis; these are not repeats of one condition")
    # One fixed set across methods and all in-range captures of this analysis.
    in_range = [r for r in records if r["included"]]
    common = np.logical_and.reduce([r["record_common_mask"] for r in in_range]) if in_range else np.zeros((16, 16), bool)
    for record in records:
        record["mask"] = common.copy() if record["included"] else np.zeros((16, 16), bool)
        excluded_here = record["record_common_mask"] & ~record["mask"]
        record["status"][excluded_here] = "outside_actual_load_range" if not record["included"] else "excluded_by_fixed_batch_common_mask"
    return sorted(records, key=lambda r: (r["actual_load_g"], r["source"]))


def _native_statistics(values: np.ndarray) -> dict[str, Any]:
    from evaluation_plotting import describe
    result = describe(values)
    result.pop("cv_percent", None)
    return result


def _statistics(values: np.ndarray, actual: float) -> dict[str, Any]:
    result = _native_statistics(values)
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    errors = finite - actual
    result.update({"unit": "g", "bias_g": float(errors.mean()) if errors.size else None,
                   "mae_g": float(np.abs(errors).mean()) if errors.size else None,
                   "rmse_g": float(np.sqrt(np.square(errors).mean())) if errors.size else None,
                   "mean_estimate_absolute_percentage_error": abs(float(errors.mean())) / abs(actual) * 100 if errors.size and actual != 0 else None,
                   "cell_mean_absolute_percentage_error": float(np.abs(errors).mean()) / abs(actual) * 100 if errors.size and actual != 0 else None})
    return result


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    mask = record["mask"]
    reasons, counts = np.unique(record["status"][~mask], return_counts=True)
    return {k: record[k] for k in ("source", "module_id", "fsr", "actual_load_g", "included", "load_range_g", "provenance", "source_frames", "capture_metadata", "model_quality_flags")} | {
        "common_cell_count": int(mask.sum()), "record_common_cell_count": int(record["record_common_mask"].sum()),
        "common_cell_mask": mask.tolist(),
        "exclusion_reasons": dict(zip(reasons.tolist(), counts.tolist())),
        "raw_all_finite_statistics": _native_statistics(record["raw"]) | {"unit": "ADC code"},
        "methods": {name: {"matched_statistics": _statistics(values[mask], record["actual_load_g"]),
                             "all_finite_source_statistics": _statistics(values, record["actual_load_g"]),
                             "below_0g_count": int(np.sum(np.isfinite(values) & (values < 0))),
                             "above_upper_range_count": int(np.sum(np.isfinite(values) & (values > record["load_range_g"][1]))),
                             "at_0g_count": int(np.sum(values == 0)), "at_upper_range_count": int(np.sum(values == record["load_range_g"][1]))}
                    for name, values in record["estimates_g"].items()}}


def quality_policy(bounds: list[float]) -> dict[str, Any]:
    lower, upper = validated_range(bounds)
    return {"protocol_id": PROTOCOL_ID, "range_g": [lower, upper],
            "estimand": "equivalent whole-layer calibration mass (g), not local pressure",
            "comparison_units": "All analyzed predictions are in g. Version 4: recorded LINEAR/GAMMA/FIT_PRESS in g, unchanged. Version 3 compatibility: multiply recorded LINEAR/NORM_CAL ratios by the sweep upper load U exactly once; FIT_PRESS already in g.",
            "common_mask": "finite RAW, finite two-point endpoints with positive span, all three predictions finite; intersection across all in-range captures and methods",
            "prediction_range_filter": "none: finite poor or out-of-range predictions are retained",
            "quality_flags": "reported, not automatically excluded",
            "zero_load_percentage_error": None,
            "repeats": "n is capture count; independent loading is not inferred from frame or cell count",
            "batch_condition": "one module/layer, one load range, one endpoint model, one FIT model and one gamma; model SHA takes priority over copied-file paths",
            "population": "spatial cells of per-cell medians across captured frames; spatial SD is not repeatability SD",
            "spatial_variance_ddof": 0,
            "dispersion": "spatial SD (g), population variance (g squared), IQR (g), MAD (g), computed directly on the same mass predictions without normalization",
            "repeat_error_bars": "sample SD of per-capture metrics when at least two captures exist; n=1 has undefined SD and no error bar",
            "gamma": "read from capture provenance; never refitted to validation data",
            "saturation_annotation": "legacy 1200/3000 g thresholds are not applied"}


def _write_cells(path: Path, records: list[dict[str, Any]],
                 methods: tuple[str, ...] = METHODS) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        columns = {"LINEAR": "linear_g", "GAMMA": "gamma_g", "FIT_PRESS": "fit_g",
                   SHARED_LUT_METHOD: "global_lut_g"}
        writer.writerow(["source", "actual_load_g", "row", "column", "raw_adc", "common_valid", "status", "quality_flags", *[columns[name] for name in methods]])
        for record in records:
            flags = record["model_quality_flags"]
            flag_lookup = {(int(cell["row"]), int(cell["column"])): cell.get("flags", []) for cell in flags if isinstance(cell, dict) and "row" in cell and "column" in cell} if isinstance(flags, list) else {}
            for row, col in np.ndindex((16, 16)):
                values = [record["raw"][row, col]] + [record["estimates_g"][name][row, col] for name in methods]
                values = [float(v) if np.isfinite(v) else "" for v in values]
                writer.writerow([record["source"], record["actual_load_g"], row + 1, col + 1, values[0], bool(record["mask"][row, col]), record["status"][row, col], "|".join(flag_lookup.get((row + 1, col + 1), [])), *values[1:]])


def _batch_compact_record(record: dict[str, Any]) -> dict[str, Any]:
    """Add the historical CV metric to batch tables using mass values directly."""
    result = compact_record(record)
    for method in result["methods"].values():
        for key in ("matched_statistics", "all_finite_source_statistics"):
            stats = method[key]
            mean, sd = stats["mean"], stats["std"]
            stats["cv_percent"] = (100 * sd / abs(mean) if mean is not None
                                    and sd is not None and abs(mean) > 1e-12
                                    and stats["count"] > 1 else None)
    return result


def _accuracy_rows(compact: list[dict[str, Any]],
                   methods: tuple[str, ...] = METHODS) -> list[dict[str, Any]]:
    rows = []
    for index, record in enumerate(compact, start=1):
        for name in methods:
            stats = record["methods"][name]["matched_statistics"]
            reference = record["methods"][name]["all_finite_source_statistics"]
            included = record["included"] and stats["mean"] is not None
            rows.append({"record_index": index, "method": name, "source": record["source"],
                         "source_capture": record["source"], "module_id": record["module_id"],
                         "fsr": record["fsr"], "frame_count": record["source_frames"].get("count"),
                         "actual_load_g": record["actual_load_g"],
                         "inferred_load_g": stats["mean"] if included else None,
                         "actual_unit": "g", "inferred_unit": "g",
                         "valid_cells": record["common_cell_count"],
                         "excluded_cells": 256 - record["common_cell_count"],
                         "included": included,
                         "exclusion_reason": None if included else "actual_load_outside_calibrated_range" if not record["included"] else "no_common_valid_cells",
                         "signed_error_g": stats["bias_g"] if included else None,
                         "absolute_error_g": abs(stats["bias_g"]) if included else None,
                         "mae_g": stats["mae_g"] if included else None,
                         "rmse_g": stats["rmse_g"] if included else None,
                         "error_rate_percent": stats["mean_estimate_absolute_percentage_error"] if included else None,
                         "zero_load_excluded_from_percentage_error": record["actual_load_g"] == 0,
                         "display_reference_inferred_load_g": reference["mean"],
                         "display_reference_signed_error_g": reference["bias_g"],
                         "display_reference_error_rate_percent": reference["mean_estimate_absolute_percentage_error"]})
    return rows


def _accuracy_metrics(rows: list[dict[str, Any]],
                      methods: tuple[str, ...] = METHODS) -> dict[str, Any]:
    result = {}
    for name in methods:
        selected = [row for row in rows if row["method"] == name]
        included = [row for row in selected if row["included"]]
        rates = [row["error_rate_percent"] for row in included if row["error_rate_percent"] is not None]
        result[name] = {"record_count": len(included), "total_source_records": len(selected),
                        "excluded_records": len(selected) - len(included),
                        "nonzero_load_records": len(rates),
                        "zero_load_records_excluded": sum(row["actual_load_g"] == 0 for row in included),
                        "mean_error_rate_percent": float(np.mean(rates)) if rates else None,
                        "max_error_rate_percent": float(np.max(rates)) if rates else None,
                        "min_error_rate_percent": float(np.min(rates)) if rates else None,
                        "mean_absolute_error_g": float(np.mean([row["absolute_error_g"] for row in included])) if included else None,
                        "aggregation": "one saved complete capture receives one weight; percentage errors exclude zero load"}
    return result


def _groups(compact: list[dict[str, Any]],
            methods: tuple[str, ...] = METHODS) -> list[dict[str, Any]]:
    groups = []
    for load in sorted({r["actual_load_g"] for r in compact if r["included"]}):
        members = [r for r in compact if r["included"] and r["actual_load_g"] == load]
        method_groups = {}
        for name in methods:
            metrics = {}
            for metric in ("mean", "bias_g", "mae_g", "rmse_g", "std", "cv_percent", "mad", "variance", "iqr", "mean_estimate_absolute_percentage_error"):
                values = [r["methods"][name]["matched_statistics"].get(metric) for r in members]
                values = [v for v in values if v is not None]
                metrics[metric] = {"mean": float(np.mean(values)) if values else None,
                                   "sd": float(np.std(values, ddof=1)) if len(values) > 1 else None,
                                   "n": len(values)}
            method_groups[name] = metrics
        groups.append({"actual_load_g": load, "capture_count": len(members), "record_count": len(members),
                       "valid_count_min": min(r["common_cell_count"] for r in members),
                       "valid_count_max": max(r["common_cell_count"] for r in members),
                       "excluded_count_total": sum(256-r["common_cell_count"] for r in members),
                       "sources": [r["source"] for r in members], "methods": method_groups})
    return groups


def _plot_group_metric(axis, groups: list[dict[str, Any]], metric: str,
                       methods: tuple[str, ...] = METHODS) -> None:
    from evaluation_plotting import COLORS
    for name in methods:
        color = "#263b59" if name == SHARED_LUT_METHOD else COLORS[name]
        label = "Shared LUT" if name == SHARED_LUT_METHOD else name
        points = [(g["actual_load_g"], g["methods"][name][metric]) for g in groups]
        points = [(x, stats) for x, stats in points if stats["mean"] is not None]
        if not points:
            continue
        axis.plot([p[0] for p in points], [p[1]["mean"] for p in points],
                  marker={"LINEAR": "o", "GAMMA": "s", "FIT_PRESS": "^", SHARED_LUT_METHOD: "D"}[name],
                  linewidth=1.8, markersize=5, color=color, label=label)
        repeated = [(x, stats) for x, stats in points if stats["sd"] is not None]
        if repeated:
            axis.errorbar([p[0] for p in repeated], [p[1]["mean"] for p in repeated],
                          yerr=[p[1]["sd"] for p in repeated], fmt="none", capsize=3,
                          color=color, label="_nolegend_")


def _batch_note(groups: list[dict[str, Any]], *, include_shared_lut: bool = False) -> str:
    import textwrap
    counts = "; ".join(f"{group['actual_load_g']:g} g: n={group['capture_count']}" for group in groups)
    prediction_note = ("Fixed original common cells; original saved predictions plus per-cell Shared LUT from the frozen training model."
                       if include_shared_lut else "Fixed common cells and the same saved predictions for all methods.")
    return (prediction_note + " Error bars: capture-to-capture SD only when n > 1.\n"
            "n counts captures, not temporal frames or spatial cells. Independent reloading must be documented.\n"
            + textwrap.fill("Capture counts: " + counts, width=145))


def _plot_zero_load_detail(axis, groups: list[dict[str, Any]],
                           methods: tuple[str, ...]) -> dict[str, Any] | None:
    """Show measured zero-load points and a separate table above the main plot."""
    from evaluation_plotting import COLORS
    from matplotlib.patches import ConnectionPatch, Rectangle
    zero = next((group for group in groups if group["actual_load_g"] == 0), None)
    if zero is None:
        return None
    entries = {}
    for name in methods:
        stats = zero["methods"][name]["bias_g"]
        if stats["mean"] is not None:
            entries[name] = {"signed_error_g": stats["mean"],
                             "absolute_error_g": abs(stats["mean"]),
                             "sd_g": stats["sd"], "n_captures": stats["n"]}
    if not entries:
        return None
    extrema = [0.0]
    for entry in entries.values():
        sd = entry["sd_g"] or 0.0
        extrema.extend([entry["signed_error_g"] - sd, entry["signed_error_g"] + sd])
    low, high = min(extrema), max(extrema)
    span = max(high - low, 1.0)
    y_limits = (low - .15 * span, high + .20 * span)
    panel = axis.figure.add_axes([.095, .725, .39, .22], zorder=6)
    panel.set_facecolor("white")
    panel.set_xticks([])
    panel.set_yticks([])
    for spine in panel.spines.values():
        spine.set_visible(True)
        spine.set_color("#87909e")
        spine.set_linewidth(.8)
    panel.text(.04, .94, "Zero-load detail (0 g)", transform=panel.transAxes,
               va="top", fontsize=8.5, fontweight="semibold")
    points_axis = panel.inset_axes([.13, .20, .22, .62])
    points_axis.set_xlim(-1, 1)
    points_axis.set_ylim(*y_limits)
    points_axis.set_xticks([0])
    points_axis.yaxis.set_major_locator(MaxNLocator(nbins=3))
    points_axis.tick_params(labelsize=7, length=2, pad=2)
    points_axis.set_xlabel("Load (g)", fontsize=7, labelpad=1)
    points_axis.set_ylabel("Signed error (g)", fontsize=7, labelpad=2)
    rows, row_colors = [], []
    for name, entry in entries.items():
        color = "#263b59" if name == SHARED_LUT_METHOD else COLORS[name]
        marker = {"LINEAR": "o", "GAMMA": "s", "FIT_PRESS": "^", SHARED_LUT_METHOD: "D"}[name]
        label = "Shared LUT" if name == SHARED_LUT_METHOD else name
        points_axis.scatter([0], [entry["signed_error_g"]], color=color,
                            marker=marker, s=24, zorder=3)
        rows.append([label, f"{entry['absolute_error_g']:.3f}"])
        row_colors.append(color)
    table = panel.table(cellText=rows, colLabels=["Method", "|error| (g)"],
                        cellLoc="left", colLoc="left", colWidths=[.61, .39],
                        bbox=[.42, .13, .55, .70])
    table.auto_set_font_size(False)
    table.set_fontsize(7.5)
    for (row, column), cell in table.get_celld().items():
        cell.set_edgecolor("#d8dde3")
        cell.set_linewidth(.5)
        if row == 0:
            cell.set_facecolor("#f1f3f6")
            cell.get_text().set_fontweight("semibold")
        else:
            cell.get_text().set_color(row_colors[row - 1])
    x_limits = axis.get_xlim()
    half_width = max((x_limits[1] - x_limits[0]) * .012, .1)
    region = Rectangle((-half_width, y_limits[0]), 2 * half_width,
                       y_limits[1] - y_limits[0], facecolor="none",
                       edgecolor="#59677b", linewidth=1, linestyle="--",
                       clip_on=False, zorder=5)
    axis.add_patch(region)
    arrow = ConnectionPatch(xyA=(.04, 0), coordsA=panel.transAxes,
                            xyB=(0, y_limits[1]), coordsB=axis.transData,
                            arrowstyle="-|>", mutation_scale=11, linewidth=1,
                            color="#59677b", connectionstyle="arc3,rad=.035",
                            clip_on=False, zorder=5)
    axis.figure.add_artist(arrow)
    return {"actual_load_g": 0.0, "methods": entries,
            "definition": "The four points retain signed mean error at zero load; the adjacent table gives its absolute value in g. No connecting curves, percentage errors or fitted intercepts are added.",
            "main_plot_region": {"x_g": [-half_width, half_width], "y_g": list(y_limits)}}


def _load_axis_limits(groups: list[dict[str, Any]]) -> tuple[float, float]:
    loads = [float(group["actual_load_g"]) for group in groups]
    if not loads:
        return 0.0, 1.0
    low, high = min(loads), max(loads)
    padding = (high - low) * .05 if high > low else max(abs(high) * .05, 1.0)
    return max(0.0, low - padding), high + padding


def _label_error_line_ends(axis, groups, metric, methods, accuracy_metrics):
    """Attach capture-weighted APE summaries to each method's last plotted point."""
    from evaluation_plotting import COLORS
    low, high = axis.get_ylim()
    span = max(high - low, 1e-12)
    endings = []
    for name in methods:
        points = [(g["actual_load_g"], g["methods"][name][metric]["mean"])
                  for g in groups if g["methods"][name][metric]["mean"] is not None]
        if points:
            x, y = points[-1]
            endings.append((name, x, y, min(.93, max(.07, (y - low) / span))))
    endings.sort(key=lambda item: item[3])
    positions = []
    for item in endings:
        positions.append(max(item[3], positions[-1] + .13 if positions else .07))
    if positions and positions[-1] > .93:
        positions = [p - (positions[-1] - .93) for p in positions]
    if positions and positions[0] < .07:
        positions = np.linspace(.07, .93, len(positions)).tolist()
    axis.text(1.025, 1.025, "APE: mean / max / min (%)", transform=axis.transAxes,
              fontsize=8, ha="left", va="bottom")
    for (name, x, y, _), label_y in zip(endings, positions):
        color = "#263b59" if name == SHARED_LUT_METHOD else COLORS[name]
        label = "Shared LUT" if name == SHARED_LUT_METHOD else name
        values = [accuracy_metrics[name][key] for key in
                  ("mean_error_rate_percent", "max_error_rate_percent", "min_error_rate_percent")]
        text = label + "\n" + " / ".join("n/a" if v is None else f"{v:.2f}" for v in values)
        axis.annotate(text, xy=(x, y), xytext=(1.025, label_y), textcoords="axes fraction",
                      color=color, fontsize=8, ha="left", va="center", annotation_clip=False,
                      bbox={"facecolor": "white", "edgecolor": "none", "pad": 1},
                      arrowprops={"arrowstyle": "-", "color": color, "linewidth": .8,
                                  "relpos": (0, .5)})


def _set_load_axis(axis, limits: tuple[float, float]) -> None:
    axis.set_xlim(*limits)
    axis.xaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=3))


def analyze_batch(evaluation_dir: Path, output_dir: Path, *, kind: str = "accuracy",
                  capture_paths: list[Path] | None = None,
                  include_shared_lut: bool = False) -> dict[str, Path]:
    from evaluation_plotting import COLORS, plot_style, write_json, finish_figure
    if kind not in {"accuracy", "dispersion"}:
        raise ValueError("Analysis kind must be accuracy or dispersion")
    paths = selected_capture_paths(evaluation_dir, capture_paths)
    records = load_matched_batch(paths)
    _completed_paths, incomplete = partition_completed(paths)
    lower, upper = records[0]["load_range_g"]
    shared_lut = None
    methods = METHODS
    if kind == "accuracy" and include_shared_lut:
        from shared_lut_baseline import build_shared_lut, predict_shared_lut
        shared_lut = build_shared_lut(records[0])
        if validated_range(shared_lut.get("load_range_g")) != (lower, upper):
            raise ValueError("Shared LUT range differs from the recorded comparison condition")
        for record in records:
            values = _matrix(predict_shared_lut(record["raw"], shared_lut), "Shared LUT predictions")
            if not np.all(np.isfinite(values[record["mask"]])):
                raise ValueError("Shared LUT predictions must be finite on the original fixed common mask; refusing to change the comparison population")
            record["estimates_g"][SHARED_LUT_METHOD] = values
        methods = METHODS + (SHARED_LUT_METHOD,)
    compact = [_batch_compact_record(r) for r in records]
    groups = _groups(compact, methods)
    x_limits = _load_axis_limits(groups)
    observed_loads = [float(group["actual_load_g"]) for group in groups]
    observed_limits = [min(observed_loads), max(observed_loads)] if observed_loads else None
    accuracy_rows = _accuracy_rows(compact, methods)
    accuracy_metrics = _accuracy_metrics(accuracy_rows, methods)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    zero_load_detail = None
    if shared_lut is not None:
        outputs["shared_lut_model"] = output_dir / "shared_lut_model.json"
        write_json(outputs["shared_lut_model"], shared_lut)
    with plot_style():
        if kind == "accuracy":
            metrics = (("bias_g", "Signed mean error (g)", "load_error_vs_load.png"),
                       ("mean", "Inferred load (g)", "load_comparison.png"),
                       ("mean_estimate_absolute_percentage_error", "Absolute percentage error (%)", "load_error_rate_vs_load.png"))
            for metric, ylabel, filename in metrics:
                fig, axis = plt.subplots(figsize=(11.8, 7.7 if metric == "bias_g" else 6.2))
                _plot_group_metric(axis, groups, metric, methods)
                if metric == "mean" and observed_limits is not None:
                    axis.plot(observed_limits, observed_limits, "k--", alpha=.5, label="Ideal")
                elif metric == "bias_g":
                    axis.axhline(0, color="gray", linestyle="--", linewidth=1, label="Zero error")
                _set_load_axis(axis, x_limits)
                axis.set(xlabel="Actual load (g)", ylabel=ylabel)
                axis.grid(axis="y", alpha=.75)
                if metric == "bias_g":
                    axis.legend(loc="upper left", bbox_to_anchor=(.53, .815),
                                bbox_transform=fig.transFigure, borderaxespad=0,
                                ncol=2, fontsize=8)
                else:
                    axis.legend(loc="upper right" if metric.endswith("percentage_error") else "upper left",
                                ncol=2, fontsize=8)
                if metric.endswith("percentage_error"):
                    axis.set_ylim(bottom=0)
                title = {"bias_g": "Load error: inferred minus actual", "mean": "Actual vs inferred load",
                         "mean_estimate_absolute_percentage_error": "Relative load error"}[metric]
                finish_figure(fig, f"M{records[0]['module_id']} {records[0]['fsr']} | {title}",
                              _batch_note(groups, include_shared_lut=shared_lut is not None) + "\nZero load is excluded only from percentage errors; positive signed error indicates overestimation.")
                fig.subplots_adjust(left=.095, right=.72, bottom=.10 if metric == "bias_g" else .12,
                                    top=.66 if metric == "bias_g" else .86)
                if metric == "bias_g":
                    zero_load_detail = _plot_zero_load_detail(axis, groups, methods)
                _label_error_line_ends(axis, groups, metric, methods, accuracy_metrics)
                outputs[metric] = output_dir / filename
                fig.savefig(outputs[metric], dpi=150)
                if metric == "bias_g":
                    outputs["pdf"] = output_dir / "load_error_vs_load.pdf"
                    fig.savefig(outputs["pdf"])
                plt.close(fig)
            outputs["plot"] = outputs["mean"]
            outputs["comparison_plot"] = outputs["mean"]
            outputs["error_plot"] = outputs["bias_g"]
            outputs["error_rate_plot"] = outputs["mean_estimate_absolute_percentage_error"]
            outputs["primary_plot"] = outputs["bias_g"]
        else:
            for metric, title, unit, filename in (
                    ("cv_percent", "Coefficient of variation", "%", "dispersion_cv.png"),
                    ("variance", "Population variance", "g²", "dispersion_variance.png"),
                    ("iqr", "Interquartile range", "g", "dispersion_iqr.png"),
                    ("mad", "Median absolute deviation", "g", "dispersion_mad.png"),
                    ("std", "Population standard deviation", "g", "dispersion_sd.png")):
                single = metric in {"cv_percent", "std"}
                figure, panels = plt.subplots(1, 1 if single else 4,
                                             figsize=(11.8, 6.2) if single else (21.2, 5.7), squeeze=False)
                for index, axis in enumerate(panels.flat):
                    chosen = METHODS if single or index == 3 else (METHODS[index],)
                    _plot_group_metric(axis, groups, metric, methods=chosen)
                    _set_load_axis(axis, x_limits)
                    axis.set(xlabel="Actual load (g)", ylabel=f"{title} ({unit})")
                    if metric != "cv_percent":
                        axis.set_title(" + ".join(chosen), loc="left", color=COLORS[chosen[0]])
                    axis.grid(axis="y", alpha=.75)
                    axis.legend(loc="best", fontsize=8, frameon=True, facecolor="white", edgecolor="none", framealpha=.95)
                    if metric == "cv_percent":
                        axis.text(0, 1.055, "CV = population SD / |mean| × 100%; calculated from predictions in g",
                                  transform=axis.transAxes, fontsize=9)
                note = _batch_note(groups)
                if metric == "cv_percent":
                    note += "\nCV is undefined at zero mean and can be unstable near zero; no Min–Max scaling is applied."
                finish_figure(figure, f"M{records[0]['module_id']} {records[0]['fsr']} | {title}", note)
                figure.subplots_adjust(bottom=.13, top=.82, left=.065, right=.985, wspace=.30)
                outputs[metric] = output_dir / filename
                figure.savefig(outputs[metric], dpi=150)
                outputs[f"{metric}_pdf"] = outputs[metric].with_suffix(".pdf")
                figure.savefig(outputs[f"{metric}_pdf"])
                plt.close(figure)
            fig, axes = plt.subplots(2, 2, figsize=(12, 9))
            for axis, (metric, ylabel) in zip(axes.flat, (("std", "Spatial SD (g)"),
                              ("variance", "Spatial variance (g²)"), ("iqr", "Spatial IQR (g)"),
                              ("mad", "Spatial MAD (g)"))):
                _plot_group_metric(axis, groups, metric)
                _set_load_axis(axis, x_limits)
                axis.set(xlabel="Actual load (g)", ylabel=ylabel)
                axis.grid(axis="y", alpha=.5)
                axis.legend()
            fig.suptitle(f"M{records[0]['module_id']} {records[0]['fsr']} | Dispersion of the three load predictions")
            fig.tight_layout(rect=(0, 0, 1, .96))
            outputs["combined"] = output_dir / "dispersion_comparison.png"
            outputs["plot"] = outputs["cv_percent"]
            outputs["primary_plot"] = outputs["cv_percent"]
            fig.savefig(outputs["combined"], dpi=150)
            outputs["combined_pdf"] = output_dir / "dispersion_comparison.pdf"
            outputs["pdf"] = outputs["cv_percent_pdf"]
            fig.savefig(outputs["combined_pdf"])
            plt.close(fig)
    outputs["metrics_csv"] = output_dir / "metrics_by_load.csv"
    with outputs["metrics_csv"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["actual_load_g", "method", "metric", "unit", "mean", "sd", "n_captures"])
        for group in groups:
            for method, values in group["methods"].items():
                for metric, stats in values.items():
                    unit = "g^2" if metric == "variance" else "%" if metric == "cv_percent" or metric.endswith("percentage_error") else "g"
                    writer.writerow([group["actual_load_g"], method, metric, unit, stats["mean"], stats["sd"], stats["n"]])
    outputs["csv"] = output_dir / ("load_comparison.csv" if kind == "accuracy" else "dispersion_metrics.csv")
    with outputs["csv"].open("w", encoding="utf-8", newline="") as handle:
        if kind == "accuracy":
            writer = csv.DictWriter(handle, fieldnames=list(accuracy_rows[0]))
            writer.writeheader()
            writer.writerows(accuracy_rows)
        else:
            fields = ["actual_load_g", "record_count"]
            metrics = ("mean", "std", "cv_percent", "iqr", "mad", "variance")
            for name in METHODS:
                fields.extend(f"{name}_{key}" for key in ("unit", "valid_count_min", "valid_count_max", "excluded_count_total"))
                fields.extend(f"{name}_{metric}{suffix}" for metric in metrics for suffix in ("", "_sd", "_n"))
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for group in groups:
                row = {"actual_load_g": group["actual_load_g"], "record_count": group["capture_count"]}
                for name in METHODS:
                    row[f"{name}_unit"] = "g (variance: g^2; CV: %)"
                    for key in ("valid_count_min", "valid_count_max", "excluded_count_total"):
                        row[f"{name}_{key}"] = group[key]
                    for metric in metrics:
                        stats = group["methods"][name][metric]
                        row[f"{name}_{metric}"] = stats["mean"]
                        row[f"{name}_{metric}_sd"] = stats["sd"]
                        row[f"{name}_{metric}_n"] = stats["n"]
                writer.writerow(row)
    outputs["cells"] = output_dir / "matched_comparison_cells.csv"
    _write_cells(outputs["cells"], records, methods)
    outputs["summary"] = output_dir / ("load_comparison_summary.json" if kind == "accuracy" else "dispersion_comparison_summary.json")
    batch_policy = quality_policy([lower, upper])
    if shared_lut is not None:
        batch_policy["shared_lut"] = "One inverse LUT from the frozen training mean-cell response, applied independently to each RAW cell before spatial statistics; no validation fitting or RAW averaging before inversion"
        batch_policy["shared_lut_common_mask"] = "Original LINEAR/GAMMA/FIT_PRESS common mask is unchanged; any nonfinite Shared LUT estimate on this mask aborts analysis"
    batch_policy["dispersion"] = "historical CV (%), variance (g squared), IQR (g), MAD (g) plots restored; all metrics use the same mass predictions directly, without Min–Max normalization; spatial SD is additionally reported"
    write_json(outputs["summary"], {"format": "e-skin-matched-calibration-evaluation", "version": 1,
               "created_at": datetime.now(timezone.utc).isoformat(), "quality_policy": batch_policy,
               "groups": groups, "records": compact,
               "excluded_incomplete_captures": incomplete,
               "excluded_incomplete_capture_count": len(incomplete),
               "selected_source_captures": [portable_path(path) for path in paths],
               "primary_plot": portable_path(outputs["primary_plot"]),
               "plot_actual_load_range_g": observed_limits,
               "plot_x_limits_g": list(x_limits),
               "x_axis_policy": "Included actual loads with 5% display padding and automatic major ticks; independent of the calibration upper bound",
               "plot_metrics": ["mean", "mean_estimate_absolute_percentage_error", "bias_g"] if kind == "accuracy" else ["cv_percent", "variance", "iqr", "mad"],
               "supplementary_plot_metrics": [] if kind == "accuracy" else ["std", "std/variance/iqr/mad combined"],
               "metrics_by_method": accuracy_metrics,
               "zero_load_detail": zero_load_detail,
               "methods": list(methods),
               "shared_lut_baseline": ({"model_file": portable_path(outputs["shared_lut_model"]),
                                         "model": shared_lut, "validation_refit": False,
                                         "prediction_order": "per-cell inverse LUT, then matched-cell spatial statistics"}
                                        if shared_lut is not None else None),
               "accuracy_records": accuracy_rows,
               "excluded_records": [record for record in compact if not record["included"] or not record["common_cell_count"]],
               "error_definitions": {"signed_error_g": "mean predicted load minus actual load", "absolute_error_g": "absolute signed mean error", "mae_g": "mean absolute per-cell error", "rmse_g": "root mean squared per-cell error"},
               "metrics_by_load_csv": portable_path(outputs["metrics_csv"]),
               "dispersion_units": {"mean": "g", "std": "g", "variance": "g^2", "iqr": "g", "mad": "g", "cv_percent": "%"},
               "source_evaluation_dir": portable_path(evaluation_dir)})
    return outputs


def analyze_capture(input_path: Path, output_dir: Path) -> dict[str, Path]:
    from evaluation_plotting import write_json
    from capture_distribution_style import render_capture_distributions
    issue = completion_issue(json.loads(input_path.read_text(encoding="utf-8")))
    if issue is not None:
        raise ValueError(f"Cannot evaluate incomplete capture: {issue}")
    record = load_matched_batch([input_path])[0]
    lower, upper = record["load_range_g"]
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs, plot_metadata = render_capture_distributions(record, output_dir)
    outputs["cells"] = output_dir / "view_distribution_cells.csv"
    _write_cells(outputs["cells"], [record])
    outputs["summary"] = output_dir / "view_distribution_summary.json"
    write_json(outputs["summary"], {"format": "e-skin-matched-calibration-distribution", "version": 1,
               "quality_policy": quality_policy([lower, upper]), "record": compact_record(record),
               "distribution_plot_policy": plot_metadata})
    return outputs
