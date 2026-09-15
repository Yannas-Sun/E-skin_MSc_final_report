"""Compare validation loads with the mean in-range FIT PRESS cell load."""

from __future__ import annotations

import argparse
import csv
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
from portable_paths import portable_path

from evaluation_plotting import (
    COLORS, EXCLUDED_COLOR, FIT_MIN_G, FIT_MAX_G, finish_figure, plot_style,
    policy, write_json, mark_range, load_capture, prepare_views, describe, in_load_range,
)


def collect_records(evaluation_dir: Path) -> list[dict[str, Any]]:
    records = []
    paths = sorted((evaluation_dir / "view_distribution").glob("*/view_distribution_capture.json"))
    for index, path in enumerate(paths, start=1):
        source = load_capture(path)
        fit = prepare_views(source)["FIT_PRESS"]
        actual = float(source["actual_load"]["value"])
        inferred = describe(fit["values"])["mean"]
        included = in_load_range(actual) and inferred is not None
        error = inferred - actual if included else None
        reference = describe(fit["original"])["mean"]
        reference_error = reference - actual if reference is not None else None
        records.append({
            "record_index": index, "source": portable_path(path),
            "source_capture": portable_path(path), "frame_count": source.get("source_frames", {}).get("count"),
            "module_id": source["module_id"], "fsr": source["fsr"],
            "actual_load_g": actual, "inferred_load_g": inferred if included else None,
            "actual_unit": "g", "inferred_unit": "g",
            "valid_fit_cells": fit["count"], "excluded_fit_cells": fit["excluded_count"],
            "included": included,
            "exclusion_reason": None if included else "actual_load_outside_0_3000g" if not in_load_range(actual) else "no_valid_fit_cells",
            "signed_error_g": error, "absolute_error_g": abs(error) if error is not None else None,
            "error_rate_percent": abs(error) / abs(actual) * 100 if error is not None and actual != 0 else None,
            "zero_load_excluded": actual == 0,
            "display_reference_inferred_load_g": reference,
            "display_reference_signed_error_g": reference_error,
            "display_reference_error_rate_percent": (
                abs(reference_error) / abs(actual) * 100
                if reference_error is not None and actual != 0 else None),
        })
    if not records:
        raise ValueError(f"No view-distribution captures under {evaluation_dir}")
    if len({(r["module_id"], r["fsr"]) for r in records}) != 1:
        raise ValueError("Analyze one module/FSR evaluation directory at a time")
    return sorted(records, key=lambda r: (r["actual_load_g"], r["source"]))


def save_plot(path: Path, records: list[dict[str, Any]], metrics: dict[str, Any], kind: str) -> None:
    with plot_style():
        fig, axis = plt.subplots(figsize=(11.8, 6.2))
        # Valid curves keep their original mask; excluded tests are separate reference points.
        plotted = [r for r in records if r["included"]]
        excluded = [r for r in records if not r["included"]]
        low = min(0., *(r["actual_load_g"] for r in records))
        high = max(1., *(r["actual_load_g"] for r in records))
        limits = (low - (high-low)*.03 if low < 0 else 0., high + (high-low)*.06)
        x = np.array([r["actual_load_g"] for r in plotted], dtype=float)
        inferred = np.array([np.nan if r["inferred_load_g"] is None else r["inferred_load_g"] for r in plotted])
        if kind == "comparison":
            axis.plot([low, high], [low, high], color=COLORS["FIT_PRESS"], linestyle="--",
                      label="Actual load", linewidth=1.5)
            axis.plot(x, inferred, color=COLORS["FIT_PRESS"], marker="^", markersize=5,
                      linewidth=1.8, label="Mean valid FIT load")
            title, ylabel = "Actual vs inferred load", "Load (g)"
            ref_key = "display_reference_inferred_load_g"
        elif kind == "rate":
            y = [np.nan if r["error_rate_percent"] is None else r["error_rate_percent"] for r in plotted]
            axis.plot(x, y, color=COLORS["NORM_CAL"], marker="s", linewidth=1.8, markersize=5,
                      label="Absolute percentage error")
            title, ylabel = "Relative load error", "Absolute error rate (%)"
            ref_key = "display_reference_error_rate_percent"
        else:
            axis.plot(x, inferred - x, color=COLORS["RAW"], marker="o", linewidth=1.8, markersize=5,
                      label="Inferred - actual")
            axis.axhline(0, color=COLORS["FIT_PRESS"], linewidth=1, linestyle="--")
            title, ylabel = "Load error: inferred minus actual", "Error (g)"
            ref_key = "display_reference_signed_error_g"
        refs = [r for r in excluded if r[ref_key] is not None]
        if refs:
            axis.scatter([r["actual_load_g"] for r in refs], [r[ref_key] for r in refs],
                         marker="x", color=EXCLUDED_COLOR, s=60, linewidths=1.6, zorder=5,
                         label="Excluded test (reference only)")
        if kind == "comparison":
            y_values = [high] + [r[ref_key] for r in refs] + [v for v in inferred if np.isfinite(v)]
            axis.set_ylim(min(0., min(y_values)) - (max(y_values)-min(0., min(y_values))) * .01,
                          max(y_values) * 1.08)
        elif kind == "rate":
            axis.set_ylim(bottom=0)
        axis.set(xlabel="Actual load (g)", ylabel=ylabel, xlim=limits)
        mark_range(axis, limits)
        axis.grid(axis="y", alpha=.75)
        legend_location = "lower left" if kind == "signed" else "upper right" if kind == "rate" else "upper left"
        axis.legend(loc=legend_location, ncol=2, fontsize=8)
        stats = [metrics[k] for k in ("mean_error_rate_percent", "max_error_rate_percent", "min_error_rate_percent")]
        formatted = ["n/a" if value is None else f"{value:.2f}%" for value in stats]
        axis.text(0, 1.035, f"In-range tests only  |  Mean / max / min error rate: {' / '.join(formatted)}",
                  transform=axis.transAxes, fontsize=10, color=COLORS["FIT_PRESS"])
        note = (f"FIT statistics: 0–{FIT_MAX_G:g} g; soft saturation retained. Included tests: {metrics['record_count']}; "
                f"excluded: {metrics['excluded_records']}.\n"
                "Gray crosses: unfiltered source-mean estimates for excluded tests, display only; excluded from error statistics.\n"
                "Zero load is excluded from percentage-error statistics. Positive error indicates overestimation.")
        finish_figure(fig, f"M{records[0]['module_id']} {records[0]['fsr']}  |  {title}", note)
        fig.subplots_adjust(left=.095, bottom=.20)
        fig.savefig(path)
        plt.close(fig)


def analyze(evaluation_dir: Path, output_dir: Path, *, include_shared_lut: bool = True) -> dict[str, Path]:
    from new_protocol_evaluation import PROTOCOL_ID, batch_protocol, capture_paths, analyze_batch
    if batch_protocol(capture_paths(evaluation_dir))[0] == PROTOCOL_ID:
        return analyze_batch(evaluation_dir, output_dir, kind="accuracy", include_shared_lut=include_shared_lut)
    records = collect_records(evaluation_dir)
    valid = [r for r in records if r["included"]]
    rates = [r["error_rate_percent"] for r in valid if r["error_rate_percent"] is not None]
    metrics = {
        "record_count": len(valid), "total_source_records": len(records),
        "excluded_records": len(records)-len(valid), "nonzero_load_records": len(rates),
        "zero_load_records_excluded": sum(r["actual_load_g"] == 0 for r in valid),
        "mean_error_rate_percent": float(np.mean(rates)) if rates else None,
        "max_error_rate_percent": float(np.max(rates)) if rates else None,
        "min_error_rate_percent": float(np.min(rates)) if rates else None,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for key, filename, kind in (
        ("plot", "load_comparison.png", "comparison"),
        ("error_rate_plot", "load_error_rate_vs_load.png", "rate"),
        ("error_plot", "load_error_vs_load.png", "signed"),
    ):
        outputs[key] = output_dir / filename
        save_plot(outputs[key], records, metrics, kind)
    outputs["csv"] = output_dir / "load_comparison.csv"
    with outputs["csv"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    outputs["summary"] = output_dir / "load_comparison_summary.json"
    write_json(outputs["summary"], {
        "format": "e-skin-load-accuracy-analysis", "version": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_evaluation_dir": portable_path(evaluation_dir),
        "quality_policy": policy(), "metrics": metrics,
        "records": records, "excluded_records": [r for r in records if not r["included"]],
        "error_definitions": {"signed_error_g": "inferred - actual", "absolute_error_g": "abs(inferred - actual)"},
    })
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-shared-lut", action="store_true", help="Compatibility for old exports without a frozen mean-cell inverse LUT")
    args = parser.parse_args()
    evaluation_dir = args.evaluation_dir.resolve()
    outputs = analyze(evaluation_dir, (args.output_dir or evaluation_dir / "analysis" / "error").resolve(),
                      include_shared_lut=not args.no_shared_lut)
    for name, path in outputs.items():
        print(f"Generated {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
