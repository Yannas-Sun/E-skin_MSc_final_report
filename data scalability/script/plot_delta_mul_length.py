"""Plot the length of every captured DELTA MUL1 frame.

The recorder writes one row per complete MUL1 frame to ``packet_log.csv``.
This script uses ``elapsed_s`` for the x-axis and ``declared_length`` for the
y-axis. It creates one PNG for every recording found below the DELTA data
directory.

Default usage from any working directory::

    python plot_delta_mul_length.py

An optional common output directory can be supplied explicitly. Without it,
each PNG is written beside the corresponding ``packet_log.csv``::

    python plot_delta_mul_length.py --input "...\\data\\DELTA"
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


FINAL_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FINAL_DIR))
from figure_style import (  # noqa: E402
    DARK_CHARCOAL,
    DEEP_TEAL,
    GRID,
    MINT_GREEN,
    MUTED_LAVENDER,
    PUBLICATION_STYLE,
    SLATE_BLUE,
    TEAL_CYAN,
)

plt.rcParams.update(PUBLICATION_STYLE)


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR.parent / "data" / "DELTA"
# The outer MUL1 packet always reserves one 4-byte block header per module.
# A zero-load DELTA payload still contains the ESK header, two 32-byte masks,
# and the inner CRC: 16 + 32 + 32 + 4 = 84 B.
MUL1_HEADER_BYTES = 20
MODULE_BLOCK_HEADER_BYTES = 4
MODULE_COUNT_IN_OUTER_PACKET = 4
OUTER_CRC_BYTES = 4
DELTA_MIN_INNER_BYTES = 84
MUL1_FIXED_OVERHEAD_BYTES = (
    MUL1_HEADER_BYTES
    + MODULE_COUNT_IN_OUTER_PACKET * MODULE_BLOCK_HEADER_BYTES
    + OUTER_CRC_BYTES
)
# FULL reference frame in the current four-module MUL1 envelope: the packet
# keeps one 4-byte block header for each of the four module positions, while
# only active modules contribute a 1044-byte ESKF payload.
FULL_MUL1_FIXED_OVERHEAD_BYTES = (
    MUL1_HEADER_BYTES
    + MODULE_COUNT_IN_OUTER_PACKET * MODULE_BLOCK_HEADER_BYTES
    + OUTER_CRC_BYTES
)
FULL_MODULE_BLOCK_BYTES = 1044

# Stable colors for module-specific sync markers. If more modules are ever
# enabled, the palette cycles without changing the existing module mapping.
MODULE_SYNC_COLORS = (
    TEAL_CYAN,  # M0
    DEEP_TEAL,  # M1
    SLATE_BLUE,  # M2
    MINT_GREEN,  # M3
    MUTED_LAVENDER,  # M4+
    DARK_CHARCOAL,  # M5+
)


def parse_algorithm_tokens(value: str | None) -> tuple[str, ...]:
    """Return one algorithm label per module from the CSV field."""

    if not value:
        return ()
    return tuple(token.strip() or "NONE" for token in value.split(","))


def parse_updated_mask(value: str | None) -> int:
    """Parse the CSV's hexadecimal updated-module mask."""

    if not value:
        return 0
    try:
        return int(value.strip(), 0)
    except ValueError:
        return 0


def read_packet_log(
    path: Path,
) -> tuple[list[float], list[int], list[tuple[str, ...]], set[int]]:
    """Read time, MUL1 length, per-module algorithms, and active modules."""

    times: list[float] = []
    lengths: list[int] = []
    algorithms: list[tuple[str, ...]] = []
    active_module_ids: set[int] = set()

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"elapsed_s", "declared_length", "received_bytes"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{path}: missing columns: {', '.join(sorted(missing))}"
            )

        for line_number, row in enumerate(reader, start=2):
            try:
                elapsed = float(row["elapsed_s"])
                declared_text = (row.get("declared_length") or "").strip()
                received_text = (row.get("received_bytes") or "").strip()
                length = int(declared_text or received_text)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{path}: invalid time or length at CSV line {line_number}"
                ) from exc

            if declared_text and received_text and int(declared_text) != int(received_text):
                print(
                    f"Warning: {path} line {line_number}: declared_length "
                    "does not equal received_bytes",
                    file=sys.stderr,
                )

            times.append(elapsed)
            lengths.append(length)
            row_algorithms = parse_algorithm_tokens(row.get("algorithms"))
            algorithms.append(row_algorithms)

            updated_mask = parse_updated_mask(row.get("updated_mask"))
            active_module_ids.update(
                module_id
                for module_id in range(8)
                if updated_mask & (1 << module_id)
            )
            # Keep the plot adaptive even when an older log is missing a
            # useful updated_mask but still contains per-module algorithms.
            active_module_ids.update(
                module_id
                for module_id, algorithm in enumerate(row_algorithms)
                if algorithm != "NONE"
            )

    if not times:
        raise ValueError(f"{path}: no valid MUL1 rows found")
    return times, lengths, algorithms, active_module_ids


def plot_recording(
    packet_log: Path, input_root: Path, output_root: Path | None = None
) -> Path:
    times, lengths, algorithms, active_module_ids = read_packet_log(packet_log)
    if output_root is None:
        output_path = packet_log.parent / "mul1_length_over_time.png"
    else:
        output_root.mkdir(parents=True, exist_ok=True)
        relative_parent = packet_log.parent.relative_to(input_root)
        parts = [part for part in relative_parent.parts if part not in (".", "")]
        stem = "_".join(parts) if parts else packet_log.parent.name
        output_path = output_root / f"{stem}_mul_length.png"

    relative_parent = packet_log.parent.relative_to(input_root)
    label = "/".join(relative_parent.parts)

    figure, axis = plt.subplots(figsize=(14, 7.0))
    sync_times_by_module: dict[int, list[float]] = {}
    sync_lengths: list[int] = []
    normal_times: list[float] = []
    normal_lengths: list[int] = []
    for time, length, row_algorithms in zip(times, lengths, algorithms):
        row_sync = False
        for module_id, algorithm in enumerate(row_algorithms):
            if algorithm == "DELTA_SYNC":
                sync_times_by_module.setdefault(module_id, []).append(time)
                sync_lengths.append(length)
                row_sync = True
        if not row_sync:
            normal_times.append(time)
            normal_lengths.append(length)

    axis.plot(
        normal_times,
        normal_lengths,
        color=SLATE_BLUE,
        linewidth=0.75,
        label="MUL1 length",
        zorder=2,
    )
    active_count = len(active_module_ids)
    theoretical_zero_load = (
        MUL1_FIXED_OVERHEAD_BYTES + active_count * DELTA_MIN_INNER_BYTES
    )
    theoretical_full_length = (
        FULL_MUL1_FIXED_OVERHEAD_BYTES + active_count * FULL_MODULE_BLOCK_BYTES
    )
    mean_length = sum(lengths) / len(lengths)
    axis.axhline(
        theoretical_zero_load,
        color=MUTED_LAVENDER,
        linewidth=1.2,
        linestyle="-",
        label=(
            "Theoretical zero-load MUL1 "
            f"({theoretical_zero_load} B, N={active_count})"
        ),
        zorder=1,
    )
    axis.axhline(
        theoretical_full_length,
        color=TEAL_CYAN,
        linewidth=1.2,
        linestyle="-",
        label=(
            "Theoretical FULL MUL1 "
            f"({theoretical_full_length} B/frame, N={active_count})"
        ),
        zorder=1,
    )
    axis.axhline(
        mean_length,
        color=DEEP_TEAL,
        linewidth=1.5,
        linestyle="-",
        label=f"Mean MUL1 length (all frames) ({mean_length:.2f} B)",
        zorder=4,
    )

    for module_id, sync_times in sorted(sync_times_by_module.items()):
        color = MODULE_SYNC_COLORS[module_id % len(MODULE_SYNC_COLORS)]
        for index, sync_time in enumerate(sync_times):
            axis.axvline(
                sync_time,
                color=color,
                linewidth=0.9,
                linestyle=(0, (5, 4)),
                alpha=0.35,
                label=f"M{module_id} DELTA_SYNC (dashed)" if index == 0 else None,
                zorder=1,
            )

    data_max = max(lengths)
    sync_max = max(sync_lengths, default=data_max)
    y_upper = max(
        sync_max, data_max, theoretical_zero_load, theoretical_full_length
    )
    # Leave a small headroom above the highest sync frame while keeping the
    # requested zero-to-maximum view and avoiding a clipped top marker.
    y_upper = max(1, int(y_upper * 1.05))

    axis.set_title(f"DELTA MUL1 length over time | {label}")
    axis.set_xlabel("Time from recording start (s)")
    axis.set_ylabel("Current MUL1 length (B)")
    axis.grid(True, color=GRID, alpha=0.65, linewidth=0.6)
    # Keep the legend in a dedicated bottom area so it never hides the MUL1
    # trace or the horizontal reference lines.
    axis.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=2,
        borderaxespad=0.0,
    )
    axis.set_xlim(left=0)
    axis.set_ylim(0, y_upper)
    figure.tight_layout(rect=(0.0, 0.22, 1.0, 1.0))
    figure.savefig(output_path, dpi=300, bbox_inches=None,
                   facecolor="white", transparent=False)
    plt.close(figure)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate one MUL1-length line plot for each DELTA recording."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"DELTA data root (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "optional common PNG output directory; by default each PNG is "
            "written beside its packet_log.csv"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_root = args.input.resolve()
    output_root = args.output.resolve() if args.output is not None else None

    if not input_root.is_dir():
        print(f"Input directory does not exist: {input_root}", file=sys.stderr)
        return 2

    packet_logs = sorted(input_root.rglob("packet_log.csv"))
    if not packet_logs:
        print(f"No packet_log.csv found below: {input_root}", file=sys.stderr)
        return 1

    generated = 0
    for packet_log in packet_logs:
        try:
            output_path = plot_recording(packet_log, input_root, output_root)
        except (OSError, ValueError) as exc:
            print(f"Skipping {packet_log}: {exc}", file=sys.stderr)
            continue
        print(f"Generated: {output_path}")
        generated += 1

    print(f"Generated {generated}/{len(packet_logs)} plot(s).")
    return 0 if generated == len(packet_logs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
