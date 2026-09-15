"""Seven report 2.3 figures from the complete, provenance-checked Power matrix.

All 15 physical combinations appear once for each recorded ZERO/MAX condition.
The original analysis_v2_1 and raw measurements remain immutable.  Across-
combination SD describes observed spread, not repeated-trial uncertainty.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import shutil
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FormatStrFormatter
import numpy as np

import power_revision_figures as old
from power_revision_figures import (
    ROOT, FINAL, REPORT_FIGURES, STYLE, LOADS, COLORS, MARKERS, LABELS, MODULES,
    DARK_CHARCOAL, SLATE_BLUE, PUBLICATION_STYLE, GRID, canvas, count_axis,
    panel_label, load_handles, legend, export, digest, figure_47_drop_cmap,
)

INPUT = ROOT / "DATA" / "analysis" / "current" / "all_power_review_20260907"
OUTPUT = ROOT / "DATA" / "reference" / "report_v2_3_figures"
EVENT = ROOT / "DATA/raw/canonical/power_experiment_records/quality_events/supply_contact_M0_20260907.json"
LEGACY = ROOT / "DATA/reference/analysis_v2_1/analysis_summary.json"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def number(row, field):
    value = row[field]
    if value == "":
        raise ValueError(f"Required measurement missing: {field}: {row}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Nonfinite measurement: {field}: {row}")
    return value


def normalized_data():
    configs = read_csv(INPUT / "configuration_summary.csv")
    raw_branches = read_csv(INPUT / "branch_readings.csv")
    predictions = read_csv(INPUT / "additivity_checks.csv")
    groups = read_csv(INPUT / "group_summary.csv")
    assert len(configs) == 30 and len(raw_branches) == 64 and len(predictions) == 22
    runs, branches = [], []
    for r in configs:
        assert r["protocol_mode"] == "FULL" and r["configured_frequency_Hz"] == "200"
        assert r["host_state"] == old.CONTINUOUS
        runs.append({
            **r, "run_id": r["combo"] + ":" + r["load"],
            "N": int(r["module_count"]), "modules": r["combo"].split("-"),
            "state": r["host_state"], "frequency_hz": 200,
            "I_sum_mA": number(r, "I_sum_mA"),
            "P_output_est_mW": number(r, "P_source_output_estimate_mW"),
            "V_source_recorded_V": number(r, "V_source_main_V"),
            "T_regulator_recorded_C": number(r, "T_regulator_C"),
            "T_Teensy_recorded_C": number(r, "T_teensy_C"),
        })
    run_map = {r["run_id"]: r for r in runs}
    for b in raw_branches:
        run_id = b["combo"] + ":" + b["load"]
        run = run_map[run_id]
        branches.append({
            **b, "run_id": run_id, "N": int(b["module_count"]),
            "I_recorded_mA": number(b, "I_main_mA"),
            "V_recorded_V": number(b, "V_module_main_V"),
            "V_min_recorded_V": number(b, "V_module_min_V"),
            "V_max_recorded_V": number(b, "V_module_max_V"),
            "drop_recorded_mV": number(b, "source_minus_module_main_mV"),
            "T_STM32_recorded_C": number(b, "T_stm32_C"),
            "T_regulator_recorded_C": run["T_regulator_recorded_C"],
            "T_Teensy_recorded_C": run["T_Teensy_recorded_C"],
        })
    assert len(run_map) == len(runs)
    for r in runs:
        bb = [b for b in branches if b["run_id"] == r["run_id"]]
        assert len(bb) == r["N"] and {b["module_id"] for b in bb} == set(r["modules"])
        assert math.isclose(sum(b["I_recorded_mA"] for b in bb), r["I_sum_mA"], abs_tol=1e-9)
        assert math.isclose(r["P_output_est_mW"], r["I_sum_mA"] * r["V_source_recorded_V"], abs_tol=1e-9)
    for load in LOADS:
        assert [sum(r["load"] == load and r["N"] == n for r in runs) for n in range(1, 5)] == [4, 6, 4, 1]
        assert sum(p["load"] == load for p in predictions) == 11
        for n in range(1, 5):
            for plot_field, group_field in (("I_sum_mA", "I_sum_mA"), ("P_output_est_mW", "P_source_output_estimate_mW")):
                yy = [r[plot_field] for r in runs if r["load"] == load and r["N"] == n]
                g, = [g for g in groups if g["load"] == load and g["module_count"] == str(n)
                      and g["photo_filename_date_batch"] == "ALL" and g["metric"] == group_field]
                assert math.isclose(np.mean(yy), float(g["mean"]), abs_tol=1e-9)
                if len(yy) > 1:
                    assert math.isclose(np.std(yy, ddof=1), float(g["sample_SD_across_configurations"]), abs_tol=1e-9)
                else:
                    assert g["sample_SD_across_configurations"] == ""
    corrected, = [b for b in branches if b["combo"] == "M0-M1-M2" and b["load"] == "ZERO" and b["module_id"] == "M0"]
    assert corrected["V_recorded_V"] == 3.241 and corrected["drop_recorded_mV"] == 35
    return runs, branches, predictions


def plot_scaling(runs, out):
    fig, axes = canvas(columns=2, height=110, top=.82, bottom=.19, wspace=.36)
    for ax, field, ylabel, tag in (
        (axes[0, 0], "I_sum_mA", "Recorded branch-current sum (mA)", "(a) Current"),
        (axes[0, 1], "P_output_est_mW", "Estimated source-output power (mW)", "(b) Output power"),
    ):
        for load in LOADS:
            means, deviations = [], []
            xx = np.arange(1, 5) + (-.11 if load == "ZERO" else .11)
            for n, x in zip(range(1, 5), xx):
                group = sorted((r for r in runs if r["load"] == load and r["N"] == n), key=lambda r: r["combo"])
                yy = np.array([r[field] for r in group])
                spread = np.linspace(-.065, .065, len(group)) if len(group) > 1 else np.array([0.])
                ax.scatter(x + spread, yy, color=COLORS[load], marker=MARKERS[load],
                           s=24, edgecolors=DARK_CHARCOAL, linewidths=.4, zorder=4)
                means.append(float(yy.mean()))
                deviations.append(float(yy.std(ddof=1)) if len(yy) > 1 else None)
            ax.plot(xx, means, ls=(0, (3, 3)), lw=.9, color=COLORS[load], zorder=2)
            ax.errorbar(xx[:3], means[:3], yerr=deviations[:3], fmt="D", ms=4.3,
                        mfc="white", mec=DARK_CHARCOAL, mew=.55, ecolor=DARK_CHARCOAL,
                        elinewidth=.9, capsize=3.3, capthick=.9, zorder=6)
            ax.plot(xx[3], means[3], marker="D", ms=4.3, mfc="white", mec=DARK_CHARCOAL, mew=.55, zorder=6)
            ax.annotate(f"{means[-1]:.3f}" if field == "I_sum_mA" else f"{means[-1]:.2f}",
                        (xx[-1], means[-1]), xytext=(-5, -14 if load == "ZERO" else 8),
                        textcoords="offset points", ha="right", fontsize=7.5, color=COLORS[load])
        count_axis(ax)
        ax.set(ylim=(0, max(r[field] for r in runs) * 1.16), ylabel=ylabel)
        panel_label(ax, tag)
    legend(fig, load_handles() + [Line2D([], [], color=DARK_CHARCOAL, ls="--", marker="D",
                                       mfc="white", ms=4.3, lw=.9, label="Mean ± combination SD")], y=.98)
    return export(fig, out, "current_power_scaling",
                  "All 30 recorded configuration conditions: current sums and estimated source-output powers, with across-combination sample SD.",
                  {"points": "All 15 module combinations per load; one record per combination and load.",
                   "means": "Arithmetic means by load and N, counts 4, 6, 4, 1. All individual configuration points shown.",
                   "uncertainty": "Sample SD (ddof=1) across different combinations for N=1,2,3, never same-condition repeat SD. N=4 SD absent.",
                   "power": "Source main voltage multiplied by sequential branch-current main-reading sum; excludes Teensy USB and regulator loss.",
                   "lines": "Dashed descriptive mean connectors; no model fit or extrapolation.",
                   "jitter": "Deterministic equally spaced horizontal offsets; no measurement value modified."})


def plot_voltage(runs, branches, event, out):
    fig, axes = canvas(columns=2, height=115, top=.78, bottom=.17, wspace=.25)
    for load, ax in zip(LOADS, axes.flat):
        for n in range(1, 5):
            group = sorted((r for r in runs if r["load"] == load and r["N"] == n), key=lambda r: r["combo"])
            offsets = np.linspace(-.23, .23, len(group)) if len(group) > 1 else [0.]
            for row, offset in zip(group, offsets):
                xx = n + offset
                ax.scatter(xx, row["V_source_recorded_V"], marker="^", color=SLATE_BLUE, s=24, zorder=5)
                bb = [b for b in branches if b["run_id"] == row["run_id"]]
                local = np.linspace(-.035, .035, len(bb)) if len(bb) > 1 else [0.]
                for branch, jj in zip(bb, local):
                    lo, hi = branch["V_min_recorded_V"], branch["V_max_recorded_V"]
                    ax.vlines(xx + jj, lo, hi, color=DARK_CHARCOAL, lw=.7, zorder=2)
                    ax.hlines([lo, hi], xx + jj - .013, xx + jj + .013, color=DARK_CHARCOAL, lw=.7, zorder=2)
                    corrected = load == "ZERO" and row["combo"] == "M0-M1-M2" and branch["module_id"] == "M0"
                    ax.scatter(xx + jj, branch["V_recorded_V"], marker="*" if corrected else "o",
                               s=53 if corrected else 16, color=COLORS[load], edgecolors=DARK_CHARCOAL, linewidth=.4, zorder=4)
        ax.axhline(3.135, color=DARK_CHARCOAL, ls=(0, (4, 3)), lw=.8)
        ax.axhline(3.3, color=SLATE_BLUE, ls=":", lw=.75)
        ax.text(.75, 3.141, "3.135 V lower guideline", fontsize=7, color=DARK_CHARCOAL)
        if load == "ZERO":
            old_v = event["original_M0_voltage_V"]["main"]
            ax.scatter(2.62, old_v, marker="x", s=38, linewidths=1.2, color=DARK_CHARCOAL, zorder=7)
            ax.annotate("3.224 V contact fault", (2.62, old_v), xytext=(3.14, 3.195), fontsize=7,
                        ha="center", arrowprops={"arrowstyle": "-", "lw": .6, "color": DARK_CHARCOAL})
        count_axis(ax)
        ax.set(ylim=(3.115, 3.315), ylabel="Recorded voltage (V)")
        ax.set_yticks([3.15, 3.20, 3.25, 3.30])
        ax.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
        panel_label(ax, "(a) Zero load" if load == "ZERO" else "(b) Loaded (recorded)")
    handles = [Line2D([], [], marker="^", color=SLATE_BLUE, ls="none", label="Source main"),
               Line2D([], [], marker="o", color=DARK_CHARCOAL, ls="none", label="Module main"),
               Line2D([], [], marker="_", color=DARK_CHARCOAL, lw=.7, label="Module DMM MIN–MAX"),
               Line2D([], [], marker="*", color=COLORS["ZERO"], mec=DARK_CHARCOAL, ls="none", ms=8, label="M0 retest (3.241 V)"),
               Line2D([], [], marker="x", color=DARK_CHARCOAL, ls="none", label="Historical contact fault")]
    legend(fig, handles, columns=3, y=.98)
    return export(fig, out, "voltage_scaling",
                  "All 30 accepted source readings and 64 module voltage readings, with separate historical M0 connector fault and pointwise voltage retest.",
                  {"points": "30 source main and 64 accepted module main readings; one additional historical M0 fault marker.",
                   "intervals": "Module instrument MIN–MAX, not repeated-trial SD, synchronized extrema, or transient bounds.",
                   "fault": "Original M0=3.224 V is a real supply-connector contact fault; retained as separate historical X, not an accepted normal-connection value.",
                   "correction": "M0=3.241 V separate retest shown by star; SOURCE/M1/M2 voltages in ZERO M0-M1-M2 retained under user confirmation. No extra independent run.",
                   "guidelines": "3.135 V project lower guideline and 3.3 V nominal reference; no dynamic or component certification.",
                   "jitter": "Deterministic offsets separate combinations and modules; physical N remains integer."})


def plot_drop(runs, branches, out):
    combos = sorted({(r["N"], r["combo"]) for r in runs})
    fig, axes = canvas(columns=2, height=165, top=.91, bottom=.17, left=.225, right=.965, wspace=.15)
    vmax = math.ceil(max(b["drop_recorded_mV"] for b in branches) / 10) * 10
    cmap = figure_47_drop_cmap()
    cmap.set_bad("#F2F1EF")
    for load, ax in zip(LOADS, axes.flat):
        matrix = np.full((len(combos), 4), np.nan)
        for b in branches:
            if b["load"] == load:
                matrix[combos.index((b["N"], b["combo"])), MODULES.index(b["module_id"])] = b["drop_recorded_mV"]
        im = ax.pcolormesh(np.arange(5) - .5, np.arange(len(combos) + 1) - .5,
                          np.ma.masked_invalid(matrix), vmin=0, vmax=vmax, cmap=cmap,
                          shading="flat", rasterized=False)
        ax.set(xlim=(-.5, 3.5), ylim=(len(combos) - .5, -.5))
        for iy, (_, combo) in enumerate(combos):
            for ix in range(4):
                value = matrix[iy, ix]
                label = f"{value:.0f}" if np.isfinite(value) else "—"
                if load == "ZERO" and combo == "M0-M1-M2" and ix == 0:
                    label += "*"
                ax.text(ix, iy, label, ha="center", va="center", fontsize=7.5,
                        color="#20252D" if np.isfinite(value) else DARK_CHARCOAL)
        ax.set_xticks(range(4), MODULES)
        ax.set_yticks(range(len(combos)), [combo.replace("-", "+") for _, combo in combos])
        ax.tick_params(axis="both", length=0, labelsize=7.5)
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_visible(False)
        for boundary in (3.5, 9.5, 13.5):
            ax.axhline(boundary, color="white", lw=1.6)
        if load == "MAX":
            ax.set_yticklabels([])
        panel_label(ax, "(a) Zero load" if load == "ZERO" else "(b) Loaded (recorded)")
    color_ax = fig.add_axes([.30, .110, .56, .018])
    cb = fig.colorbar(im, cax=color_ax, orientation="horizontal")
    cb.solids.set_rasterized(False)
    cb.set_label("Source-to-module main-reading difference (mV)", labelpad=4)
    return export(fig, out, "module_voltage_drop",
                  "Main-reading voltage differences for all 15 physical combinations and both load conditions, with a marked pointwise M0 correction.",
                  {"cells": "64 active-module cells: 1000 × (source main V − accepted module main V), sequential observations.",
                   "correction": "35* mV in ZERO M0-M1-M2/M0 uses separately retested M0=3.241 V and retained, user-confirmed source=3.276 V. Cross-record pointwise estimate, not synchronous new measurement.",
                   "missing": "An em dash denotes a physically absent module, not missing or zero voltage.",
                   "range": "Shared linear zero-based 0–50 mV colour scale; complete accepted records only. Historical faulty 52 mV difference retained in voltage event, not accepted cell.",
                   "uncertainty": "One configuration-condition observation per active cell; no repeat uncertainty."})


def plot_prediction(predictions, out):
    combos = sorted({(int(p["module_count"]), p["combo"]) for p in predictions})
    fig, axes = canvas(columns=2, height=145, top=.84, bottom=.15, left=.105, right=.98, wspace=.82)
    left, right = axes[0]
    xfield = "I_prediction_from_same_load_N1_physical_modules_mA"
    yfield = "I_observed_sum_mA"
    bounds = [number(p, field) for p in predictions for field in (xfield, yfield)]
    lower, upper = min(bounds) - 3, max(bounds) + 3
    left.plot([lower, upper], [lower, upper], ls="--", color=SLATE_BLUE, lw=1)
    for load in LOADS:
        rows = sorted((p for p in predictions if p["load"] == load), key=lambda p: (int(p["module_count"]), p["combo"]))
        left.scatter([number(p, xfield) for p in rows], [number(p, yfield) for p in rows],
                     color=COLORS[load], marker=MARKERS[load], s=31,
                     edgecolors=DARK_CHARCOAL, linewidths=.4, zorder=4)
        yy = np.arange(len(rows)) + (-.13 if load == "ZERO" else .13)
        right.scatter([number(p, "residual_percent_of_prediction") for p in rows], yy,
                      color=COLORS[load], marker=MARKERS[load], s=30,
                      edgecolors=DARK_CHARCOAL, linewidths=.4, zorder=4)
    left.set(xlim=(lower, upper), ylim=(lower, upper), xlabel="Separate N=1 current sum (mA)", ylabel="Multi-module current sum (mA)")
    left.set_aspect("equal", adjustable="box")
    right.axvline(0, color=DARK_CHARCOAL, lw=.8)
    right.set(yticks=range(len(combos)), yticklabels=[c.replace("-", "+") for _, c in combos],
              xlabel="Signed relative residual (%)", xlim=(-3.15, .7), ylim=(len(combos) - .5, -.5))
    right.tick_params(axis="y", labelsize=7.3)
    right.set_xticks([-3, -2, -1, 0])
    right.grid(axis="y", visible=False)
    right.grid(axis="x", color=GRID, lw=.55)
    for boundary in (5.5, 9.5):
        right.axhline(boundary, color=GRID, lw=.65)
    panel_label(left, "(a) Same-label N=1 reference")
    panel_label(right, "(b) Descriptive residual")
    legend(fig, load_handles() + [Line2D([], [], color=SLATE_BLUE, ls="--", lw=1, label="Equality (panel a)")], y=.97)
    return export(fig, out, "independent_current_prediction",
                  "Separate single-module reference sums and signed residuals for all 11 multi-module combinations under each recorded load label.",
                  {"prediction": "Sum of separate N=1 main currents of exactly the physical modules present, using the same ZERO/MAX label.",
                   "points": "11 distinct multi-module combinations per load, 22 comparisons total; one record per combination-condition, not independent repeats.",
                   "residual": "100 × (multi-module branch-current sum − separate N=1 reference sum) / separate N=1 reference sum.",
                   "limitations": "Descriptive additivity only; shared modules and batches, no repeatability or instrument-uncertainty estimate. MAX labels do not establish matched load mass/area/distribution.",
                   "axes": "Prediction and observation share identical linear limits with equality line. Residual axis includes zero and every observation."})


def source_audit():
    supplied = json.loads((INPUT / "source_manifest.json").read_text(encoding="utf-8-sig"))
    verified = []
    for entry in supplied["sources"]:
        path = ROOT / entry["relative_path"]
        actual = digest(path)
        if actual != entry["sha256"]:
            raise ValueError(f"Source checksum mismatch: {path}")
        verified.append({"relative_path": entry["relative_path"], "sha256": actual})
    direct_paths = list(INPUT.glob("*.csv")) + [INPUT / "summary.json", INPUT / "source_manifest.json", EVENT, LEGACY,
                                                Path(__file__), Path(old.__file__), STYLE, FINAL / "figure_style.py"]
    return verified, [{"path_relative_to_Final": str(p.relative_to(FINAL)).replace("\\", "/"),
                       "sha256": digest(p)} for p in sorted(set(direct_paths))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--copy-to-report", action="store_true")
    args = parser.parse_args()
    sources, direct_sources = source_audit()
    runs, branches, predictions = normalized_data()
    legacy = json.loads(LEGACY.read_text(encoding="utf-8-sig"))
    blocked = [r for r in legacy["runs"] if r["N"] == 1 and r["frequency_hz"] == 200 and r["protocol_mode"] == "FULL"
               and r["load"] == "ZERO" and r["state"] == old.BLOCKED]
    assert len(blocked) == 4
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with plt.style.context(STYLE), matplotlib.rc_context(PUBLICATION_STYLE):
        matplotlib.rcParams.update({"svg.hashsalt": "eskin-power-report-2.3", "font.size": 8.5,
                                    "axes.labelsize": 8.5, "xtick.labelsize": 8,
                                    "ytick.labelsize": 8, "legend.fontsize": 7.5})
        figures = [plot_scaling(runs, out), plot_voltage(runs, branches, json.loads(EVENT.read_text(encoding="utf-8")), out),
                   plot_drop(runs, branches, out), old.plot_screening(blocked + runs, out),
                   old.plot_branches(branches, out), old.plot_temperature(runs, branches, out), plot_prediction(predictions, out)]
    for entry in figures:
        if entry["stem"] == "branch_current_balance":
            entry["semantics"].update(points="All 64 branch main readings, eight combination-condition observations per physical module per load.",
                                      jitter="Deterministic offsets separate load and all different combinations at each N; no current altered.")
        if entry["stem"] == "temperature_scaling":
            entry["semantics"].update(STM32="Highest of all active-module STM32 point readings in each of the 30 configuration conditions; all 64 active-module readings available.",
                                      regulator_and_host="One regulator and one Teensy point reading per configuration condition; 30 each, not duplicated as independent branch measurements.")
    # Copy the exact input tables as an accessible numerical alternative, preserving every field.
    for name in ("configuration_summary.csv", "branch_readings.csv", "additivity_checks.csv", "group_summary.csv"):
        shutil.copy2(INPUT / name, out / name)
    manifest = {
        "report_version": "2.3", "audience": "Imperial individual-project manuscript; no publisher-compliance claim",
        "data_counts": {"configuration_conditions": 30, "branches": 64, "combinations_per_load_by_N": [4, 6, 4, 1],
                        "same_configuration_condition_records": 1, "historical_blocked_screening_only": 4},
        "source_input_dir": INPUT.relative_to(FINAL).as_posix(), "direct_sources": direct_sources, "verified_upstream_sources": sources,
        "versions": {"python": sys.version.split()[0], "matplotlib": matplotlib.__version__, "numpy": np.__version__},
        "export": {"width_mm": 180, "PNG_dpi": 300, "PDF_fonttype": 42, "SVG_fonttype": "none", "opaque_white_background": True,
                   "bbox_inches": None, "no_data_smoothing_or_random_jitter": True},
        "figures": figures,
    }
    manifest_path = out / "figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.copy_to_report:
        REPORT_FIGURES.mkdir(parents=True, exist_ok=True)
        for entry in figures:
            for file in entry["files"]:
                target = REPORT_FIGURES / file["name"]
                shutil.copy2(out / file["name"], target)
                assert digest(target) == file["sha256"]
        shutil.copy2(manifest_path, REPORT_FIGURES / "figure_manifest_v2_3.json")
    print(json.dumps({"figures": len(figures), "output": str(out), "copy_to_report": args.copy_to_report,
                      "verified_sources": len(sources), "direct_sources": len(direct_sources)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
