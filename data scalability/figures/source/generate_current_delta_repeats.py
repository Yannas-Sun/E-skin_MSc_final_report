"""Plot the three 2026-09-07 M1 large-area DELTA repeats in the original style.

This is a diagnostic comparison of all three consecutive windows in one batch,
not a replacement for the report's historical N=1/N=4 condition comparison.
The independent CHECK disposition is read from the current run index.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

FINAL = Path(__file__).resolve().parents[3]
DATA = FINAL / "data scalability" / "data"
DEFAULT_RENDERER = (FINAL.parents[1] / "hardware/new/firmware/active/"
                    "four-module-variable-spi/pc/recording_plots.py")
DEFAULT_OUTPUT = FINAL / "data scalability/figures/current_recordings"
RUN_IDS = ("20260907_040621_371357", "20260907_040701_400114",
           "20260907_040741_429011")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renderer", type=Path, default=DEFAULT_RENDERER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("recording_plots", args.renderer)
    plots = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plots)
    with (DATA / "run_index.csv").open(encoding="utf-8-sig", newline="") as stream:
        index = {row["run_id"]: row for row in csv.DictReader(stream)}
    selected = [index[run_id] for run_id in RUN_IDS]
    assert len({r["batch_id"] for r in selected}) == 1
    assert [int(r["repeat"]) for r in selected] == [1, 2, 3]
    assert all(r["mode"] == "DELTA" and r["condition"] == "large_area"
               and r["modules"] == "M1" and r["N"] == "1" for r in selected)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    manifest = {"purpose": "Diagnostic M1 large-area comparison, all three batch repeats",
                "source_run_ids": list(RUN_IDS), "renderer": str(args.renderer.resolve()),
                "renderer_sha256": sha256(args.renderer),
                "index_sha256": sha256(DATA / "run_index.csv"), "records": [],
                "definitions": {
                    "trace": "Ordinary DELTA only; entire packets containing DELTA_SYNC use vertical event markers instead",
                    "mean": "Original main-window complete outer-valid MUL1 byte mean, ESKF included",
                    "time": "Full capture, PC packet-completion elapsed time; initial 10 s shaded and excluded from main mean",
                    "ESKF": "All logged DELTA_SYNC events; trigger cause not encoded",
                    "repeat": "Three consecutive time windows in one unchanged setup, not independent loading trials"}}
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 9,
                         "svg.fonttype": "none", "savefig.facecolor": "white"}):
        fig, axes = plt.subplots(3, 1, figsize=(10.8, 9.0), sharex=True,
                                 facecolor="white")
        fig.subplots_adjust(left=.085, right=.83, top=.91, bottom=.16, hspace=.39)
        legend = {}
        for number, (row, ax) in enumerate(zip(selected, axes), 1):
            directory = (DATA / row["new_relative_path"]).resolve()
            directory.relative_to(DATA.resolve())
            before = {name: sha256(directory / name)
                      for name in ("summary.json", "packet_log.csv")}
            data = plots.load_plot_data(directory)
            if data["errors"]:
                raise RuntimeError(data["errors"])
            review = data["independent_review"]["status"]
            plots.draw_length_panel(data, ax, panel_label=f"({chr(96+number)}) Repeat {number}")
            ax.text(.20, 1.025, f"Independent review: {review}", transform=ax.transAxes,
                    ha="left", color=plots.FULL if review == "CHECK" else plots.K0,
                    fontsize=8)
            ax.set_xlabel("")
            for handle, label in zip(*ax.get_legend_handles_labels()):
                legend.setdefault(label, handle)
            ordinary = [p for p in data["valid"] if "DELTA_SYNC" not in p["algorithms"]
                        and "DELTA" in p["algorithms"]]
            manifest["records"].append({"run_id": row["run_id"], "directory": str(directory),
                "repeat": number, "independent_review": data["independent_review"],
                "original_recording_status": {"main": data["main"].get("status"),
                                               "full_run": data["full"].get("status")},
                "main_calculated": data["main_calculated"],
                "maximum_ordinary_MUL1_B": max(p["bytes"] for p in ordinary),
                "sources": before})
            assert before == {name: sha256(directory / name) for name in before}
        axes[-1].set_xlabel("PC completion time from record start (s)",
                            fontsize=9, color=plots.K0)
        fig.text(.085, .968, "M1 large-area DELTA | three consecutive repeats",
                 fontsize=12, color=plots.K0)
        fig.text(.085, .946, "Diagnostic records: module sequence discontinuities require review",
                 fontsize=9, color=plots.FULL)
        order = [label for label in ("Ordinary DELTA", "Mean incl. ESKF", "K=0", "FULL", "M1 ESKF")
                 if label in legend]
        order.extend(label for label in legend if label not in order)
        fig.legend([legend[label] for label in order], order, frameon=False,
                   loc="lower center", bbox_to_anchor=(.48, .071),
                   ncol=3, fontsize=8, labelcolor=plots.K0, handlelength=2.3)
        fig.text(.085, .022,
                 "Shading: initial 10 s. Mean: main window after 10 s, including ESKF. K=0: theoretical lower bound.\n"
                 "ESKF lines show recorded events; trigger causes are unknown. Original GUI main PASS / full CHECK retained.",
                 fontsize=7, color=plots.K0, linespacing=1.5)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        outputs = {}
        for ext in ("png", "svg"):
            output = args.output_dir / f"m1_large_area_repeats.{ext}"
            fig.savefig(output, dpi=300, facecolor="white")
            outputs[output.name] = {"path": str(output.resolve()), "sha256": sha256(output)}
        plt.close(fig)
    manifest["outputs"] = outputs
    manifest_path = args.output_dir / "m1_large_area_repeats.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"outputs": outputs, "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
