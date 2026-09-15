"""Shared data-driven color normalization for the two Power preview heatmaps."""
import numpy as np
from matplotlib.ticker import MaxNLocator


def data_color_scale(values):
    values = np.asarray(list(values), dtype=float).ravel()
    values = values[np.isfinite(values)]
    if not values.size:
        raise ValueError('Cannot normalize a heatmap without finite observations')
    low, high = float(values.min()), float(values.max())
    bounds = (low, high) if low < high else (low - .5, high + .5)
    ticks = MaxNLocator(nbins=6, steps=[1, 2, 2.5, 5, 10], min_n_ticks=4).tick_values(*bounds)
    return dict(data_min=low, data_max=high, vmin=float(ticks[0]), vmax=float(ticks[-1]),
                ticks=[float(t) for t in ticks],
                policy='Linear scale enclosing all plotted values with readable ticks; shared by ZERO and MAX panels in each figure')
