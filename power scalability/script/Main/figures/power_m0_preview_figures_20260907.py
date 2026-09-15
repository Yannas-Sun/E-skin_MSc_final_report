"""Standalone latest-M0 Power previews; never write to manuscript or report assets.

Inputs are a separate compiled view prepared from report 2.4 and the five M0
point retests. N1 M0 ZERO voltage 3.252 V is confirmed by the user.
Reusing a source voltage is not a synchronous new measurement.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PathCollection
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.lines import Line2D
from matplotlib.ticker import FormatStrFormatter, FuncFormatter, MaxNLocator
import numpy as np

import power_retest_figures as prior
import power_revision_figures as old
from power_m0_preview_heatmap_scale_20260907 import data_color_scale
from power_revision_figures import (
    ROOT, STYLE, PUBLICATION_STYLE, LOADS, COLORS, MARKERS, MODULES,
    DARK_CHARCOAL, SLATE_BLUE, canvas, count_axis, panel_label, load_handles,
    legend, digest, figure_47_drop_cmap,
)

PREVIEW = ROOT / "DATA/archive/m0_n1_n2_preview_20260907"
INPUT = PREVIEW / "data"
OUTPUT = PREVIEW / "figures"
TARGETS = {
    ("M0", "ZERO", "M0"), ("M0", "MAX", "M0"),
    ("M0-M1", "ZERO", "M0"), ("M0-M2", "ZERO", "M0"),
    ("M0-M3", "ZERO", "M0"),
    ("M0-M1-M2", "ZERO", "M0"), ("M1-M2-M3", "MAX", "M3"),
}
TARGET_RUNS = {(combo, load) for combo, load, _ in TARGETS}
ALL_BRANCHES = []
ALL_RUNS = []


def key(row):
    return row["combo"], row["load"], row["module_id"]


def export(fig, out, stem, description, semantics):
    """Constrain every output to the new directory; export PNG and SVG only."""
    if Path(out).resolve() != OUTPUT.resolve():
        raise ValueError("Preview export outside its isolated output directory")
    if stem == "branch_current_balance":
        fig.subplots_adjust(bottom=.18)
        for module, ax in zip(MODULES, fig.axes):
            for load in LOADS:
                for n in range(1, 5):
                    rows = sorted((b for b in ALL_BRANCHES if b["module_id"] == module
                                   and b["load"] == load and b["N"] == n), key=lambda b: b["combo"])
                    xx = n + (-.10 if load == "ZERO" else .10) + (
                        np.linspace(-.045, .045, len(rows)) if len(rows) > 1 else np.array([0.]))
                    for row, x in zip(rows, xx):
                        if key(row) in TARGETS:
                            ax.scatter(x, row["I_recorded_mA"], marker="*", s=67,
                                       color=COLORS[load], edgecolors=DARK_CHARCOAL, linewidths=.5, zorder=7)
        semantics["points"] = "64 selected branch readings; seven targeted currents are marked with stars. No extra whole-configuration runs."
        semantics["jitter"] = "Deterministic offsets distinguish load and every available combination at each N."
    if stem == "single_module_screening":
        ax = fig.axes[0]
        for load, x in (("ZERO", 0.), ("MAX", .15)):
            row, = [r for r in ALL_RUNS if r["combo"] == "M0" and r["load"] == load]
            ax.scatter(x, row["I_sum_mA"], marker="*", s=78, color=COLORS[load],
                       edgecolors=DARK_CHARCOAL, linewidths=.5, zorder=7)
        semantics["conditions"] = "200 Hz FULL. Historical N1 blocked readings retained; continuous M0 ZERO and MAX currents use latest targeted retests."
    if stem == "temperature_scaling":
        semantics["STM32"] = "Maximum of the identified module temperatures in each of 30 compiled condition entries; all 64 module readings available."
        semantics["regulator_and_host"] = "30 regulator and 30 Teensy point readings, retained unchanged; not duplicated as branch observations."
    semantics.update(
        preview="Standalone preview only; this script does not edit the manuscript, published PDF or report figure assets. Concurrent work by other agents is outside this script's scope.",
        selection="Five newest M0 targeted retests added to two earlier point retests; 30 compiled condition entries and 64 selected branches remain.",
        retained="Source voltage, unmodified branches and temperatures are retained readings, not newly repeated measurements.",
        confirmed_N1_voltage="User confirms N1 M0 ZERO voltage 3.252 V and its photo assignment; the difference from the retained 3.280 V source is 28 mV.",
        user_correction="N2 M0-M1 ZERO M0 voltage 3.251 V is user-confirmed; the wrongly assigned 3.243 V photo is excluded.",
    )
    note = "Sources and other readings retained; SD denotes spread across combinations, not repeated trials."
    if stem in {"branch_current_balance", "single_module_screening"}:
        note = "Stars: selected targeted current retests. Other readings retained; no added full-condition repeats."
    if stem == "temperature_scaling":
        note = "Temperature observations retained unchanged; no new thermal run or equilibrium claim."
    if stem == "voltage_scaling":
        note = "N1 ZERO M0: 3.252 V confirmed. Source readings retained; MIN-MAX is the DMM range."
    if stem == "module_voltage_drop":
        note = "N1 ZERO M0 voltage confirmed. u: M0+M1 ZERO M0 voltage confirmed by user."
    fig.text(.5, .035, note, ha="center", va="bottom", fontsize=6.1, color=DARK_CHARCOAL)
    fig.text(.5, .012, "M0 retest preview | Not applied to report", ha="center", va="bottom", fontsize=6.4, color=DARK_CHARCOAL)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    outside = []
    for artist in fig.findobj(matplotlib.text.Text):
        if artist.get_visible() and artist.get_text().strip():
            bb = artist.get_window_extent(renderer)
            if bb.x0 < fig.bbox.x0 - 1 or bb.x1 > fig.bbox.x1 + 1 or bb.y0 < fig.bbox.y0 - 1 or bb.y1 > fig.bbox.y1 + 1:
                outside.append(artist.get_text())
    if outside:
        raise ValueError(f"Text outside preview canvas: {stem}: {outside}")
    scatter_count = 0
    for ax in fig.axes:
        xmin, xmax = sorted(ax.get_xlim())
        ymin, ymax = sorted(ax.get_ylim())
        for collection in ax.collections:
            if isinstance(collection, PathCollection):
                points = np.asarray(collection.get_offsets(), dtype=float)
                scatter_count += len(points)
                if len(points) and (np.any(points[:, 0] < xmin) or np.any(points[:, 0] > xmax)
                                    or np.any(points[:, 1] < ymin) or np.any(points[:, 1] > ymax)):
                    raise ValueError(f"Scatter point outside axes: {stem}")
    files = []
    for extension in ("png", "svg"):
        path = OUTPUT / f"{stem}.{extension}"
        metadata = {"Title": stem.replace("_", " "), "Description": "LATEST M0 PREVIEW: " + description}
        if extension == "svg":
            metadata["Date"] = None
        fig.savefig(path, dpi=300, bbox_inches=None, facecolor="white", metadata=metadata)
        files.append({"name": path.name, "sha256": digest(path), "bytes": path.stat().st_size})
    dimensions = [round(x * 25.4, 3) for x in fig.get_size_inches()]
    plt.close(fig)
    return {"stem": stem, "description": description, "semantics": semantics,
            "dimensions_mm": dimensions, "files": files, "text_outside_canvas": outside,
            "scatter_points_count_including_overlays": scatter_count}


def plot_scaling(runs):
    fig, axes = canvas(columns=2, height=115, top=.82, bottom=.21, wspace=.36)
    for ax, field, ylabel, tag in (
        (axes[0, 0], "I_sum_mA", "Compiled branch-current sum (mA)", "(a) Current"),
        (axes[0, 1], "P_output_est_mW", "Estimated source-output power (mW)", "(b) Output power"),
    ):
        for load in LOADS:
            means, deviations = [], []
            xx = np.arange(1, 5) + (-.11 if load == "ZERO" else .11)
            for n, x in zip(range(1, 5), xx):
                rows = sorted((r for r in runs if r["load"] == load and r["N"] == n), key=lambda r: r["combo"])
                yy = np.array([r[field] for r in rows])
                spread = np.linspace(-.065, .065, len(rows)) if len(rows) > 1 else np.array([0.])
                ax.scatter(x + spread, yy, color=COLORS[load], marker=MARKERS[load], s=24,
                           edgecolors=DARK_CHARCOAL, linewidths=.4, zorder=4)
                for row, px, py in zip(rows, x + spread, yy):
                    if (row["combo"], load) in TARGET_RUNS:
                        ax.scatter(px, py, color=COLORS[load], marker="*", s=90,
                                   edgecolors=DARK_CHARCOAL, linewidths=.5, zorder=7)
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
    legend(fig, load_handles() + [Line2D([], [], color=DARK_CHARCOAL, ls="--", marker="D", mfc="white", ms=4.3, lw=.9,
                                        label="Mean ± combination SD (n=4,6,4,1)"),
                                  Line2D([], [], marker="*", color=DARK_CHARCOAL, ls="none", ms=8, label="Targeted current retest entry")], columns=2, y=.98)
    return export(fig, OUTPUT, "current_power_scaling", "Latest compiled current and estimated source-output power for all combinations.",
                  {"means": "Counts 4,6,4,1 by N in each load; sample SD across combinations for N1-N3 only. N4 SD absent.",
                   "power": "Retained source main voltage multiplied by the compiled sequential branch-current sum; excludes Teensy USB and regulator loss.",
                   "lines": "Descriptive mean connectors, not fitted or extrapolated models."})


def plot_voltage(runs, branches):
    fig, axes = canvas(columns=2, height=122, top=.78, bottom=.20, wspace=.25)
    for load, ax in zip(LOADS, axes.flat):
        for n in range(1, 5):
            rows = sorted((r for r in runs if r["load"] == load and r["N"] == n), key=lambda r: r["combo"])
            offsets = np.linspace(-.23, .23, len(rows)) if len(rows) > 1 else [0.]
            for row, offset in zip(rows, offsets):
                x = n + offset
                ax.scatter(x, row["V_source_recorded_V"], marker="^", color=SLATE_BLUE, s=24, zorder=5)
                bb = [b for b in branches if b["run_id"] == row["run_id"]]
                local = np.linspace(-.035, .035, len(bb)) if len(bb) > 1 else [0.]
                for b, jitter in zip(bb, local):
                    px, val = x + jitter, b["V_recorded_V"]
                    lo, hi = b["V_min_recorded_V"], b["V_max_recorded_V"]
                    ax.vlines(px, lo, hi, color=DARK_CHARCOAL, lw=.7, zorder=2)
                    ax.hlines([lo, hi], px - .013, px + .013, color=DARK_CHARCOAL, lw=.7, zorder=2)
                    selected = key(b) in TARGETS
                    ax.scatter(px, val, marker="*" if selected else "o",
                               s=53 if selected else 16,
                               facecolors=COLORS[load], edgecolors=DARK_CHARCOAL, linewidth=.6, zorder=6)
        ax.axhline(3.135, color=DARK_CHARCOAL, ls=(0, (4, 3)), lw=.8)
        ax.axhline(3.3, color=SLATE_BLUE, ls=":", lw=.75)
        ax.text(.75, 3.141, "3.135 V lower guideline", fontsize=7, color=DARK_CHARCOAL)
        if load == "ZERO":
            ax.scatter(2.62, 3.224, marker="x", s=38, linewidths=1.2, color=DARK_CHARCOAL, zorder=7)
            ax.annotate("3.224 V contact fault", (2.62, 3.224), xytext=(3.12, 3.185), fontsize=7,
                        ha="center", arrowprops={"arrowstyle": "-", "lw": .6, "color": DARK_CHARCOAL})
        else:
            ax.scatter(3.34, 3.232, marker="x", s=38, linewidths=1.2, color=DARK_CHARCOAL, zorder=7)
            ax.annotate("M3 earlier: 3.232 V", (3.34, 3.232), xytext=(2.78, 3.195), fontsize=7,
                        ha="center", arrowprops={"arrowstyle": "-", "lw": .6, "color": DARK_CHARCOAL})
        count_axis(ax)
        ax.set(ylim=(3.115, 3.315), ylabel="Recorded voltage (V)")
        ax.set_yticks([3.15, 3.20, 3.25, 3.30])
        ax.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
        panel_label(ax, "(a) Zero load" if load == "ZERO" else "(b) Loaded (recorded)")
    handles = [Line2D([], [], marker="^", color=SLATE_BLUE, ls="none", label="Retained source main"),
               Line2D([], [], marker="o", color=DARK_CHARCOAL, ls="none", label="Module main"),
               Line2D([], [], marker="_", color=DARK_CHARCOAL, lw=.7, label="Module DMM MIN–MAX"),
               Line2D([], [], marker="*", color=COLORS["ZERO"], mec=DARK_CHARCOAL, ls="none", ms=8, label="Selected module retest"),
               Line2D([], [], marker="x", color=DARK_CHARCOAL, ls="none", label="Earlier reading")]
    legend(fig, handles, columns=3, y=.98)
    return export(fig, OUTPUT, "voltage_scaling", "Retained source voltages and selected module voltages with latest M0 retests.",
                  {"points": "30 source readings and 64 selected module readings; N1 ZERO M0 voltage confirmed as 3.252 V. Two earlier N3 readings shown separately.",
                   "intervals": "DMM MIN-MAX, not repeat SD or transient bounds.",
                   "guidelines": "Existing project references retained, no new electrical certification."})


def plot_drop(runs, branches):
    combos = sorted({(r["N"], r["combo"]) for r in runs})
    scale = data_color_scale([b["drop_recorded_mV"] for b in branches])
    matrices = {}
    for load in LOADS:
        matrix = np.full((len(combos), 4), np.nan)
        for b in branches:
            if b["load"] == load:
                matrix[combos.index((b["N"], b["combo"])), MODULES.index(b["module_id"])] = b["drop_recorded_mV"]
        matrices[load] = matrix
    assert np.array_equal(np.isfinite(matrices["ZERO"]), np.isfinite(matrices["MAX"]))
    delta = matrices["MAX"] - matrices["ZERO"]
    changes = delta[np.isfinite(delta)]
    assert len(changes) == 32
    assert np.allclose(changes, np.round(changes), atol=1e-9)
    maxabs = max(float(np.max(np.abs(changes))), .5)
    delta_ticks = MaxNLocator(nbins=4, steps=[1, 2, 2.5, 5, 10]).tick_values(-maxabs, maxabs)
    delta_bound = float(np.max(np.abs(delta_ticks)))
    delta_scale = {"data_min": float(changes.min()), "data_max": float(changes.max()),
                   "vmin": -delta_bound, "vmax": delta_bound,
                   "ticks": [float(tick) for tick in delta_ticks], "center": 0.,
                   "policy": "Independent linear diverging scale, symmetric about zero with enclosing bounds determined by maximum absolute observed change."}
    fig, axes = canvas(columns=3, height=182, top=.91, bottom=.23, left=.17, right=.98, wspace=.14)
    fig.set_size_inches(250 / 25.4, 182 / 25.4)
    cmap = figure_47_drop_cmap()
    cmap.set_bad("#F2F1EF")
    change_cmap = LinearSegmentedColormap.from_list("drop_change", ["#167F91", "#FAFAF8", "#B8442D"])
    change_cmap.set_bad("#F2F1EF")
    images = []
    for load, ax in zip((*LOADS, "CHANGE"), axes.flat):
        is_change = load == "CHANGE"
        matrix = delta if is_change else matrices[load]
        color_options = {"cmap": change_cmap, "norm": TwoSlopeNorm(vmin=-delta_bound, vcenter=0, vmax=delta_bound)} if is_change else {
            "cmap": cmap, "vmin": scale["vmin"], "vmax": scale["vmax"]}
        im = ax.pcolormesh(np.arange(5) - .5, np.arange(len(combos) + 1) - .5,
                          np.ma.masked_invalid(matrix), **color_options, shading="flat", rasterized=False)
        images.append(im)
        ax.set(xlim=(-.5, 3.5), ylim=(len(combos) - .5, -.5))
        for iy, (_, combo) in enumerate(combos):
            for ix, module in enumerate(MODULES):
                value = matrix[iy, ix]
                label = f"{value:.0f}" if np.isfinite(value) else "—"
                if is_change and np.isfinite(value):
                    label = f"{value:+.0f}" if value != 0 else "0"
                elif not is_change:
                    marker = (combo, load, module)
                    if marker == ("M0-M1", "ZERO", "M0"):
                        label += "u"
                    elif marker in TARGETS:
                        label += "*"
                ax.text(ix, iy, label, ha="center", va="center", fontsize=7.5,
                        color="white" if is_change and np.isfinite(value) and abs(value) >= .75 * delta_bound else "#20252D" if np.isfinite(value) else DARK_CHARCOAL)
        ax.set_xticks(range(4), MODULES)
        ax.set_yticks(range(len(combos)), [combo.replace("-", "+") for _, combo in combos])
        ax.tick_params(axis="both", length=0, labelsize=7.5)
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_visible(False)
        for boundary in (3.5, 9.5, 13.5):
            ax.axhline(boundary, color="white", lw=1.6)
        if load != "ZERO":
            ax.set_yticklabels([])
        panel_label(ax, {"ZERO": "(a) Zero load", "MAX": "(b) Loaded (recorded)", "CHANGE": "(c) Loaded − zero"}[load])
    positions = [ax.get_position() for ax in axes.flat]
    color_ax = fig.add_axes([positions[0].x0 + .025, .168, positions[1].x1 - positions[0].x0 - .05, .018])
    cb = fig.colorbar(images[0], cax=color_ax, orientation="horizontal", ticks=scale["ticks"])
    cb.solids.set_rasterized(False)
    cb.set_label("Source-to-module main-reading difference (mV)", labelpad=4)
    delta_ax = fig.add_axes([positions[2].x0 + .01, .168, positions[2].width - .02, .018])
    dcb = fig.colorbar(images[2], cax=delta_ax, orientation="horizontal", ticks=delta_ticks,
                      format=FuncFormatter(lambda value, _: f"{value:+g}" if value != 0 else "0"))
    dcb.solids.set_rasterized(False)
    dcb.set_label("Change in voltage drop (mV)", labelpad=4)
    fig.text(.5, .087, "Change = recorded loaded − zero: + increase, − decrease, 0 unchanged; descriptive, not a controlled causal effect.", ha="center", fontsize=6.6)
    fig.text(.5, .064, "* Selected point retest. All differences use retained source voltages.", ha="center", fontsize=6.6)
    return export(fig, OUTPUT, "module_voltage_drop", "Zero-load and recorded loaded voltage drops for all combinations, with 32 signed loaded-minus-zero module comparisons.",
                  {"cells": "1000 × (retained source main V − selected module main V). Cross-record differences, not synchronous drops.",
                   "panels": "(a) ZERO, (b) loaded/MAX, (c) loaded/MAX minus ZERO for the same physical combination and module.",
                   "change_formula": "delta_drop_mV = drop_MAX_mV − drop_ZERO_mV = 1000 × [(V_source_MAX − V_module_MAX) − (V_source_ZERO − V_module_ZERO)].",
                   "change_comparisons": len(changes),
                   "change_labels": "Positive increases use +; negative decreases use −; unchanged is 0. Values are differences of selected point readings, not averages.",
                   "change_inference": "Descriptive difference between separate recorded conditions; loading equivalence, timing and causal isolation are not established.",
                   "missing": "Em dash denotes a physically absent module.",
                   "range": "One shared linear data-adaptive colour scale for ZERO and MAX, using nice enclosing bounds from all 64 current branch differences.",
                   "color_scale": scale,
                   "change_color_scale": delta_scale,
                   "uncertainty": "One selected value per condition/module cell; N1 ZERO M0 voltage and photo assignment are user-confirmed."})


def main():
    global ALL_BRANCHES, ALL_RUNS
    OUTPUT.mkdir(parents=True, exist_ok=True)
    prior.INPUT = INPUT
    prior.export = export
    old.export = export
    runs, branches, predictions = prior.normalized_data()
    ALL_RUNS, ALL_BRANCHES = runs, branches
    assert sum(key(b) in TARGETS for b in branches) == 7
    confirmed, = [b for b in branches if key(b) == ("M0", "ZERO", "M0")]
    assert confirmed["V_recorded_V"] == 3.252 and confirmed["drop_recorded_mV"] == 28
    corrected, = [b for b in branches if key(b) == ("M0-M1", "ZERO", "M0")]
    assert corrected["V_recorded_V"] == 3.251 and corrected["drop_recorded_mV"] == 30
    legacy = json.loads(prior.LEGACY.read_text(encoding="utf-8-sig"))
    blocked = [r for r in legacy["runs"] if r["N"] == 1 and r["frequency_hz"] == 200 and r["protocol_mode"] == "FULL"
               and r["load"] == "ZERO" and r["state"] == old.BLOCKED]
    assert len(blocked) == 4
    with plt.style.context(STYLE), matplotlib.rc_context(PUBLICATION_STYLE):
        matplotlib.rcParams.update({"svg.hashsalt": "eskin-latest-m0-preview-20260907", "font.size": 8.5,
                                    "axes.labelsize": 8.5, "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 7.2})
        figures = [plot_scaling(runs), plot_voltage(runs, branches), plot_drop(runs, branches),
                   old.plot_screening(blocked + runs, OUTPUT), old.plot_branches(branches, OUTPUT),
                   old.plot_temperature(runs, branches, OUTPUT), prior.plot_prediction(predictions, OUTPUT)]
    prediction = next(entry for entry in figures if entry["stem"] == "independent_current_prediction")
    prediction["semantics"]["points"] = "22 comparisons: 11 physical multi-module combinations per recorded load; newest M0 N1 references used. No added complete condition repeats."
    inputs = [INPUT / name for name in ("configuration_summary.csv", "branch_readings.csv", "additivity_checks.csv", "group_summary.csv")]
    inputs += [Path(__file__), Path(prior.__file__), Path(old.__file__), STYLE, prior.LEGACY,
               Path(__file__).with_name("power_m0_preview_heatmap_scale_20260907.py")]
    manifest = {"status": "Preview, not published report", "report_modified_by_script": False,
                "source_directory": str(INPUT), "counts": {"compiled_conditions": 30, "selected_branches": 64,
                "combination_counts_per_load_by_N": [4, 6, 4, 1], "selected_targeted_current_retests": 7,
                "additional_full_condition_repeats": 0},
                "inputs": [{"path": str(path), "sha256": digest(path)} for path in inputs],
                "versions": {"matplotlib": matplotlib.__version__, "numpy": np.__version__},
                "figures": figures}
    (OUTPUT / "base_figure_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"figures": len(figures), "output": str(OUTPUT), "report_modified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
