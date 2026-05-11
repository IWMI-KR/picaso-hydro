"""SWAT 2012 calibration/validation analysis workflow.

Mirrors calibration.R :: Swat.Observation.Run() and
Swat.Observation.Rch.Analysis().
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd

from swat_py.config.env import EnvConfig
from swat_py.io.station import load_station_csv
from swat_py.io.weather_swat import write_all_weather
from swat_py.io.config_swat import patch_file_cio
from swat_py.output.reader_swat import parse_output_rch, extract_rch_outtype
from swat_py.output.aggregator import add_date_parts, aggregate_output
from swat_py.runner.executor import SwatExecutor
from swat_py.runner.file_manager import rename_outputs, setup_run_dir
from swat_py.viz.summary import plot_summary_figure


_OUTTYPE_META = {
    "flow":  {"funtype": "mean", "obs_col": "inflow_cms", "sim_col": "flow_cms",  "use_flow_obs": True},
    "flowd": {"funtype": "sum",  "obs_col": "inflow_cms", "sim_col": "flow_mm",   "use_flow_obs": True},
    "sedc":  {"funtype": "mean", "obs_col": "ss_mgl",     "sim_col": "Sed_mgl",   "use_flow_obs": False},
    "tnc":   {"funtype": "mean", "obs_col": "tn_mgl",     "sim_col": "TN_mgl",    "use_flow_obs": False},
    "tpc":   {"funtype": "mean", "obs_col": "tp_mgl",     "sim_col": "TP_mgl",    "use_flow_obs": False},
    "sed":   {"funtype": "sum",  "obs_col": "ss_mgl",     "sim_col": "Sed_ton",   "use_flow_obs": False},
    "tn":    {"funtype": "sum",  "obs_col": "tn_mgl",     "sim_col": "TN_kg",     "use_flow_obs": False},
    "tp":    {"funtype": "sum",  "obs_col": "tp_mgl",     "sim_col": "TP_kg",     "use_flow_obs": False},
}


def run_observation(
    cfg: EnvConfig,
    sim_type: str,
    syear: int,
    eyear: int,
    exe_name: str = "SWAT2020.exe",
) -> None:
    """Write weather inputs, run SWAT 2012, rename outputs.

    Mirrors Swat.Observation.Run().
    """
    nyskip = int(cfg.CioNYSKIP)
    run_dir = Path(cfg.SwatRunDir)
    obs_out_dir = Path(cfg.SwatObsDir) / "Output"
    setup_run_dir(obs_out_dir)

    stations = load_station_csv(
        Path(cfg.ObsDayDir) / cfg.StnFile,
        cfg.StnIDs,
    )
    write_all_weather(
        stations=stations,
        wthr_dir=Path(cfg.ObsDayDir),
        out_dir=run_dir,
        fnamestr=None,
    )

    nbyr = eyear - syear + 1 + nyskip
    iyr = syear - nyskip
    patch_file_cio(run_dir, nbyr, iyr, nyskip)

    SwatExecutor(run_dir, exe_name).run()

    # SWAT 2012 outputs to rename (extensions from OutputTypes or defaults)
    ext_list = cfg.OutputTypes if cfg.OutputTypes else ["rch"]
    rename_outputs(
        run_dir=run_dir,
        out_dir=obs_out_dir,
        output_types=ext_list,
        scenario_name=sim_type,
        model="swat2012",
    )


def run_calibration_analysis(
    cfg: EnvConfig,
    sim_type: str,
    out_types: List[str],
    syear: int,
) -> None:
    """Parse rch outputs, compare with observations, save CSV + PNG.

    Mirrors Swat.Observation.Rch.Analysis().
    """
    nyskip = int(cfg.CioNYSKIP)
    out_dir = Path(cfg.SwatObsDir) / "Output"
    analysis_dir = Path(cfg.SwatObsDir) / "Analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    sdate = f"{syear}-01-01"
    sdate2 = f"{syear + nyskip}-01-01"

    for outtype in out_types:
        meta = _OUTTYPE_META[outtype]
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
            rch_path = out_dir / f"output-{sim_type}.rch"
            raw = parse_output_rch(rch_path, outlet, sdate)
            if raw is None:
                print(f"[WARN] No data for outlet {outlet} in {rch_path}")
                continue

            sim_typed = extract_rch_outtype(raw, outtype)
            sim_typed = add_date_parts(sim_typed)
            sim_typed = sim_typed[sim_typed["date"] >= pd.Timestamp(sdate2)]

            # Prepare obs
            obs_sub = _prepare_obs(obs_df, outtype, obs_col)
            sim_join = sim_typed[["date", sim_col]].rename(columns={sim_col: "sim"})
            obs_join = obs_sub.rename(columns={obs_col: "obs"})
            sim_join["date"] = pd.to_datetime(sim_join["date"])
            obs_join["date"] = pd.to_datetime(obs_join["date"])
            daily = pd.merge(sim_join, obs_join, on="date", how="left")

            daily_tmp = add_date_parts(daily)
            msim = daily_tmp.groupby("yearmon")["sim"].mean().reset_index()
            mobs = daily_tmp.groupby("yearmon")["obs"].mean().reset_index()
            monthly = pd.merge(msim, mobs, on="yearmon", how="left")

            tag = f"{sim_type}_{outtype}_{outlet}-{outlet_nm}"
            daily.to_csv(analysis_dir / f"{tag}-daily.csv", index=False)
            monthly.to_csv(analysis_dir / f"{tag}-monthly.csv", index=False)

            plot_summary_figure(
                out_dir=analysis_dir,
                name=tag,
                title=tag,
                daily_df=daily,
                monthly_df=monthly,
                outtype=outtype,
            )


def _prepare_obs(obs_df: pd.DataFrame, outtype: str, obs_col: str) -> pd.DataFrame:
    df = obs_df.copy()
    if "day" in df.columns and "mon" in df.columns and "year" in df.columns:
        df["date"] = pd.to_datetime(
            df[["year", "mon", "day"]].rename(columns={"mon": "month"})
        )
    elif "date" not in df.columns:
        raise KeyError("Observed data must have either (year/mon/day) or 'date' columns.")
    else:
        df["date"] = pd.to_datetime(df["date"])
    return df[["date", obs_col]]
