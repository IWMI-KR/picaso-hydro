"""4-panel summary figure (daily + monthly time series + scatter plots).

Mirrors graph_swat.R :: Swat.Summary.Graph.Table().
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import pandas as pd

from swat_py.viz.timeseries import plot_timeseries
from swat_py.viz.scatter import plot_scatter


_YLABEL_MAP = {
    "flow":  "streamflow (cms)",
    "flowd": "streamflow (mm)",
    "sedc":  "sediment (mg/l)",
    "tnc":   "TN (mg/l)",
    "tpc":   "TP (mg/l)",
    "sed":   "sediment (ton)",
    "tn":    "TN (kg)",
    "tp":    "TP (kg)",
}


def plot_summary_figure(
    out_dir: Path,
    name: str,
    title: str,
    daily_df: Optional[pd.DataFrame],
    monthly_df: pd.DataFrame,
    outtype: str = "flow",
    dpi: int = 400,
) -> Path:
    """Create and save a 4-panel PNG figure.

    Panel layout (mirrors R split.screen):
      Top-left:      Daily time series
      Top-right:     Monthly time series
      Bottom-left:   Daily scatter plot (if daily_df provided)
      Bottom-right:  Monthly scatter plot

    Parameters
    ----------
    out_dir:    Directory where the PNG is saved.
    name:       Base filename (without extension).
    title:      Figure super-title.
    daily_df:   Daily obs/sim DataFrame; may be None.
    monthly_df: Monthly obs/sim DataFrame (required).
    outtype:    Output type key for y-axis labeling.
    dpi:        Output resolution (default 400, mirrors R's res=400).

    Returns
    -------
    Path to the saved PNG.
    """
    ylabel = _YLABEL_MAP.get(outtype, outtype)
    fig = plt.figure(figsize=(8, 11))
    fig.suptitle(title, fontsize=10, y=0.98)

    gs = gridspec.GridSpec(
        2, 2,
        figure=fig,
        left=0.1, right=0.95,
        top=0.94, bottom=0.12,
        hspace=0.45, wspace=0.35,
    )

    ax_daily_ts = fig.add_subplot(gs[0, 0])
    ax_mon_ts = fig.add_subplot(gs[0, 1])
    ax_daily_sc = fig.add_subplot(gs[1, 0])
    ax_mon_sc = fig.add_subplot(gs[1, 1])

    # Daily time series
    if daily_df is not None and not daily_df.empty:
        plot_timeseries(daily_df, tstep="daily", is_line=False,
                        ylabel=ylabel, ax=ax_daily_ts)
        ax_daily_ts.set_title("Daily", fontsize=8)
    else:
        ax_daily_ts.set_visible(False)

    # Monthly time series
    plot_timeseries(monthly_df, tstep="monthly", is_line=False,
                    ylabel=ylabel, ax=ax_mon_ts)
    ax_mon_ts.set_title("Monthly", fontsize=8)

    # Daily scatter
    if daily_df is not None and not daily_df.empty:
        plot_scatter(
            daily_df,
            show_pbias=True,
            xlabel=f"observed {ylabel}",
            ylabel=f"simulated {ylabel}",
            ax=ax_daily_sc,
        )
        ax_daily_sc.set_title("Daily (scatter)", fontsize=8)
    else:
        ax_daily_sc.set_visible(False)

    # Monthly scatter
    plot_scatter(
        monthly_df,
        show_pbias=False,
        xlabel=f"observed {ylabel}",
        ylabel=f"simulated {ylabel}",
        ax=ax_mon_sc,
    )
    ax_mon_sc.set_title("Monthly (scatter)", fontsize=8)

    out_path = Path(out_dir) / f"{name}.png"
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out_path
