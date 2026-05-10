"""Scatter plot for observed vs. simulated data.

Mirrors graph_swat.R :: Swat.Scatter.Plot.Graph().
"""

from __future__ import annotations

from typing import Dict, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from swat_py.metrics.performance import calc_all


def plot_scatter(
    data: pd.DataFrame,
    show_pbias: bool = True,
    xlabel: str = "observed",
    ylabel: str = "simulated",
    ax: Optional[plt.Axes] = None,
) -> Dict[str, float]:
    """Scatter plot with 1:1 line and OLS fit.

    Parameters
    ----------
    data:
        DataFrame with columns [date/yearmon, obs, sim].
    show_pbias:
        Whether to show % bias (PBIAS) below NSE/RMSE/RSR.
    xlabel, ylabel:
        Axis labels.
    ax:
        Existing Axes; creates one if None.

    Returns
    -------
    dict of performance metrics (NSE, RMSE, RSR, PBIAS, R², MAE, NOF).
    """
    if ax is None:
        _, ax = plt.subplots()

    obs = pd.to_numeric(data["obs"], errors="coerce").values
    sim = pd.to_numeric(data["sim"], errors="coerce").values
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs_c, sim_c = obs[mask], sim[mask]

    ymax = np.nanmax([obs_c, sim_c]) * 1.1
    ax.set_xlim(0, ymax)
    ax.set_ylim(0, ymax)

    # 1:1 line
    ax.plot([0, ymax], [0, ymax], "k--", linewidth=1, label="1:1")

    # Scatter points
    ax.scatter(obs_c, sim_c, s=20, facecolors="none", edgecolors="black")

    # OLS fit line
    if len(obs_c) >= 2:
        coeffs = np.polyfit(obs_c, sim_c, 1)
        x_fit = np.array([obs_c.min(), obs_c.max()])
        y_fit = np.polyval(coeffs, x_fit)
        ax.plot(x_fit, y_fit, "k-", linewidth=2)
        r2_val = np.corrcoef(obs_c, sim_c)[0, 1] ** 2
        a, b = coeffs
        xloc = ymax * 0.05
        yloc = ymax * 0.9
        ax.text(xloc, yloc, f"y = {a:.3f}x + {b:.3f}", fontsize=8)
        ax.text(xloc, yloc * 0.85, f"R² = {r2_val:.4f}", fontsize=8)

    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)

    # Metrics annotation below x-axis
    metrics = calc_all(obs_c, sim_c)
    ann = (
        f"NSE={metrics['nse']:.2f}  "
        f"RMSE={metrics['rmse']:.1f}  "
        f"RSR={metrics['rsr']:.2f}"
    )
    if show_pbias:
        ann += f"  PBIAS={metrics['pbias']:.1f}%"
    ax.annotate(
        ann,
        xy=(0.5, -0.18),
        xycoords="axes fraction",
        ha="center",
        fontsize=7,
    )

    return metrics
