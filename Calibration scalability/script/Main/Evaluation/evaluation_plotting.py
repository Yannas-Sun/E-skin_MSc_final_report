"""Shared source-data QC and figure style for calibration evaluation."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import matplotlib as mpl
import numpy as np


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT / "Utility"))
from saturation_regions import NORMAL_MAX_G, SOFT_SATURATION_MAX_G, mark_saturation_regions


CALIBRATION_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CALIBRATION_ROOT))
from figure_style import (  # noqa: E402
    DARK_CHARCOAL,
    GRID,
    K240_LAVENDER,
    MUTED_LAVENDER,
    PUBLICATION_STYLE,
    SLATE_BLUE,
    TEAL_CYAN,
)

ROWS = COLS = 16
FIT_MIN_G = 0.0
FIT_MAX_G = SOFT_SATURATION_MAX_G
VIEW_ORDER = ("RAW", "NORM_CAL", "FIT_PRESS")
LABELS = {
    "RAW": "RAW",
    "LINEAR": "LINEAR",
    "NORM_CAL": "NORM CAL",
    "FIT_PRESS": "FIT PRESS",
}
UNITS = {
    "RAW": "ADC code",
    "LINEAR": "ratio",
    "NORM_CAL": "ratio",
    "FIT_PRESS": "g",
}
COLORS = {
    "RAW": TEAL_CYAN,
    "LINEAR": K240_LAVENDER,
    "NORM_CAL": SLATE_BLUE,
    "GAMMA": SLATE_BLUE,
    "FIT_PRESS": TEAL_CYAN,
}
MARKERS = {
    "RAW": "o",
    "LINEAR": "o",
    "NORM_CAL": "s",
    "FIT_PRESS": "^",
}
LINESTYLES = {"RAW": "-", "NORM_CAL": "--", "FIT_PRESS": "-."}
EXCLUDED_COLOR = SLATE_BLUE
FIGURE_STYLE = dict(PUBLICATION_STYLE)
FIGURE_STYLE.update({
    "font.size": 10,
    "axes.titlesize": 12, "axes.labelsize": 10,
    "axes.titleweight": "semibold", "axes.titlepad": 12,
    "grid.color": GRID, "grid.linewidth": 0.7,
    "legend.fontsize": 9,
    "savefig.dpi": 300,
})


def plot_style():
    return mpl.rc_context(FIGURE_STYLE)


def in_load_range(load: float) -> bool:
    return bool(np.isfinite(load) and FIT_MIN_G <= load <= FIT_MAX_G)


def excluded_values(view: dict[str, Any]) -> np.ndarray:
    original = np.asarray(view["original"], dtype=float)
    return original[(~view["mask"]) & np.isfinite(original)]


def fit_display_limits(view: dict[str, Any], actual: float) -> tuple[float, float]:
    """Display all finite source values while retaining the statistical range."""
    source = np.asarray(view["original"], dtype=float)
    source = source[np.isfinite(source)]
    low = min(FIT_MIN_G, actual, float(source.min()) if source.size else FIT_MIN_G)
    high = max(1.0, actual, float(source.max()) if source.size else actual)
    padding = (high - low) * .035
    return low - padding if low < FIT_MIN_G else FIT_MIN_G, high + padding


def mark_range(axis, limits: tuple[float, float], orientation: str = "x", *, shade: bool = True) -> None:
    low, high = limits
    span = axis.axvspan if orientation == "x" else axis.axhspan
    if shade:
        mark_saturation_regions(axis, limits, orientation=orientation)
    if shade and low < FIT_MIN_G:
        span(low, FIT_MIN_G, color=EXCLUDED_COLOR, alpha=.08, zorder=0)


def load_capture(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("format") != "e-skin-fsr-view-distribution-capture":
        raise ValueError(f"{path}: unsupported capture format")
    actual = data.get("actual_load", {})
    if not isinstance(actual, dict) or str(actual.get("unit", "g")).lower() not in {"g", "gram", "grams"}:
        raise ValueError(f"{path}: actual load must be in grams")
    if not np.isfinite(float(actual["value"])):
        raise ValueError(f"{path}: actual load must be finite")
    from new_protocol_evaluation import PROTOCOL_ID, protocol_key, recorded_predictions_g
    protocol, _lower, upper = protocol_key(data)
    if protocol == PROTOCOL_ID:
        recorded_predictions_g(data, upper)
        return data
    for name in VIEW_ORDER:
        view = data.get("views", {}).get(name)
        if not isinstance(view, dict):
            raise ValueError(f"{path}: missing {name}")
        if np.asarray(view.get("values"), dtype=float).shape != (ROWS, COLS):
            raise ValueError(f"{path}: {name} must have a 16x16 matrix")
    unit = str(data["views"]["FIT_PRESS"].get("unit", "")).lower()
    if unit not in {"g", "gram", "grams"}:
        raise ValueError(f"{path}: FIT PRESS must be in grams")
    return data


def prepare_views(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Legacy-only masks; explicitly marked new captures use matched evaluation."""
    from new_protocol_evaluation import PROTOCOL_ID, protocol_key
    if protocol_key(data)[0] == PROTOCOL_ID:
        raise ValueError("Use new_protocol_evaluation.prepare_matched for the shared-endpoint protocol")
    result = {}
    actual = float(data["actual_load"]["value"])
    for name in VIEW_ORDER:
        original = np.asarray(data["views"][name]["values"], dtype=float)
        status = np.full(original.shape, "ok", dtype="<U32")
        status[~np.isfinite(original)] = "nonfinite"
        if name == "FIT_PRESS":
            status[np.isfinite(original) & (original < FIT_MIN_G)] = "below_0g"
            status[np.isfinite(original) & (original > FIT_MAX_G)] = "saturated_above_3000g"
            # An out-of-range validation load is not evidence within the chosen range.
            if not in_load_range(actual):
                status[status == "ok"] = "actual_load_outside_0_3000g"
        mask = status == "ok"
        reasons, counts = np.unique(status[~mask], return_counts=True)
        result[name] = {
            "original": original,
            "values": original[mask],
            "mask": mask,
            "status": status,
            "count": int(mask.sum()),
            "excluded_count": int((~mask).sum()),
            "excluded_reasons": {str(k): int(v) for k, v in zip(reasons, counts)},
            "unit": UNITS[name],
            "source_unit": str(data["views"][name].get("unit", UNITS[name])),
        }
    return result


def describe(values: np.ndarray) -> dict[str, Any]:
    flat = np.asarray(values, dtype=float).ravel()
    flat = flat[np.isfinite(flat)]
    names = ("mean", "std", "sample_std", "median", "minimum", "q1", "q3",
             "maximum", "cv_percent", "variance", "iqr", "mad")
    if not flat.size:
        return {"count": 0, **dict.fromkeys(names)}
    mean = float(np.mean(flat))
    std = float(np.std(flat, ddof=0))
    median = float(np.median(flat))
    q1, q3 = np.percentile(flat, [25.0, 75.0])
    return {
        "count": int(flat.size), "mean": mean, "std": std,
        "sample_std": float(np.std(flat, ddof=1)) if flat.size > 1 else None,
        "median": median, "minimum": float(flat.min()),
        "q1": float(q1), "q3": float(q3), "maximum": float(flat.max()),
        "cv_percent": None if abs(mean) <= 1e-12 or flat.size < 2 else std / abs(mean) * 100,
        "variance": std**2, "iqr": float(q3 - q1),
        "mad": float(np.median(np.abs(flat - median))),
    }


def policy() -> dict[str, Any]:
    return {
        "fit_valid_range_g": [FIT_MIN_G, FIT_MAX_G],
        "range_inclusive": True,
        "fit_outside_range": "excluded, never clipped to 3000 or replaced with zero",
        "soft_saturation_g": [NORMAL_MAX_G, SOFT_SATURATION_MAX_G],
        "soft_saturation_statistics": "included; gray background in load plots",
        "saturation_g": ">3000; retained as labeled reference data, excluded from statistics",
        "actual_load_outside_range": "excluded from aggregate metrics; per-run QC retained",
        "normalization": "none; recorded values used in their native units",
        "population": "spatial cell values after the capture's one-second temporal average",
        "fit_filter_changes_cell_count": True,
        "out_of_range_display": "finite excluded values remain visible in gray; reference-only statistics are separate",
    }


def panel_title(axis, name: str, view: dict[str, Any], letter: str) -> None:
    axis.set_title(letter, loc="left", color=COLORS[name])
    axis.text(1.0, 1.025, f"n = {view['count']}/256  |  excluded {view['excluded_count']}",
              transform=axis.transAxes, ha="right", va="bottom", fontsize=8, color=SLATE_BLUE)
    axis.grid(axis="y", alpha=0.75)
    axis.set_axisbelow(True)


def finish_figure(fig, title: str, note: str) -> None:
    fig.suptitle(title, x=0.055, y=0.985, ha="left", fontsize=16, fontweight="semibold")
    # Detailed sampling and QC notes remain in summaries and report captions.
    fig.subplots_adjust(left=0.07, right=0.98, bottom=0.12, top=0.86, wspace=0.36)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
