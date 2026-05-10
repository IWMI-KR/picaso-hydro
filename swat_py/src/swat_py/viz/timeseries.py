"""Time-series plot for observed vs. simulated data.

Mirrors graph_swat.R :: Swat.Time.Series.Graph().
"""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_timeseries(
    data: pd.DataFrame,
    tstep: str = "daily",
    is_line: bool = False,
    ylabel: str = "streamflow (cms)",
    ax: Optional[plt.Axes] = None,
) -> plt.Axes:
    """Plot observed (gray fill / line) vs. simulated (dashed line).

    Parameters
    ----------
    data:
        DataFrame with columns: [date/yearmon, obs, sim].
    tstep:
        ``"daily"`` or ``"monthly"``.
    is_line:
        If True, draw observed as a line rather than a filled polygon.
    ylabel:
        Y-axis label.
    ax:
        Existing Axes to draw on; creates one if None.

    Returns
    -------
    Axes object.
    """
    if ax is None:
        _, ax = plt.subplots()

    time_col = data.columns[0]
    obs = data["obs"].values
    sim = data["sim"].values
    n = len(data)
    x = np.arange(1, n + 1)

    ymax = np.nanmax([obs, sim])
    ax.set_ylim(0, ymax * 1.15)
    ax.set_xlim(0, n + 1)

    if is_line:
        ax.plot(x, obs, color="black", linewidth=1, label="observed")
    else:
        ax.fill_between(x, obs, color="gray", alpha=0.7, label="observed")

    ax.plot(x, sim, color="black", linewidth=1, linestyle="--", label="simulated")

    # X-axis tick placement
    if tstep == "daily":
        tick_pos = np.arange(365, n + 1, 365)
        label_pos = tick_pos - 182
        label_pos = label_pos[(label_pos > 0) & (label_pos <= n)]
        labels = [str(data.iloc[p - 1][time_col])[:4] for p in label_pos]
        ax.set_xticks(tick_pos, minor=False)
        ax.set_xticklabels([""] * len(tick_pos))
        ax.set_xticks(label_pos, minor=True)
        ax.set_xticklabels(labels, minor=True)
        ax.tick_params(axis="x", which="minor", length=0)
    else:
        tick_pos = np.arange(12, n + 1, 12)
        label_pos = tick_pos - 6
        label_pos = label_pos[(label_pos > 0) & (label_pos <= n)]
        labels = [str(data.iloc[p - 1][time_col])[:4] for p in label_pos]
        ax.set_xticks(tick_pos, minor=False)
        ax.set_xticklabels([""] * len(tick_pos))
        ax.set_xticks(label_pos, minor=True)
        ax.set_xticklabels(labels, minor=True)
        ax.tick_params(axis="x", which="minor", length=0)

    ax.set_ylabel(ylabel)
    ax.legend(loc="upper right", frameon=False, ncol=2)

    return ax
