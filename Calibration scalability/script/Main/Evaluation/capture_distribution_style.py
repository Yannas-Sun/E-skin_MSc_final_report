"""Restore the historical distribution artwork using matched predictions in g.

This module draws already-selected recorded values. It does not reconstruct
models, normalise predictions, select cells, or apply legacy load thresholds.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
import textwrap
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from evaluation_plotting import (
    COLORS, DARK_CHARCOAL, SLATE_BLUE, finish_figure, plot_style,
)
from portable_paths import portable_path

METHODS = ("LINEAR", "GAMMA", "FIT_PRESS")
LABELS = {"LINEAR": "LINEAR", "GAMMA": "GAMMA", "FIT_PRESS": "FIT PRESS"}
EXCLUDED_COLOR = "#8A8A8A"


def _finish_figure(fig, title: str, note: str) -> None:
    """Keep long experiment labels within the historical header layout."""
    title = textwrap.fill(title, width=max(35, int(fig.get_size_inches()[0] * 5.5)))
    finish_figure(fig, title, note)


def prepare_plot_views(record: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], np.ndarray, tuple[float, float]]:
    """Use the evaluator's common mask unchanged and one shared mass axis."""
    mask = np.asarray(record["mask"], dtype=bool)
    if mask.shape != (16, 16):
        raise ValueError("Distribution mask must be 16x16")
    views: dict[str, dict[str, Any]] = {}
    all_finite = []
    for name in METHODS:
        original = np.asarray(record["estimates_g"][name], dtype=float)
        if original.shape != mask.shape:
            raise ValueError(f"{name} predictions must be 16x16")
        if not np.all(np.isfinite(original[mask])):
            raise ValueError("Common included cells must be finite for every method")
        finite = original[np.isfinite(original)]
        views[name] = {
            "original": original, "values": original[mask], "finite": finite,
            "excluded": original[~mask & np.isfinite(original)],
            "count": int(mask.sum()), "excluded_count": int((~mask).sum()),
            "unit": "g",
        }
        all_finite.append(finite)
    low, high = map(float, record["load_range_g"])
    finite = np.concatenate(all_finite)
    actual = float(record["actual_load_g"])
    low = min(low, actual, float(finite.min()) if finite.size else low)
    high = max(high, actual, float(finite.max()) if finite.size else high)
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        raise ValueError("Distribution display requires a finite positive mass range")
    # Equal bins, coordinates and limits for all three methods; finite values
    # outside the calibration interval remain visible instead of being removed.
    edges = np.linspace(low, high, 51)
    return views, edges, (low, high)


def _panel_title(axis, name: str, view: dict[str, Any], letter: str) -> None:
    axis.set_title(f"{letter}  {LABELS[name]}".strip(), loc="left", color=COLORS[name])
    axis.text(1., 1.025, f"n = {view['count']}/256  |  excluded {view['excluded_count']}",
              transform=axis.transAxes, ha="right", va="bottom", fontsize=8, color=SLATE_BLUE)
    axis.grid(axis="y", alpha=.75)
    axis.set_axisbelow(True)


def plot_distribution(axis, name: str, view: dict[str, Any], actual: float,
                      letter: str, edges: np.ndarray, limits: tuple[float, float]) -> None:
    _panel_title(axis, name, view, letter)
    axis.set(xlabel="Equivalent whole-layer mass (g)", ylabel="Probability density (1/g)", xlim=limits)
    flat, excluded, finite = view["values"], view["excluded"], view["finite"]
    if not finite.size:
        axis.text(.5, .5, "No finite source values", transform=axis.transAxes, ha="center", color=EXCLUDED_COLOR)
        return
    widths = np.diff(edges)
    valid_density = np.histogram(flat, bins=edges)[0] / (finite.size * widths)
    excluded_density = np.histogram(excluded, bins=edges)[0] / (finite.size * widths)
    if flat.size:
        axis.bar(edges[:-1], valid_density, width=widths, align="edge", color=COLORS[name],
                 alpha=.48, edgecolor="white", linewidth=.7, label="Included cells")
    if excluded.size:
        axis.bar(edges[:-1], excluded_density, bottom=valid_density, width=widths,
                 align="edge", color=EXCLUDED_COLOR, alpha=.40, edgecolor=EXCLUDED_COLOR,
                 linewidth=.7, label="Excluded cells (shown only)")
    if flat.size:
        mean = float(np.mean(flat))
        std = float(np.std(flat, ddof=1)) if flat.size > 1 else 0.
        if std > 0:
            x = np.linspace(limits[0], limits[1], 600)
            density = np.exp(-.5 * ((x - mean) / std) ** 2) / (std * math.sqrt(2 * math.pi))
            axis.plot(x, density * flat.size / finite.size, color=COLORS["FIT_PRESS"],
                      linewidth=1.6, label="Normal reference (included)")
        axis.axvline(mean, color=COLORS["FIT_PRESS"], linestyle="--", linewidth=1.3,
                     label=f"Included mean {mean:.3g} g")
    axis.axvline(actual, color=COLORS["GAMMA"], linestyle=":", linewidth=1.5,
                 label=f"Actual {actual:g} g")
    axis.legend(fontsize=7.5, loc="upper right")


def plot_boxplot(axis, name: str, view: dict[str, Any], actual: float,
                 letter: str, limits: tuple[float, float]) -> None:
    _panel_title(axis, name, view, letter)
    flat, excluded = view["values"], view["excluded"]
    axis.set(ylabel="Equivalent whole-layer mass (g)", xlim=(.5, 1.5), ylim=limits)
    reference_only = not flat.size and bool(excluded.size)
    values = excluded if reference_only else flat
    color = EXCLUDED_COLOR if reference_only else COLORS[name]
    if values.size:
        axis.boxplot(values, patch_artist=True, widths=.38, whis=1.5, showmeans=True,
                     showfliers=not reference_only,
                     boxprops={"facecolor": color, "alpha": .30, "edgecolor": color, "linewidth": 1.3},
                     medianprops={"color": DARK_CHARCOAL, "linewidth": 2},
                     whiskerprops={"color": SLATE_BLUE, "linewidth": 1.2},
                     capprops={"color": SLATE_BLUE, "linewidth": 1.2},
                     meanprops={"marker": "D", "markerfacecolor": color, "markeredgecolor": DARK_CHARCOAL, "markersize": 5},
                     flierprops={"marker": "o", "markerfacecolor": "none", "markeredgecolor": color, "alpha": .65, "markersize": 3.5})
    else:
        axis.text(.5, .5, "No finite source values", transform=axis.transAxes, ha="center", color=EXCLUDED_COLOR)
    if excluded.size:
        jitter = np.random.default_rng(0).uniform(-.12, .12, excluded.size)
        axis.scatter(1 + jitter, excluded, marker="x", color=EXCLUDED_COLOR, s=18,
                     linewidths=.8, alpha=.65, zorder=4, label="Excluded cells (shown only)")
    axis.set_xticks([1], [LABELS[name] + ("\nReference only" if reference_only else "")])
    axis.axhline(actual, color=COLORS["GAMMA"], linewidth=1.4, linestyle=":", label=f"Actual {actual:g} g")
    axis.legend(loc="upper right", fontsize=7.5)


def write_exclusions(path: Path, record: dict[str, Any]) -> None:
    mask = np.asarray(record["mask"], dtype=bool)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["view", "row", "column", "source_value", "unit", "exclusion_reason"])
        for name in METHODS:
            values = np.asarray(record["estimates_g"][name], dtype=float)
            for row, column in np.argwhere(~mask):
                value = values[row, column]
                writer.writerow([name, int(row) + 1, int(column) + 1,
                                 float(value) if np.isfinite(value) else "", "g", str(record["status"][row, column])])


def plot_distribution_overlay(axis, views: dict[str, dict[str, Any]], actual: float,
                              edges: np.ndarray, limits: tuple[float, float]) -> None:
    """Overlay included gram predictions without centring or rescaling them."""
    for name in METHODS:
        values = views[name]["values"]
        if not values.size:
            continue
        axis.hist(values, bins=edges, density=True, histtype="bar", color=COLORS[name],
                  alpha=.30, edgecolor="none", linewidth=0, label=f"{LABELS[name]} data")
        mean = float(np.mean(values))
        sigma = float(np.std(values, ddof=1)) if values.size > 1 else 0.
        if sigma > 0:
            x = np.linspace(limits[0], limits[1], 600)
            density = np.exp(-.5 * ((x - mean) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
            axis.plot(x, density, color=COLORS[name], linewidth=1.8,
                      label=f"{LABELS[name]} Normal reference")
        axis.axvline(mean, color=COLORS[name], linestyle="--", linewidth=1.1,
                     label=f"{LABELS[name]} mean {mean:.3g} g")
    axis.axvline(actual, color=DARK_CHARCOAL, linestyle=":", linewidth=1.5,
                 label=f"Actual {actual:g} g")
    axis.set(xlabel="Equivalent whole-layer mass (g)", ylabel="Probability density (1/g)", xlim=limits)
    axis.grid(axis="y", alpha=.75)
    axis.set_axisbelow(True)
    axis.legend(loc="upper right", fontsize=7.5, ncol=2, frameon=True,
                facecolor="white", edgecolor="none", framealpha=.95)


def render_capture_distributions(record: dict[str, Any], output_dir: Path) -> tuple[dict[str, Path], dict[str, Any]]:
    """Draw the historical single/combined/boxplot family, retaining g units."""
    views, edges, limits = prepare_plot_views(record)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    label = f"M{record['module_id']} {record['fsr']}  |  Actual load {record['actual_load_g']:g} g"
    if record.get("capture_metadata", {}).get("synthetic_test_only"):
        label = "SYNTHETIC SOFTWARE TEST  |  " + label
    low, high = record["load_range_g"]
    note = (f"Same common cells and recorded predictions in g; calibration range {low:g}–{high:g} g. RAW and model files remain unchanged.\n"
            "Gray bars/crosses show excluded cells only. Finite poor predictions are retained. No prediction normalization or assumed saturation thresholds.\n"
            "Cell n describes spatial observations, not independent loading repeats. Normal curves are descriptive references, not a normality claim.")
    with plot_style():
        for key, filename, box in (("combined", "view_distributions.png", False),
                                   ("boxplot", "boxplot_distributions.png", True)):
            fig, axes = plt.subplots(1, 3, figsize=(16, 5.8))
            for axis, name, letter in zip(axes, METHODS, "ABC"):
                if box:
                    plot_boxplot(axis, name, views[name], record["actual_load_g"], letter, limits)
                else:
                    plot_distribution(axis, name, views[name], record["actual_load_g"], letter, edges, limits)
            extra = "\nBox: Q1–Q3; bar: median; diamond: mean; whiskers: 1.5×IQR. Gray reference box only when no included cells." if box else ""
            _finish_figure(fig, label + ("  |  Boxplots" if box else "  |  Distributions"), note + extra)
            fig.subplots_adjust(bottom=.12)
            outputs[key] = output_dir / filename
            fig.savefig(outputs[key])
            plt.close(fig)
        for name in METHODS:
            fig, axis = plt.subplots(figsize=(7.8, 5.8))
            plot_distribution(axis, name, views[name], record["actual_load_g"], "", edges, limits)
            single_note = "\n".join(textwrap.fill(line, 100) for line in note.split("\n"))
            _finish_figure(fig, label, single_note)
            fig.subplots_adjust(left=.12, right=.97, bottom=.12)
            outputs[name.lower()] = output_dir / f"{name.lower()}_distribution.png"
            fig.savefig(outputs[name.lower()])
            plt.close(fig)
        fig, axis = plt.subplots(figsize=(9.2, 5.8))
        plot_distribution_overlay(axis, views, record["actual_load_g"], edges, limits)
        overlay_note = ("Same included cells; recorded predictions in g. Each method retains its own mean and absolute spread.\n"
                        "No division by U, mean-centering, standardization or min-max scaling. Normal references are descriptive.\n"
                        "Histogram height is probability density (1/g); exclusions are documented in the individual plots and CSV.")
        _finish_figure(fig, label + "  |  Shared gram axis", overlay_note)
        fig.subplots_adjust(left=.10, right=.97, bottom=.12)
        outputs["distribution_comparison"] = output_dir / "distribution_comparison.png"
        fig.savefig(outputs["distribution_comparison"])
        plt.close(fig)
    outputs["exclusions"] = output_dir / "view_distribution_exclusions.csv"
    write_exclusions(outputs["exclusions"], record)
    metadata = {
        "style_reference": "historical analyze_view_distributions.py distribution and boxplot family",
        "prediction_units": "g", "methods": list(METHODS),
        "method_naming": "GAMMA replaces the old NORM CAL label; no normalized-value aliases are written",
        "common_display_range_g": list(limits), "histogram_bin_edges_g": edges.tolist(),
        "histogram_density": "included and excluded counts / (all finite source count for that method * common bin width); probability density in 1/g",
        "normal_reference": "mean and sample SD of included spatial predictions; descriptive reference only, scaled by included/finite-source cell count",
        "normalization": "none applied to prediction values; probability-density axes do not rescale mass predictions",
        "overlay": {"filename": "distribution_comparison.png", "unit": "g",
                    "input": "same common included cells for every method",
                    "transformation": "none; each method's recorded mean and spread are retained",
                    "density": "included count / (included cell count * common bin width)"},
        "boxplot": {"whiskers": "1.5 times IQR", "mean_marker": "method-coloured diamond", "excluded_display": "gray crosses; gray reference box only if there are no included cells"},
        "outputs": {key: portable_path(path) for key, path in outputs.items()},
    }
    return outputs, metadata
