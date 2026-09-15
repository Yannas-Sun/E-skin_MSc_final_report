"""Compare spatial dispersion of LINEAR, captured NORM CAL and FIT PRESS.

Min–Max:
    LINEAR is derived from each cell's two-point zero/full-load range.
    NORM CAL is read from the GUI capture without reapplying a gamma transform.
    FIT PRESS uses the fixed 0–3000 g range (soft saturation retained).
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT / "Utility"))

from evaluation_plotting import (
    EXCLUDED_COLOR, FIT_MAX_G, FIT_MIN_G, LABELS, MARKERS,
    COLORS, describe, finish_figure, in_load_range, load_capture,
    plot_style, prepare_views, policy, write_json,
)
from saturation_regions import (
    SOFT_SATURATION_COLOR, SOFT_SATURATION_MAX_G, mark_soft_saturation_region,
)
from portable_paths import portable_path

CAPTURE_NAME = "view_distribution_capture.json"
DATA_ORDER = ("LINEAR", "NORM_CAL", "FIT_PRESS")
DATA_LABELS = {
    "LINEAR": "LINEAR two-point scaled ADC",
    "NORM_CAL": "NORM CAL (captured)",
    "FIT_PRESS": "FIT PRESS",
}
DATA_COLORS = {
    "LINEAR": COLORS["LINEAR"],
    "NORM_CAL": COLORS["NORM_CAL"],
    "FIT_PRESS": COLORS["FIT_PRESS"],
}
DATA_MARKERS = {
    "LINEAR": "o",
    "NORM_CAL": "s",
    "FIT_PRESS": "^",
}
METRICS = ("mean", "std", "cv_percent", "iqr", "mad", "variance")
PLOT_NAMES = {
    "cv_percent": "dispersion_cv.png",
    "iqr": "dispersion_iqr.png",
    "mad": "dispersion_mad.png",
    "variance": "dispersion_variance.png",
}
TITLES = {
    "cv_percent": "Coefficient of variation",
    "iqr": "Interquartile range",
    "mad": "Median absolute deviation",
    "variance": "Population variance",
}


def plot_dispersion_series(
    axis: Any,
    x: list[float],
    y: list[float | None],
    *,
    color: str,
    marker: str,
    label: str,
) -> None:
    """Plot a series with gray values and links inside soft saturation."""
    x_values = np.asarray(x, dtype=float)
    y_values = np.asarray(
        [np.nan if value is None else value for value in y], dtype=float,
    )
    finite = np.isfinite(x_values) & np.isfinite(y_values)
    soft = finite & (x_values >= 1200.0) & (x_values <= SOFT_SATURATION_MAX_G)

    axis.plot(
        x_values, y_values, color=color, marker=marker,
        linewidth=2, markersize=5, markeredgecolor="white",
        markeredgewidth=.6, label=label, zorder=2,
    )

    # Re-draw links ending at a soft-saturation point in gray. This includes
    # the transition from the last normal-response point into the first gray
    # point, while leaving the series color unchanged outside the interval.
    for index in range(1, len(x_values)):
        if soft[index] and finite[index - 1]:
            axis.plot(
                x_values[index - 1:index + 1], y_values[index - 1:index + 1],
                color=SOFT_SATURATION_COLOR, linewidth=2, zorder=3,
                label="_nolegend_",
            )
    if soft.any():
        axis.scatter(
            x_values[soft], y_values[soft], color=SOFT_SATURATION_COLOR,
            marker=marker, s=38, edgecolors="white", linewidths=.6,
            zorder=4, label="_nolegend_",
        )


def load_two_point_calibration(evaluation_dir: Path) -> tuple[Path, np.ndarray, np.ndarray]:
    """Load per-cell zero and full-load medians from the matching calibration."""
    directory = evaluation_dir.parent / "two_point"
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No two-point calibration JSON under {directory}")
    path = paths[-1]
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    try:
        zero = np.asarray(data["zero_load"]["median"], dtype=float)
        # The two-point routine records the maximum of the six full-load
        # corner measurements as the per-cell upper calibration endpoint.
        full = np.asarray(data["full_load"]["maximum_over_all_corners"], dtype=float)
    except (KeyError, TypeError) as error:
        raise ValueError(f"{path}: missing zero_load/full_load median matrices") from error
    if zero.shape != (16, 16) or full.shape != (16, 16):
        raise ValueError(f"{path}: calibration matrices must be 16x16")
    return path, zero, full


def minmax_source(raw: np.ndarray, zero: np.ndarray, full: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    span = full - zero
    valid = np.isfinite(raw) & np.isfinite(zero) & np.isfinite(span) & (span > 0)
    result = np.full(raw.shape, np.nan, dtype=float)
    result[valid] = np.clip((raw[valid] - zero[valid]) / span[valid], 0.0, 1.0)
    return result, valid


def minmax_fit(fit: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    valid = np.isfinite(fit) & (fit >= FIT_MIN_G) & (fit <= FIT_MAX_G)
    result = np.full(fit.shape, np.nan, dtype=float)
    result[valid] = (fit[valid] - FIT_MIN_G) / (FIT_MAX_G - FIT_MIN_G)
    return result, valid


def collect_records(evaluation_dir: Path) -> tuple[list[dict[str, Any]], Path]:
    calibration_path, zero, full = load_two_point_calibration(evaluation_dir)
    records = []
    for path in sorted(evaluation_dir.rglob(CAPTURE_NAME)):
        data = load_capture(path)
        actual = float(data["actual_load"]["value"])
        original = prepare_views(data)
        raw = original["RAW"]["original"]
        norm_cal = original["NORM_CAL"]["original"]
        fit = original["FIT_PRESS"]["original"]
        linear, linear_valid = minmax_source(raw, zero, full)
        norm_cal_valid = np.isfinite(norm_cal)
        fit_minmax, fit_minmax_valid = minmax_fit(fit)
        methods = {
            "min_max": {
                "LINEAR": {
                    "unit": "ratio",
                    "values": linear[linear_valid],
                    "original": linear,
                    "mask": linear_valid,
                    "valid_count": int(linear_valid.sum()),
                    "excluded_count": int((~linear_valid).sum()),
                    "reference_metrics": describe(linear[np.isfinite(linear)]),
                },
                "NORM_CAL": {
                    "unit": "ratio",
                    "values": norm_cal[norm_cal_valid],
                    "original": norm_cal,
                    "mask": norm_cal_valid,
                    "valid_count": int(norm_cal_valid.sum()),
                    "excluded_count": int((~norm_cal_valid).sum()),
                    "reference_metrics": describe(norm_cal[norm_cal_valid]),
                },
                "FIT_PRESS": {
                    "unit": "ratio",
                    "values": fit_minmax[fit_minmax_valid],
                    "original": fit_minmax,
                    "mask": fit_minmax_valid,
                    "valid_count": int(fit_minmax_valid.sum()),
                    "excluded_count": int((~fit_minmax_valid).sum()),
                    "reference_metrics": describe(
                        (fit - FIT_MIN_G) / (FIT_MAX_G - FIT_MIN_G)
                    ),
                },
            },
        }
        for method in methods.values():
            for view in method.values():
                view["metrics"] = describe(view["values"])
        records.append({
            "source": portable_path(path),
            "module_id": data.get("module_id"),
            "fsr": data.get("fsr"),
            "actual_load_g": actual,
            "frame_count": data.get("source_frames", {}).get("count"),
            "included": in_load_range(actual),
            "exclusion_reason": None if in_load_range(actual) else "actual_load_outside_0_3000g",
            "methods": methods,
        })
    if not records:
        raise ValueError(f"No {CAPTURE_NAME} found under {evaluation_dir}")
    identities = {(record["module_id"], record["fsr"]) for record in records}
    if len(identities) != 1:
        raise ValueError("Analyze one module/FSR evaluation directory at a time")
    return sorted(records, key=lambda record: (record["actual_load_g"], record["source"])), calibration_path


def aggregate_by_load(records: list[dict[str, Any]], method: str) -> list[dict[str, Any]]:
    grouped: dict[float, list[dict[str, Any]]] = {}
    for record in records:
        if record["included"]:
            grouped.setdefault(record["actual_load_g"], []).append(record)
    groups = []
    for load, group in sorted(grouped.items()):
        views = {}
        for name in DATA_ORDER:
            samples = {
                metric: [record["methods"][method][name]["metrics"][metric] for record in group
                          if record["methods"][method][name]["metrics"][metric] is not None]
                for metric in METRICS
            }
            views[name] = {
                "unit": group[0]["methods"][method][name]["unit"],
                "metrics": {
                    metric: float(np.mean(values)) if values else None
                    for metric, values in samples.items()
                },
                "valid_count_min": min(record["methods"][method][name]["valid_count"] for record in group),
                "valid_count_max": max(record["methods"][method][name]["valid_count"] for record in group),
                "excluded_count_total": sum(record["methods"][method][name]["excluded_count"] for record in group),
            }
        groups.append({
            "actual_load_g": load,
            "record_count": len(group),
            "views": views,
            "sources": [record["source"] for record in group],
        })
    return groups


def compact_records(records: list[dict[str, Any]], method: str) -> list[dict[str, Any]]:
    """Keep JSON provenance without serializing the per-cell matrices twice."""
    compact = []
    for record in records:
        compact.append({
            "source": record["source"], "module_id": record["module_id"],
            "fsr": record["fsr"], "actual_load_g": record["actual_load_g"],
            "frame_count": record["frame_count"], "included": record["included"],
            "exclusion_reason": record["exclusion_reason"],
            "views": {
                name: {
                    "unit": view["unit"], "valid_count": view["valid_count"],
                    "excluded_count": view["excluded_count"],
                    "metrics": view["metrics"],
                    "reference_metrics": view["reference_metrics"],
                    **({"parameters": view["parameters"]} if "parameters" in view else {}),
                }
                for name, view in record["methods"][method].items()
            },
        })
    return compact


def save_plot(path: Path, groups: list[dict[str, Any]], records: list[dict[str, Any]],
              method: str, metric: str) -> None:
    with plot_style():
        is_cv = metric == "cv_percent"
        columns = 1 if is_cv else len(DATA_ORDER) + 1
        fig, axes = plt.subplots(
            1, columns, figsize=(11.8, 6.2) if is_cv else (21.2, 5.7),
            squeeze=False,
        )
        loads = [float(record["actual_load_g"]) for record in records]
        low = min(0.0, *loads)
        data_high = max(loads)
        padding = max((data_high - low) * .08, 25.0)
        limits = (low, data_high + padding)
        x = [group["actual_load_g"] for group in groups]
        all_y = []
        for index, name in enumerate(DATA_ORDER):
            axis = axes[0, 0] if is_cv else axes[0, index]
            y = [group["views"][name]["metrics"][metric] for group in groups]
            all_y.extend(value for value in y if value is not None)
            plot_dispersion_series(
                axis, x, y, color=DATA_COLORS[name],
                marker=DATA_MARKERS[name], label=DATA_LABELS[name],
            )
            references = [
                (record["actual_load_g"], record["methods"][method][name]["reference_metrics"][metric])
                for record in records if not record["included"]
                and record["methods"][method][name]["reference_metrics"][metric] is not None
            ]
            if references:
                rx, ry = zip(*references)
                all_y.extend(ry)
                axis.scatter(rx, ry, marker="x", color=EXCLUDED_COLOR, s=52,
                             linewidths=1.6, zorder=5,
                             label="Excluded test (reference only)" if index == 0 else None)
            axis.grid(axis="y", alpha=.75)
            axis.set_xlabel("Actual load (g)")
            axis.set_xlim(*limits)
            mark_soft_saturation_region(axis, limits)
            if not is_cv:
                axis.set_title(DATA_LABELS[name], loc="left", color=DATA_COLORS[name])
            axis.set_ylabel(f"{TITLES[metric]} (dimensionless)")
            if metric != "cv_percent":
                axis.set_ylim(bottom=0)
        if not is_cv:
            combined = axes[0, -1]
            for index, name in enumerate(DATA_ORDER):
                y = [group["views"][name]["metrics"][metric] for group in groups]
                plot_dispersion_series(
                    combined, x, y, color=DATA_COLORS[name],
                    marker=DATA_MARKERS[name], label=DATA_LABELS[name],
                )
                references = [
                    (record["actual_load_g"],
                     record["methods"][method][name]["reference_metrics"][metric])
                    for record in records if not record["included"]
                    and record["methods"][method][name]["reference_metrics"][metric] is not None
                ]
                if references:
                    rx, ry = zip(*references)
                    combined.scatter(
                        rx, ry, marker="x", color=EXCLUDED_COLOR, s=52,
                        linewidths=1.6, zorder=5,
                        label="Excluded test (reference only)" if index == 0 else None,
                    )
            combined.set_title(
                "LINEAR + NORM CAL + FIT PRESS", loc="left", color=COLORS["LINEAR"]
            )
            combined.set_xlabel("Actual load (g)")
            combined.set_ylabel(f"{TITLES[metric]} (dimensionless)")
            combined.set_xlim(*limits)
            combined.set_ylim(bottom=0)
            mark_soft_saturation_region(combined, limits)
            combined.grid(axis="y", alpha=.75)
        for axis in axes.ravel():
            axis.legend(loc="best", fontsize=8, frameon=True,
                        facecolor="white", edgecolor="none", framealpha=.95)
        if is_cv:
            axes[0, 0].set_ylim(0, max(all_y, default=1.0) * 1.12 or 1.0)
            method_label = "Min–Max"
            axes[0, 0].set_title(
                f"{method_label}: LINEAR / NORM CAL / FIT PRESS",
                loc="left", color=COLORS["LINEAR"],
            )
            axes[0, 0].text(
                0, 1.015, r"CV = population SD / |mean| × 100%",
                transform=axes[0, 0].transAxes, color=SOFT_SATURATION_COLOR, fontsize=9,
            )
        identity = records[0]
        method_label = "Min–Max"
        note = (
            f"{method_label}; valid FIT range: 0–{FIT_MAX_G:g} g inclusive. "
            f"Included tests: {sum(record['included'] for record in records)}; "
            f"excluded tests: {sum(not record['included'] for record in records)}."
        )
        note += "\nGray crosses: excluded tests, display-only reference; not included in aggregates."
        finish_figure(
            fig,
            f"M{identity['module_id']} {identity['fsr']}  |  {method_label} {TITLES[metric]}",
            note,
        )
        fig.subplots_adjust(bottom=.21, top=.80, left=.065, right=.985, wspace=.24)
        fig.savefig(path)
        plt.close(fig)


def save_csv(path: Path, groups: list[dict[str, Any]], method: str) -> None:
    fields = ["actual_load_g", "record_count"]
    for name in DATA_ORDER:
        fields += [
            f"{name}_{key}" for key in
            ("unit", "valid_count_min", "valid_count_max", "excluded_count_total", *METRICS)
        ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for group in groups:
            row = {"actual_load_g": group["actual_load_g"], "record_count": group["record_count"]}
            for name in DATA_ORDER:
                view = group["views"][name]
                for key in ("unit", "valid_count_min", "valid_count_max", "excluded_count_total"):
                    row[f"{name}_{key}"] = view[key]
                for metric in METRICS:
                    row[f"{name}_{metric}"] = view["metrics"][metric]
            writer.writerow(row)


def save_normalized_variance_csv(
    path: Path, groups_by_method: dict[str, list[dict[str, Any]]]
) -> None:
    """Write the three Min–Max normalized-view variances."""
    fields = ["actual_load_g", "record_count"]
    fields.extend(f"{name}_min_max_variance" for name in DATA_ORDER)
    groups = groups_by_method.get("min_max", [])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for group in groups:
            row: dict[str, Any] = {
                "actual_load_g": group["actual_load_g"],
                "record_count": group["record_count"],
            }
            for name in DATA_ORDER:
                row[f"{name}_min_max_variance"] = group["views"][name]["metrics"]["variance"]
            writer.writerow(row)


def save_normalized_variance_plot(
    path: Path,
    groups_by_method: dict[str, list[dict[str, Any]]],
    records: list[dict[str, Any]],
) -> None:
    """Plot the three Min–Max normalized-view variances."""
    with plot_style():
        fig, axis = plt.subplots(figsize=(10.8, 5.8))
        loads = [float(record["actual_load_g"]) for record in records]
        low = min(0.0, *loads)
        data_high = max(loads)
        padding = max((data_high - low) * .08, 25.0)
        limits = (low, data_high + padding)
        groups = groups_by_method.get("min_max", [])
        x = [float(group["actual_load_g"]) for group in groups]
        panel_y: list[float] = []
        for index, name in enumerate(DATA_ORDER):
            y = [group["views"][name]["metrics"]["variance"] for group in groups]
            panel_y.extend(value for value in y if value is not None)
            plot_dispersion_series(
                axis, x, y, color=DATA_COLORS[name],
                marker=DATA_MARKERS[name], label=DATA_LABELS[name],
            )
            references = [
                (record["actual_load_g"],
                 record["methods"]["min_max"][name]["reference_metrics"]["variance"])
                for record in records if not record["included"]
                and record["methods"]["min_max"][name]["reference_metrics"]["variance"] is not None
            ]
            if references:
                rx, ry = zip(*references)
                panel_y.extend(ry)
                axis.scatter(
                    rx, ry, marker="x", color=EXCLUDED_COLOR, s=52,
                    linewidths=1.6, zorder=5,
                    label="Excluded test (reference only)" if index == 0 else None,
                )
        axis.set_xlim(*limits)
        axis.set_ylim(0, max(panel_y, default=1.0) * 1.12 or 1.0)
        axis.set_xlabel("Actual load (g)")
        axis.set_ylabel("Population variance (dimensionless)")
        axis.set_title("Min–Max normalized variance", loc="left", color=COLORS["LINEAR"])
        axis.grid(axis="y", alpha=.75)
        mark_soft_saturation_region(axis, limits)
        axis.legend(loc="best", fontsize=8, frameon=True,
                    facecolor="white", edgecolor="none", framealpha=.95)
        identity = records[0]
        finish_figure(
            fig,
            f"M{identity['module_id']} {identity['fsr']}  |  Normalized variance comparison",
            "LINEAR and NORM CAL use ratio values; FIT PRESS is divided by 3000 g. "
            "Gray region: 1200–3000 g soft saturation; excluded tests are reference only.",
        )
        fig.subplots_adjust(bottom=.21, top=.80, left=.08, right=.985)
        fig.savefig(path)
        plt.close(fig)


def analyze(evaluation_dir: Path, output_dir: Path) -> dict[str, Path]:
    from new_protocol_evaluation import PROTOCOL_ID, batch_protocol, capture_paths, analyze_batch
    if batch_protocol(capture_paths(evaluation_dir))[0] == PROTOCOL_ID:
        return analyze_batch(evaluation_dir, output_dir, kind="dispersion")
    records, calibration_path = collect_records(evaluation_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    methods = {}
    groups_by_method: dict[str, list[dict[str, Any]]] = {}
    for method in ("min_max",):
        groups = aggregate_by_load(records, method)
        groups_by_method[method] = groups
        method_dir = output_dir / method
        method_dir.mkdir(parents=True, exist_ok=True)
        for metric, filename in PLOT_NAMES.items():
            path = method_dir / filename
            save_plot(path, groups, records, method, metric)
            outputs[f"{method}_{metric}"] = path
        csv_path = method_dir / "dispersion_metrics.csv"
        save_csv(csv_path, groups, method)
        outputs[f"{method}_csv"] = csv_path
        methods[method] = {
            "formula": (
                "LINEAR = clip((RAW - two_point_zero) / "
                "(two_point_full - two_point_zero), 0, 1); "
                "NORM_CAL is read from the GUI capture without reapplying Gamma"
            ),
            "fit_formula": (
                f"FIT_PRESS / {FIT_MAX_G:g} g, valid only for 0 <= FIT_PRESS <= {FIT_MAX_G:g} g"
            ),
            "groups": groups,
            "records": compact_records(records, method),
        }
    variance_path = output_dir / "normalized_variance.csv"
    save_normalized_variance_csv(variance_path, groups_by_method)
    outputs["normalized_variance_csv"] = variance_path
    variance_plot_path = output_dir / "normalized_variance_comparison.png"
    save_normalized_variance_plot(variance_plot_path, groups_by_method, records)
    outputs["normalized_variance_plot"] = variance_plot_path
    summary_path = output_dir / "dispersion_comparison_summary.json"
    write_json(summary_path, {
        "format": "e-skin-fsr-dispersion-calibration-comparison",
        "version": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_evaluation_dir": portable_path(evaluation_dir),
        "two_point_calibration": portable_path(calibration_path),
        "methods": methods,
        "quality_policy": policy(),
        "normalized_variance_csv": portable_path(variance_path),
        "interpretation": (
            "Min–Max is applied to LINEAR, the captured NORM CAL view and FIT PRESS. "
            "LINEAR and NORM CAL are dimensionless ratios; FIT PRESS is divided by "
            f"{FIT_MAX_G:g} g. These dispersion values must not be interpreted as physical pressure."
        ),
    })
    outputs["summary"] = summary_path
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evaluation_dir = args.evaluation_dir.resolve()
    output_dir = (args.output_dir or evaluation_dir / "analysis" / "dispersion").resolve()
    outputs = analyze(evaluation_dir, output_dir)
    for name, path in outputs.items():
        print(f"Generated {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
