"""Report 2.4 voltage-drop means by N, preserving pointwise retest provenance."""
from __future__ import annotations
import argparse
import csv
import json
import math
import statistics
import shutil
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from power_revision_figures import (
    ROOT, FINAL, REPORT_FIGURES, STYLE, LOADS, COLORS, MARKERS, LABELS, MODULES,
    DARK_CHARCOAL, PUBLICATION_STYLE, GRID, canvas, panel_label,
    load_handles, legend, export, digest, figure_47_drop_cmap,
)

SOURCE = ROOT / "DATA/reference/report_v2_4_analysis"
OUTPUT = ROOT / "DATA/reference/voltage_drop_by_N_v2_4"
EXPECTED = {1: 1, 2: 3, 3: 3, 4: 1}
MEAN_CHECK = {
    "ZERO": [[45,26,32,29], [133/3,85/3,31,34],
             [106/3,82/3,95/3,29], [34,29,31,26]],
    "MAX": [[50,31,34,32], [112/3,83/3,103/3,97/3],
            [110/3,28,100/3,97/3], [36,28,33,31]],
}

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def corrected(b):
    return b["combo"] == "M0-M1-M2" and b["load"] == "ZERO" and b["module_id"] == "M0"

def corrected_m3(b):
    return b["combo"] == "M1-M2-M3" and b["load"] == "MAX" and b["module_id"] == "M3"

def collect():
    manifest = json.loads((SOURCE / "source_manifest.json").read_text(encoding="utf-8-sig"))
    for item in manifest["sources"]:
        p = ROOT / item.get("relative_path", item.get("path"))
        assert digest(p) == item["sha256"], "Changed source: " + str(p)
    branches = read_csv(SOURCE / "branch_readings.csv")
    assert len(branches) == 64
    assert len({(b["combo"], b["load"], b["module_id"]) for b in branches}) == 64
    groups = []
    for load in LOADS:
        for n in range(1, 5):
            for i, module in enumerate(MODULES):
                rows = sorted((b for b in branches if b["load"] == load
                               and int(b["module_count"]) == n and b["module_id"] == module),
                              key=lambda b: b["combo"])
                assert len(rows) == EXPECTED[n]
                vals = [Decimal(b["source_minus_module_main_mV"]) for b in rows]
                for b, value in zip(rows, vals):
                    assert value == 1000*(Decimal(b["V_source_main_V"])-Decimal(b["V_module_main_V"]))
                mean = statistics.mean(vals)
                sd = statistics.stdev(vals) if len(vals) > 1 else None
                assert math.isclose(float(mean), MEAN_CHECK[load][n-1][i], abs_tol=1e-10)
                groups.append({
                    "load": load, "N": n, "module_id": module,
                    "n_combinations_containing_module": len(rows),
                    "mean_drop_mV": str(mean), "sample_SD_across_combinations_mV": "" if sd is None else str(sd),
                    "min_drop_mV": str(min(vals)), "max_drop_mV": str(max(vals)),
                    "combination_ids": ";".join(b["combo"] for b in rows),
                    "individual_drop_mV": ";".join(str(v) for v in vals),
                    "contains_separate_M0_retest_estimate": any(corrected(b) for b in rows),
                    "contains_separate_M3_retest_estimate": any(corrected_m3(b) for b in rows),
                    "compiled_entries_per_exact_condition": 1,
                    "additional_full_configuration_repeats": 0,
                })
    return branches, groups, len(manifest["sources"])

def save_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

def semantic():
    return {
        "measurement": "1000*(source main V - accepted module main V), sequential DMM readings.",
        "estimator": "Equal-weight arithmetic mean within each recorded load, N and physical module.",
        "counts_per_module_by_N": [1,3,3,1],
        "spread": "Sample SD (ddof=1) across distinct combinations at N=2,3. No SD at N=1,4.",
        "independence": "One compiled entry per exact combination/load; targeted module retests do not add full-condition replicates. Modules and sources are shared; not independent repeat trials.",
        "correction": "ZERO N3 M0 includes 35 mV from separate 3.241 V M0 retest with retained user-confirmed source 3.276 V. Original 52 mV contact-fault difference is preserved in source event and original report, outside accepted means.",
        "loading": "MAX is the recorded load label; mass/area/distribution are not harmonised.",
        "jitter": "Deterministic horizontal separation only; all measured y values unchanged.",
        "M3_retest": "MAX N3 M3 includes 33 mV from 3.243 V targeted retest with retained, user-confirmed 3.276 V source. Original 44 mV remains in the report retest table. Connector was reinserted; cause and load matching are unconfirmed.",
        "report": "Version 2.4 figures use a separate compiled analysis; original report 2.3 and original supplementary outputs are preserved.",
    }

def heatmap(groups):
    fig, axes = canvas(columns=2, height=112, top=.83, bottom=.31, left=.15, right=.97, wspace=.23)
    for load, ax in zip(LOADS, axes.flat):
        matrix = np.array([[float(next(g for g in groups if g["load"] == load and g["N"] == n
                                      and g["module_id"] == m)["mean_drop_mV"])
                            for m in MODULES] for n in range(1,5)])
        mesh = ax.pcolormesh(np.arange(5)-.5, np.arange(5)-.5, matrix,
                            vmin=0, vmax=50, cmap=figure_47_drop_cmap(),
                            edgecolors="white", linewidth=.6, rasterized=False)
        ax.set(xlim=(-.5,3.5), ylim=(3.5,-.5), xticks=range(4), xticklabels=MODULES,
               yticks=range(4), yticklabels=[f"N = {n} (n = {EXPECTED[n]})" for n in range(1,5)])
        ax.tick_params(length=0, labelsize=8)
        ax.grid(False)
        for sp in ax.spines.values():
            sp.set_visible(False)
        if load == "MAX":
            ax.set_yticklabels([])
        for iy in range(4):
            for ix in range(4):
                label = f"{matrix[iy,ix]:.1f}"
                if load == "ZERO" and iy == 2 and ix == 0:
                    label += "*"
                if load == "MAX" and iy == 2 and ix == 3:
                    label += "†"
                ax.text(ix, iy, label, ha="center", va="center", color="#20252D", fontsize=9)
        panel_label(ax, "(a) Zero load" if load == "ZERO" else "(b) Loaded (recorded)")
    cax = fig.add_axes([.28,.21,.54,.026])
    cb = fig.colorbar(mesh, cax=cax, orientation="horizontal")
    cb.solids.set_rasterized(False)
    cb.set_label("Mean source-to-module difference (mV)", fontsize=8)
    fig.text(.15,.095,"n = combinations containing the module; one compiled value per condition.", fontsize=7.5)
    fig.text(.15,.053,"* M0 earlier retest; † M3 targeted retest. Source voltages retained.", fontsize=7.5)
    return export(fig, OUTPUT, "module_drop_mean_by_N",
                  "Mean accepted voltage drop by N and module, separately for zero and recorded load.", semantic())

def draw_points(ax, n, branches, groups):
    for load in LOADS:
        for i, module in enumerate(MODULES):
            x = i + (-.16 if load == "ZERO" else .16)
            rows = sorted((b for b in branches if b["load"] == load and int(b["module_count"]) == n
                           and b["module_id"] == module), key=lambda b:b["combo"])
            yy = [float(b["source_minus_module_main_mV"]) for b in rows]
            jitter = np.linspace(-.075,.075,len(rows)) if len(rows)>1 else np.array([0.])
            ax.scatter(x+jitter, yy, s=24, marker=MARKERS[load], color=COLORS[load],
                       edgecolors=DARK_CHARCOAL, linewidth=.4, zorder=4)
            g, = [g for g in groups if (g["load"],g["N"],g["module_id"]) == (load,n,module)]
            mean = float(g["mean_drop_mV"])
            if g["sample_SD_across_combinations_mV"]:
                ax.errorbar(x, mean, yerr=float(g["sample_SD_across_combinations_mV"]),
                            fmt="D", mfc="none", mec=DARK_CHARCOAL, ms=6.3, mew=.9,
                            ecolor=DARK_CHARCOAL, elinewidth=.8, capsize=3, zorder=5)
            else:
                ax.plot(x, mean, "D", mfc="none", mec=DARK_CHARCOAL, ms=6.3, mew=.9, zorder=5)
            if n == 3 and module == "M0" and load == "ZERO":
                ax.annotate("*", (x+jitter[0], yy[0]), xytext=(-7,-12), textcoords="offset points", fontsize=10)
            if n == 3 and module == "M3" and load == "MAX":
                ax.annotate("33†", (x+jitter[-1], yy[-1]), xytext=(8,10),
                            textcoords="offset points", ha="center", fontsize=7.5)
    ax.set(xlim=(-.5,3.6), ylim=(0,56), xticks=range(4), xticklabels=MODULES,
           yticks=[0,10,20,30,40,50], xlabel="Module ID", ylabel="Source-to-module difference (mV)")
    ax.tick_params(labelsize=8)
    panel_label(ax, f"N = {n}  |  n = {EXPECTED[n]} per module")

def handles():
    return load_handles() + [Line2D([],[],color=DARK_CHARCOAL,ls="none",marker="D",
                                    mfc="none",ms=6,label="Mean ± combination SD")]

def plot_four(branches, groups):
    fig, axes = canvas(rows=2, columns=2, height=170, top=.84, bottom=.145, left=.105, right=.965,
                       wspace=.40, hspace=.52)
    for n, ax in enumerate(axes.flat,1):
        draw_points(ax,n,branches,groups)
        ax.set_ylabel("Voltage difference (mV)")
    legend(fig,handles(),y=.98)
    fig.text(.105,.047,"Points = combinations; diamonds = means. Combination SD only at N=2,3; not repeat SD.",fontsize=7.5)
    fig.text(.105,.019,"* M0 earlier retest; † M3 targeted retest. Earlier values retained in report retest table.",fontsize=7)
    return export(fig,OUTPUT,"module_drop_N1_N4",
                  "Four panels compare individual and mean module voltage drops for N=1,2,3,4.",semantic())

def plot_single(n,branches,groups):
    fig, axes = canvas(height=98,top=.78,bottom=.22,left=.12,right=.97)
    draw_points(axes[0,0],n,branches,groups)
    legend(fig,handles(),y=.99)
    note = ("Points = individual combinations; diamonds = means. SD unavailable: n=1 per module."
            if n in (1,4) else
            "Points = individual combinations; diamonds = means; SD describes combination spread.")
    fig.text(.12,.07,note,fontsize=7.5)
    if n == 3:
        fig.text(.12,.03,"* ZERO M0 earlier retest; † loaded M3 retest. Both retain the original source readings.",fontsize=7.5)
    return export(fig,OUTPUT,f"module_drop_N{n}",
                  f"Individual points and per-module means at N={n}, both recorded load labels.",semantic())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--copy-to-report", action="store_true")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    protected = [FINAL/"main 2.3.pdf", FINAL/"report_versions/v2.3/manifest.json"]
    protected += list((ROOT/"DATA/analysis/current/voltage_drop_by_N_20260907").glob("*"))
    protected += list((ROOT/"DATA/reference/report_v2_3_figures").glob("*"))
    before = {str(p):digest(p) for p in protected if p.is_file()}
    branches, groups, source_count = collect()
    save_csv(OUTPUT/"module_drop_by_N_summary.csv",groups)
    save_csv(OUTPUT/"contributing_branch_readings.csv",branches)
    with plt.style.context(STYLE), matplotlib.rc_context(PUBLICATION_STYLE):
        matplotlib.rcParams.update({"svg.hashsalt": "eskin-power-drop-2.4", "font.size": 8.5,
                                    "axes.labelsize": 8.5, "xtick.labelsize": 8,
                                    "ytick.labelsize": 8, "legend.fontsize": 7.5})
        figures = [heatmap(groups),plot_four(branches,groups)]
        figures += [plot_single(n,branches,groups) for n in range(1,5)]
    intro = """# 按模块数量 N 汇总的压降图

本次为报告 2.4 的 Power 图更新，使用独立的逐点复测合并数据视图。
已发布的 main 2.3、原分析数据和旧补充图均保留。
对象为已接受的源端与模块端 DMM 主读数之差，单位 mV；不是高速瞬态压降。

## 文件

- [均值热图](module_drop_mean_by_N.png)：两种负载各一幅 N×模块矩阵。
- [N=1–4 四面板图](module_drop_N1_N4.png)：各组合点、模块均值及组合间样本 SD。
- module_drop_N1 至 module_drop_N4：四张可单独使用的图。
- 所有图提供 PNG（300 dpi）、PDF（矢量）和 SVG（可编辑文字）。
- module_drop_by_N_summary.csv：32行完整均值、SD、n、极值与对应组合。
- contributing_branch_readings.csv：64条来源分支，保留逐点 provenance。

## 统计口径

固定负载标签、N 和模块编号，对所有包含该模块的组合等权取平均；
没有把 M0–M3 或不同 N 混在一起平均。每个模块的 n 在 N=1/2/3/4
下分别为 1/3/3/1，这是组合数，不是独立重复次数。每个条件仅一个编制后的条目；
两个目标模块的复测不构成新的完整组合重复。SD 使用 ddof=1；
N=1 和 N=4 没有可计算的 SD，留空而非写成零。N=2、ZERO、M2
的三个已记录读数恰好同为31 mV，所以其组合间SD为零，并不表示测量无不确定性。

| 负载 | N | 每模块 n | M0 / mV | M1 / mV | M2 / mV | M3 / mV |
|---|---:|---:|---:|---:|---:|---:|
"""
    table = []
    for load in LOADS:
        for n in range(1,5):
            cells = []
            for m in MODULES:
                g, = [g for g in groups if (g["load"],g["N"],g["module_id"]) == (load,n,m)]
                label = f'{float(g["mean_drop_mV"]):.2f}'
                if g["sample_SD_across_combinations_mV"]:
                    label += f' ± {float(g["sample_SD_across_combinations_mV"]):.2f}'
                if g["contains_separate_M0_retest_estimate"]:
                    label += "*"
                if g["contains_separate_M3_retest_estimate"]:
                    label += "†"
                cells.append(label)
            table.append(f"| {load} | {n} | {EXPECTED[n]} | " + " | ".join(cells) + " |")
    notes = """

星号：ZERO、N=3、M0 的三个值为35*、36、35 mV；35*采用单独复测
M0=3.241 V和用户确认未变的原SOURCE=3.276 V，属于跨记录估计。
旧接头故障的3.224 V及其52 mV差值仍在原始事件和报告中保留，不混入接受后的均值。

## 是否值得添加到论文

有价值，适合作为概览图。正文可使用均值热图，便于比较同一模块在不同N下的差异；
如果讨论组合间波动，使用四面板原始点+均值±SD图。原15组合热图应保留在附录，
避免平均数掩盖个别较高读数。一般无需把这两种概览和四张单图全部重复放进正文。

匕首号：MAX、N=3、M3的三个当前值为32、32、33† mV，均值32.33±0.58 mV。
33† mV由复测模块端3.243 V与用户确认未变的SOURCE=3.276 V计算。
原M1-M2-M3、M3的44 mV在原数据与报告复测表中保留；复测前重插了接头，
但接触问题的因果作用及加载是否严格匹配均未确认。原值对应均值36.00±6.93 mV。
这些数据没有显示所有模块的压降随N一致增大的趋势；也不能把M0的下降
解释成扩展改善了供电。不同批次、组合与未完全定义的加载条件限制因果解释。
P-H2电压边界仍应基于逐点最低模块电压，平均压降不能代替最不利工况检查。

## Suggested captions

Mean heatmap: Mean source-to-module voltage differences for each physical
module at N=1–4, separated by recorded load label. Means include all combinations
containing that module (n=1,3,3,1, respectively); each exact condition has one
compiled entry. Starred and daggered means include targeted M0 and M3 voltage
retests, respectively, with retained, user-confirmed source readings. All differences are derived
from sequential DMM main readings.

Point panels: Individual configuration voltage differences and their per-module
means at each N. Error bars are sample SD across combinations at N=2 and N=3,
not independent repeat uncertainty; SD is unavailable at N=1 and N=4.
The starred M0 and daggered M3 values are cross-record retest estimates.
Earlier values remain in the report comparison table, outside these revised means.

复现：从 Final 目录运行 python -B "power scalability/script/Main/figures/power_retest_drop_by_count.py"。
绘图脚本和来源哈希记录在 figure_manifest.json。目标为本项目报告的补充图，
未声称满足某个期刊的投稿规范。
"""
    (OUTPUT/"README_CN.md").write_text(intro+"\n".join(table)+"\n"+notes,encoding="utf-8")
    assert all(digest(p) == h for p,h in before.items())
    manifest = {
        "created_at_utc":datetime.now(timezone.utc).isoformat(),
        "figures":figures, "source_hashes_checked":source_count,
        "input_files":{str(p.relative_to(ROOT)):digest(p) for p in SOURCE.iterdir() if p.is_file()},
        "script_sha256":digest(__file__), "helper_sha256":digest(Path(__file__).with_name("power_revision_figures.py")),
        "style_sha256":digest(STYLE), "shared_style_sha256":digest(FINAL/"figure_style.py"),
        "matplotlib":matplotlib.__version__,"semantics":semantic(),
        "summary_rows":len(groups),"contributing_rows":len(branches),
        "protected_report_hashes":before,
    }
    (OUTPUT/"figure_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if args.copy_to_report:
        for entry in figures[:2]:
            for f in entry["files"]:
                shutil.copy2(OUTPUT/f["name"], REPORT_FIGURES/f["name"])
                assert digest(REPORT_FIGURES/f["name"]) == f["sha256"]
        shutil.copy2(OUTPUT/"figure_manifest.json", REPORT_FIGURES/"figure_manifest_drop_v2_4.json")
    print(json.dumps({"output":str(OUTPUT),"figures":len(figures),"summary_rows":len(groups),
                      "source_hashes_checked":source_count,"copy_to_report":args.copy_to_report,"published_2_3_unchanged":True},indent=2))

if __name__ == "__main__":
    main()
