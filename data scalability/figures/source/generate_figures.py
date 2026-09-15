from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np
from PIL import Image


FINAL_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(FINAL_DIR))
from figure_style import (  # noqa: E402
    DARK_CHARCOAL,
    DEEP_TEAL,
    FIGURE_44_SURFACE_START,
    GRID,
    K240_LAVENDER,
    MINT_GREEN,
    MUTED_LAVENDER,
    PALE_LAVENDER,
    PALE_MINT,
    PALE_TEAL,
    PUBLICATION_STYLE,
    SLATE_BLUE,
    TEAL_CYAN,
    figure_44_surface_cmap,
    publication_cmap,
)


FIGURES_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = FIGURES_DIR.parent / "data"
DATA_DIR = DEFAULT_DATA_DIR
EXPORT_DIR = FIGURES_DIR / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
TABLE_DIR = FIGURES_DIR / "tables"
REPORT_FIGURE_DIR = (
    FIGURES_DIR.parent.parent
    / "Imperial College Individual Project Template_LaTeX"
    / "figures"
    / "data"
)
STYLE_PATH = FIGURES_DIR / "source" / "report.mplstyle"
MAX_MODULES = 100
MAX_FREQUENCY_HZ = 700
CROSS_SECTION_HZ = 200
USB_SECTION_MAX_MODULES = 700
HOST_SPI_3D_MAX_MODULES = 10
HOST_SPI_SECTION_MAX_MODULES = 30
DELTA_MODULE_BASE_BYTES = 84
DELTA_SYNC_PERIOD_SECONDS = 1.0
CURRENT_CONFIGURED_SLOTS = 4
SPI_CURRENT_MBIT = 10.0
SPI_REFERENCE_MBIT = 40.0
USB_REFERENCE_MBIT = 480.0
FULL_COLOR = TEAL_CYAN
DELTA_COLOR = DEEP_TEAL
MID_COLOR = SLATE_BLUE
SPI_COLOR = SLATE_BLUE
USB_COLOR = DARK_CHARCOAL

# Figure 4.3 is a 2x2 composition of four source panels.  The source panels
# are rendered at a larger canvas and then placed into the composite, so use
# dedicated typography sizes here to keep the labels legible after scaling.
FIGURE_43_AXIS_LABEL_SIZE = 13.5
FIGURE_43_TICK_SIZE = 11.5
FIGURE_43_ANNOTATION_SIZE = 13.0
FIGURE_43_LEGEND_SIZE = 13.0

plt.rcParams.update(PUBLICATION_STYLE)

def load_records() -> list[dict]:
    records = []
    for path in sorted(DATA_DIR.rglob("summary.json")):
        item = json.loads(path.read_text(encoding="utf-8-sig"))
        if int(item.get("schema_version", 1)) >= 2:
            raise ValueError(
                f"Unsupported summary schema_version >= 2: {path}. "
                "New recordings require scopes.main statistics and explicit run selection; "
                "this legacy figure generator cannot plot them using the old summary fields."
            )
        item["_path"] = path
        records.append(item)
    return records


def condition(record: dict) -> dict:
    return record.get("test_condition", {})


def algorithm(record: dict) -> str:
    return str(condition(record).get("algorithm", "")).upper()


def module_count(record: dict) -> int:
    return int(condition(record).get("module_count", 0))


def mbit_rate(record: dict) -> float:
    return float(record.get("average_usb_rate_Mbitps", 0.0))


def minimum_configured_slots(n):
    """Explicit extrapolation policy, not a claim about the current firmware."""
    return np.maximum(CURRENT_CONFIGURED_SLOTS, np.asarray(n))


def round_overhead_bytes(m):
    """H(M)=24+4M; M counts configured slots, independently of active N."""
    return 24 + 4 * np.asarray(m)


def configured_slots(n, m=None):
    """Use explicit M, or the minimum-capacity policy for existing N-axis plots."""
    active = np.asarray(n)
    slots = minimum_configured_slots(active) if m is None else np.asarray(m)
    if np.any(active < 0) or np.any(slots < 1) or np.any(active > slots):
        raise ValueError("Require 0 <= active N <= configured M, with M >= 1")
    return slots


def full_frame_bytes(n, m=None):
    return round_overhead_bytes(configured_slots(n, m)) + 1044 * np.asarray(n)


def delta_frame_bytes(n, k, m=None):
    """Ordinary ESKD frames; periodic ESKF syncs are excluded from this bound."""
    return round_overhead_bytes(configured_slots(n, m)) + np.asarray(n) * (84 + 2 * np.asarray(k))


def theoretical_mbit(frame_bytes: int, frequency_hz: float) -> float:
    return frame_bytes * frequency_hz * 8.0 / 1_000_000.0


def usb_crossing_modules(payload_bytes: int, frequency_hz: float, rate_mbit: float,
                         m=None) -> float:
    """Invert H(M)+N*payload; default is the explicit minimum-capacity policy."""
    budget_bytes = rate_mbit * 1_000_000.0 / (8.0 * frequency_hz)
    if m is not None:
        n = (budget_bytes - round_overhead_bytes(m)) / payload_bytes
        configured_slots(n, m)
        return float(n)
    n = (budget_bytes - round_overhead_bytes(CURRENT_CONFIGURED_SLOTS)) / payload_bytes
    return n if n <= 4 else (budget_bytes - 24.0) / (payload_bytes + 4.0)


def host_spi_round_bytes(n):
    """FULL Host SPI bytes; the USB wrapper is added on the separate link."""
    return 1044 * np.asarray(n)


def host_spi_delta_round_bytes(n, k):
    """Valid variable-length DELTA bytes; no fixed-slot padding or MUL1 wrapper."""
    return (DELTA_MODULE_BASE_BYTES + 2 * np.asarray(k)) * np.asarray(n)


def host_spi_crossing_modules(frequency_hz: float, rate_mbit: float, k: int = 480) -> float:
    """Pure clock-budget crossing for a selected DELTA activity level."""
    payload = DELTA_MODULE_BASE_BYTES + 2 * k
    return rate_mbit * 1_000_000.0 / (8.0 * payload * frequency_hz)


def periodic_reference_q(frequency_hz, period_s=DELTA_SYNC_PERIOD_SECONDS):
    """Nominal periodic-only fraction; q_other=0, not an observed fraction.

    This continuous-cycle approximation uses min(1, 1/(f*T)), not the exact
    regular-scan rule 1/ceil(f*T). q=0 at f=0 denotes no produced frames.
    Other ESKF events reset the firmware timer, so do not add an independent
    fixed periodic fraction to an assumed other-event fraction.
    """
    frequency = np.asarray(frequency_hz, dtype=float)
    if not np.isfinite(period_s) or period_s <= 0 or np.any(~np.isfinite(frequency)) or np.any(frequency < 0):
        raise ValueError("Require finite f >= 0 and T > 0")
    inverse = np.divide(1.0, frequency * period_s, out=np.zeros_like(frequency), where=frequency > 0)
    return np.minimum(1.0, inverse)


def mean_delta_module_bytes(k_d, q):
    """Mean encoded bytes; K_D is conditional on ESKD, q counts all ESKF.

    An ESKF replaces an ESKD in the same round; it is not an extra frame.
    Event causes must be mutually exclusive if q is decomposed by cause.
    """
    k_d, q = np.asarray(k_d, dtype=float), np.asarray(q, dtype=float)
    if np.any(~np.isfinite(k_d)) or np.any((k_d < 0) | (k_d > 480)):
        raise ValueError("Require finite 0 <= mean K_D <= 480")
    if np.any(~np.isfinite(q)) or np.any((q < 0) | (q > 1)):
        raise ValueError("Require finite 0 <= total ESKF fraction q <= 1")
    return (1.0-q) * (DELTA_MODULE_BASE_BYTES+2*k_d) + 1044*q


def mean_delta_frame_bytes(n, k_d, q, m=None):
    return round_overhead_bytes(configured_slots(n, m)) + np.asarray(n)*mean_delta_module_bytes(k_d, q)


def mean_host_spi_delta_round_bytes(n, k_d, q):
    return np.asarray(n)*mean_delta_module_bytes(k_d, q)


def mean_host_spi_crossing_modules(frequency_hz, rate_mbit, k_d, q):
    """Average raw-clock budget crossing, not a per-round deadline guarantee."""
    if frequency_hz <= 0 or rate_mbit <= 0:
        raise ValueError("Crossings require positive frequency and link rate")
    return float(rate_mbit*1e6/(8*frequency_hz*mean_delta_module_bytes(k_d, q)))


def save(fig: plt.Figure, filename: str) -> None:
    fig.tight_layout()
    fig.savefig(EXPORT_DIR / filename, bbox_inches="tight")
    plt.close(fig)


def save_report(fig: plt.Figure, stem: str) -> None:
    """Preserve the layout and physical canvas size in PNG and editable PDF."""
    png_path = EXPORT_DIR / f"{stem}.png"
    fig.savefig(png_path, dpi=300, facecolor="white", transparent=False)
    # Matplotlib may retain an alpha channel even for an opaque white canvas.
    # Convert the delivered raster explicitly so the report figures are RGB.
    with Image.open(png_path) as image:
        if image.mode != "RGB":
            image.convert("RGB").save(png_path, dpi=(300, 300))
    pdf_path = EXPORT_DIR / f"{stem}.pdf"
    fig.savefig(pdf_path, dpi=300, facecolor="white", transparent=False)
    REPORT_FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, REPORT_FIGURE_DIR / pdf_path.name)
    plt.close(fig)


def trim_white_margins(image: Image.Image, threshold: int = 248, pad: int = 18) -> Image.Image:
    """Remove unused white margins before a standalone panel is composed."""
    rgb = np.asarray(image.convert("RGB"))
    content = np.any(rgb < threshold, axis=2)
    if not np.any(content):
        return image
    rows, columns = np.where(content)
    left = max(int(columns.min()) - pad, 0)
    top = max(int(rows.min()) - pad, 0)
    right = min(int(columns.max()) + pad + 1, image.width)
    bottom = min(int(rows.max()) + pad + 1, image.height)
    return image.crop((left, top, right, bottom))


def write_table(name: str, fields: list[str], rows) -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    with (TABLE_DIR / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows(rows)


def heading(fig, title: str, subtitle: str) -> None:
    fig.text(0.055, 0.963, title, fontsize=21, fontweight="medium", va="top")
    fig.text(0.055, 0.918, subtitle, fontsize=10.5, color=SLATE_BLUE, va="top")


def style_axis(ax, *, labelsize=None, ticksize=None) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.65)
    ax.set_axisbelow(True)
    if ticksize is not None:
        ax.tick_params(axis="both", which="major", labelsize=ticksize)
    if labelsize is not None:
        ax.xaxis.label.set_size(labelsize)
        ax.yaxis.label.set_size(labelsize)


def style_figure_43_3d(ax) -> None:
    """Increase 3-D axis typography used by the Figure 4.3 source panels."""
    ax.tick_params(axis="both", which="major", labelsize=FIGURE_43_TICK_SIZE)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.label.set_fontsize(FIGURE_43_AXIS_LABEL_SIZE)
        for label in axis.get_ticklabels():
            label.set_fontsize(FIGURE_43_TICK_SIZE)


def frame_payload_mean(records: list[dict]) -> float:
    """Pooled per-module payload, including sync frames, calibrated at N=4."""
    if not records or any(module_count(r) != 4 for r in records):
        raise ValueError("Projection requires explicit N=4 calibration records")
    frames = sum(int(r["complete_mul_count"]) for r in records)
    total_bytes = sum(int(r["recorded_bytes"]) for r in records)
    return (total_bytes / frames - float(round_overhead_bytes(4))) / 4


def full_200_records(records: list[dict]) -> list[dict]:
    return [
        r for r in records
        if algorithm(r) == "FULL"
        and int(condition(r).get("target_scan_rate_hz", 0)) == 200
    ]


def delta_records(records: list[dict]) -> list[dict]:
    return [r for r in records if algorithm(r) == "DELTA"]


def group_mean(records: list[dict], key) -> dict:
    grouped = defaultdict(list)
    for record in records:
        grouped[key(record)].append(mbit_rate(record))
    return {k: float(np.mean(v)) for k, v in grouped.items() if v}


def make_protocol_flow() -> None:
    fig, ax = plt.subplots(figsize=(12, 3.3))
    ax.axis("off")
    boxes = [
        (0.03, "FSR acquisition\nSTM32"),
        (0.25, "Host SPI\nDELTA payload"),
        (0.47, "Teensy bridge\nMUL assembly"),
        (0.69, "USB serial\nlogical payload"),
        (0.91, "PC parser\nmetrics + plots"),
    ]
    colors = [PALE_TEAL, PALE_LAVENDER, PALE_MINT, PALE_TEAL, PALE_LAVENDER]
    for (x, label), color in zip(boxes, colors):
        ax.text(
            x, 0.5, label, ha="center", va="center", fontsize=12,
            bbox={"boxstyle": "round,pad=0.65", "facecolor": color,
                  "edgecolor": DARK_CHARCOAL, "linewidth": 1.2},
            transform=ax.transAxes,
        )
    for (x1, _), (x2, _) in zip(boxes[:-1], boxes[1:]):
        ax.annotate(
            "", xy=(x2 - 0.075, 0.5), xytext=(x1 + 0.075, 0.5),
            xycoords=ax.transAxes, textcoords=ax.transAxes,
            arrowprops={"arrowstyle": "->", "lw": 1.4, "color": DARK_CHARCOAL},
        )
    ax.text(0.375, 0.13, "FULL: complete FSR values", ha="center", transform=ax.transAxes,
            color=TEAL_CYAN, fontsize=10)
    ax.text(0.69, 0.86, "DELTA: masks + changed values", ha="center", transform=ax.transAxes,
            color=DEEP_TEAL, fontsize=10)
    ax.set_title("Data path used for the scalability evaluation", pad=12)
    save(fig, "01_protocol_data_path.png")


def usb_models():
    return [
        ("FULL / mean DELTA K_D=480", lambda n, f=CROSS_SECTION_HZ: full_frame_bytes(n), FULL_COLOR, "-"),
        ("Mean DELTA K_D=240", lambda n, f=CROSS_SECTION_HZ: mean_delta_frame_bytes(n, 240, periodic_reference_q(f)), K240_LAVENDER, "--"),
        ("Mean DELTA K_D=0", lambda n, f=CROSS_SECTION_HZ: mean_delta_frame_bytes(n, 0, periodic_reference_q(f)), DELTA_COLOR, "-."),
    ]


def spi_references():
    return [
        (SPI_CURRENT_MBIT, SLATE_BLUE, "10 MHz tested setting: 10 Mbit/s raw", ":"),
        (SPI_REFERENCE_MBIT, SPI_COLOR, "40 MHz untested reference: 40 Mbit/s raw", "--"),
    ]


def link_3d_axis(fig, zlabel, n_max=MAX_MODULES, z_max=630, z_ticks=None):
    if z_ticks is None:
        z_ticks = [0, 150, 300, 450, 600]
    if n_max >= 100:
        x_ticks = [1, 25, 50, 75, 100]
    elif n_max <= 10:
        x_ticks = sorted(set([1, 2, 4, 6, 8, n_max]))
    else:
        x_ticks = sorted(set([1, 5, 10, 15, n_max]))
    ax = fig.add_axes([0.06, 0.235, 0.86, 0.63], projection="3d")
    ax.set(xlim=(1, n_max), ylim=(0, MAX_FREQUENCY_HZ), zlim=(0, z_max),
           xticks=x_ticks, yticks=[0, 200, 400, 700], zticks=z_ticks)
    ax.set_xlabel("Active modules, N", labelpad=13)
    ax.set_ylabel("Round frequency, f (Hz)", labelpad=13)
    ax.set_zlabel(zlabel, labelpad=13)
    ax.set_box_aspect((1.5, 1.05, 0.9), zoom=1.04)
    ax.view_init(elev=24, azim=-133)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.set_pane_color((0.98, 0.985, 0.99, 0.5))
    return ax


def reference_plane(ax, level, color, linestyle, n_max=MAX_MODULES):
    px, py = np.meshgrid([1, n_max], [0, MAX_FREQUENCY_HZ])
    ax.plot_surface(px, py, np.full_like(px, level, dtype=float),
                    color=color, alpha=0.065, shade=False)
    ax.plot([1, n_max, n_max, 1, 1],
            [0, 0, MAX_FREQUENCY_HZ, MAX_FREQUENCY_HZ, 0], [level] * 5,
            color=color, linestyle=linestyle, linewidth=1.6)


def projection_marker(ax, n, rate, color):
    ax.vlines(n, 0, rate, color=color, linestyles=(0, (3, 3)),
              linewidth=1.3, alpha=0.85, zorder=4)
    ax.scatter([n], [rate], color=color, s=40, edgecolors="white",
               linewidths=0.8, zorder=5)
    ax.plot(n, 0, marker="v", color=color, markersize=5,
            clip_on=False, zorder=5)


def marked_xticks(ax, normal_ticks, crossings):
    ticks = sorted([*normal_ticks, *crossings])
    ax.set_xticks(ticks, [f"{n:.2f}" if n in crossings else f"{n:g}" for n in ticks])
    for n, label in zip(ticks, ax.get_xticklabels()):
        if n in crossings:
            label.set_color(crossings[n])
            label.set_fontweight("bold")


def usb_legend(fig, *, fontsize=FIGURE_43_LEGEND_SIZE):
    handles = [Line2D([], [], color=color, linestyle=ls, label=name)
               for name, _, color, ls in usb_models()]
    handles.append(Line2D([], [], color=USB_COLOR, linestyle=":",
                          label="USB 2.0 HS: 480 Mbit/s raw signaling"))
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.08),
                ncol=2, columnspacing=2.3, handlelength=2.9, fontsize=fontsize)
    fig.text(0.5, 0.043,
             "Nominal periodic ESKF only: T=1 s; q=min(1,1/fT); q_other=0. Continuous-cycle approximation.",
             ha="center", fontsize=9.5, color=SLATE_BLUE)
    fig.text(0.5, 0.021,
             "H(M) = 24 + 4M B; N <= M. Current M = 4; N > 4 uses M = max(4, N) as extrapolation.",
             ha="center", fontsize=9.5, color=SLATE_BLUE)


def write_usb_theory_table(name, modules, frequencies):
    write_table(name,
        ["N", "M_configured_slots", "frequency_Hz", "FULL_Mbit_s", "DELTA_K0_Mbit_s",
         "DELTA_K240_Mbit_s", "DELTA_K480_Mbit_s", "USB_raw_Mbit_s", "q_ESKF_total", "T_sync_s",
         "DELTA_K0_no_ESKF_bound_Mbit_s", "DELTA_K240_no_ESKF_bound_Mbit_s", "DELTA_K480_no_ESKF_bound_Mbit_s"],
        ([int(n), int(minimum_configured_slots(n)), int(f), float(theoretical_mbit(full_frame_bytes(n), f)),
          *[float(theoretical_mbit(mean_delta_frame_bytes(n, k, periodic_reference_q(f)), f)) for k in (0, 240, 480)],
          USB_REFERENCE_MBIT, float(periodic_reference_q(f)), DELTA_SYNC_PERIOD_SECONDS,
          *[float(theoretical_mbit(delta_frame_bytes(n, k), f)) for k in (0, 240, 480)]]
         for n in modules for f in frequencies))


def make_usb_3d():
    modules = np.arange(1, MAX_MODULES + 1)
    frequencies = np.arange(0, MAX_FREQUENCY_HZ + 1, 25)
    ng, fg = np.meshgrid(modules, frequencies)
    with plt.style.context(STYLE_PATH):
        fig = plt.figure(figsize=(12.6, 9.0))
        heading(fig, "02A  USB: theoretical application-data demand",
                "N = 1–100  |  f = 0–700 Hz  |  MUL1 framing included")
        ax = link_3d_axis(fig, "USB application demand (Mbit/s)")
        style_figure_43_3d(ax)
        for _, fn, color, ls in usb_models():
            ax.plot_surface(ng, fg, theoretical_mbit(fn(ng, fg), fg), color=color,
                            alpha=0.23, rstride=2, cstride=5, linewidth=0.2,
                            edgecolor=color, shade=False, antialiased=True)
            ax.plot(modules, np.full_like(modules, MAX_FREQUENCY_HZ),
                    theoretical_mbit(fn(modules, MAX_FREQUENCY_HZ), MAX_FREQUENCY_HZ),
                    color=color, linewidth=2.2, linestyle=ls)
        reference_plane(ax, USB_REFERENCE_MBIT, USB_COLOR, ":")
        usb_legend(fig)
        save_report(fig, "02_usb_theoretical_3d")
    write_usb_theory_table("02_usb_theoretical_3d.csv", modules, frequencies)


def make_usb_200hz():
    modules = np.arange(1, USB_SECTION_MAX_MODULES + 1)
    with plt.style.context(STYLE_PATH):
        fig = plt.figure(figsize=(12.6, 9.0))
        heading(fig, "02B  USB: 200 Hz demand across 700 modules",
                "N = 1–700  |  fixed round frequency = 200 Hz  |  theoretical demand, not achieved throughput")
        ax = fig.add_axes([0.095, 0.265, 0.84, 0.60])
        for _, fn, color, ls in usb_models():
            y = theoretical_mbit(fn(modules), CROSS_SECTION_HZ)
            ax.plot(modules, y, color=color, linestyle=ls, linewidth=2.5)
            near_reference = abs(y[-1] - USB_REFERENCE_MBIT) < 50
            ax.annotate(f"{y[-1]:.1f}", (modules[-1], y[-1]),
                        xytext=(-6, -10 if near_reference else 7),
                        textcoords="offset points", ha="right",
                        va="top" if near_reference else "bottom", color=color,
                        fontsize=FIGURE_43_ANNOTATION_SIZE)
        ax.axhline(USB_REFERENCE_MBIT, color=USB_COLOR, linestyle=":", linewidth=1.8)
        ax.text(USB_SECTION_MAX_MODULES - 5, USB_REFERENCE_MBIT + 13, "480 Mbit/s", ha="right",
                color=USB_COLOR, fontsize=FIGURE_43_ANNOTATION_SIZE)
        crossings = {}
        for _, fn, color, _ in usb_models():
            payload = float(fn(1) - round_overhead_bytes(CURRENT_CONFIGURED_SLOTS))
            crossing = usb_crossing_modules(payload, CROSS_SECTION_HZ, USB_REFERENCE_MBIT)
            if 1 <= crossing <= USB_SECTION_MAX_MODULES:
                projection_marker(ax, crossing, USB_REFERENCE_MBIT, color)
                crossings[crossing] = color
        marked_xticks(ax, [1, 100, 200, 400, 600, 700], crossings)
        ax.set(xlim=(1, USB_SECTION_MAX_MODULES), ylim=(0, 1300),
               yticks=[0, 300, 600, 900, 1200],
               xlabel="Active modules, N", ylabel="USB application demand (Mbit/s)")
        style_axis(ax, labelsize=FIGURE_43_AXIS_LABEL_SIZE,
                   ticksize=FIGURE_43_TICK_SIZE)
        ax.text(0.025, 0.96,
                "The marked N is a raw-rate reference crossing,\nnot an achievable module-capacity claim.",
                transform=ax.transAxes, va="top", color=SLATE_BLUE,
                fontsize=FIGURE_43_ANNOTATION_SIZE)
        usb_legend(fig)
        save_report(fig, "02b_usb_theoretical_200hz")
    write_usb_theory_table("02b_usb_theoretical_200hz.csv", modules, [CROSS_SECTION_HZ])


def make_delta_usb_k_overview() -> None:
    """Plot the 200-Hz USB DELTA model against changed-cell count."""
    modules = np.arange(1, MAX_MODULES + 1)
    k_values = np.arange(0, 481)
    n_grid, k_grid = np.meshgrid(modules, k_values)
    q_reference = periodic_reference_q(CROSS_SECTION_HZ)
    delta_surface = theoretical_mbit(
        mean_delta_frame_bytes(n_grid, k_grid, q_reference), CROSS_SECTION_HZ
    )
    full_surface = theoretical_mbit(
        full_frame_bytes(n_grid), CROSS_SECTION_HZ
    )
    full_max = float(np.max(full_surface))
    z_max = full_max * 1.08
    z_tick_max = int(np.ceil(z_max / 50.0) * 50)
    selected = [(1, FULL_COLOR), (25, DELTA_COLOR),
                (50, FIGURE_44_SURFACE_START), (100, DARK_CHARCOAL)]

    with plt.style.context(STYLE_PATH):
        fig = plt.figure(figsize=(13.8, 7.8), facecolor="white")
        grid = fig.add_gridspec(
            1, 2, left=0.045, right=0.985, bottom=0.18, top=0.95,
            width_ratios=[1.16, 0.84], wspace=0.12,
        )
        surface_axis = fig.add_subplot(grid[0], projection="3d")
        curve_axis = fig.add_subplot(grid[1])
        curve_position = curve_axis.get_position()
        curve_height = curve_position.height * 0.80
        curve_axis.set_position([
            curve_position.x0,
            curve_position.y0 + (curve_position.height - curve_height) / 2.0,
            curve_position.width,
            curve_height,
        ])

        surface_axis.plot_surface(
            n_grid, k_grid, delta_surface,
            cmap=figure_44_surface_cmap(), alpha=0.58, rstride=8, cstride=4,
            linewidth=0, edgecolor="none", shade=False,
            antialiased=True,
        )
        surface_axis.set(
            xlim=(0, MAX_MODULES), ylim=(0, 480), zlim=(0, z_max),
            xticks=[0, 25, 50, 75, 100],
            yticks=[0, 120, 240, 360, 480],
            zticks=list(range(0, z_tick_max + 1, 50)),
            xlabel="Active modules, N",
            ylabel=r"Mean ESKD activity, $\overline{K}_D$",
            zlabel="Mean USB demand at 200 Hz (Mbit/s)",
        )
        surface_axis.view_init(elev=27, azim=-132)
        surface_axis.set_box_aspect((1.45, 1.0, 0.9), zoom=1.02)
        for axis in (surface_axis.xaxis, surface_axis.yaxis, surface_axis.zaxis):
            axis.set_pane_color((1.0, 1.0, 1.0, 1.0))
        surface_axis.text2D(
            0.015, 0.975, "(a)", transform=surface_axis.transAxes,
            ha="left", va="top", fontsize=13, color=DARK_CHARCOAL,
        )

        for n, color in selected:
            delta_curve = theoretical_mbit(
                mean_delta_frame_bytes(n, k_values, q_reference), CROSS_SECTION_HZ
            )
            full_value = float(theoretical_mbit(full_frame_bytes(n), CROSS_SECTION_HZ))
            curve_axis.plot(
                k_values, delta_curve, color=color, linewidth=2.2,
            )
            curve_axis.axhline(
                full_value, color=color, linestyle=(0, (4, 3)),
                linewidth=1.05, alpha=0.60,
            )
            curve_axis.scatter(
                [480], [full_value], color=color, s=26,
                edgecolors="white", linewidths=0.8, zorder=5,
            )
            curve_axis.annotate(
                f"N={n} | FULL={full_value:.2f} Mbit/s",
                xy=(480, full_value), xytext=(-7, 7),
                textcoords="offset points", ha="right", va="bottom",
                color=color, fontsize=10,
            )
        curve_axis.set(
            xlabel=r"Mean ESKD activity, $\overline{K}_D$",
            ylabel="Mean USB demand at 200 Hz (Mbit/s)",
            xlim=(0, 480), ylim=(0, full_max * 1.16),
            xticks=[0, 120, 240, 360, 480],
        )
        curve_axis.text(
            0.015, 0.82, "(b)", transform=curve_axis.transAxes,
            ha="left", va="top", fontsize=13, color=DARK_CHARCOAL,
        )
        style_axis(curve_axis)
        curve_axis.legend(
            handles=[
                Line2D([], [], color=DARK_CHARCOAL, linewidth=2.2,
                       label="solid: mean DELTA, q=0.005"),
                Line2D([], [], color=DARK_CHARCOAL, linewidth=1.2,
                       linestyle=(0, (4, 3)), alpha=0.60,
                       label="dashed: current FULL reference"),
            ], loc="upper left", frameon=False, fontsize=10.5,
        )
        fig.legend(
            handles=[
                Line2D([], [], color=FIGURE_44_SURFACE_START, linewidth=2.3,
                       label="Mean DELTA: nominal periodic ESKF only (T=1 s, q_other=0)"),
            ], loc="lower center", bbox_to_anchor=(0.34, 0.045),
             ncol=1, frameon=False, fontsize=9.5,
        )
        fig.text(0.5, 0.015,
                 "H(M) = 24 + 4M B; N <= M. Current M = 4; N > 4 uses M = max(4, N) as extrapolation.",
                 ha="center", fontsize=10.0, color=SLATE_BLUE)
        save_report(fig, "02e_delta_usb_k_overview_200hz")

    write_table(
        "02e_delta_usb_k_overview_200hz.csv",
         ["N", "M_configured_slots", "mean_K_D_per_ESKD", "frequency_Hz", "DELTA_USB_Mbit_s", "FULL_USB_Mbit_s",
          "q_ESKF_total", "T_sync_s", "DELTA_no_ESKF_bound_USB_Mbit_s"],
        (
            [int(n), int(minimum_configured_slots(n)), int(k), CROSS_SECTION_HZ,
              float(theoretical_mbit(mean_delta_frame_bytes(n, k, q_reference), CROSS_SECTION_HZ)),
              float(theoretical_mbit(full_frame_bytes(n), CROSS_SECTION_HZ)), float(q_reference), DELTA_SYNC_PERIOD_SECONDS,
              float(theoretical_mbit(delta_frame_bytes(n, k), CROSS_SECTION_HZ))]
            for n in modules for k in k_values
        ),
    )


def spi_legend(fig, *, fontsize=FIGURE_43_LEGEND_SIZE):
    handles = [Line2D([], [], color=DELTA_COLOR, linestyle="-.",
                      label="Mean DELTA, K_D=0"),
               Line2D([], [], color=K240_LAVENDER, linestyle="--",
                      label="Mean DELTA, K_D=240"),
               Line2D([], [], color=FULL_COLOR, linestyle="-",
                      label="FULL / mean DELTA K_D=480")]
    handles.extend(Line2D([], [], color=color, linestyle=ls, label=label)
                   for _, color, label, ls in spi_references())
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.08),
                ncol=2, columnspacing=2.3, handlelength=2.9, fontsize=fontsize)
    fig.text(0.5, 0.043,
             "Nominal periodic ESKF only: T=1 s; q=min(1,1/fT); q_other=0. Continuous-cycle approximation.",
             ha="center", fontsize=9.5, color=SLATE_BLUE)
    fig.text(0.5, 0.021,
             "Mean SCK budget; no gaps, software or retries. FULL bursts may exceed a round deadline. N>4: extrapolation.",
             ha="center", fontsize=9.3, color=SLATE_BLUE)


def make_figure_02_overview():
    """Create a title-free 2x2 overview with only (a)–(d) panel labels."""
    stems = [
        "02_usb_theoretical_3d",
        "02b_usb_theoretical_200hz",
        "02c_host_spi_theoretical_3d",
        "02d_host_spi_theoretical_200hz",
    ]
    images = []
    for stem in stems:
        with Image.open(EXPORT_DIR / f"{stem}.png") as image:
            images.append(trim_white_margins(image.convert("RGB")))
    left_width = max(images[0].width, images[2].width)
    right_width = max(images[1].width, images[3].width)
    row_heights = [max(images[0].height, images[1].height),
                   max(images[2].height, images[3].height)]
    # Mask the title/subtitle band in each standalone panel while preserving
    # the original panel geometry; the report caption carries the descriptions.
    with plt.style.context(STYLE_PATH):
        fig = plt.figure(figsize=(12.6, 9.0), dpi=600, facecolor="white")
        overview_grid = fig.add_gridspec(
            2, 2, left=0.045, right=0.985, bottom=0.0, top=1.0,
            width_ratios=[left_width, right_width], height_ratios=row_heights,
            wspace=0.12, hspace=0.0,
        )
        for index, image in enumerate(images):
            ax = fig.add_subplot(overview_grid[index // 2, index % 2])
            # Keep each source panel's aspect ratio; do not independently
            # compress its height to fit a common rectangular cell.
            ax.imshow(image, aspect="equal")
            ax.add_patch(Rectangle(
                (0.0, 0.86), 1.0, 0.14, transform=ax.transAxes,
                facecolor="white", edgecolor="none", zorder=3,
            ))
            ax.text(
                0.018, 0.955, f"({chr(ord('a') + index)})",
                transform=ax.transAxes, ha="left", va="top",
                fontsize=16, color=DARK_CHARCOAL, zorder=4,
            )
            ax.axis("off")
        png_path = EXPORT_DIR / "02_four_panel_overview.png"
        pdf_path = EXPORT_DIR / "02_four_panel_overview.pdf"
        fig.savefig(png_path, dpi=600, facecolor="white", transparent=False)
        fig.savefig(pdf_path, dpi=300, facecolor="white", transparent=False)
        with Image.open(png_path) as image:
            if image.mode != "RGB":
                image.convert("RGB").save(png_path, dpi=(600, 600))
        REPORT_FIGURE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf_path, REPORT_FIGURE_DIR / pdf_path.name)
        plt.close(fig)


def write_spi_table(name, modules, frequencies):
    write_table(name,
                ["N", "frequency_Hz", "DELTA_K0_SPI_Mbit_s",
                 "DELTA_K240_SPI_Mbit_s", "DELTA_K480_SPI_Mbit_s",
                  "configured_raw_Mbit_s", "hypothetical_raw_Mbit_s", "q_ESKF_total", "T_sync_s",
                  "DELTA_K0_no_ESKF_bound_SPI_Mbit_s", "DELTA_K240_no_ESKF_bound_SPI_Mbit_s", "DELTA_K480_no_ESKF_bound_SPI_Mbit_s"],
                ([int(n), int(f),
                   *[float(theoretical_mbit(mean_host_spi_delta_round_bytes(n, k, periodic_reference_q(f)), f)) for k in (0, 240, 480)],
                   SPI_CURRENT_MBIT, SPI_REFERENCE_MBIT, float(periodic_reference_q(f)), DELTA_SYNC_PERIOD_SECONDS,
                   *[float(theoretical_mbit(host_spi_delta_round_bytes(n, k), f)) for k in (0, 240, 480)]]
                 for n in modules for f in frequencies))


def make_host_spi_3d():
    modules = np.arange(1, HOST_SPI_3D_MAX_MODULES + 1)
    frequencies = np.arange(0, MAX_FREQUENCY_HZ + 1, 25)
    ng, fg = np.meshgrid(modules, frequencies)
    with plt.style.context(STYLE_PATH):
        fig = plt.figure(figsize=(12.6, 9.0))
        heading(fig, "02C  Host SPI: mean DELTA demand",
                "N = 1–10  |  f = 0–700 Hz  |  ESKD / ESKF mixture; no padding or MUL1 wrapper")
        ax = link_3d_axis(fig, "Host SPI demand (Mbit/s)", n_max=HOST_SPI_3D_MAX_MODULES,
                          z_max=75, z_ticks=[0, 25, 50, 75])
        style_figure_43_3d(ax)
        for k, color, ls in [(0, DELTA_COLOR, "-."), (240, K240_LAVENDER, "--"),
                             (480, FULL_COLOR, "-")]:
            ax.plot_surface(ng, fg, theoretical_mbit(mean_host_spi_delta_round_bytes(ng, k, periodic_reference_q(fg)), fg),
                            color=color, alpha=0.20, rstride=2, cstride=2,
                            linewidth=0.2, edgecolor=color, shade=False)
            ax.plot(modules, np.full_like(modules, MAX_FREQUENCY_HZ),
                    theoretical_mbit(mean_host_spi_delta_round_bytes(modules, k, periodic_reference_q(MAX_FREQUENCY_HZ)), MAX_FREQUENCY_HZ),
                    color=color, linestyle=ls, linewidth=2.0)
        for rate, color, _, ls in spi_references():
            reference_plane(ax, rate, color, ls, n_max=HOST_SPI_3D_MAX_MODULES)
        spi_legend(fig)
        save_report(fig, "02c_host_spi_theoretical_3d")
    write_spi_table("02c_host_spi_theoretical_3d.csv", modules, frequencies)


def make_host_spi_200hz():
    modules = np.arange(1, HOST_SPI_SECTION_MAX_MODULES + 1)
    refs = spi_references()
    with plt.style.context(STYLE_PATH):
        fig = plt.figure(figsize=(12.6, 9.0))
        heading(fig, "02D  Host SPI: 200 Hz mean DELTA demand",
                "N = 1–30  |  nominal periodic reference q=0.005  |  no padding or MUL1 wrapper")
        ax = fig.add_axes([0.095, 0.265, 0.84, 0.60])
        for k, color, ls in [(0, DELTA_COLOR, "-."), (240, K240_LAVENDER, "--"),
                             (480, FULL_COLOR, "-")]:
            curve = theoretical_mbit(mean_host_spi_delta_round_bytes(modules, k, periodic_reference_q(CROSS_SECTION_HZ)), CROSS_SECTION_HZ)
            ax.plot(modules, curve, color=color, linestyle=ls, linewidth=2.3)
            ax.annotate(f"{curve[-1]:.1f}", (modules[-1], curve[-1]), xytext=(-6, 7),
                        textcoords="offset points", ha="right", color=color,
                        fontsize=FIGURE_43_ANNOTATION_SIZE)
        for rate, color, _, ls in refs:
            ax.axhline(rate, color=color, linestyle=ls, linewidth=1.6)
            ax.text(HOST_SPI_SECTION_MAX_MODULES - 0.3, rate + 1.3, f"{rate:g} Mbit/s",
                    ha="right", color=color, fontsize=FIGURE_43_ANNOTATION_SIZE)
        ax.set(xlim=(1, HOST_SPI_SECTION_MAX_MODULES), ylim=(0, 56),
               xticks=[1, 5, 10, 15, 20, 25, 30], yticks=[0, 10, 20, 30, 40, 50],
               xlabel="Active modules, N", ylabel="Host SPI demand (Mbit/s)")
        style_axis(ax, labelsize=FIGURE_43_AXIS_LABEL_SIZE,
                   ticksize=FIGURE_43_TICK_SIZE)
        crossings = {}
        for rate, color, _, ls in refs:
            for k, curve_color in [(0, DELTA_COLOR), (240, K240_LAVENDER), (480, FULL_COLOR)]:
                n = mean_host_spi_crossing_modules(CROSS_SECTION_HZ, rate, k, periodic_reference_q(CROSS_SECTION_HZ))
                if 1 <= n <= HOST_SPI_SECTION_MAX_MODULES:
                    ax.axvline(n, color=curve_color, linestyle=(0, (3, 3)),
                               linewidth=0.9, alpha=0.55)
                    projection_marker(ax, n, rate, curve_color)
                    crossings[n] = curve_color
        # Keep normal ticks separate from the 40 MHz crossing (N≈23.95).
        marked_xticks(ax, [1, 5, 10, 15, 20, 30], crossings)
        spi_legend(fig)
        save_report(fig, "02d_host_spi_theoretical_200hz")
    write_spi_table("02d_host_spi_theoretical_200hz.csv", modules, [CROSS_SECTION_HZ])


def make_link_theory_figures():
    make_usb_3d()
    make_usb_200hz()
    make_host_spi_3d()
    make_host_spi_200hz()
    make_figure_02_overview()
    make_delta_usb_k_overview()
    crossings = []
    fields = ["link", "model", "frequency_Hz", "reference", "raw_Mbit_s",
               "continuous_N", "integer_modules_at_reference", "payload_B_per_module",
               "mean_K_D_per_ESKD", "within_figure_domain", "M_policy", "assumptions", "q_ESKF_total", "q_basis", "T_sync_s"]
    slot_policy = "current M=4; extrapolation uses M=max(4,N), N<=M"
    spi_assumptions = ("mean SCK clock budget; no padding; "
                        "no CS setup/hold, IRQ wait, software or retries; "
                        "MOSI command simultaneous; USB envelope excluded; "
                        "current firmware supports 4 modules only; FULL bursts may violate a round deadline")
    cases = [("FULL", None, 1.0, "FULL_every_frame")]
    for q, basis in [(0.0, "no_ESKF_bound"), (float(periodic_reference_q(CROSS_SECTION_HZ)), "nominal_periodic_only")]:
        cases.extend((f"Mean DELTA K_D={k}", k, q, basis) for k in (0, 27, 240, 480))
    links = [("USB", USB_REFERENCE_MBIT, "USB HS raw signaling", USB_SECTION_MAX_MODULES)]
    links.extend(("HOST_SPI", rate, name, HOST_SPI_SECTION_MAX_MODULES) for rate, _, name, _ in spi_references())
    for link, rate, reference, domain in links:
        for label, k, q, basis in cases:
            payload = 1044.0 if k is None else float(mean_delta_module_bytes(k, q))
            n = (usb_crossing_modules(payload, CROSS_SECTION_HZ, rate) if link == "USB"
                 else rate*1e6/(8*payload*CROSS_SECTION_HZ))
            assumptions = ("application mean bytes vs raw signaling; H(M)=24+4M; segmentation overhead excluded; "
                           if link == "USB" else spi_assumptions+"; ")
            assumptions += ("q=0 ordinary-ESKD bound; no ESKF" if basis == "no_ESKF_bound" else
                            "nominal periodic-only reference; q_other=0; continuous-cycle approximation; not measurement"
                            if basis == "nominal_periodic_only" else "FULL every frame")
            crossings.append([link, label, CROSS_SECTION_HZ, reference, rate, n, int(np.floor(n)), payload,
                              "" if k is None else k, 1 <= n <= domain, slot_policy, assumptions,
                              q, basis, DELTA_SYNC_PERIOD_SECONDS])
    write_table("02_bandwidth_intersections_200Hz.csv", fields, crossings)


def make_delta_load_comparison(records: list[dict]) -> None:
    delta = delta_records(records)
    zero = [r for r in delta if "Zero_load" in str(r["_path"])]
    zero_by_n = group_mean(zero, module_count)

    dynamic_groups = {}
    for record in delta:
        load = str(condition(record).get("load_condition", ""))
        n = module_count(record)
        if not load:
            continue
        if "Small-area" in load:
            label = "Small area\nN=1"
        elif "Large-area" in load:
            label = "Large area\nN=1"
        elif "High-frequency" in load:
            label = "High-frequency\nrolling, N=1"
        elif "Full-coverage" in load:
            label = f"Full coverage\nN={n}"
        else:
            continue
        dynamic_groups.setdefault((label, n), []).append(mbit_rate(record))

    items = [("Zero load\nN=1", 1, zero_by_n.get(1)),
             ("Small area\nN=1", 1, None),
             ("Large area\nN=1", 1, None),
             ("High-frequency\nrolling, N=1", 1, None),
             ("Full coverage\nN=2", 2, None),
             ("Full coverage\nN=4", 4, None)]
    values = []
    reductions = []
    for label, n, zero_value in items:
        value = zero_value
        if value is None:
            rows = dynamic_groups.get((label, n), [])
            value = float(np.mean(rows)) if rows else np.nan
        values.append(value)
        full_ref = theoretical_mbit(full_frame_bytes(n), 200)
        reductions.append(100 * (1 - value / full_ref) if np.isfinite(value) else np.nan)

    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    x = np.arange(len(items))
    bars = ax.bar(x, values, color=[K240_LAVENDER, TEAL_CYAN, DEEP_TEAL,
                                    SLATE_BLUE, MINT_GREEN, MUTED_LAVENDER])
    for bar, value, reduction in zip(bars, values, reductions):
        if np.isfinite(value):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.06,
                    f"{value:.3f}\n−{reduction:.1f}%", ha="center", va="bottom", fontsize=8)
    ax.set_title("DELTA USB rate under different change densities")
    ax.set_xlabel("Load condition")
    ax.set_ylabel("Measured USB data rate (Mbit/s)")
    ax.set_xticks(x, [item[0] for item in items])
    ax.set_ylim(0, max(values) * 1.27)
    save(fig, "04_delta_load_comparison.png")


def make_module_scaling(records: list[dict]) -> None:
    full_records = full_200_records(records)
    zero_records = [r for r in delta_records(records) if "Zero_load" in str(r["_path"])]
    dynamic_full = [
        r for r in delta_records(records)
        if "Full-coverage" in str(condition(r).get("load_condition", ""))
    ]
    zero_calibration = [r for r in zero_records if module_count(r) == 4]
    dynamic_calibration = [r for r in dynamic_full if module_count(r) == 4]
    zero_payload = frame_payload_mean(zero_calibration)
    dynamic_payload = frame_payload_mean(dynamic_calibration)
    ns = np.arange(1, MAX_MODULES + 1)
    full_model = theoretical_mbit(full_frame_bytes(ns), 200)
    zero_projection = theoretical_mbit(round_overhead_bytes(minimum_configured_slots(ns)) + ns * zero_payload, 200)
    dynamic_projection = theoretical_mbit(round_overhead_bytes(minimum_configured_slots(ns)) + ns * dynamic_payload, 200)
    observations = [(full_records, FULL_COLOR, "o", "FULL"),
                    (zero_records, DELTA_COLOR, "s", "DELTA: zero load"),
                    (dynamic_full, MID_COLOR, "D", "DELTA: full coverage")]

    with plt.style.context(STYLE_PATH):
        fig = plt.figure(figsize=(14.5, 7.8))
        heading(fig, "Module scaling: observations and conditional projections",
                "Target 200 Hz  |  observed N = 1–4  |  modelled extension to N = 100")
        gs = fig.add_gridspec(1, 2, left=0.065, right=0.97, bottom=0.285, top=0.83,
                             width_ratios=[1.6, 1], wspace=0.24)
        ax = fig.add_subplot(gs[0])
        detail = fig.add_subplot(gs[1])
        ax.axvspan(1, 4, color=PALE_TEAL, alpha=0.5, zorder=0)
        ax.plot(ns, full_model, color=FULL_COLOR, linewidth=2.5)
        ax.plot(ns, zero_projection, color=DELTA_COLOR, linestyle="--", linewidth=2.4)
        ax.plot(ns, dynamic_projection, color=MID_COLOR, linestyle="--", linewidth=2.4)
        for curve, color in [(full_model, FULL_COLOR), (zero_projection, DELTA_COLOR), (dynamic_projection, MID_COLOR)]:
            ax.annotate(f"{curve[-1]:.1f}", (100, curve[-1]), xytext=(-5, 7),
                        textcoords="offset points", color=color, ha="right", fontsize=11)
        ax.set(title="A   1–100 modules: bandwidth demand model", xlabel="Active modules, N",
               ylabel="USB data rate (Mbit/s)", xlim=(1, 100), ylim=(0, 185),
               xticks=[1, 20, 40, 60, 80, 100])
        detail.plot([1, 2, 3, 4], theoretical_mbit(full_frame_bytes(np.arange(1, 5)), 200),
                    color=FULL_COLOR, linestyle=":", linewidth=1.5)
        for group, color, marker, name in observations:
            means = group_mean(group, module_count)
            nx = sorted(means)
            for panel in [ax, detail]:
                panel.scatter(nx, [means[n] for n in nx], s=42, color=color,
                              marker=marker, edgecolors="white", linewidths=0.5, zorder=5)
            detail.scatter([module_count(r) for r in group], [mbit_rate(r) for r in group],
                           s=20, facecolors="none", edgecolors=color, alpha=0.45,
                           marker=marker, linewidths=0.8, zorder=4)
        detail.set(title="B   Observed range: 1–4 modules", xlabel="Active modules, N",
                   ylabel="Measured USB rate (Mbit/s)", xlim=(0.75, 4.25), ylim=(0, 7.2),
                   xticks=[1, 2, 3, 4])
        for panel in [ax, detail]:
            style_axis(panel)
        handles = [Line2D([], [], color=FULL_COLOR, label="FULL: theoretical model"),
                   Line2D([], [], color=DELTA_COLOR, linestyle="--", label="DELTA zero load: projection"),
                   Line2D([], [], color=MID_COLOR, linestyle="--", label="DELTA full coverage: projection"),
                   Line2D([], [], color=FULL_COLOR, marker="o", linestyle="", label="FULL observed"),
                   Line2D([], [], color=DELTA_COLOR, marker="s", linestyle="", label="DELTA zero load observed"),
                   Line2D([], [], color=MID_COLOR, marker="D", linestyle="", label="DELTA full coverage observed")]
        fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.128),
                   ncol=3, handlelength=2.6, columnspacing=1.8)
        fig.text(0.065, 0.09,
                 f"DELTA projections hold the N=4 mean payload constant: {zero_payload:.2f} B/module (zero load), "
                 f"{dynamic_payload:.2f} B/module (full coverage).", fontsize=9, color=SLATE_BLUE)
        fig.text(0.065, 0.062,
                 "Payload means include periodic syncs; projections assume 200 Hz and unchanged activity per module. Beyond N=4 is unmeasured.",
                 fontsize=9, color=SLATE_BLUE)
        fig.text(0.065, 0.034,
                 "Filled markers: arithmetic means of run rates; open markers: individual runs. All recorded runs, including CHECK REQUIRED, are retained.",
                 fontsize=9, color=SLATE_BLUE)
        save_report(fig, "05_module_scaling")

    write_table("05_module_scaling_projection.csv",
                ["N", "assumed_frequency_Hz", "FULL_model_Mbit_s", "DELTA_zero_projection_Mbit_s", "DELTA_full_coverage_projection_Mbit_s"],
                zip(ns, [200] * len(ns), full_model, zero_projection, dynamic_projection))
    write_table("05_module_scaling_observations.csv",
                ["condition", "N", "run_id", "measured_Hz", "USB_Mbit_s", "result", "summary_path"],
                ([label, module_count(r), r["run_id"], r["average_packet_rate_Hz"],
                  mbit_rate(r), r["result"], str(r["_path"].relative_to(FIGURES_DIR.parent))]
                 for group, _, _, label in observations for r in group))


def make_integrity_summary(records: list[dict]) -> None:
    total = len(records)
    passed = sum(str(r.get("result", "")).startswith("PASS") for r in records)
    checked = total - passed
    counter_fields = [
        ("Outer CRC", "outer_crc_errors"),
        ("Inner CRC", "inner_crc_errors"),
        ("Sequence gaps", "sequence_gap_events"),
        ("Lost frames", "lost_frames"),
        ("Duplicate frames", "duplicate_frames"),
        ("Out-of-order", "out_of_order_frames"),
        ("Format errors", "format_errors"),
        ("Delta base mismatch", "delta_base_mismatches"),
    ]
    counts = [sum(int(r.get("counters", {}).get(key, 0)) for r in records) for _, key in counter_fields]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.8), gridspec_kw={"width_ratios": [0.9, 1.6]})
    ax1.bar(["PASS", "CHECK\nREQUIRED"], [passed, checked], color=[DEEP_TEAL, MUTED_LAVENDER])
    ax1.set_title(f"Run status (n={total})")
    ax1.set_ylabel("Number of runs")
    for i, v in enumerate([passed, checked]):
        ax1.text(i, v + 0.5, str(v), ha="center", fontsize=11)

    ax2.barh([label for label, _ in counter_fields], counts, color=SLATE_BLUE)
    ax2.set_title("Accumulated integrity counters")
    ax2.set_xlabel("Count")
    ax2.invert_yaxis()
    for i, v in enumerate(counts):
        ax2.text(v + 0.15, i, str(v), va="center", fontsize=9)
    save(fig, "06_integrity_summary.png")


def make_delta_model() -> None:
    k_values = np.arange(0, 481)
    modules = np.arange(1, MAX_MODULES + 1)
    K, N = np.meshgrid(k_values, modules)
    lengths = delta_frame_bytes(N, K)
    with plt.style.context(STYLE_PATH):
        fig = plt.figure(figsize=(14.5, 7.6))
        heading(fig, "DELTA frame-length model for 100 modules",
                "Ordinary DELTA frames  |  K = changed cells per module  |  decimal kB = 1,000 B")
        gs = fig.add_gridspec(1, 2, left=0.065, right=0.95, bottom=0.255,
                             top=0.835, width_ratios=[1.05, 1], wspace=0.30)
        ax = fig.add_subplot(gs[0])
        curves = fig.add_subplot(gs[1])
        mesh = ax.pcolormesh(k_values, modules, lengths / 1000.0, shading="nearest",
                             cmap=publication_cmap(), vmin=0, vmax=105, rasterized=True)
        ax.set(title="A   All 100 module counts", xlabel="Changed cells per module, K",
               ylabel="Active modules, N", xlim=(0, 480), ylim=(1, 100),
               xticks=[0, 120, 240, 360, 480], yticks=[1, 25, 50, 75, 100])
        cb = fig.colorbar(mesh, ax=ax, pad=0.035, fraction=0.046)
        cb.set_label("Equivalent round size (kB)")
        for n, color, linestyle in [(1, FULL_COLOR, ":"), (25, DELTA_COLOR, "-."),
                                     (50, MID_COLOR, "--"), (100, DARK_CHARCOAL, "-")]:
            y = delta_frame_bytes(n, k_values) / 1000.0
            curves.plot(k_values, y, color=color, linestyle=linestyle, label=f"N={n}", linewidth=2.2)
            curves.annotate(f"N={n}: {y[-1]:.2f}", (480, y[-1]), xytext=(-7, 6),
                            textcoords="offset points", color=color, ha="right", fontsize=10)
        curves.set(title="B   Selected module counts", xlabel="Changed cells per module, K",
                   ylabel="Equivalent round size (kB)", xlim=(0, 480), ylim=(0, 117),
                   xticks=[0, 120, 240, 360, 480])
        style_axis(curves)
        fig.text(0.065, 0.132,
                 r"$L_{\mathrm{DELTA}}(N,K)=24+4\max(4,N)+N(84+2K)\quad\mathrm{B}$", fontsize=14)
        fig.text(0.065, 0.084,
                 "Four module headers are retained for N <= 4; one header per module is assumed for N > 4. Same K is assumed in each module.",
                 fontsize=9, color=SLATE_BLUE)
        fig.text(0.065, 0.053,
                 "At K=480, DELTA equals FULL; K>480 triggers FULL fallback. N>4 is an extended logical-round model, not a current MUL1 packet.",
                 fontsize=9, color=SLATE_BLUE)
        save_report(fig, "07_delta_model_k")
    write_table("07_delta_model_k.csv", ["N", "K_per_module", "round_length_B"],
                ([int(n), int(k), int(delta_frame_bytes(n, k))] for n in modules for k in k_values))


def write_manifest(selected: list[str], records: list[dict]) -> None:
    manifest = {
        "generated_at_UTC": datetime.now(timezone.utc).isoformat(),
        "figures_updated": selected,
        "matplotlib": matplotlib.__version__, "numpy": np.__version__,
        "scope": "General report figure; no target journal specified",
        "axes": {"N": [1, MAX_MODULES], "frequency_Hz": [0, MAX_FREQUENCY_HZ], "K": [0, 480]},
        "figure_02": {
            "layout": "Four independent PNG/PDF figures plus a USB DELTA-versus-K overview; USB and Host SPI are separate links",
            "02A": {"link": "USB", "N": [1, MAX_MODULES], "frequency_Hz": [0, MAX_FREQUENCY_HZ],
                    "stem": "02_usb_theoretical_3d", "references_Mbit_s": [USB_REFERENCE_MBIT]},
            "02B": {"link": "USB", "N": [1, USB_SECTION_MAX_MODULES], "frequency_Hz": CROSS_SECTION_HZ,
                    "stem": "02b_usb_theoretical_200hz", "references_Mbit_s": [USB_REFERENCE_MBIT]},
            "02C": {"link": "HOST_SPI", "N": [1, HOST_SPI_3D_MAX_MODULES], "frequency_Hz": [0, MAX_FREQUENCY_HZ],
                    "stem": "02c_host_spi_theoretical_3d", "references_Mbit_s": [SPI_CURRENT_MBIT, SPI_REFERENCE_MBIT]},
            "02D": {"link": "HOST_SPI", "N": [1, HOST_SPI_SECTION_MAX_MODULES], "frequency_Hz": CROSS_SECTION_HZ,
                    "stem": "02d_host_spi_theoretical_200hz", "references_Mbit_s": [SPI_CURRENT_MBIT, SPI_REFERENCE_MBIT]},
            "02E": {"link": "USB", "N": [0, MAX_MODULES], "K": [0, 480], "frequency_Hz": CROSS_SECTION_HZ,
                    "stem": "02e_delta_usb_k_overview_200hz", "references": "FULL USB demand for each selected N"},
            "overview": {"stem": "02_four_panel_overview", "layout": "02A top-left; 02B top-right; 02C bottom-left; 02D bottom-right"},
            "USB_scope": "Mean ESKD/ESKF mixture plus MUL1 application framing; q=0 bounds separately retained in CSV",
            "HOST_SPI_scope": "Mean encoded ESKD/ESKF bytes; no fixed-slot padding or MUL1 wrapper; gaps/retries excluded",
            "HOST_SPI_Mbit_s": "8*N*((1-q)*(84+2*K_D)+1044*q)*f/1e6",
            "crossings": "Average raw-rate references only; no achieved capacity or per-round deadline guarantee; FULL bursts can be limiting",
        },
        "overhead_B": "H(M) = 24 + 4*M",
        "configured_slots_M": "M is maximum configured slot count; current M=4; require N<=M",
        "extrapolation_M_policy": "M=max(4,N) only for minimum-capacity expansion beyond current firmware",
        "FULL_round_B": "24 + 4*M + 1044*N",
        "DELTA_round_B": "24 + 4*M + N*(84+2*K)",
        "DELTA_ordinary_bound_note": "The ordinary helper and DELTA_round_B retain the q=0 ESKD-only bound; theory figures use the mean model below.",
        "DELTA_mean_round_B": "24+4*M+N*((1-q)*(84+2*K_D)+1044*q)",
        "mean_K_D_definition": "Mean mask popcount conditional on ordinary ESKD, not an effective K inferred from mixed-frame packet length",
        "q_definition": "All ESKF / (ESKF+ESKD); if decomposed, event categories must be mutually exclusive. ESKF replaces ESKD, not an added frame.",
        "periodic_reference": {
            "T_seconds": DELTA_SYNC_PERIOD_SECONDS,
            "q_formula": "q(f)=min(1,1/(f*T)) for f>0; q=0 at f=0 (no frames)",
            "q_at_200Hz": float(periodic_reference_q(CROSS_SECTION_HZ)), "q_other": 0,
            "interpretation": "Illustrative periodic-only nominal reference, not measured q",
            "cycle_approximation": "Continuous cycles replace the regular-scan 1/ceil(f*T) rule; firmware checks elapsed >=1000ms at encoding. Finite-window phase and millisecond quantization are excluded.",
            "timer_reset": "Every ESKF resets the timer; other-event ESKF can replace/defer periodic events, so periodic and other event rates are not independent additive inputs.",
            "attribution": "Current records contain total ESKF q and PC-observed intervals, not a unique per-frame trigger label.",
        },
        "SPI_reference": {"clock_Hz": 40_000_000, "raw_Mbit_s_per_direction": SPI_REFERENCE_MBIT,
                          "source": "User-specified theoretical reference; not hardware-tested and not a proven hardware maximum"},
        "SPI_current": {"clock_Hz": 10_000_000,
                        "source": "hardware/new/firmware/active/four-module-variable-spi/teensy/four_module/four_module.ino: SPI_HZ and two-part SPI.transfer",
                        "validation": "User confirmed successful testing at 10 MHz; no new measurements generated here"},
        "USB_reference": {"raw_Mbit_s": USB_REFERENCE_MBIT, "source": "https://www.pjrc.com/store/teensy41.html",
                          "checked": "2026-09-02", "kind": "USB 2.0 High-Speed signaling, not usable payload throughput"},
        "projection_05": "N=4 pooled per-module mean payload incl. sync frames, held constant to N=100; assumed f=200 Hz",
        "observations_05": "Arithmetic mean rates and every individual recorded run; no QC-based exclusion",
        "new_hardware_measurements": False,
        "current_firmware_limits": "4 modules; 8-bit updated mask; 16-bit MUL1 packet length; current SPI configured at 10 MHz",
        "extrapolation_limits": "N>4 needs firmware/protocol expansion; aggregate byte totals above 65535 need segmentation; its additional overhead is excluded",
        "data_root": str(DATA_DIR),
        "data_sources": [str(r["_path"].relative_to(DATA_DIR)) for r in records],
        "outputs": {"PNG_dpi": 300, "PDF_fonttype": 42, "background": "white"},
    }
    (FIGURES_DIR / "figure_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    global DATA_DIR
    parser = argparse.ArgumentParser(description="Generate the current data scalability report figures")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_DIR,
                        help=f"Measured-data root; no automatic history fallback (default: {DEFAULT_DATA_DIR})")
    parser.add_argument("--figures", nargs="+", choices=["01", "02", "02E", "04", "05", "06", "07"],
                        default=["01", "02", "04", "05", "06", "07"])
    args = parser.parse_args()
    DATA_DIR = args.data_root.resolve()
    needs_measurements = bool(set(args.figures) & {"04", "05", "06"})
    records = load_records() if needs_measurements else []
    if needs_measurements and not records:
        raise SystemExit(f"No summary.json files found under {DATA_DIR}. "
                         "Select a dataset explicitly with --data-root; history is not searched automatically.")
    generators = {"01": make_protocol_flow, "02": make_link_theory_figures,
                  "02E": make_delta_usb_k_overview,
                  "04": lambda: make_delta_load_comparison(records),
                  "05": lambda: make_module_scaling(records),
                  "06": lambda: make_integrity_summary(records), "07": make_delta_model}
    for number in args.figures:
        generators[number]()
    write_manifest(args.figures, records)
    print(f"Generated figures in {EXPORT_DIR}")


if __name__ == "__main__":
    main()
