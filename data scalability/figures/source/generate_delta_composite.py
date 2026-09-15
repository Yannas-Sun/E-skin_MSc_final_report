"""Generate the combined DELTA result figure used in the report.

The figure is rebuilt from each recording's ``packet_log.csv`` and
``summary.json`` rather than compositing screenshots.  The raw recordings and
the original per-run plots are left untouched.

Usage::

    python generate_delta_composite.py --force
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from PIL import Image


FINAL_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(FINAL_DIR))
from figure_style import (  # noqa: E402
    DARK_CHARCOAL,
    DEEP_TEAL,
    GRID,
    MINT_GREEN,
    MUTED_LAVENDER,
    PALE_TEAL,
    SLATE_BLUE,
    TEAL_CYAN,
    X_AXIS_CHARCOAL,
)


SCRIPT_DIR = Path(__file__).resolve().parent
FIGURES_DIR = SCRIPT_DIR.parent
DEFAULT_DATA_ROOT = FIGURES_DIR.parent / "data"
DATA_ROOT = DEFAULT_DATA_ROOT
DEFAULT_OUTPUT_DIR = FIGURES_DIR / "exports"
REPORT_OUTPUT_DIR = (
    FIGURES_DIR.parent.parent
    / "Imperial College Individual Project Template_LaTeX"
    / "figures"
    / "data"
)
STYLE_PATH = SCRIPT_DIR / "report.mplstyle"

MUL1_FIXED_OVERHEAD_BYTES = 40
DELTA_MIN_INNER_BYTES = 84
FULL_MODULE_BLOCK_BYTES = 1044

# Figure 4.1/4.2 reference-line roles.
ZERO_REFERENCE_COLOR = DARK_CHARCOAL
MEAN_REFERENCE_COLOR = SLATE_BLUE
FULL_REFERENCE_COLOR = DEEP_TEAL

# Okabe--Ito-inspired colours keep the module markers distinguishable in
# colour and in print; dashed styling is the redundant visual cue.
SYNC_COLORS = {
    "M0": TEAL_CYAN,
    "M1": DEEP_TEAL,
    "M2": SLATE_BLUE,
    "M3": MINT_GREEN,
}


@dataclass(frozen=True)
class RecordSpec:
    title: str
    relative_dir: Path
    phase: str | None = None


@dataclass
class Record:
    spec: RecordSpec
    times: list[float]
    lengths: list[int]
    ordinary_times: list[float]
    ordinary_lengths: list[int]
    sync_times_by_module: dict[str, list[float]]
    module_ids: tuple[str, ...]
    summary: dict


RECORDS = (
    RecordSpec(
        "N=1 | M1 | zero load",
        Path("DELTA/Zero_load/N=1/M1/Repeat_3"),
    ),
    RecordSpec(
        "N=1 | M1 | large-area dynamic load",
        Path("DELTA/Dynamic_load/M1/Large_area/Repeat_3"),
        "large",
    ),
    RecordSpec(
        "N=4 | M0–M3 | zero load",
        # Explicit historical baseline: run 20260901_205141.
        Path("DELTA/Zero_load/N=4/M0_M1_M2_M3/R1"),
    ),
    RecordSpec(
        "N=4 | M0–M3 | full-coverage simultaneous load",
        Path(
            "DELTA/Dynamic_load/N=4/M0_M1_M2_M3/"
            "Full_coverage_all_FSR/Repeat_1"
        ),
        "full",
    ),
)


def parse_algorithms(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(token.strip() or "NONE" for token in value.split(","))


def parse_updated_mask(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(value.strip(), 0)
    except ValueError:
        return 0


def read_record(spec: RecordSpec) -> Record:
    record_dir = DATA_ROOT / spec.relative_dir
    summary_path = record_dir / "summary.json"
    packet_path = record_dir / "packet_log.csv"
    if not summary_path.is_file():
        raise FileNotFoundError(
            f"Selected record is missing: {summary_path}. "
            "Choose its dataset with --data-root; no other dataset is searched automatically."
        )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if int(summary.get("schema_version", 1)) >= 2:
        raise ValueError(
            f"Unsupported summary schema_version >= 2: {summary_path}. "
            "New recordings require scopes.main statistics and explicit run selection; "
            "this legacy composite cannot plot them using the old summary fields."
        )
    if not packet_path.is_file():
        raise FileNotFoundError(f"Selected record is missing: {packet_path}")

    times: list[float] = []
    lengths: list[int] = []
    ordinary_times: list[float] = []
    ordinary_lengths: list[int] = []
    sync_times_by_module: dict[str, list[float]] = {}
    active_ids: set[str] = set()

    with packet_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"elapsed_s", "declared_length", "received_bytes"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{packet_path}: missing columns {sorted(missing)}")

        for row in reader:
            elapsed = float(row["elapsed_s"])
            declared = (row.get("declared_length") or "").strip()
            received = (row.get("received_bytes") or "").strip()
            length = int(declared or received)
            algorithms = parse_algorithms(row.get("algorithms"))
            updated_mask = parse_updated_mask(row.get("updated_mask"))

            times.append(elapsed)
            lengths.append(length)

            row_is_sync = False
            for module_index, algorithm in enumerate(algorithms):
                if algorithm != "NONE":
                    active_ids.add(f"M{module_index}")
                if algorithm == "DELTA_SYNC":
                    module_id = f"M{module_index}"
                    sync_times_by_module.setdefault(module_id, []).append(elapsed)
                    row_is_sync = True
            for module_index in range(8):
                if updated_mask & (1 << module_index):
                    active_ids.add(f"M{module_index}")

            if not row_is_sync:
                ordinary_times.append(elapsed)
                ordinary_lengths.append(length)

    if not times:
        raise ValueError(f"{packet_path}: no complete MUL1 rows")

    condition = summary.get("test_condition", {})
    summary_ids = condition.get("active_module_ids") or []
    module_ids = tuple(summary_ids) if summary_ids else tuple(sorted(active_ids))
    if not module_ids:
        raise ValueError(f"{summary_path}: no active module IDs")
    return Record(
        spec=spec,
        times=times,
        lengths=lengths,
        ordinary_times=ordinary_times,
        ordinary_lengths=ordinary_lengths,
        sync_times_by_module=sync_times_by_module,
        module_ids=module_ids,
        summary=summary,
    )


def reference_lengths(record: Record) -> tuple[int, int]:
    module_count = len(record.module_ids)
    zero_load = MUL1_FIXED_OVERHEAD_BYTES + module_count * DELTA_MIN_INNER_BYTES
    full = MUL1_FIXED_OVERHEAD_BYTES + module_count * FULL_MODULE_BLOCK_BYTES
    return zero_load, full


def add_dynamic_context(axis, phase: str | None) -> None:
    # Keep the plotting area neutral.  The experiment phases are documented
    # in the report caption rather than encoded as background shading.
    return None


def add_right_edge_label(axis, value: float, text: str, color: str, *,
                         offset_y: float = 0.0) -> None:
    """Label a horizontal reference line in a dedicated right-side gutter."""
    y_min, y_max = axis.get_ylim()
    y_fraction = (value - y_min) / (y_max - y_min)
    axis.annotate(
        text,
        xy=(1.0, y_fraction),
        xycoords=axis.transAxes,
        xytext=(10, offset_y),
        textcoords="offset points",
        ha="left",
        va="center",
        fontsize=12,
        color=color,
        clip_on=False,
        arrowprops={"arrowstyle": "-", "color": color, "lw": 0.7},
        zorder=7,
    )


def add_maximum_marker(axis, record: Record) -> None:
    """Mark the highest ordinary (non-synchronisation) DELTA frame."""
    if not record.ordinary_lengths:
        return
    maximum_index = max(
        range(len(record.ordinary_lengths)),
        key=record.ordinary_lengths.__getitem__,
    )
    maximum_time = record.ordinary_times[maximum_index]
    maximum_length = record.ordinary_lengths[maximum_index]
    axis.scatter(
        [maximum_time],
        [maximum_length],
        s=22,
        color=DARK_CHARCOAL,
        edgecolors="white",
        linewidths=0.7,
        zorder=8,
    )
    if maximum_time > 25:
        text_offset = (-8, 8)
        horizontal_alignment = "right"
    else:
        text_offset = (8, 8)
        horizontal_alignment = "left"
    axis.annotate(
        f"max {maximum_length} B",
        xy=(maximum_time, maximum_length),
        xytext=text_offset,
        textcoords="offset points",
        ha=horizontal_alignment,
        va="bottom",
        fontsize=12,
        color=DARK_CHARCOAL,
        arrowprops={"arrowstyle": "-", "color": DARK_CHARCOAL, "lw": 0.7},
        clip_on=False,
        zorder=8,
    )


def plot_combined(
    records: list[Record],
    stem: str,
    output_dir: Path,
    force: bool,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / f"{stem}.png"
    pdf_path = output_dir / f"{stem}.pdf"
    if not force:
        existing = [path for path in (png_path, pdf_path) if path.exists()]
        if existing:
            raise FileExistsError(
                "Output exists; use --force to replace: "
                + ", ".join(str(path) for path in existing)
            )

    with plt.style.context(str(STYLE_PATH)):
        figure, axes = plt.subplots(4, 1, figsize=(11.5, 13.8), sharex=True)
        figure.subplots_adjust(
            left=0.08,
            right=0.84,
            top=0.98,
            bottom=0.09,
            hspace=0.35,
        )
        for index, (axis, record) in enumerate(zip(axes, records)):
            zero_load, full_length = reference_lengths(record)
            panel_y_max = max(max(record.lengths), zero_load, full_length)
            add_dynamic_context(axis, record.spec.phase)
            # Figures 4.1 and 4.2 use a single teal data trace and one
            # terracotta colour for all three horizontal references.
            axis.axhline(zero_load, color=ZERO_REFERENCE_COLOR, linewidth=1.15, zorder=1)
            axis.axhline(full_length, color=FULL_REFERENCE_COLOR, linewidth=1.15, zorder=1)
            axis.plot(
                record.ordinary_times,
                record.ordinary_lengths,
                color=TEAL_CYAN,
                linewidth=0.65,
                alpha=0.88,
                zorder=2,
            )
            axis.set_xlim(0, 30.2)
            axis.set_ylim(0, panel_y_max * 1.08)
            mean_length = sum(record.lengths) / len(record.lengths)
            axis.axhline(
                mean_length,
                color=MEAN_REFERENCE_COLOR,
                linewidth=1.8,
                zorder=4,
            )

            add_right_edge_label(
                axis, zero_load, f"{zero_load:.0f} B", ZERO_REFERENCE_COLOR, offset_y=-8
            )
            add_right_edge_label(
                axis, full_length, f"{full_length:.0f} B", FULL_REFERENCE_COLOR, offset_y=0
            )
            add_right_edge_label(
                axis, mean_length, f"{mean_length:.1f} B", MEAN_REFERENCE_COLOR, offset_y=8
            )
            if index in (1, 3):
                add_maximum_marker(axis, record)

            for module_id, sync_times in sorted(record.sync_times_by_module.items()):
                color = SYNC_COLORS.get(module_id, SLATE_BLUE)
                for sync_time in sync_times:
                    axis.axvline(
                        sync_time,
                        color=color,
                        linewidth=0.75,
                        linestyle=(0, (4, 4)),
                        alpha=0.22,
                        zorder=1,
                    )

            # Panel labels are structural markers only; conditions and values
            # are stated in the report captions.
            axis.text(
                0.01,
                0.93,
                f"({chr(ord('a') + index)})",
                transform=axis.transAxes,
                ha="left",
                va="top",
                fontsize=10,
                color=DARK_CHARCOAL,
            )
            axis.grid(True, color=GRID, alpha=0.65, linewidth=0.55)
            axis.set_ylabel("MUL1 length (B)")
            axis.set_xlabel(
                "Time from recording start (s)" if index == len(records) - 1 else ""
            )
            axis.spines["bottom"].set_color(X_AXIS_CHARCOAL)
            axis.tick_params(axis="x", colors=X_AXIS_CHARCOAL)
            axis.xaxis.label.set_color(X_AXIS_CHARCOAL)

        # The captions carry the experiment descriptions and numerical values;
        # the legend only decodes the graphical encodings.
        module_ids = sorted(
            {
                module_id
                for record in records
                for module_id in record.sync_times_by_module
            }
        )
        legend_handles = [
            Line2D([], [], color=TEAL_CYAN, linewidth=1.2, label="ordinary DELTA frame"),
            Line2D([], [], color=MEAN_REFERENCE_COLOR, linewidth=1.8, label="recorded mean"),
            Line2D([], [], color=ZERO_REFERENCE_COLOR, linewidth=1.2, label="theoretical zero-load"),
            Line2D([], [], color=FULL_REFERENCE_COLOR, linewidth=1.2, label="theoretical FULL"),
        ]
        legend_handles.extend(
            Line2D(
                [], [], color=SYNC_COLORS.get(module_id, SLATE_BLUE),
                linewidth=1.0, linestyle=(0, (4, 4)), alpha=0.65,
                label=f"{module_id} DELTA_SYNC"
            )
            for module_id in module_ids
        )
        figure.legend(
            handles=legend_handles,
            loc="lower center",
            bbox_to_anchor=(0.5, 0.015),
            ncol=4,
            frameon=False,
            fontsize=10.5,
            columnspacing=1.2,
            handlelength=2.2,
        )
        figure.savefig(png_path, dpi=300, facecolor="white")
        figure.savefig(pdf_path, facecolor="white")
        plt.close(figure)

    # Make the raster export explicitly opaque for consistent report previews.
    with Image.open(png_path) as image:
        image.convert("RGB").save(png_path, dpi=(300, 300))
    return png_path, pdf_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root", type=Path, default=DEFAULT_DATA_ROOT,
        help=f"Root containing the explicitly selected records; no history fallback (default: {DEFAULT_DATA_ROOT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace existing composite outputs",
    )
    return parser.parse_args()


def main() -> int:
    global DATA_ROOT
    args = parse_args()
    DATA_ROOT = args.data_root.resolve()
    try:
        if not DATA_ROOT.is_dir():
            raise FileNotFoundError(
                f"Data root does not exist: {DATA_ROOT}. "
                "Select a dataset explicitly with --data-root; history is not searched automatically."
            )
        records = [read_record(spec) for spec in RECORDS]
        results = [
            plot_combined(
                records,
                "08_delta_combined_results",
                args.output_dir.resolve(),
                args.force,
            )
        ]
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}")
        return 1
    for png_path, pdf_path in results:
        print(f"Generated: {png_path}")
        print(f"Generated: {pdf_path}")
        REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        report_pdf = REPORT_OUTPUT_DIR / pdf_path.name
        shutil.copy2(pdf_path, report_pdf)
        print(f"Synced report figure: {report_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
