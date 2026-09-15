"""Shared load-equivalent response-region annotations for FSR figures."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any


CALIBRATION_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CALIBRATION_ROOT))
from figure_style import (  # noqa: E402
    SATURATION_BG,
    SATURATION_LINE,
    SOFT_SATURATION_BG,
)


NORMAL_MAX_G = 1200.0
SOFT_SATURATION_MAX_G = 3000.0
# Public alias retained for plotting modules that use the soft-region line
# colour for the connecting segments and boundary markers.
SOFT_SATURATION_COLOR = SATURATION_LINE


def mark_saturation_regions(
    axis: Any,
    x_limits: tuple[float, float] | None = None,
    *,
    lower_boundary: float = NORMAL_MAX_G,
    upper_boundary: float = SOFT_SATURATION_MAX_G,
    lower_label: str = "1200 g",
    upper_label: str = "3000 g",
    orientation: str = "x",
) -> None:
    """Shade normal, soft-saturation, and saturation load-equivalent regions.

    ``lower_boundary`` and ``upper_boundary`` are expressed in the plotted
    coordinate system. For pressure plots the caller converts 1200 g and
    3000 g to the corresponding mean-cell pressure before calling this
    function. The underlying curve is never modified.
    """
    if x_limits is None:
        x_limits = axis.get_xlim() if orientation == "x" else axis.get_ylim()
    low, high = sorted(float(value) for value in x_limits)
    span = axis.axvspan if orientation == "x" else axis.axhspan
    line = axis.axvline if orientation == "x" else axis.axhline

    regions = (
        (max(low, lower_boundary), min(high, upper_boundary),
         f"Soft saturation ({lower_label}–{upper_label})", SOFT_SATURATION_BG, .12),
        (max(low, upper_boundary), high, f"Saturation (>{upper_label})", SATURATION_BG, .10),
    )
    for start, end, label, color, alpha in regions:
        if end <= start:
            continue
        span(
            start, end, facecolor=color, edgecolor="none", alpha=alpha,
            linewidth=0, label=label, zorder=0,
        )

    for boundary, color, style in (
        (lower_boundary, SATURATION_LINE, "--"),
        (upper_boundary, SATURATION_LINE, "-"),
    ):
        if low <= boundary <= high:
            line(
                boundary, color=color, linestyle=style, linewidth=.75,
                label="_nolegend_", zorder=1,
            )
    # Annotation patches must not recursively expand shared-axis limits in
    # the 16x16 per-cell grid (each axvspan otherwise adds another margin).
    if orientation == "x":
        axis.set_xlim(low, high)
    else:
        axis.set_ylim(low, high)


def mark_soft_saturation_region(
    axis: Any,
    x_limits: tuple[float, float] | None = None,
    *,
    lower_boundary: float = NORMAL_MAX_G,
    upper_boundary: float = SOFT_SATURATION_MAX_G,
    label: str = "Soft saturation (1200 g–3000 g)",
) -> None:
    """Mark soft saturation; label saturation only when the data reach it."""
    if x_limits is None:
        x_limits = axis.get_xlim()
    low, high = sorted(float(value) for value in x_limits)
    start = max(low, lower_boundary)
    end = min(high, upper_boundary)
    if end > start:
        axis.axvspan(
            start, end, facecolor=SOFT_SATURATION_BG, edgecolor="none",
            alpha=.12, linewidth=0, label=label, zorder=0,
        )
    if high > upper_boundary:
        axis.axvspan(max(low, upper_boundary), high, color=SATURATION_BG,
                     alpha=.10, linewidth=0, label="Saturation (>3000 g; excluded)", zorder=0)
    for boundary, style in (
        (lower_boundary, "--"),
        (upper_boundary, "-"),
    ):
        if low <= boundary <= high:
            axis.axvline(
                boundary, color=SATURATION_LINE, linestyle=style,
                linewidth=.7, label="_nolegend_", zorder=1,
            )
    axis.set_xlim(low, high)
