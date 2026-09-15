"""Report styling only: no modification of raw data or statistical estimators.

All figures use a 180 mm page width, English labels, explicit sample/measurement
notes, and redundant color/marker encodings. PNG, PDF and SVG share one canvas.
The style is adapted from the scientific-visualization skill's publication asset.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import FormatStrFormatter, MultipleLocator
import numpy as np


FINAL_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(FINAL_DIR))
from figure_style import (  # noqa: E402
    DARK_CHARCOAL,
    DEEP_TEAL,
    GRID as PALETTE_GRID,
    MINT_GREEN,
    MUTED_LAVENDER,
    PALE_LAVENDER,
    PALE_MINT,
    PALE_TEAL,
    PUBLICATION_STYLE,
    SLATE_BLUE,
    TEAL_CYAN,
    figure_46_drop_cmap,
    publication_cmap,
    figure_47_drop_cmap,
)


STYLE_PATH = Path(__file__).with_name("power_report.mplstyle")
WIDTH_IN = 180 / 25.4
FORMATS = ("png", "pdf", "svg")
DPI = 300
INK = DARK_CHARCOAL
MUTED = SLATE_BLUE
GRID = PALETTE_GRID
PALE = PALE_TEAL
BLUE, ORANGE, GREEN, PURPLE = (TEAL_CYAN, DEEP_TEAL, SLATE_BLUE, MINT_GREEN)
MODULES = ("Module0", "Module1", "Module2", "Module3")
MODULE_COLORS = dict(zip(MODULES, (BLUE, ORANGE, GREEN, PURPLE)))
MODULE_MARKERS = dict(zip(MODULES, ("o", "s", "^", "D")))
COUNTS = (1, 2, 3, 4)
LOW_V, HIGH_V = 3.3 * 0.95, 3.3 * 1.05
SAMPLE_NOTE = "N=1: four independent module references. N=2: two module combinations (M0+M1 and M2+M3). N=3: two module combinations (M0+M1+M2 and M1+M2+M3). N=4: one run (R1)."
LOWEST_MODULE_COLOR = DARK_CHARCOAL


def _canvas(title: str, subtitle: str, *, height_mm: float = 118, columns: int = 1,
            rows: int = 1, bottom: float = 0.16, top: float = 0.92):
    fig, axes = plt.subplots(rows, columns, figsize=(WIDTH_IN, height_mm / 25.4),
                             squeeze=False)
    # Clean report artwork: no visible figure title, subtitle, rule, or footer.
    # The explanatory material is carried by the LaTeX caption instead.
    # Do not combine this explicit layout with tight_layout or bbox_inches='tight'.
    fig.subplots_adjust(left=0.105, right=0.96, bottom=bottom, top=top,
                        wspace=0.30 if columns == 2 else 0.32, hspace=0.55)
    for ax in axes.flat:
        ax.grid(axis="y", color=GRID, lw=0.55)
        ax.tick_params(pad=4)
        ax.xaxis.labelpad = 7
        ax.yaxis.labelpad = 7
    return fig, axes


def _legend(fig, handles, *, y: float = 0.98, columns: int | None = None) -> None:
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.055, y),
               borderaxespad=0, ncol=columns or len(handles), handlelength=2.0,
               handletextpad=0.55, columnspacing=1.7)


def _module_legend():
    return [Line2D([], [], ls="none", marker=MODULE_MARKERS[m], color=MODULE_COLORS[m],
                   markeredgecolor=INK, markeredgewidth=0.4, markersize=5,
                   label=m.replace("Module", "Module ")) for m in MODULES]


def _point_label(ax, x, y, text, *, offset=(0, 7), ha="center", va="bottom", color=INK):
    ax.annotate(text, (x, y), xytext=offset, textcoords="offset points",
                ha=ha, va=va, color=color, fontsize=7.5,
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.7})


def _export(fig, path: Path, *, title: str, description: str,
            semantics: dict[str, Any]) -> dict[str, Any]:
    """Explicitly overwrite generated artwork only, preserving exact canvas size."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas_box = fig.bbox
    outside = []
    for artist in fig.findobj(matplotlib.text.Text):
        if not artist.get_visible() or not artist.get_text().strip():
            continue
        extent = artist.get_window_extent(renderer)
        if (extent.x0 < canvas_box.x0 - 1 or extent.x1 > canvas_box.x1 + 1
                or extent.y0 < canvas_box.y0 - 1 or extent.y1 > canvas_box.y1 + 1):
            outside.append(artist.get_text())
    if outside:
        raise ValueError(f"Text outside canvas in {path.name}: {outside}")
    files = []
    for format_name in FORMATS:
        target = path.with_suffix(f".{format_name}")
        metadata = {"Title": title, "Creator": "E-SKIN power_figures.py"}
        if format_name == "pdf":
            metadata["Subject"] = description
        else:
            metadata["Description"] = description
        fig.savefig(target, format=format_name, dpi=DPI, bbox_inches=None,
                    facecolor="white", transparent=False, metadata=metadata)
        files.append({"name": target.name, "bytes": target.stat().st_size,
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    dimensions = [round(float(v) * 25.4, 3) for v in fig.get_size_inches()]
    plt.close(fig)
    return {"stem": path.stem, "title": title, "alt_text": description,
            "dimensions_mm": dimensions, "dpi": DPI, "formats": files,
            "semantics": semantics, "text_outside_canvas": outside}


def plot_current_power(path, scaling, fits):
    x = np.asarray([row["module_count"] for row in scaling], dtype=float)
    fig, axes = _canvas("Current and power scaling",
                        "200 Hz  |  FULL  |  ZERO load  |  external module supply only",
                        height_mm=115, columns=2, bottom=0.18, top=0.88)
    panels = [
        (axes[0, 0], "I_total_avg_mA", "current", BLUE, "Current (mA)", 80),
        (axes[0, 1], "source_power_mW", "power", GREEN, "Power (mW)", 250),
    ]
    for ax, field, fit_key, color, ylabel, ymax in panels:
        y = np.asarray([row[field] for row in scaling], dtype=float)
        fit = fits[fit_key]
        # Model-only area is not represented as additional experimental observations.
        ax.axvspan(4.0, 8.25, color=PALE, zorder=0)
        ax.axvline(4, color=GRID, lw=0.75, ls=(0, (3, 3)))
        observed_x = np.linspace(1, 4, 40)
        extrapolated_x = np.linspace(4, 8, 60)
        ax.plot(observed_x, fit["slope"] * observed_x + fit["intercept"], color=INK,
                lw=1.1, zorder=2)
        ax.plot(extrapolated_x, fit["slope"] * extrapolated_x + fit["intercept"],
                color=INK, lw=1.1, ls=(0, (4, 3)), zorder=2)
        ax.scatter(x, y, c=color, s=29, marker="o", edgecolors="white", linewidths=0.6,
                   zorder=5)
        if fit_key == "current":
            for row in scaling:
                sd = row["I_total_std_mA"]
                # Missing repeat uncertainty remains missing, not a zero-length error bar.
                if sd is not None:
                    ax.errorbar(row["module_count"], row[field], yerr=sd, fmt="none",
                                ecolor=color, capsize=3, lw=1, zorder=4)
        for xx, yy in zip(x, y):
            _point_label(ax, xx, yy, f"{yy:.3f}", offset=(0, 8), color=color)
        ax.set(xlabel="Module count, N", ylabel=ylabel,
               xlim=(0.65, 8.25), ylim=(0, ymax), xticks=(1, 2, 3, 4, 6, 8))
        if fit_key == "power":
            ax.set_yticks(np.arange(0, ymax + 1, 50))
    _legend(fig, [Line2D([], [], ls="none", marker="o", color=BLUE, label="Recorded / aggregated"),
                  Line2D([], [], color=INK, lw=1.1, label="Fit: N=1-4"),
                  Line2D([], [], color=INK, lw=1.1, ls="--", label="Extrapolation: N>4")])
    return _export(fig, path, title="Current and power scaling",
                   description="Current and output power rise across N=1-4; the N=2 point aggregates M0+M1 and M2+M3, the N=3 point aggregates M0+M1+M2 and M1+M2+M3, and the N=4 point uses the new record. Dashed lines to N=8 are unvalidated extrapolations.",
                   semantics={"aggregation": "Unchanged power_scaling.csv estimators and fits.",
                              "uncertainty": "N=1 current: sample SD across four distinct module references, not repeatability or CI. N=2-4: no same-combination repeat uncertainty available; N=2 and N=3 aggregate different module combinations.",
                              "model": "Solid least-squares fit at N=1-4; dashed extrapolation N=4-8."})


def plot_voltage_scaling(path, scaling):
    fig, axes = _canvas("Supply voltage and operating margin",
                        "200 Hz  |  FULL  |  ZERO load  |  lowest module readings at each N",
                        height_mm=112, bottom=0.17, top=0.90)
    ax = axes[0, 0]
    x = [r["module_count"] for r in scaling]
    ax.axhspan(LOW_V, HIGH_V, color=TEAL_CYAN, alpha=0.16, zorder=0)
    for threshold in (LOW_V, HIGH_V):
        ax.axhline(threshold, color=DEEP_TEAL, ls=(0, (4, 3)), lw=1.1)
    ax.axhline(3.3, color=SLATE_BLUE, lw=0.8, ls=":")
    # Direct comparison: observed source mean is teal, while the worst-case
    # module mean uses slate blue for stronger separation from the source.
    styles = [("V_source_avg_V", "Source mean", MINT_GREEN, "o", "-"),
              ("worst_module_avg_V", "Lowest module mean", LOWEST_MODULE_COLOR, "s", "--")]
    for field, label, color, marker, linestyle in styles:
        ax.plot(x, [r[field] for r in scaling], color=color, marker=marker, ls=linestyle,
                markersize=5, lw=1.3, label=label, markeredgecolor="white", markeredgewidth=0.45)
    for row in scaling:
        xx = row["module_count"]
        _point_label(ax, xx, row["V_source_avg_V"], f"{row['V_source_avg_V']:.3f} V",
                     offset=(0, 8), color=MINT_GREEN)
        module_id = row.get("worst_module_id") or "Module?"
        module_label = module_id.replace("Module", "M")
        _point_label(ax, xx, row["worst_module_avg_V"],
                     f"{module_label}: {row['worst_module_avg_V']:.3f} V",
                     offset=(0, -10), va="top", color=LOWEST_MODULE_COLOR)
    _legend(fig, [Line2D([], [], color=c, marker=m, ls=ls, label=l)
                  for _, l, c, m, ls in styles])
    ax.set(xlabel="Module count, N", ylabel="Voltage (V)", xticks=x,
           xlim=(0.85, 4.55), ylim=(3.11, 3.49))
    ax.yaxis.set_major_locator(MultipleLocator(0.05))
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.text(1.00, HIGH_V + 0.007, "3.465", fontsize=7.5, color=DEEP_TEAL)
    ax.text(1.00, LOW_V + 0.009, "3.135", fontsize=7.5, color=DEEP_TEAL)
    ax.text(4.5, 3.305, "3.3 V nominal", ha="right", fontsize=7, color=MUTED)
    last = scaling[-1]
    headroom = (last["worst_module_min_V"] - LOW_V) * 1000
    # Every measured point already has a direct label; this call adds only the
    # N=4 minimum and headroom context, not a duplicate mean label.
    ax.annotate(f"{last.get('worst_module_id', 'Module?').replace('Module', 'M')} min: {last['worst_module_min_V']:.3f} V\n+{headroom:.0f} mV headroom",
                xy=(4, last["worst_module_avg_V"]), xytext=(2.45, 3.17),
                fontsize=7.8, color=INK, ha="left", va="center",
                arrowprops={"arrowstyle": "-", "color": INK, "lw": 0.8},
                bbox={"facecolor": "white", "edgecolor": GRID, "pad": 4})
    return _export(fig, path, title="Voltage margin",
                   description="Full 3.135-3.465 V design band shown. Source mean is 3.278 V at N=4; the lowest module minimum is 3.259 V, 124 mV above the lower limit.",
                   semantics={"scale": "Linear voltage axis; full +/-5% design band shown.",
                              "uncertainty": "Minimum and mean are recorded window statistics, not CIs."})


def plot_voltage_drop(path, branches):
    fig, axes = _canvas("Source-to-module voltage drop",
                        "Mean source-to-module drop  |  values in mV  |  one row per physical module",
                        height_mm=108, bottom=0.14, top=0.91)
    fig.subplots_adjust(left=0.14, right=0.88)
    ax = axes[0, 0]
    values = np.full((4, 4), np.nan)
    for i, module in enumerate(MODULES):
        for j, count in enumerate(COUNTS):
            matches = [r["voltage_drop_avg_V"] * 1000 for r in branches
                       if r["module_id"] == module and r["module_count"] == count]
            if matches:
                values[i, j] = np.mean(matches)
    observed = values[np.isfinite(values)]
    if observed.size == 0:
        raise ValueError("Figure 4.6 has no measured voltage-drop values")
    vmin = float(np.min(observed))
    vmax = float(np.max(observed))
    if vmin == vmax:
        vmax = vmin + 1.0
    cmap = figure_46_drop_cmap().with_extremes(bad=PALE_TEAL)
    image = ax.imshow(np.ma.masked_invalid(values), cmap=cmap, vmin=vmin, vmax=vmax,
                      aspect="auto", interpolation="nearest")
    ax.grid(False)
    ax.set(xticks=range(4), xticklabels=[f"N={n}" for n in COUNTS],
           yticks=range(4), yticklabels=[m.replace("Module", "Module ") for m in MODULES])
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks(np.arange(-0.5, 4), minor=True)
    ax.set_yticks(np.arange(-0.5, 4), minor=True)
    ax.grid(which="minor", color="white", lw=3)
    ax.tick_params(which="minor", length=0)
    for (i, j), value in np.ndenumerate(values):
        if np.isnan(value):
            ax.text(j, i, "—", ha="center", va="center", color=MUTED, fontsize=12)
        else:
            mapped = (value - vmin) / (vmax - vmin)
            ax.text(j, i, f"{value:.0f}", ha="center", va="center", fontsize=12,
                    weight="bold", color="white" if mapped >= 0.62 else INK)
    i, j = np.unravel_index(np.nanargmax(values), values.shape)
    ax.add_patch(Rectangle((j - 0.47, i - 0.47), 0.94, 0.94, fill=False,
                           edgecolor=INK, linewidth=1.5))
    cbar_ticks = np.array([vmin, (vmin + vmax) / 2, vmax])
    cbar = fig.colorbar(image, ax=ax, fraction=0.032, pad=0.035, ticks=cbar_ticks)
    cbar.ax.yaxis.set_major_formatter(FormatStrFormatter("%.0f"))
    cbar.set_label("Mean voltage drop (mV)", fontsize=8)
    cbar.outline.set_visible(False)
    return _export(fig, path, title="Source-to-module voltage drop",
                   description=f"Annotated 4 by 4 voltage-drop matrix. The colour scale spans the measured range of {vmin:.0f}-{vmax:.0f} mV; grey dash cells are modules absent from the run, not zeros.",
                   semantics={"normalization": f"Sequential white-to-teal scale from the measured minimum {vmin:.0f} mV to maximum {vmax:.0f} mV, linear.",
                              "missing": "Absent module-count combinations are explicitly masked; no interpolation.",
                              "aggregation": "Mean across available records per module and N; currently one each."})


def plot_branch_current(path, branches):
    fig, axes = _canvas("Per-module current across configurations",
                        "200 Hz  |  FULL  |  ZERO load  |  numbers are recorded branch means",
                        height_mm=139, columns=2, rows=2, bottom=0.14, top=0.89)
    _legend(fig, _module_legend(), y=0.98)
    for ax, count in zip(axes.flat, COUNTS):
        ax.grid(False)
        ax.grid(axis="x", color=GRID, lw=0.55)
        ax.text(0.02, 0.96, f"N={count}", transform=ax.transAxes,
                ha="left", va="top", fontsize=8.5, weight="bold", color=INK)
        ax.set(xlim=(7.76, 9.40), ylim=(3.65, -0.65), yticks=range(4),
               yticklabels=[f"M{i}" for i in range(4)], xticks=(8.0, 8.5, 9.0),
               xlabel="Branch mean (mA)")
        ax.spines["left"].set_visible(False)
        ax.tick_params(axis="y", length=0)
        for i, module in enumerate(MODULES):
            match = next((r for r in branches if r["module_id"] == module and r["module_count"] == count), None)
            if match is None:
                ax.text(8.02, i, "—", ha="left", va="center", color=MUTED, fontsize=10)
                continue
            value = match["I_module_avg_mA"]
            ax.scatter(value, i, marker=MODULE_MARKERS[module], c=MODULE_COLORS[module],
                       s=36, edgecolors=INK, linewidths=0.4, zorder=3)
            ax.annotate(f"{value:.3f}", (value, i), xytext=(7, 0), textcoords="offset points",
                        va="center", ha="left", fontsize=8, color=INK)
    return _export(fig, path, title="Per-branch average current",
                   description="Four same-scale dot panels compare branch means. Module 2 has 8.988 mA in its single-module reference; the N=4 Module 1 branch mean is 8.189 mA. Absent modules are labelled not in run.",
                   semantics={"encoding": "Dots with exact values; color and marker shape identify physical modules.",
                              "scale": "Identical focused x-axis in all panels; not a bar chart.",
                              "uncertainty": "Not estimated from one run; no fabricated error bars."})


def plot_temperature(path, scaling):
    fig, axes = _canvas("Temperature observations (preliminary)",
                        "Stabilization duration missing  |  historical temperature-field conflict unresolved",
                        height_mm=108, columns=3, bottom=0.18, top=0.89)
    styles = [("max_stm32_C", "STM32", GREEN, "o"),
              ("T_regulator_C", "LM2596", ORANGE, "s"),
              ("T_teensy_C", "Teensy", PURPLE, "^")]
    for ax, (field, label, color, marker) in zip(axes.flat, styles):
        x = np.asarray([r["module_count"] for r in scaling])
        y = np.asarray([r[field] if r[field] is not None else np.nan for r in scaling])
        ax.scatter(x, y, c=color, s=28, marker=marker, edgecolors=INK, linewidths=0.35, zorder=3)
        for xx, yy in zip(x, y):
            if np.isfinite(yy):
                _point_label(ax, xx, yy, f"{yy:.1f}", offset=(0, 7))
        ax.set(xlabel="Module count, N", xticks=COUNTS,
               xlim=(0.5, 4.5), ylim=(20, 52), yticks=(20, 25, 30, 35, 40, 45, 50))
        ax.text(0.02, 0.96, label, transform=ax.transAxes,
                ha="left", va="top", fontsize=8.5, weight="bold", color=INK)
    axes[0, 0].set_ylabel("Temperature (°C)")
    return _export(fig, path, title="Recorded temperatures",
                   description="Three same-scale point panels show recorded STM32, regulator and USB-powered Teensy temperatures. Duration is missing; no thermal scaling trend is asserted.",
                   semantics={"aggregation": "Unchanged thermal_summary.csv: N=1 max STM32 and mean regulator/Teensy.",
                              "limitation": "Durations missing and historical field conflict unresolved; no fit or connecting trend line.",
                              "scale": "Shared linear 20-52 degC range in all three panels."})


def plot_peak_upper(path, scaling):
    fig, axes = _canvas("Mean current and non-synchronous maximum sums",
                        "200 Hz  |  FULL  |  ZERO load  |  DMM readings collected separately",
                        height_mm=108, bottom=0.16, top=0.89)
    ax = axes[0, 0]
    x = np.asarray([r["module_count"] for r in scaling])
    mean = np.asarray([r["I_total_avg_mA"] for r in scaling])
    max_sum = np.asarray([r["I_peak_upper_est_mA"] for r in scaling])
    bars1 = ax.bar(x - 0.18, mean, width=0.32, color=BLUE, edgecolor=INK, linewidth=0.45)
    bars2 = ax.bar(x + 0.18, max_sum, width=0.32, color=PALE_LAVENDER, edgecolor=MUTED,
                   hatch="///", linewidth=0.6)
    ax.bar_label(bars1, labels=[f"{v:.2f}" for v in mean], padding=4, fontsize=8, color=INK)
    ax.bar_label(bars2, labels=[f"{v:.2f}" for v in max_sum], padding=4, fontsize=8, color=INK)
    ax.set(xlabel="Module count, N", ylabel="Current (mA)", xticks=COUNTS,
           xlim=(0.5, 4.5), ylim=(0, 80))
    _legend(fig, [Patch(facecolor=BLUE, edgecolor=INK, label="Mean current"),
                  Patch(facecolor=PALE_LAVENDER, edgecolor=MUTED, hatch="///", label="Separately recorded maximum sum")])
    return _export(fig, path, title="Average versus separately captured maxima",
                   description="Zero-baseline grouped bars show 32.492 mA mean and 64.22 mA sum of separately captured branch maxima at N=4. The latter is not a synchronized peak measurement.",
                   semantics={"baseline": "Both bar series start at zero.",
                              "estimator": "Unchanged I_peak_upper_est_mA; N=1 mean of four independent maximum readings.",
                              "limitation": "Non-synchronous recorded maxima do not establish a bound on unrecorded transients."})


def plot_single_module_screening(path, rows):
    fig, axes = _canvas("Frequency and load screening",
                        "Single-module checks  |  FULL protocol  |  focused y-scales, not zero-based bars",
                        height_mm=112, columns=2, bottom=0.19, top=0.88)
    conditions = ((100, "ZERO"), (200, "ZERO"), (200, "MAX"))
    x = np.arange(3)
    for module in MODULES[:2]:
        values = [[], []]
        for frequency, load in conditions:
            row = next((r for r in rows if r.get("module_ids", "").strip() == module
                        and int(r["frequency_hz"]) == frequency and r.get("load", "").strip().upper() == load), None)
            for target, field in zip(values, ("I_source_avg_mA", "V_module0_avg_V")):
                raw = None if row is None else row.get(field)
                target.append(float(raw) if raw not in (None, "") else np.nan)
        for ax, y in zip(axes.flat, values):
            ax.plot(x, y, color=MODULE_COLORS[module], marker=MODULE_MARKERS[module],
                    linestyle="-" if module == "Module0" else "--", lw=1.3,
                    markersize=5, markeredgecolor="white", markeredgewidth=0.5)
            _point_label(ax, 2, y[-1], f"{y[-1]:.3f}", offset=(0, 8))
    for ax in axes.flat:
        ax.set(xticks=x, xticklabels=["100 Hz\nZERO", "200 Hz\nZERO", "200 Hz\nMAX"], xlim=(-0.25, 2.30))
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
    axes[0, 0].set(ylabel="Current (mA)", ylim=(8.105, 8.150))
    axes[0, 0].set_yticks(np.arange(8.11, 8.151, 0.01))
    axes[0, 0].yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    axes[0, 1].set(ylabel="Voltage (V)", ylim=(3.259, 3.279))
    axes[0, 1].set_yticks(np.arange(3.26, 3.276, 0.005))
    axes[0, 1].yaxis.set_major_formatter(FormatStrFormatter("%.3f"))
    _legend(fig, [Line2D([], [], color=MODULE_COLORS[m], marker=MODULE_MARKERS[m],
                        ls="-" if m == "Module0" else "--", label=m.replace("Module", "Module ")) for m in MODULES[:2]])
    return _export(fig, path, title="Single-module screening",
                   description="Two panels show unchanged Module 0 and Module 1 recorded average currents and module voltages across 100 Hz ZERO, 200 Hz ZERO and 200 Hz MAX.",
                   semantics={"scale": "Explicit focused linear y-ranges; no offset notation, no bar-length encoding.",
                              "data": "Original three recorded conditions for Module0 and Module1; no smoothing or invented repeats."})


def build_figures(outputs, scaling, fits, branches, rows, input_path: Path):
    """Scoped style and shared export manifest; caller retains numerical analysis."""
    with plt.style.context(STYLE_PATH):
        entries = [
            plot_current_power(outputs["current_power_plot"], scaling, fits),
            plot_voltage_scaling(outputs["voltage_plot"], scaling),
            plot_voltage_drop(outputs["drop_plot"], branches),
            plot_branch_current(outputs["branch_plot"], branches),
            plot_temperature(outputs["temperature_plot"], scaling),
            plot_peak_upper(outputs["peak_plot"], scaling),
            plot_single_module_screening(outputs["screening_plot"], rows),
        ]
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_csv": str(input_path.resolve()),
        "source_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "style_sha256": hashlib.sha256(STYLE_PATH.read_bytes()).hexdigest(),
        "plot_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "versions": {"python": sys.version.split()[0], "matplotlib": matplotlib.__version__, "numpy": np.__version__},
        "destination": "General English-language report / Markdown; 180 mm wide. Target journal unspecified.",
        "source_changes": "The active N=2 M2+M3 and N=3 M1+M2+M3 records were added; the active N=4 source row uses PS01_M3DROP_A_R1; the previous N=4 backup and diagnostic rawdata archive are no longer retained.",
        "accessibility": "Okabe-Ito-derived colors plus marker shapes, text labels, hatching or separate panels. Not a compliance certification.",
        "exports": "300 dpi opaque PNG; TrueType-embedded PDF; SVG with editable (unembedded) text.",
        "figures": entries,
    }
    output = outputs["current_power_plot"].parent / "figure_manifest.json"
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output
