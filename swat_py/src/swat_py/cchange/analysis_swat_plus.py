"""SWAT-Plus climate change output analysis.

Mirrors cchange_swat_cha_plus.R :: Swat.CChange.Cha.Analysis.Plus() and
cchange_swat.R :: Swat.CChange.Rch.Cha.Summary().
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

from swat_py.config.env import EnvConfig
from swat_py.output.reader_swat_plus import parse_channel_sd_day, extract_cha_outtype
from swat_py.output.aggregator import add_date_parts


def analyse_cchange_cha_plus(
    cfg: EnvConfig,
    out_types: List[str],
) -> None:
    """Extract daily/monthly time series for each model × scenario × outlet.

    Saves CSVs to ``SwatCcDir/Analysis/{model}/``.
    Saves climatology summaries (Monthly-Mean, Monthly-Max,
    Tenday-Mean, Tenday-Max) per outlet × outtype × scenario.
    """
    syear_rcp_vals = (
        cfg.Syear_rcp if isinstance(cfg.Syear_rcp, list) else [cfg.Syear_rcp]
    )
    eyear_rcp_vals = (
        cfg.Eyear_rcp if isinstance(cfg.Eyear_rcp, list) else [cfg.Eyear_rcp]
    )

    for outtype in out_types:
        outlets = cfg.OutletFlowIDs if outtype == "flow" else cfg.OutletWqIDs
        outlet_nms = cfg.OutletFlowNms if outtype == "flow" else cfg.OutletWqNms

        for outlet, outlet_nm in zip(outlets, outlet_nms):
            for mdl_nm in cfg.MdlNms:
                mdl_dir = Path(cfg.SwatCcDir) / "Output" / mdl_nm
                analysis_dir = Path(cfg.SwatCcDir) / "Analysis" / mdl_nm
                analysis_dir.mkdir(parents=True, exist_ok=True)

                for scn_nm in cfg.ScnNms:
                    if scn_nm == "historical":
                        syear = int(cfg.Syear_hist)
                    else:
                        syear = min(int(v) for v in syear_rcp_vals)

                    sdate = f"{syear}-01-01"

                    cha_path = mdl_dir / f"channel_sd_day-{scn_nm}.txt"
                    raw = parse_channel_sd_day(cha_path, outlet, sdate)
                    if raw is None:
                        continue

                    typed = extract_cha_outtype(raw, outtype)
                    typed = add_date_parts(typed)

                    # Daily CSV
                    tag = f"{outtype}_{outlet}-{outlet_nm}"
                    typed.to_csv(
                        analysis_dir / f"output_{scn_nm}_{tag}-daily.csv",
                        index=False,
                    )

                    # Monthly mean CSV
                    sim_col = _main_sim_col(outtype)
                    monthly = (
                        typed.groupby("yearmon")[sim_col].mean().reset_index()
                    )
                    monthly.to_csv(
                        analysis_dir / f"output_{scn_nm}_{tag}-monthly.csv",
                        index=False,
                    )

            # Build climatology summaries across all models
            _build_climatology(cfg, outtype, outlet, outlet_nm)


def _main_sim_col(outtype: str) -> str:
    return {
        "flow":  "flow_cms",
        "sedc":  "Sed_mgl",
        "tnc":   "TN_mgl",
        "tpc":   "TP_mgl",
    }[outtype]


def _build_climatology(
    cfg: EnvConfig,
    outtype: str,
    outlet: int,
    outlet_nm: str,
) -> None:
    """Compute monthly and 10-day climatology statistics.

    Saves results to ``SwatCcDir/Summary/`` per scenario × period.
    Mirrors Swat.CChange.Rch.Cha.Summary().
    """
    syear_rcp_vals = (
        cfg.Syear_rcp if isinstance(cfg.Syear_rcp, list) else [cfg.Syear_rcp]
    )
    eyear_rcp_vals = (
        cfg.Eyear_rcp if isinstance(cfg.Eyear_rcp, list) else [cfg.Eyear_rcp]
    )
    sim_col = _main_sim_col(outtype)
    summary_dir = Path(cfg.SwatCcDir) / "Summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{outlet}-{outlet_nm}_{outtype}"

    for scn_nm in cfg.ScnNms:
        if scn_nm == "historical":
            period_pairs = [(int(cfg.Syear_hist), int(cfg.Eyear_hist))]
        else:
            period_pairs = list(zip(
                [int(v) for v in syear_rcp_vals],
                [int(v) for v in eyear_rcp_vals],
            ))

        for (syear, eyear) in period_pairs:
            frames: List[pd.DataFrame] = []
            for mdl_nm in cfg.MdlNms:
                analysis_dir = Path(cfg.SwatCcDir) / "Analysis" / mdl_nm
                daily_path = (
                    analysis_dir
                    / f"output_{scn_nm}_{outtype}_{outlet}-{outlet_nm}-daily.csv"
                )
                if not daily_path.exists():
                    continue
                df = pd.read_csv(daily_path, parse_dates=["date"])
                df = df[(df["date"].dt.year >= syear) & (df["date"].dt.year <= eyear)]
                df["model"] = mdl_nm
                frames.append(df)

            if not frames:
                continue

            all_data = pd.concat(frames, ignore_index=True)
            all_data = add_date_parts(all_data)

            period_str = f"{syear}-{eyear}"

            # Monthly-Mean
            mm = (
                all_data.groupby(["model", "month"])[sim_col]
                .mean()
                .unstack("model")
                .reset_index()
            )
            mm.to_csv(
                summary_dir / f"Monthly-Mean-clim_{tag}_{scn_nm}_{period_str}.csv",
                index=False,
            )

            # Monthly-Max
            mx = (
                all_data.groupby(["model", "month"])[sim_col]
                .max()
                .unstack("model")
                .reset_index()
            )
            mx.to_csv(
                summary_dir / f"Monthly-Max-clim_{tag}_{scn_nm}_{period_str}.csv",
                index=False,
            )

            # 10-day mean & max
            all_data["tenday"] = ((all_data["date"].dt.dayofyear - 1) // 10) + 1
            all_data["tenday"] = all_data["tenday"].clip(upper=36)

            td_mean = (
                all_data.groupby(["model", "tenday"])[sim_col]
                .mean()
                .unstack("model")
                .reset_index()
            )
            td_mean.to_csv(
                summary_dir / f"Tenday-Mean-clim_{tag}_{scn_nm}_{period_str}.csv",
                index=False,
            )

            td_max = (
                all_data.groupby(["model", "tenday"])[sim_col]
                .max()
                .unstack("model")
                .reset_index()
            )
            td_max.to_csv(
                summary_dir / f"Tenday-Max-clim_{tag}_{scn_nm}_{period_str}.csv",
                index=False,
            )
