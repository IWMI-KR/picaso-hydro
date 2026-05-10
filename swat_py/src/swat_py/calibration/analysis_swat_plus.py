"""SWAT-Plus calibration/validation analysis workflow.

Mirrors calibration-plus.R :: Swat.Observation.Run.Plus() and
Swat.Observation.Cha.Analysis.Plus().
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

import pandas as pd

from swat_py.config.env import EnvConfig
from swat_py.io.station import load_station_csv
from swat_py.io.weather_swat_plus import write_all_weather_plus
from swat_py.io.config_swat_plus import write_time_sim, patch_print_prt
from swat_py.output.reader_swat_plus import parse_channel_sd_day, extract_cha_outtype
from swat_py.output.aggregator import add_date_parts, aggregate_output
from swat_py.runner.executor import SwatExecutor
from swat_py.runner.file_manager import rename_outputs, setup_run_dir
from swat_py.viz.summary import plot_summary_figure


# ── outtype metadata ───────────────────────────────────────────────────────────

_OUTTYPE_META = {
    "flow":  {"funtype": "mean", "obs_col": "inflow_cms", "sim_col": "flow_cms",  "use_flow_obs": True},
    "flowd": {"funtype": "sum",  "obs_col": "inflow_cms", "sim_col": "flow_mm",   "use_flow_obs": True},
    "sedc":  {"funtype": "mean", "obs_col": "ss_mgl",     "sim_col": "Sed_mgl",   "use_flow_obs": False},
    "tnc":   {"funtype": "mean", "obs_col": "tn_mgl",     "sim_col": "TN_mgl",    "use_flow_obs": False},
    "tpc":   {"funtype": "mean", "obs_col": "tp_mgl",     "sim_col": "TP_mgl",    "use_flow_obs": False},
}

_YLABEL = {
    "flow":  "streamflow (cms)",
    "flowd": "streamflow (mm)",
    "sedc":  "sediment (mg/l)",
    "tnc":   "TN (mg/l)",
    "tpc":   "TP (mg/l)",
}


# ── run ────────────────────────────────────────────────────────────────────────

def run_observation_plus(
    cfg: EnvConfig,
    sim_type: str,
    syear: int,
    eyear: int,
    exe_name: str = "SWAT-Plus.exe",
) -> None:
    """Write weather inputs, run SWAT-Plus, rename outputs.

    Mirrors Swat.Observation.Run.Plus().

    Parameters
    ----------
    cfg:       Loaded :class:`EnvConfig`.
    sim_type:  Descriptive tag, e.g. ``"Calibration"`` or ``"Validation"``.
    syear:     First year of the analysis period (before warm-up).
    eyear:     Last year of the analysis period.
    exe_name:  SWAT-Plus executable filename.
    """
    nyskip = int(cfg.CioNYSKIP)
    run_dir = Path(cfg.SwatRunDir)
    obs_dir = Path(cfg.SwatObsDir) / "Output"
    setup_run_dir(obs_dir)

    # Write weather inputs
    stations = load_station_csv(
        Path(cfg.ObsDayDir) / cfg.StnFile,
        cfg.StnIDs,
    )
    write_all_weather_plus(
        stations=stations,
        wthr_dir=Path(cfg.ObsDayDir),
        out_dir=run_dir,
        fnamestr=None,
    )

    # Update time.sim and print.prt
    nbyr = eyear - syear + 1 + nyskip
    iyr = syear - nyskip
    write_time_sim(run_dir, nbyr, iyr)
    patch_print_prt(run_dir, nbyr, iyr, nyskip)

    # Run SWAT-Plus
    executor = SwatExecutor(run_dir, exe_name)
    executor.run()

    # Rename outputs
    rename_outputs(
        run_dir=run_dir,
        out_dir=obs_dir,
        output_types=cfg.OutputTypes,
        scenario_name=sim_type,
        model="swat_plus",
    )


# ── analysis ──────────────────────────────────────────────────────────────────

def run_calibration_analysis_plus(
    cfg: EnvConfig,
    sim_type: str,
    out_types: List[str],
    syear: int,
) -> None:
    """Parse outputs, compare with observations, save CSV + PNG.

    Mirrors Swat.Observation.Cha.Analysis.Plus().

    Parameters
    ----------
    cfg:       Loaded :class:`EnvConfig`.
    sim_type:  Tag matching the run (e.g. ``"Calibration"``).
    out_types: List of output types, e.g. ``["flow", "sedc", "tnc", "tpc"]``.
    syear:     Analysis start year (before warm-up skip).
    """
    nyskip = int(cfg.CioNYSKIP)
    out_dir = Path(cfg.SwatObsDir) / "Output"
    analysis_dir = Path(cfg.SwatObsDir) / "Analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    sdate = f"{syear}-01-01"
    sdate2 = f"{syear + nyskip}-01-01"

    for outtype in out_types:
        meta = _OUTTYPE_META[outtype]
        funtype: str = meta["funtype"]
        use_flow_obs: bool = meta["use_flow_obs"]
        obs_col: str = meta["obs_col"]
        sim_col: str = meta["sim_col"]

        outlets = cfg.OutletFlowIDs if use_flow_obs else cfg.OutletWqIDs
        outlet_nms = cfg.OutletFlowNms if use_flow_obs else cfg.OutletWqNms
        obs_file = cfg.ObsFlowFile if use_flow_obs else cfg.ObsWqFile

        obs_df = pd.read_csv(
            Path(cfg.SwatDbDir) / obs_file,
            encoding="utf-8-sig",
        )

        for outlet, outlet_nm in zip(outlets, outlet_nms):
            cha_path = out_dir / f"channel_sd_day-{sim_type}.txt"
            raw = parse_channel_sd_day(cha_path, outlet, sdate)
            if raw is None:
                print(f"[WARN] No data for outlet {outlet} in {cha_path}")
                continue

            sim_typed = extract_cha_outtype(raw, outtype)
            sim_typed = add_date_parts(sim_typed)

            # Filter warm-up period
            sim_typed = sim_typed[sim_typed["date"] >= pd.Timestamp(sdate2)]

            # Prepare observed DataFrame
            obs_sub = _prepare_obs(obs_df, outtype, obs_col)

            # Join sim + obs on date
            sim_col_renamed = sim_col
            sim_join = sim_typed[["date", sim_col_renamed]].rename(
                columns={sim_col_renamed: "sim"}
            )
            obs_join = obs_sub.rename(columns={obs_col: "obs"})

            sim_join["date"] = pd.to_datetime(sim_join["date"])
            obs_join["date"] = pd.to_datetime(obs_join["date"])

            daily = pd.merge(sim_join, obs_join, on="date", how="left")

            # Monthly aggregation
            daily_tmp = add_date_parts(daily)
            msim = daily_tmp.groupby("yearmon")["sim"].mean().reset_index()
            mobs = daily_tmp.groupby("yearmon")["obs"].mean().reset_index()
            monthly = pd.merge(msim, mobs, on="yearmon", how="left")

            # Save CSVs
            tag = f"{sim_type}_{outtype}_{outlet}-{outlet_nm}"
            daily.to_csv(analysis_dir / f"{tag}-daily.csv", index=False)
            monthly.to_csv(analysis_dir / f"{tag}-monthly.csv", index=False)

            # Save summary PNG
            plot_summary_figure(
                out_dir=analysis_dir,
                name=tag,
                title=tag,
                daily_df=daily,
                monthly_df=monthly,
                outtype=outtype,
            )


def _prepare_obs(
    obs_df: pd.DataFrame,
    outtype: str,
    obs_col: str,
) -> pd.DataFrame:
    """Normalise observed data to a date + value DataFrame."""
    df = obs_df.copy()
    if "day" in df.columns and "mon" in df.columns and "year" in df.columns:
        df["date"] = pd.to_datetime(
            df[["year", "mon", "day"]].rename(columns={"mon": "month"})
        )
    elif "date" not in df.columns:
        raise KeyError("Observed data must have either (year/mon/day) or 'date' columns.")
    else:
        df["date"] = pd.to_datetime(df["date"])

    if obs_col not in df.columns:
        raise KeyError(f"Column '{obs_col}' not found in observed data.")

    return df[["date", obs_col]]
