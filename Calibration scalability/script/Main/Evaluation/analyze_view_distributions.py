"""Plot LINEAR, captured NORM CAL and FIT PRESS distributions.

The saved RAW matrix is preserved as the source record. LINEAR is derived
from that matrix and the matching two-point calibration; NORM CAL and FIT
PRESS are read from the capture exactly as saved by the GUI.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from evaluation_plotting import (
    COLORS, LABELS, FIT_MIN_G, FIT_MAX_G, EXCLUDED_COLOR,
    excluded_values, fit_display_limits, mark_range,
    describe, finish_figure, in_load_range, load_capture, panel_title,
    plot_style, policy, prepare_views, write_json,
)
from portable_paths import portable_path
from figure_style import DARK_CHARCOAL, SLATE_BLUE
ANALYSIS_VIEW_ORDER = ("LINEAR", "NORM_CAL", "FIT_PRESS")
RETAINED_DATA_ORDER = ("RAW", *ANALYSIS_VIEW_ORDER)


def load_two_point_calibration(capture_path: Path) -> tuple[Path, np.ndarray, np.ndarray]:
    """Load the newest two-point calibration matching one saved capture."""
    evaluation_dir = capture_path.parent.parent.parent
    fsr_dir = evaluation_dir.parent
    with capture_path.open(encoding="utf-8") as handle:
        capture = json.load(handle)
    module_id = str(capture["module_id"])
    fsr_name = str(capture["fsr"])
    if fsr_dir.name != fsr_name or fsr_dir.parent.name != f"module_{module_id}":
        raise ValueError(f"{capture_path}: capture identity does not match its directory")
    paths = sorted((fsr_dir / "two_point").glob(f"{fsr_name}_calibration_*.json"))
    if not paths:
        raise FileNotFoundError(f"No two-point calibration JSON under {fsr_dir / 'two_point'}")
    path = paths[-1]
    with path.open(encoding="utf-8") as handle:
        calibration = json.load(handle)
    try:
        zero = np.asarray(calibration["zero_load"]["median"], dtype=float)
        full = np.asarray(calibration["full_load"]["maximum_over_all_corners"], dtype=float)
    except (KeyError, TypeError) as error:
        raise ValueError(f"{path}: missing zero/full calibration matrices") from error
    if zero.shape != (16, 16) or full.shape != (16, 16):
        raise ValueError(f"{path}: calibration matrices must be 16x16")
    return path, zero, full


def linear_two_point(raw: np.ndarray, zero: np.ndarray, full: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the per-cell linear two-point ratio and its validity mask."""
    raw = np.asarray(raw, dtype=float)
    span = np.asarray(full, dtype=float) - np.asarray(zero, dtype=float)
    valid = np.isfinite(raw) & np.isfinite(zero) & np.isfinite(full) & (span > 0.0)
    result = np.full(raw.shape, np.nan, dtype=float)
    result[valid] = np.clip((raw[valid] - zero[valid]) / span[valid], 0.0, 1.0)
    return result, valid


def histogram_edges(name: str, values: np.ndarray) -> np.ndarray:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if name == "FIT_PRESS":
        low = min(FIT_MIN_G, float(finite.min()) if finite.size else FIT_MIN_G)
        high = max(100.0, float(finite.max()) if finite.size else 100.0)
        return np.arange(math.floor(low / 100) * 100, math.ceil(high / 100) * 100 + 100, 100)
    if not finite.size:
        return np.linspace(0, 1, 21)
    return np.histogram_bin_edges(finite, bins=20)


def prepare_analysis_views(
    data: dict[str, Any], zero: np.ndarray, full: np.ndarray
) -> dict[str, dict[str, Any]]:
    """Prepare retained views, deriving LINEAR from the saved RAW matrix."""
    result = prepare_views(data)
    raw = result["RAW"]["original"]
    linear, valid = linear_two_point(raw, zero, full)
    status = np.full(linear.shape, "ok", dtype="<U32")
    status[~np.isfinite(raw)] = "nonfinite_raw"
    status[~valid & np.isfinite(raw)] = "invalid_calibration_span"
    mask = status == "ok"
    reasons, counts = np.unique(status[~mask], return_counts=True)
    result["LINEAR"] = {
        "original": linear,
        "values": linear[mask],
        "mask": mask,
        "status": status,
        "count": int(mask.sum()),
        "excluded_count": int((~mask).sum()),
        "excluded_reasons": {str(k): int(v) for k, v in zip(reasons, counts)},
        "unit": "ratio",
        "source_unit": "linear two-point normalized full-load ratio",
    }
    return result


def plot_distribution(axis, name: str, view: dict[str, Any],
                      actual: float, letter: str) -> None:
    flat = view["values"]
    excluded = excluded_values(view)
    source = view["original"][np.isfinite(view["original"])]
    panel_title(axis, name, view, letter)
    axis.set_xlabel(view["unit"])
    axis.set_ylabel("Probability density")
    if name == "FIT_PRESS":
        limits = fit_display_limits(view, actual)
        axis.set_xlim(*limits)
        mark_range(axis, limits)
    if not source.size:
        axis.text(.5, .5, "No finite source values", transform=axis.transAxes,
                  ha="center", color=EXCLUDED_COLOR)
        return
    edges = histogram_edges(name, source)
    # Both groups share one denominator; their combined density integrates to one.
    widths = np.diff(edges)
    valid_density = np.histogram(flat, bins=edges)[0] / (source.size * widths)
    excluded_density = np.histogram(excluded, bins=edges)[0] / (source.size * widths)
    if flat.size:
        axis.bar(edges[:-1], valid_density, width=widths, align="edge",
                 color=COLORS[name], alpha=.48, edgecolor="white", linewidth=.7,
                 label="Included cells")
    if excluded.size:
        axis.bar(edges[:-1], excluded_density, bottom=valid_density, width=widths, align="edge",
                 color=EXCLUDED_COLOR, alpha=.4, edgecolor=EXCLUDED_COLOR,
                 linewidth=.7, label="Excluded cells (shown only)")
    if flat.size:
        mean = float(np.mean(flat))
        std = float(np.std(flat, ddof=1)) if flat.size > 1 else 0.
        if std > 0:
            lower = min(float(flat.min()), mean - 4 * std)
            upper = max(float(flat.max()), mean + 4 * std)
            if name == "FIT_PRESS":
                lower, upper = FIT_MIN_G, FIT_MAX_G
            x = np.linspace(lower, upper, 400)
            y = np.exp(-.5 * ((x - mean) / std)**2) / (std * math.sqrt(2 * math.pi))
            axis.plot(x, y * flat.size / source.size, color=COLORS["FIT_PRESS"], linewidth=1.6,
                      label="Normal reference (included)")
        axis.axvline(mean, color=COLORS["FIT_PRESS"], linestyle="--", linewidth=1.3,
                     label=f"Included mean {mean:.3g}")
    if name == "FIT_PRESS":
        axis.axvline(actual, color=COLORS["NORM_CAL"], linestyle=":", linewidth=1.5,
                     label=f"Actual {actual:g} g")
    axis.legend(fontsize=7.5, loc="upper right")


def plot_boxplot(axis, name: str, view: dict[str, Any], actual: float, letter: str) -> None:
    flat = view["values"]
    excluded = excluded_values(view)
    panel_title(axis, name, view, letter)
    axis.set_ylabel(view["unit"])
    axis.set_xticks([1], [LABELS[name]])
    axis.set_xlim(.5, 1.5)
    if name == "FIT_PRESS":
        limits = fit_display_limits(view, actual)
        axis.set_ylim(*limits)
        mark_range(axis, limits, orientation="y")
    reference_only = not flat.size and bool(excluded.size)
    box_values = excluded if reference_only else flat
    color = EXCLUDED_COLOR if reference_only else COLORS[name]
    if box_values.size:
        axis.boxplot(
            box_values, patch_artist=True, widths=.38, whis=1.5, showmeans=True,
            showfliers=not reference_only,
            boxprops={"facecolor": color, "alpha": .30, "edgecolor": color, "linewidth": 1.3,
                      "hatch": None},
            medianprops={"color": DARK_CHARCOAL, "linewidth": 2},
            whiskerprops={"color": SLATE_BLUE, "linewidth": 1.2},
            capprops={"color": SLATE_BLUE, "linewidth": 1.2},
            meanprops={"marker": "D", "markerfacecolor": color,
                       "markeredgecolor": DARK_CHARCOAL, "markersize": 5},
            flierprops={"marker": "o", "markerfacecolor": "none", "markeredgecolor": color,
                        "alpha": .65, "markersize": 3.5},
        )
    else:
        axis.text(.5, .5, "No finite source values", transform=axis.transAxes,
                  ha="center", color=EXCLUDED_COLOR)
    if excluded.size:
        jitter = np.random.default_rng(0).uniform(-.12, .12, excluded.size)
        axis.scatter(1 + jitter, excluded, marker="x", color=EXCLUDED_COLOR,
                     s=18, linewidths=.8, alpha=.65, zorder=4,
                     label="Excluded cells (shown only)")
    axis.set_xticks([1], [LABELS[name] + ("\nReference only" if reference_only else "")])
    if name == "FIT_PRESS":
        axis.axhline(actual, color=COLORS["NORM_CAL"], linewidth=1.4, linestyle=":",
                     label=f"Actual {actual:g} g")
        axis.legend(loc="upper right", fontsize=7.5)


def normalise_view_values(name: str, values: np.ndarray) -> np.ndarray:
    """Put the three views on a common scale before mean-centering."""
    values = np.asarray(values, dtype=float)
    if name == "FIT_PRESS":
        return values / FIT_MAX_G
    return values


def centre_normalised(values: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Normalise one view, then subtract its mean without scaling its spread."""
    flat = np.asarray(values, dtype=float)
    flat = flat[np.isfinite(flat)]
    if not flat.size:
        return flat, float("nan"), float("nan")
    mean = float(np.mean(flat))
    std = float(np.std(flat, ddof=0))
    return flat - mean, mean, std


def plot_zero_mean_overlay(axis, views: dict[str, Any]) -> dict[str, dict[str, float | int | None]]:
    """Overlay mean-centred distributions while retaining their variances."""
    all_centred: dict[str, np.ndarray] = {}
    metadata: dict[str, dict[str, float | int | None]] = {}
    for name in ANALYSIS_VIEW_ORDER:
        normalised = normalise_view_values(name, views[name]["values"])
        values, mean, std = centre_normalised(normalised)
        all_centred[name] = values
        metadata[name] = {
            "count": int(values.size),
            "normalised_mean_before_centering": None if not np.isfinite(mean) else mean,
            "normalised_population_std": None if not np.isfinite(std) else std,
            "normalised_variance": None if not values.size else float(std**2),
            "centred_mean": None if not values.size else float(np.mean(values)),
        }

    finite_values = [values for values in all_centred.values() if values.size]
    if not finite_values:
        axis.text(.5, .5, "No finite values", transform=axis.transAxes,
                  ha="center", color=EXCLUDED_COLOR)
        return metadata
    # Every plotted source is on [0, 1] before centring, so the centred
    # support is [-1, 1]. Keep this common comparison fixed to that range.
    low, high = -1.0, 1.0
    bins = np.linspace(low, high, 41)
    for name in ANALYSIS_VIEW_ORDER:
        values = all_centred[name]
        if not values.size:
            continue
        axis.hist(values, bins=bins, density=True, histtype="bar",
                  color=COLORS[name], alpha=.30, edgecolor="none",
                  linewidth=0.0, label=f"{LABELS[name]} data")
        variance = float(np.var(values, ddof=0))
        if variance > 0.0:
            sigma = math.sqrt(variance)
            x = np.linspace(low, high, 600)
            normal = np.exp(-0.5 * (x / sigma)**2) / (sigma * math.sqrt(2.0 * math.pi))
            axis.plot(
                x, normal, color=COLORS[name], linewidth=1.8,
                label=f"{LABELS[name]} N(0, σ²={variance:.3g})",
            )
    axis.axvline(0.0, color=SLATE_BLUE, linestyle=":", linewidth=1.0,
                 label="Common mean = 0")
    axis.set_xlabel("Mean-centred normalised value  $(x_{norm}-\\mu)$")
    axis.set_ylabel("Probability density")
    axis.set_title("Mean-centred distribution shapes", loc="left", color=DARK_CHARCOAL)
    axis.grid(axis="y", alpha=.75)
    axis.set_axisbelow(True)
    axis.legend(loc="upper right", fontsize=8, frameon=True,
                facecolor="white", edgecolor="none", framealpha=.95)
    return metadata


def save_cells_csv(path: Path, data: dict[str, Any], views: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row", "column", "actual_load_g", "raw_adc", "linear",
                         "norm_cal", "fit_press",
                         "fit_press_included", "fit_press_status"])
        for row in range(16):
            for col in range(16):
                values = [views[name]["original"][row, col] for name in RETAINED_DATA_ORDER]
                writer.writerow([row + 1, col + 1, data["actual_load"]["value"],
                                 *[float(v) if np.isfinite(v) else "" for v in values],
                                 bool(views["FIT_PRESS"]["mask"][row, col]),
                                 str(views["FIT_PRESS"]["status"][row, col])])


def save_exclusions(path: Path, views: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["view", "row", "column", "source_value", "unit", "exclusion_reason"])
        for name in ANALYSIS_VIEW_ORDER:
            view = views[name]
            for row, col in np.argwhere(~view["mask"]):
                value = view["original"][row, col]
                writer.writerow([name, int(row)+1, int(col)+1,
                                 float(value) if np.isfinite(value) else "",
                                 view["unit"], str(view["status"][row, col])])


def analyze(input_path: Path, output_dir: Path) -> dict[str, Path]:
    data = load_capture(input_path)
    from new_protocol_evaluation import PROTOCOL_ID, protocol_key, analyze_capture
    if protocol_key(data)[0] == PROTOCOL_ID:
        return analyze_capture(input_path, output_dir)
    calibration_path, zero, full = load_two_point_calibration(input_path)
    actual = float(data["actual_load"]["value"])
    views = prepare_analysis_views(data, zero, full)
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = {}
    for name in RETAINED_DATA_ORDER:
        view = views[name]
        summary = describe(view["values"])
        summary.update({
            "unit": view["source_unit"], "original_count": 256,
            "excluded_count": view["excluded_count"], "excluded_reasons": view["excluded_reasons"],
            "histogram_bin_edges": histogram_edges(name, view["original"]).tolist(),
            "display_reference_metrics": describe(view["original"]),
            "histogram_density": "stacked counts / (all finite source count * bin width)",
        })
        if name == "FIT_PRESS":
            summary["mean_error_g"] = summary["mean"] - actual if summary["mean"] is not None else None
            summary["rmse_g"] = float(np.sqrt(np.mean((view["values"]-actual)**2))) if view["count"] else None
        summaries[name] = summary

    label = f"M{data.get('module_id')} {data.get('fsr')}  |  Actual load {actual:g} g"
    count = views["FIT_PRESS"]["excluded_count"]
    note = (f"Three plotted views; RAW is retained as the unchanged source matrix. "
            f"LINEAR is derived from RAW and the matching two-point calibration. "
            f"FIT PRESS valid range: 0–{FIT_MAX_G:g} g. "
            f"Excluded FIT cells: {count}/256.")
    if not in_load_range(actual):
        note += "\nOutside-range test: gray FIT histogram/box and crosses are reference only; excluded from statistics."
    else:
        note += "\nGray background: soft saturation, retained. Gray bars/crosses: excluded cells. No clipping."
    outputs = {}
    with plot_style():
        for key, filename, plotter in (
            ("combined", "view_distributions.png", plot_distribution),
            ("boxplot", "boxplot_distributions.png", plot_boxplot),
        ):
            fig, axes = plt.subplots(1, len(ANALYSIS_VIEW_ORDER), figsize=(16.0, 5.6))
            for axis, name, letter in zip(axes, ANALYSIS_VIEW_ORDER, "ABC"):
                plotter(axis, name, views[name], actual, letter)
            extra = "\nBox: Q1–Q3; bar: median; diamond: mean; whiskers: 1.5×IQR. Gray reference box only if no included cells." if key == "boxplot" else ""
            finish_figure(fig, label + ("  |  Boxplots" if key == "boxplot" else "  |  Distributions"), note+extra)
            outputs[key] = output_dir / filename
            fig.savefig(outputs[key])
            plt.close(fig)
        for name in ANALYSIS_VIEW_ORDER:
            fig, axis = plt.subplots(figsize=(7.8, 5.6))
            plot_distribution(axis, name, views[name], actual, "")
            finish_figure(fig, label, note)
            fig.subplots_adjust(left=.12, right=.97)
            outputs[name.lower()] = output_dir / f"{name.lower()}_distribution.png"
            fig.savefig(outputs[name.lower()])
            plt.close(fig)
        fig, axis = plt.subplots(figsize=(9.2, 5.8))
        zero_mean_views = plot_zero_mean_overlay(axis, views)
        overlay_note = (
            "Views are first put on a common normalised scale (FIT PRESS / 3000 g), "
            "then centred as x_norm − μ. Mean = 0; variance is intentionally retained."
        )
        finish_figure(fig, label + "  |  Common zero-mean comparison", overlay_note)
        fig.subplots_adjust(left=.10, right=.97, bottom=.18, top=.82)
        outputs["normalized_distributions"] = output_dir / "normalized_distributions.png"
        fig.savefig(outputs["normalized_distributions"])
        plt.close(fig)
    outputs["cells"] = output_dir / "view_distribution_cells.csv"
    outputs["exclusions"] = output_dir / "view_distribution_exclusions.csv"
    outputs["summary"] = output_dir / "view_distribution_summary.json"
    save_cells_csv(outputs["cells"], data, views)
    save_exclusions(outputs["exclusions"], views)
    write_json(outputs["summary"], {
        "format": "e-skin-fsr-view-distribution-analysis", "version": 7,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_capture": portable_path(input_path), "module_id": data.get("module_id"),
        "fsr": data.get("fsr"), "actual_load": data["actual_load"],
        "included_in_evaluation": in_load_range(actual), "quality_policy": policy(),
        "data_views": {
            "RAW": {
                "status": "stored unchanged in the source capture",
                "unit": "ADC code",
            },
            "LINEAR": {
                "status": "derived for analysis from RAW",
                "unit": "ratio",
                "two_point_calibration": portable_path(calibration_path),
                "formula": "clip((RAW - zero_median) / (full_max - zero_median), 0, 1)",
            },
            "NORM_CAL": {
                "status": "read unchanged from the GUI capture",
                "unit": str(data["views"]["NORM_CAL"].get("unit", "ratio")),
                "note": "The capture may contain the GUI display gamma configured at acquisition time.",
            },
            "FIT_PRESS": {
                "status": "read unchanged from the GUI capture",
                "unit": str(data["views"]["FIT_PRESS"].get("unit", "g")),
            },
        },
        "zero_mean_overlay": {
            "filename": "normalized_distributions.png",
            "formula": "x_norm - per_view_mean; FIT_PRESS is first divided by 3000 g",
            "purpose": "compare three fitted normal shapes with a common zero mean while retaining between-view variance",
            "views": zero_mean_views,
        },
        "boxplot": {"method": "native source values per view; FIT range exclusions applied",
                    "whiskers": "1.5 times IQR", "mean_marker": "method-coloured diamond",
                    "excluded_display": "gray crosses; gray reference-only box when no valid cells"},
        "views": summaries,
    })
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    source = args.input.resolve()
    outputs = analyze(source, args.output_dir.resolve() if args.output_dir else source.parent)
    for name, path in outputs.items():
        print(f"Generated {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
