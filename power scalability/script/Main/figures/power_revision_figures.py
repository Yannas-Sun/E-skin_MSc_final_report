"""Reproducible figures for the measured Power revision (report 2.1).

Read only DATA/reference/analysis_v2_1/analysis_summary.json.  No raw measurement is changed.
Combination means are descriptive; no repeat SD or capacity extrapolation is
inferred.  Copying into the report is an explicit, separate command-line action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PathCollection
from matplotlib.lines import Line2D
from matplotlib.ticker import FormatStrFormatter
import numpy as np

ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if parent.name == "power scalability" and (parent / "DATA").is_dir()
)
FINAL = ROOT.parent
sys.path.insert(0, str(FINAL))
from figure_style import (DARK_CHARCOAL, DEEP_TEAL, GRID, PUBLICATION_STYLE,
                         TEAL_CYAN, SLATE_BLUE, MINT_GREEN, figure_47_drop_cmap)

DEFAULT_INPUT = ROOT / "DATA" / "reference" / "analysis_v2_1" / "analysis_summary.json"
REPORT_FIGURES = FINAL / "Imperial College Individual Project Template_LaTeX" / "figures" / "power"
STYLE = Path(__file__).with_name("power_report.mplstyle")
CONTINUOUS = "CONTINUOUS_USB_READ"
BLOCKED = "BLOCKED_STANDBY_NO_CONTINUOUS_USB_READ"
LOADS = ("ZERO", "MAX")
COLORS = {"ZERO": TEAL_CYAN, "MAX": DEEP_TEAL}
MARKERS = {"ZERO": "o", "MAX": "s"}
LABELS = {"ZERO": "Zero load", "MAX": "Loaded (recorded)"}
MODULES = ("M0", "M1", "M2", "M3")
WIDTH = 180 / 25.4


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite(value):
    return value is not None and math.isfinite(float(value))


def selected(row):
    return (row["state"] == CONTINUOUS and int(row["frequency_hz"]) == 200
            and row["protocol_mode"] == "FULL" and row["load"] in LOADS)


def canvas(*, rows=1, columns=1, height=108, top=.85, bottom=.17,
           left=.11, right=.96, wspace=.34, hspace=.65):
    fig, axes = plt.subplots(rows, columns, figsize=(WIDTH, height / 25.4),
                             squeeze=False)
    fig.subplots_adjust(left=left, right=right, bottom=bottom, top=top,
                        wspace=wspace, hspace=hspace)
    for ax in axes.flat:
        ax.grid(axis="y", color=GRID, lw=.55)
        ax.tick_params(pad=4)
        ax.xaxis.labelpad = 6
        ax.yaxis.labelpad = 6
    return fig, axes


def load_handles():
    return [Line2D([], [], ls="none", marker=MARKERS[k], color=COLORS[k],
                   markeredgecolor=DARK_CHARCOAL, markeredgewidth=.4,
                   label=LABELS[k]) for k in LOADS]


def legend(fig, handles, columns=None, y=.985):
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.53, y),
               ncol=columns or len(handles), handlelength=1.6,
               columnspacing=1.45, handletextpad=.5, borderaxespad=0)


def count_axis(ax):
    ax.set(xticks=(1, 2, 3, 4), xlim=(.65, 4.35), xlabel="Module count, N")


def panel_label(ax, label):
    ax.text(0, 1.045, label, transform=ax.transAxes, ha="left", va="bottom",
            weight="semibold", fontsize=9)


def export(fig, out, stem, description, semantics):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    outside = []
    scatter_count = 0
    for ax in fig.axes:
        xlo, xhi = sorted(ax.get_xlim())
        ylo, yhi = sorted(ax.get_ylim())
        for collection in ax.collections:
            if not isinstance(collection, PathCollection):
                continue
            points = np.asarray(collection.get_offsets(), dtype=float)
            scatter_count += len(points)
            if len(points) and (np.any(points[:,0] < xlo) or np.any(points[:,0] > xhi)
                                or np.any(points[:,1] < ylo) or np.any(points[:,1] > yhi)):
                raise ValueError(f"Measured scatter point outside axes in {stem}: {points.tolist()}")
    for artist in fig.findobj(matplotlib.text.Text):
        if not artist.get_visible() or not artist.get_text().strip():
            continue
        ext = artist.get_window_extent(renderer)
        if (ext.x0 < fig.bbox.x0-1 or ext.x1 > fig.bbox.x1+1
                or ext.y0 < fig.bbox.y0-1 or ext.y1 > fig.bbox.y1+1):
            outside.append(artist.get_text())
    if outside:
        raise ValueError(f"Outside canvas in {stem}: {outside}")
    files = []
    for suffix in ("pdf", "png", "svg"):
        path = out / f"{stem}.{suffix}"
        meta = {"Title": stem.replace("_", " "), "Creator": Path(__file__).name}
        if suffix == "pdf":
            meta.update(Subject=description, CreationDate=None, ModDate=None)
        elif suffix == "svg":
            meta.update(Description=description, Date=None)
        else:
            meta["Description"] = description
        fig.savefig(path, dpi=300, bbox_inches=None, metadata=meta)
        files.append({"name": path.name, "sha256": digest(path),
                      "bytes": path.stat().st_size})
    dimensions = [round(v * 25.4, 3) for v in fig.get_size_inches()]
    plt.close(fig)
    return {"stem": stem, "description": description, "semantics": semantics,
            "dimensions_mm": dimensions, "text_outside_canvas": outside,
            "scatter_points_count": scatter_count,
            "scatter_points_outside_axes": 0,
            "files": files}


def plot_scaling(runs, out):
    fig, axes = canvas(columns=2, height=106, top=.84, bottom=.18, wspace=.36)
    for ax, field, ylabel, tag in (
            (axes[0, 0], "I_sum_mA", "Recorded branch-current sum (mA)", "(a) Current"),
            (axes[0, 1], "P_output_est_mW", "Estimated source-output power (mW)", "(b) Output power")):
        for load in LOADS:
            group_means = []
            for n in range(1, 5):
                group = sorted((r for r in runs if r["load"] == load and r["N"] == n),
                               key=lambda r: r["combo"])
                offset = -.105 if load == "ZERO" else .105
                spread = np.linspace(-.065, .065, len(group)) if len(group)>1 else np.array([0.])
                yy = [r[field] for r in group]
                ax.scatter(n + offset + spread, yy, color=COLORS[load], marker=MARKERS[load],
                           s=27, edgecolors=DARK_CHARCOAL, linewidths=.35, zorder=4)
                group_means.append(float(np.mean(yy)))
            # Dashed segments connect descriptive means only, not a fitted model.
            xx = np.arange(1, 5) + (-.105 if load == "ZERO" else .105)
            ax.plot(xx, group_means, color=COLORS[load], ls=(0, (3, 3)), lw=1,
                    marker="D", ms=5.3, mfc="white", mec=COLORS[load], zorder=3)
            ax.annotate(f"{group_means[-1]:.3f}" if field == "I_sum_mA" else f"{group_means[-1]:.2f}",
                        (xx[-1], group_means[-1]), xytext=(-5, -14 if load == "ZERO" else 8),
                        textcoords="offset points", ha="right", fontsize=7.7, color=COLORS[load],
                        bbox={"facecolor":"white", "edgecolor":"none", "pad":.6})
        count_axis(ax)
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, max(r[field] for r in runs)*1.18)
        panel_label(ax, tag)
    legend(fig, load_handles() + [Line2D([], [], color=DARK_CHARCOAL, ls="--", marker="D",
                                       mfc="white", ms=5, lw=1, label="Combination mean")])
    return export(fig, out, "current_power_scaling",
                  "Current and estimated source-output power for all 18 continuous-read records; separate zero and recorded loaded conditions.",
                  {"points": "One R1 record per exact module combination and load.",
                   "means": "Arithmetic mean across different recorded module combinations at a given N, not repeats. Counts per load: 4, 2, 2, 1.",
                   "power": "Recorded source voltage multiplied by the sum of sequential branch-current main readings.",
                   "lines": "Descriptive mean connectors; no model fit or extrapolation.",
                   "uncertainty": "No same-condition SD available; no SD or CI bars plotted."})


def plot_voltage(runs, branches, out):
    fig, axes = canvas(columns=2, height=108, top=.83, bottom=.18, wspace=.25)
    for load, ax in zip(LOADS, axes.flat):
        rr = sorted((r for r in runs if r["load"] == load), key=lambda r:(r["N"], r["combo"]))
        for n in range(1, 5):
            group = [r for r in rr if r["N"] == n]
            offsets = np.linspace(-.20, .20, len(group)) if len(group)>1 else [0.]
            for row, offset in zip(group, offsets):
                xx = n + offset
                ax.scatter(xx, row["V_source_recorded_V"], marker="^", color=SLATE_BLUE,
                           s=25, zorder=5)
                bb = [b for b in branches if b["run_id"] == row["run_id"]]
                local = np.linspace(-.045, .045, len(bb)) if len(bb)>1 else [0.]
                for branch, jj in zip(bb, local):
                    if finite(branch.get("V_min_recorded_V")) and finite(branch.get("V_max_recorded_V")):
                        ymin, ymax = branch["V_min_recorded_V"], branch["V_max_recorded_V"]
                        ax.vlines(xx+jj, ymin, ymax, color=COLORS[load], lw=.8, zorder=2)
                        ax.hlines([ymin, ymax], xx+jj-.018, xx+jj+.018, color=COLORS[load], lw=.8, zorder=2)
                    ax.scatter(xx+jj, branch["V_recorded_V"], marker="o", s=17,
                               color=COLORS[load], edgecolors=DARK_CHARCOAL, linewidth=.3, zorder=4)
        ax.axhline(3.135, color=DEEP_TEAL, ls=(0,(4,3)), lw=.9)
        ax.axhline(3.3, color=SLATE_BLUE, ls=":", lw=.75)
        ax.text(.74, 3.139, "3.135 V lower guideline", fontsize=7.2, color=DEEP_TEAL)
        count_axis(ax)
        ax.set(ylim=(3.115, 3.315), ylabel="Recorded voltage (V)")
        ax.set_yticks([3.15, 3.20, 3.25, 3.30])
        ax.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
        panel_label(ax, LABELS[load])
    legend(fig, [Line2D([], [], marker="^", color=SLATE_BLUE, ls="none", label="Source main reading"),
                 Line2D([], [], marker="o", color=DARK_CHARCOAL, ls="none", label="Module main reading"),
                 Line2D([], [], marker="_", color=DARK_CHARCOAL, lw=.8, label="Module DMM MIN–MAX")], columns=3)
    return export(fig, out, "voltage_scaling",
                  "Recorded source and module voltages in separate zero-load and loaded panels. Thin vertical intervals are instrument MIN–MAX records, not repeat variability.",
                  {"points": "All available source and active-module main readings at 200 Hz FULL continuous USB read.",
                   "intervals": "Instrument MIN and MAX plotted directly; not SD, CI, synchronized extrema, or guaranteed transient bounds.",
                   "guidelines": "3.135 V project lower guideline and 3.3 V nominal reference; not component certification.",
                   "jitter": "Horizontal offsets separate physical combinations and modules; N is integer."})


def plot_drop(runs, branches, out):
    combos = sorted({(r["N"],r["combo"]) for r in runs})
    fig, axes = canvas(columns=2, height=119, top=.87, bottom=.24, left=.20, right=.96, wspace=.20)
    vmax = math.ceil(max(b["drop_recorded_mV"] for b in branches) / 10)*10
    cmap = figure_47_drop_cmap()
    cmap.set_bad("#F2F1EF")
    im = None
    for load, ax in zip(LOADS, axes.flat):
        matrix = np.full((len(combos),4), np.nan)
        for b in branches:
            if b["load"] == load:
                matrix[combos.index((b["N"], b["combo"])), MODULES.index(b["module_id"])] = b["drop_recorded_mV"]
        im = ax.imshow(np.ma.masked_invalid(matrix), vmin=0, vmax=vmax, cmap=cmap, aspect="auto")
        for iy in range(len(combos)):
            for ix in range(4):
                value = matrix[iy,ix]
                ax.text(ix, iy, f"{value:.0f}" if np.isfinite(value) else "—", ha="center", va="center",
                        fontsize=8, color="white" if np.isfinite(value) and value>vmax*.60 else DARK_CHARCOAL)
        ax.set_xticks(range(4), MODULES)
        ax.set_yticks(range(len(combos)), [f"N={n}: {combo}" for n,combo in combos])
        ax.tick_params(axis="both", length=0)
        ax.grid(False)
        for spine in ax.spines.values(): spine.set_visible(False)
        if load == "MAX": ax.set_yticklabels([])
        panel_label(ax, LABELS[load])
    color_ax = fig.add_axes([.32,.115,.53,.027])
    cb = fig.colorbar(im, cax=color_ax, orientation="horizontal")
    cb.set_label("Source-to-module voltage difference (mV)", labelpad=5)
    return export(fig, out, "module_voltage_drop",
                  "Source-to-module differences from main readings for each recorded physical combination and load. Unconnected modules are masked.",
                  {"cells": "1000 × [source main voltage − module main voltage] within each record; individual main readings are sequential.",
                   "missing": "An em dash means the physical module is absent from that configuration.",
                   "range": "Shared zero-based colour scale for both load panels.",
                   "uncertainty": "One record per cell; no repeat uncertainty estimated."})


def plot_screening(all_runs, out):
    rows = [r for r in all_runs if r["N"] == 1 and int(r["frequency_hz"]) == 200
            and r["protocol_mode"] == "FULL" and r["load"] in LOADS]
    conditions = [(BLOCKED,"ZERO", SLATE_BLUE,"^","Blocked, zero load"),
                  (CONTINUOUS,"ZERO",TEAL_CYAN,"o","Continuous, zero load"),
                  (CONTINUOUS,"MAX",DEEP_TEAL,"s","Continuous, loaded")]
    fig, axes = canvas(height=100, top=.85, bottom=.17)
    ax=axes[0,0]
    for idx,(state,load,color,marker,label) in enumerate(conditions):
        sub=[r for r in rows if r["state"]==state and r["load"]==load]
        for r in sub:
            module = r["modules"][0]
            xx = MODULES.index(module)+(idx-1)*.15
            ax.scatter(xx, r["I_sum_mA"], color=color, marker=marker, s=38,
                       edgecolors=DARK_CHARCOAL, linewidths=.4, zorder=4)
    ax.set(xticks=range(4),xticklabels=MODULES,xlim=(-.45,3.45),ylim=(0,max(r["I_sum_mA"] for r in rows)*1.18),
           xlabel="Recorded module label",ylabel="Recorded single-module current (mA)")
    legend(fig, [Line2D([],[],ls="none",marker=marker,color=color,label=label)
                 for _,_,color,marker,label in conditions])
    return export(fig,out,"single_module_screening",
                  "Separate N=1 records compare blocked zero-load current with continuously read zero-load and loaded current for each recorded module label.",
                  {"conditions": "200 Hz FULL, three selected recorded state/load conditions. Each marker is one R1 record.",
                   "module_identity": "Labels follow experiment records; physical identity across runs was not independently verified by a hardware UID.",
                   "comparison": "Historical blocked records and later continuous records are distinct measurements, not a randomized matched state intervention.",
                   "loaded": "Recorded loaded condition; loading equivalence is not established across N.",
                   "exclusions": "100 Hz and blocked loaded screening rows are not used in this state comparison."})


def plot_branches(branches,out):
    fig,axes=canvas(rows=2,columns=2,height=135,top=.88,bottom=.12,left=.11,wspace=.28,hspace=.64)
    lower=math.floor(min(b["I_recorded_mA"] for b in branches)*2)/2-.15
    upper=math.ceil(max(b["I_recorded_mA"] for b in branches)*2)/2+.15
    for module,ax in zip(MODULES,axes.flat):
        for load in LOADS:
            for n in range(1,5):
                rr=sorted((r for r in branches if r["module_id"]==module and r["load"]==load and r["N"]==n),key=lambda r:r["combo"])
                spread=np.linspace(-.045,.045,len(rr)) if len(rr)>1 else np.array([0.])
                xx=n+(-.10 if load=="ZERO" else .10)+spread
                ax.scatter(xx,[r["I_recorded_mA"] for r in rr],color=COLORS[load],marker=MARKERS[load],s=28,
                           edgecolors=DARK_CHARCOAL,linewidths=.4,zorder=4)
        count_axis(ax)
        ax.set_ylabel("Branch main current (mA)")
        ax.set_ylim(lower,upper)
        panel_label(ax,module)
    legend(fig,load_handles())
    return export(fig,out,"branch_current_balance",
                  "Recorded branch main currents by physical module, module count and load, retaining every measured module combination.",
                  {"points": "One branch main reading per active physical module, run and load.",
                   "comparison": "Same-module differences across recorded configurations are descriptive; no independent same-configuration repeats.",
                   "jitter": "Offsets distinguish load and, where relevant, two different N=3 combinations.",
                   "lines": "No connectors or fitted lines because configurations differ."})


def temperature_records(runs,branches):
    records=[]
    fields=("T_STM32_recorded_C","T_regulator_recorded_C","T_Teensy_recorded_C")
    for r in runs:
        bb=[b for b in branches if b["run_id"]==r["run_id"]]
        row={k:r[k] for k in ("run_id","N","combo","load")}
        for field in fields:
            values=[float(b[field]) for b in bb if finite(b.get(field))]
            if not values and finite(r.get(field)): values=[float(r[field])]
            row[field]=max(values) if values else None
            # Regulator/Teensy fields duplicated onto branch rows are the same observation.
            if field != "T_STM32_recorded_C" and len(set(values))>1:
                raise ValueError(f"Conflicting {field} within run {r['run_id']}")
        records.append(row)
    return records


def plot_temperature(runs,branches,out):
    records=temperature_records(runs,branches)
    fig,axes=canvas(columns=3,height=99,top=.83,bottom=.18,left=.09,right=.97,wspace=.27)
    for ax,field,label in zip(axes.flat,("T_STM32_recorded_C","T_regulator_recorded_C","T_Teensy_recorded_C"),
                             ("STM32 (highest recorded)","Regulator","Teensy")):
        values=[]
        for load in LOADS:
            for n in range(1,5):
                rr=sorted((r for r in records if r["load"]==load and r["N"]==n and finite(r[field])),key=lambda r:r["combo"])
                if not rr: continue
                xx=n+(-.10 if load=="ZERO" else .10)+(np.linspace(-.06,.06,len(rr)) if len(rr)>1 else np.array([0.]))
                yy=[r[field] for r in rr]
                values.extend(yy)
                ax.scatter(xx,yy,color=COLORS[load],marker=MARKERS[load],s=24,edgecolors=DARK_CHARCOAL,linewidths=.35,zorder=4)
        count_axis(ax)
        panel_label(ax,label)
        ax.set_ylabel("Recorded temperature (°C)" if ax is axes[0,0] else "")
        if values: ax.set_ylim(math.floor(min(values)-1), math.ceil(max(values)+1))
        else: ax.text(.5,.5,"Not recorded",transform=ax.transAxes,ha="center")
    legend(fig,load_handles())
    return export(fig,out,"temperature_scaling",
                  "Available absolute temperature observations during continuous USB reads, separated by component and load; no thermal-equilibrium inference.",
                  {"STM32": "Highest available identified STM32 reading in each run, not a guarantee that every module was measured.",
                   "regulator_and_host": "One recorded observation per run; identical values repeated in branch rows are deduplicated.",
                   "missing": "Missing temperature values are omitted, never imputed.",
                   "limitations": "Different observation timing and unverified stabilization prevent a claim of thermal equilibrium, ambient-normalized rise, or thermal capacity."})


def plot_prediction(predictions,out):
    rows=sorted((r for r in predictions if selected(r) and r["load"]=="ZERO" and r["N"]>1),key=lambda r:(r["N"],r["combo"]))
    if len(rows)!=5: raise ValueError(f"Expected five ZERO predictions, got {len(rows)}")
    fig,axes=canvas(columns=2,height=110,top=.87,bottom=.18,left=.10,right=.97,wspace=.70)
    left,right=axes[0]
    lower=min(min(r["observed_I_mA"],r["predicted_I_mA"]) for r in rows)-3
    upper=max(max(r["observed_I_mA"],r["predicted_I_mA"]) for r in rows)+3
    left.plot([lower,upper],[lower,upper],ls="--",color=SLATE_BLUE,lw=1,label="Equality")
    for r in rows:
        left.scatter(r["predicted_I_mA"],r["observed_I_mA"],marker={2:"o",3:"s",4:"^"}[r["N"]],
                     color=TEAL_CYAN,s=36,edgecolors=DARK_CHARCOAL,linewidths=.4,zorder=4)
    left.set(xlim=(lower,upper),ylim=(lower,upper),xlabel="Independent prediction (mA)",ylabel="Multi-module record (mA)")
    left.set_aspect("equal",adjustable="box")
    left.legend(loc="upper left",fontsize=7.5)
    yy=np.arange(len(rows))
    right.barh(yy,[r["residual_percent"] for r in rows],color=TEAL_CYAN,height=.55,edgecolor=DARK_CHARCOAL,linewidth=.4)
    right.axvline(0,color=DARK_CHARCOAL,lw=.75)
    right.set(yticks=yy,yticklabels=[r["combo"] for r in rows],xlabel="Signed relative residual (%)")
    right.invert_yaxis()
    right.grid(axis="y",visible=False)
    right.grid(axis="x",color=GRID,lw=.55)
    right.set_xlim(min(r["residual_percent"] for r in rows)*1.32,.08)
    right.set_xticks([-1.5, -1.0, -.5, 0])
    for y,r in zip(yy,rows):
        right.text(r["residual_percent"]-.04,y,f"{r['residual_percent']:.2f}",ha="right",va="center",fontsize=7.5)
    panel_label(left,"(a) Zero-load prediction")
    panel_label(right,"(b) Prediction residual")
    return export(fig,out,"independent_current_prediction",
                  "Independent zero-load single-module current sums predict five multi-module records; residual equals (observed minus predicted) divided by predicted.",
                  {"prediction": "Sum of separate N=1 main current readings for precisely the physical modules present in the multi-module combination.",
                   "points": "Five distinct multi-module configurations, R1 per configuration; not five repeats of one condition.",
                   "residual": "100 × (multi-module branch-current sum − independent prediction) / independent prediction.",
                   "limitations": "Descriptive agreement without instrument uncertainty or repeatability estimate; loaded predictions excluded because loading equivalence is unconfirmed."})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,default=DEFAULT_INPUT)
    parser.add_argument("--output-dir",type=Path)
    parser.add_argument("--copy-to-report",action="store_true",
                        help="Copy these seven generated figures after their visual review.")
    args=parser.parse_args()
    source=args.input.resolve()
    out=(args.output_dir or source.parent/"figures").resolve()
    data=json.loads(source.read_text(encoding="utf-8-sig"))
    runs=[r for r in data["runs"] if selected(r)]
    if len(runs)!=18: raise ValueError(f"Expected 18 continuous FULL 200 Hz records, got {len(runs)}")
    run_ids={r["run_id"] for r in runs}
    branches=[b for b in data["branches"] if b["run_id"] in run_ids]
    for load in LOADS:
        counts=[sum(r["load"]==load and r["N"]==n for r in runs) for n in range(1,5)]
        if counts != [4,2,2,1]: raise ValueError((load,counts))
    out.mkdir(parents=True,exist_ok=True)
    with plt.style.context(STYLE), matplotlib.rc_context(PUBLICATION_STYLE):
        matplotlib.rcParams.update({"svg.hashsalt":"eskin-power-report-2.1", "font.size":8.5,
                                    "axes.labelsize":8.5,"xtick.labelsize":8,"ytick.labelsize":8,
                                    "legend.fontsize":7.5})
        figures=[plot_scaling(runs,out),plot_voltage(runs,branches,out),plot_drop(runs,branches,out),
                 plot_screening(data["runs"],out),plot_branches(branches,out),plot_temperature(runs,branches,out),
                 plot_prediction(data["predictions"],out)]
    manifest={"report_version":"2.1","source_json":str(source),"source_sha256":digest(source),
              "script_sha256":digest(__file__),"style_sha256":digest(STYLE),
              "shared_style_sha256":digest(FINAL/"figure_style.py"),
              "versions":{"python":sys.version.split()[0],"matplotlib":matplotlib.__version__,"numpy":np.__version__},
              "inclusion":"18 measured FULL 200 Hz continuous USB read records; old N=1 blocked zero records only in screening.",
              "provenance":data.get("provenance",{}),"figures":figures}
    manifest_path=out/"figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    if args.copy_to_report:
        REPORT_FIGURES.mkdir(parents=True,exist_ok=True)
        for entry in figures:
            for file in entry["files"]:
                target=REPORT_FIGURES/file["name"]
                shutil.copy2(out/file["name"],target)
                if digest(target)!=file["sha256"]: raise IOError(f"Copy mismatch: {target}")
        shutil.copy2(manifest_path,REPORT_FIGURES/"figure_manifest_v2_1.json")
    print(json.dumps({"figures":len(figures),"output":str(out),"copy_to_report":args.copy_to_report,
                      "manifest":str(manifest_path)},ensure_ascii=False))


if __name__=="__main__":
    main()
