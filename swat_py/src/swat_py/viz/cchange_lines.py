"""Climate change multi-scenario line plots.

Mirrors LineGraph_SWAT.R :: Swat.CChange.Rch.Cha.Summary.Graph().

Produces figures comparing historical vs. future SSP scenarios,
showing GCM ensemble spread as shaded bands and MME mean as a line.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from swat_py.config.env import EnvConfig


_CLIM_TYPES = ["Monthly-Mean", "Monthly-Max", "Tenday-Mean", "Tenday-Max"]

_SCN_COLORS = {
    "historical": "black",
    "ssp126": "steelblue",
    "ssp245": "goldenrod",
    "ssp370": "darkorange",
    "ssp585": "crimson",
    # Legacy RCP names
    "rcp26": "steelblue",
    "rcp45": "goldenrod",
    "rcp85": "crimson",
}

_YLABEL_MAP = {
    "flow":  "streamflow (cms)",
    "flowd": "streamflow (mm)",
    "sedc":  "sediment (mg/l)",
    "tnc":   "TN (mg/l)",
    "tpc":   "TP (mg/l)",
}


def plot_cchange_lines(
    cfg: EnvConfig,
    out_types: List[str],
    draw_together: bool = True,
    same_y: bool = True,
) -> None:
    """Create climate change line plots for each outlet × outtype.

    Reads pre-computed climatology CSVs from ``SwatCcDir/Summary/``.

    Parameters
    ----------
    cfg:           Loaded :class:`EnvConfig`.
    out_types:     Output types to plot (e.g. ``["flow", "sedc"]``).
    draw_together: If True, combine all scenarios in one figure per clim type.
    same_y:        If True, share Y-axis range across all scenarios.
    """
    summary_dir = Path(cfg.SwatCcDir) / "Summary"
    plot_dir = Path(cfg.SwatCcDir) / "Figures"
    plot_dir.mkdir(parents=True, exist_ok=True)

    syear_rcp_vals = (
        cfg.Syear_rcp if isinstance(cfg.Syear_rcp, list) else [cfg.Syear_rcp]
    )
    eyear_rcp_vals = (
        cfg.Eyear_rcp if isinstance(cfg.Eyear_rcp, list) else [cfg.Eyear_rcp]
    )

    for outtype in out_types:
        outlets = cfg.OutletFlowIDs if outtype == "flow" else cfg.OutletWqIDs
        outlet_nms = cfg.OutletFlowNms if outtype == "flow" else cfg.OutletWqNms
        ylabel = _YLABEL_MAP.get(outtype, outtype)

        for outlet, outlet_nm in zip(outlets, outlet_nms):
            tag = f"{outlet}-{outlet_nm}_{outtype}"

            for clim_type in _CLIM_TYPES:
                x_label = "Month" if "Monthly" in clim_type else "10-day period"
                n_periods = 12 if "Monthly" in clim_type else 36

                fig, ax = plt.subplots(figsize=(10, 5))
                y_max = 0.0

                for scn_nm in cfg.ScnNms:
                    if scn_nm == "historical":
                        period_str = f"{cfg.Syear_hist}-{cfg.Eyear_hist}"
                    else:
                        period_str = (
                            f"{min(int(v) for v in syear_rcp_vals)}"
                            f"-{max(int(v) for v in eyear_rcp_vals)}"
                        )

                    csv_path = (
                        summary_dir
                        / f"{clim_type}-clim_{tag}_{scn_nm}_{period_str}.csv"
                    )
                    if not csv_path.exists():
                        continue

                    df = pd.read_csv(csv_path)
                    x_col = df.columns[0]
                    model_cols = [c for c in df.columns if c != x_col]
                    if not model_cols:
                        continue

                    x = df[x_col].values
                    ens = df[model_cols].values.astype(float)
                    mme = np.nanmean(ens, axis=1)
                    ens_min = np.nanmin(ens, axis=1)
                    ens_max = np.nanmax(ens, axis=1)

                    color = _SCN_COLORS.get(scn_nm, "gray")
                    ax.fill_between(x, ens_min, ens_max, alpha=0.2, color=color)
                    ax.plot(x, mme, color=color, linewidth=2, label=f"{scn_nm} MME")
                    y_max = max(y_max, float(np.nanmax(ens_max)))

                ax.set_xlabel(x_label)
                ax.set_ylabel(ylabel)
                ax.set_title(f"{clim_type} — {outlet_nm} — {outtype}")
                ax.legend(fontsize=8, frameon=False, ncol=len(cfg.ScnNms))
                if same_y and y_max > 0:
                    ax.set_ylim(0, y_max * 1.1)

                fig_path = plot_dir / f"{clim_type}_{tag}.png"
                fig.savefig(fig_path, dpi=200, bbox_inches="tight")
                plt.close(fig)
