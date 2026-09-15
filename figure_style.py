"""Shared publication style for the E-SKIN scientific figures.

The palette is deliberately kept in one place so that the same experimental
condition has the same visual identity in every generated figure.  This module
contains presentation settings only; it does not transform or analyse data.
"""

from __future__ import annotations

from contextlib import contextmanager

import matplotlib as mpl
from cycler import cycler


# Canonical muted scientific palette.
# The public names are kept for backwards-compatible imports in the plotting
# scripts; the values are the current project palette requested for the report.
DARK_CHARCOAL = "#596073"
# Figure 4.1/4.2 x-axis override requested for stronger axis definition.
X_AXIS_CHARCOAL = "#3D3539"
TEAL_CYAN = "#7BB6BA"
DEEP_TEAL = "#B8442D"
SLATE_BLUE = "#9D725F"
MINT_GREEN = "#D7BBA5"
MUTED_LAVENDER = "#DBD4CC"
# Figure 4.3's K=240 curve uses this explicit lavender override.
K240_LAVENDER = "#8B84A3"
# Figure 4.4's 3D surface uses this explicit slate-to-mint gradient.
FIGURE_44_SURFACE_START = "#45728F"
FIGURE_44_SURFACE_END = "#8CD1B2"
# Figure 4.7's voltage-drop matrix uses a light-beige-to-teal gradient.
FIGURE_47_DROP_START = "#DBD4CC"
FIGURE_47_DROP_END = "#0F9EA8"

# Descriptive aliases for new code and figure reviews.
TERRACOTTA = DEEP_TEAL
WARM_BROWN = SLATE_BLUE
WARM_TAN = MINT_GREEN
WARM_BEIGE = MUTED_LAVENDER

WHITE = "#FFFFFF"
GRID = "#E8E4DF"
PALE_TEAL = "#EFF7F7"
PALE_MINT = "#F6F0EC"
PALE_LAVENDER = "#F3F0EC"
PALE_GREY = "#FBFAF9"
MUTED_TEXT = SLATE_BLUE
# Neutral grayscale encoding shared by calibration soft-saturation figures.
SOFT_SATURATION_BG = "#E6E6E6"
SATURATION_BG = "#BDBDBD"
SATURATION_LINE = "#7A7A7A"

PALETTE = {
    "dark_charcoal": DARK_CHARCOAL,
    "x_axis_charcoal": X_AXIS_CHARCOAL,
    "teal_cyan": TEAL_CYAN,
    "deep_teal": DEEP_TEAL,
    "slate_blue": SLATE_BLUE,
    "mint_green": MINT_GREEN,
    "muted_lavender": MUTED_LAVENDER,
    "k240_lavender": K240_LAVENDER,
    "figure_44_surface_start": FIGURE_44_SURFACE_START,
    "figure_44_surface_end": FIGURE_44_SURFACE_END,
    "figure_47_drop_start": FIGURE_47_DROP_START,
    "figure_47_drop_end": FIGURE_47_DROP_END,
    "terracotta": TERRACOTTA,
    "warm_brown": WARM_BROWN,
    "warm_tan": WARM_TAN,
    "warm_beige": WARM_BEIGE,
    "white": WHITE,
    "grid": GRID,
    "pale_teal": PALE_TEAL,
    "pale_mint": PALE_MINT,
    "pale_lavender": PALE_LAVENDER,
    "pale_grey": PALE_GREY,
    "soft_saturation_bg": SOFT_SATURATION_BG,
    "saturation_bg": SATURATION_BG,
    "saturation_line": SATURATION_LINE,
}

SERIES_COLORS = (TEAL_CYAN, DEEP_TEAL, SLATE_BLUE, MINT_GREEN, MUTED_LAVENDER)

PUBLICATION_STYLE = {
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.titleweight": "semibold",
    "axes.labelsize": 9,
    "axes.labelcolor": DARK_CHARCOAL,
    "axes.edgecolor": DARK_CHARCOAL,
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.axisbelow": True,
    "axes.facecolor": WHITE,
    "axes.grid": False,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "grid.alpha": 0.65,
    "text.color": DARK_CHARCOAL,
    "xtick.color": DARK_CHARCOAL,
    "ytick.color": DARK_CHARCOAL,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "xtick.major.width": 0.7,
    "ytick.major.width": 0.7,
    "lines.linewidth": 1.6,
    "lines.markersize": 4.5,
    "lines.markeredgewidth": 0.65,
    "legend.frameon": False,
    "legend.fontsize": 8,
    "legend.borderaxespad": 0.2,
    "figure.facecolor": WHITE,
    "figure.edgecolor": WHITE,
    "savefig.dpi": 300,
    "savefig.facecolor": WHITE,
    "savefig.edgecolor": WHITE,
    "savefig.transparent": False,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "svg.fonttype": "none",
    "axes.prop_cycle": cycler(color=SERIES_COLORS),
}


def publication_cmap():
    """Return a sequential map derived from the canonical teal palette."""

    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        "muted_teal",
        [PALE_TEAL, MINT_GREEN, TEAL_CYAN, DEEP_TEAL],
        N=256,
    )


def figure_44_surface_cmap():
    """Return the Figure 4.4 slate-blue to mint-green surface map."""

    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        "figure_44_slate_to_mint",
        [FIGURE_44_SURFACE_START, FIGURE_44_SURFACE_END],
        N=256,
    )


def figure_47_drop_cmap():
    """Return the Figure 4.7 beige-to-teal voltage-drop map."""

    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        "figure_47_beige_to_teal",
        [FIGURE_47_DROP_START, FIGURE_47_DROP_END],
        N=256,
    )


def figure_46_drop_cmap():
    """Return the Figure 4.6 white-to-teal voltage-drop map."""

    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        "figure_46_drop_white_to_teal",
        [WHITE, FIGURE_47_DROP_END],
        N=256,
    )


@contextmanager
def publication_style():
    """Temporarily apply the common publication settings."""

    with mpl.rc_context(PUBLICATION_STYLE):
        yield
