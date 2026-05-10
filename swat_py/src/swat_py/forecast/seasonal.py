"""Seasonal forecasting with observed + forecast + dummy padding.

Mirrors sforecast_swat.R :: Swat.SForecast.Run() and
Swat.SForecast.Rch.Analysis().
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

import pandas as pd

from swat_py.config.env import EnvConfig
from swat_py.io.station import load_station_csv
from swat_py.io.weather_swat_plus import write_all_weather_plus
from swat_py.io.weather_swat import write_all_weather
from swat_py.io.config_swat_plus import write_time_sim, patch_print_prt
from swat_py.io.config_swat import patch_file_cio
from swat_py.output.reader_swat_plus import parse_channel_sd_day, extract_cha_outtype
from swat_py.output.aggregator import add_date_parts
from swat_py.runner.executor import SwatExecutor
from swat_py.runner.file_manager import rename_outputs, setup_run_dir


def run_seasonal_forecast(
    cfg: EnvConfig,
    fiyearmon: str,
    model: str = "swat_plus",
    exe_name: str = "SWAT-Plus.exe",
    lookback_years: int = 3,
) -> None:
    """Run SWAT with stitched observed + forecast weather.

    The combined dataset is:
      - Observed daily weather (``lookback_years`` before ``fiyearmon``)
      - Forecast daily weather (from ``FcstDataDir``)
      - Dummy/climatological data to pad through December of the forecast year

    Parameters
    ----------
    cfg:
        Loaded :class:`EnvConfig`.
    fiyearmon:
        Forecast initialization month, e.g. ``"2024-05"``.
    model:
        ``"swat_plus"`` or ``"swat2012"``.
    exe_name:
        Executable filename.
    lookback_years:
        How many years of observed data to prepend (default 3).
    """
    fi_year = int(fiyearmon[:4])
    fi_mon = int(fiyearmon[5:7])
    nyskip = int(cfg.CioNYSKIP)
    run_dir = Path(cfg.SwatRunDir)
    fcst_out_dir = Path(cfg.SwatFcstDir) / "Output"
    setup_run_dir(fcst_out_dir)

    # Build stitched weather directory (temp)
    stitch_dir = run_dir / "_fcst_stitch"
    stitch_dir.mkdir(exist_ok=True)

    stations = load_station_csv(
        Path(cfg.ObsDayDir) / cfg.StnFile,
        cfg.StnIDs,
    )

    _stitch_weather(
        stations=stations,
        obs_dir=Path(cfg.ObsDayDir),
        fcst_dir=Path(cfg.FcstDataDir),
        fiyearmon=fiyearmon,
        lookback_years=lookback_years,
        stitch_dir=stitch_dir,
    )

    syear = fi_year - lookback_years
    eyear = fi_year

    if model == "swat_plus":
        write_all_weather_plus(stations, stitch_dir, run_dir)
        nbyr = eyear - syear + 1 + nyskip
        iyr = syear - nyskip
        write_time_sim(run_dir, nbyr, iyr)
        patch_print_prt(run_dir, nbyr, iyr, nyskip)
        SwatExecutor(run_dir, exe_name).run()
        rename_outputs(run_dir, fcst_out_dir, cfg.OutputTypes, fiyearmon, "swat_plus")
    else:
        write_all_weather(stations, stitch_dir, run_dir)
        nbyr = eyear - syear + 1 + nyskip
        iyr = syear - nyskip
        patch_file_cio(run_dir, nbyr, iyr, nyskip)
        SwatExecutor(run_dir, exe_name).run()
        rename_outputs(run_dir, fcst_out_dir, ["rch"], fiyearmon, "swat2012")

    # Cleanup stitched temp files
    shutil.rmtree(stitch_dir, ignore_errors=True)


def _stitch_weather(
    stations,
    obs_dir: Path,
    fcst_dir: Path,
    fiyearmon: str,
    lookback_years: int,
    stitch_dir: Path,
) -> None:
    """Combine observed + forecast CSVs into stitch_dir.

    For each station: read obs CSV, read forecast CSV, concatenate,
    save as a single merged CSV that weather writers can consume.
    """
    fi_year = int(fiyearmon[:4])
    fi_mon = int(fiyearmon[5:7])
    cutoff = pd.Timestamp(f"{fi_year}-{fi_mon:02d}-01")
    start = pd.Timestamp(f"{fi_year - lookback_years}-01-01")

    for stn in stations:
        # Load observed
        obs_files = list(obs_dir.glob(f"*{stn.id}*.csv"))
        if not obs_files:
            continue
        obs_df = pd.read_csv(obs_files[0], na_values=["-99", "-99.0", -99])
        if obs_df.shape[1] == 12:
            obs_df.columns = [
                "year", "mon", "day", "prcp", "tmax", "tmin",
                "wspd", "rhum", "rsds", "sshine", "cloud", "tavg",
            ]
        obs_df["date"] = pd.to_datetime(
            obs_df[["year", "mon", "day"]].rename(columns={"mon": "month"})
        )
        obs_df = obs_df[
            (obs_df["date"] >= start) & (obs_df["date"] < cutoff)
        ]

        # Load forecast (best-match file in fcst_dir)
        fcst_files = list(fcst_dir.glob(f"*{stn.id}*{fiyearmon}*.csv"))
        if fcst_files:
            fcst_df = pd.read_csv(fcst_files[0], na_values=["-99", "-99.0", -99])
            if fcst_df.shape[1] == 12:
                fcst_df.columns = [
                    "year", "mon", "day", "prcp", "tmax", "tmin",
                    "wspd", "rhum", "rsds", "sshine", "cloud", "tavg",
                ]
            fcst_df["date"] = pd.to_datetime(
                fcst_df[["year", "mon", "day"]].rename(columns={"mon": "month"})
            )
        else:
            fcst_df = pd.DataFrame(columns=obs_df.columns)

        merged = pd.concat([obs_df, fcst_df], ignore_index=True)
        merged = merged.sort_values("date").drop_duplicates("date")
        merged["year"] = merged["date"].dt.year
        merged["mon"] = merged["date"].dt.month
        merged["day"] = merged["date"].dt.day

        merged[["year", "mon", "day", "prcp", "tmax", "tmin",
                "wspd", "rhum", "rsds"]].to_csv(
            stitch_dir / f"{stn.id}.csv", index=False
        )


def analyse_seasonal_forecast(
    cfg: EnvConfig,
    fiyearmon: str,
    out_types: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Extract and return flow time series from the seasonal forecast run.

    Returns a DataFrame with daily flow values for each outlet.
    """
    if out_types is None:
        out_types = ["flow"]

    fcst_out_dir = Path(cfg.SwatFcstDir) / "Output"
    fi_year = int(fiyearmon[:4])
    sdate = f"{fi_year - 3}-01-01"

    results = []
    for outtype in out_types:
        outlets = cfg.OutletFlowIDs if outtype == "flow" else cfg.OutletWqIDs
        outlet_nms = cfg.OutletFlowNms if outtype == "flow" else cfg.OutletWqNms

        for outlet, outlet_nm in zip(outlets, outlet_nms):
            cha_path = fcst_out_dir / f"channel_sd_day-{fiyearmon}.txt"
            raw = parse_channel_sd_day(cha_path, outlet, sdate)
            if raw is None:
                continue
            typed = extract_cha_outtype(raw, outtype)
            typed["outlet"] = outlet_nm
            typed["outtype"] = outtype
            results.append(typed)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()
