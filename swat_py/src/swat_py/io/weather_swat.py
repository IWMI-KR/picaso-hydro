"""SWAT 2012 weather input writers.

Mirrors input_swat.R :: Swat.Write.Weather.Input.MultiStations().

Combined output files (all stations in one file):
  pcp1.pcp     — precipitation
  tmp1.tmp     — temperature (tmax / tmin), chunked every 150 stations
  wnd.wnd      — wind speed
  hmd.hmd      — relative humidity
  slr.slr      — solar radiation
"""

from __future__ import annotations

import fnmatch
import math
from pathlib import Path
from typing import List, Optional

import pandas as pd

from swat_py.io.station import StationInfo
from swat_py.utils.interpolate import linear_gap_fill

_MAX_STATIONS_PER_FILE = 150


def _load_station_data(
    wthr_dir: Path,
    stn_id: str,
    fnamestr: Optional[str],
) -> pd.DataFrame:
    """Load daily weather CSV (same logic as SWAT-Plus loader)."""
    pattern = (
        f"*{stn_id}_*{fnamestr}.csv" if fnamestr else f"*{stn_id}.csv"
    )
    matches = [f for f in wthr_dir.iterdir() if fnmatch.fnmatch(f.name, pattern)]
    if not matches:
        raise FileNotFoundError(
            f"No weather file for station '{stn_id}' in {wthr_dir}"
        )
    df = pd.read_csv(
        matches[0],
        na_values=["-99.00", "-99.0", "-99", -99.0, -99],
    )
    if df.shape[1] == 12:
        df.columns = [
            "year", "mon", "day",
            "prcp", "tmax", "tmin", "wspd", "rhum", "rsds",
            "sshine", "cloud", "tavg",
        ]
    df["date"] = pd.to_datetime(
        df[["year", "mon", "day"]].rename(columns={"mon": "month"})
    )
    for col in ("prcp", "tmax", "tmin", "wspd", "rhum", "rsds"):
        if col not in df.columns:
            df[col] = float("nan")
    return df[["date", "prcp", "tmax", "tmin", "wspd", "rhum", "rsds"]].copy()


def _header_lati_long_elev(stations: List[StationInfo]) -> str:
    """Build the 3-line Lati/Long/Elev header for SWAT 2012 combined files."""
    if len(stations) == 1:
        lati = f"Lati{stations[0].lat:8.2f}"
        long = f"Long{stations[0].lon:8.1f}"
        elev = f"Elev{stations[0].elev:8.0f}"
    else:
        lati = (
            f"Lati{stations[0].lat:8.2f}"
            + "".join(f"{s.lat:5.2f}" for s in stations[1:])
        )
        long = (
            f"Long{stations[0].lon:8.1f}"
            + "".join(f"{s.lon:5.1f}" for s in stations[1:])
        )
        elev = (
            f"Elev{stations[0].elev:8.0f}"
            + "".join(f"{s.elev:5.0f}" for s in stations[1:])
        )
    return f"{lati}\n{long}\n{elev}\n"


def write_pcp(
    stations: List[StationInfo],
    wthr_dir: Path,
    out_dir: Path,
    fnamestr: Optional[str] = None,
) -> Path:
    """Write pcp1.pcp combining all station precipitation."""
    # Merge all stations into a wide DataFrame
    merged: Optional[pd.DataFrame] = None
    for stn in stations:
        df = _load_station_data(wthr_dir, stn.id, fnamestr)
        col = linear_gap_fill(df["prcp"]).fillna(-99.0).rename(stn.id)
        tmp = pd.concat([df["date"], col], axis=1)
        merged = tmp if merged is None else merged.merge(tmp, on="date", how="outer")

    assert merged is not None
    merged = merged.sort_values("date")
    years = merged["date"].dt.year
    julians = merged["date"].dt.dayofyear
    val_cols = [s.id for s in stations]

    out_path = out_dir / "pcp1.pcp"
    with out_path.open("w") as fh:
        fh.write(
            "Precipitation Input File pcp.pcp          created using swat_py\n"
        )
        fh.write(_header_lati_long_elev(stations))
        for y, j, row in zip(years, julians, merged[val_cols].itertuples(index=False)):
            vals = "".join(f"{v:05.1f}" for v in row)
            fh.write(f"{y:4d}{j:03d}{vals}\n")
    return out_path


def _write_combined_single(
    var: str,
    ext: str,
    title: str,
    stations: List[StationInfo],
    wthr_dir: Path,
    out_dir: Path,
    fnamestr: Optional[str],
) -> Path:
    """Generic writer for wnd.wnd, hmd.hmd, slr.slr.

    Note (SWAT 2012 format difference vs pcp/tmp):
      - wnd / hmd / slr do NOT have Lati/Long/Elev header lines.
      - Data values use %08.3f (8 wide, 3 decimal) instead of %05.1f.
      Reference: rSWAT/R/input_swat.R lines 116-148.
    """
    merged: Optional[pd.DataFrame] = None
    for stn in stations:
        df = _load_station_data(wthr_dir, stn.id, fnamestr)
        col = linear_gap_fill(df[var]).fillna(-99.0).rename(stn.id)
        tmp = pd.concat([df["date"], col], axis=1)
        merged = tmp if merged is None else merged.merge(tmp, on="date", how="outer")

    assert merged is not None
    merged = merged.sort_values("date")
    years = merged["date"].dt.year
    julians = merged["date"].dt.dayofyear
    val_cols = [s.id for s in stations]

    out_path = out_dir / f"{ext}.{ext}"
    with out_path.open("w") as fh:
        fh.write(f"{title} created using swat_py\n")
        # NO Lati/Long/Elev headers for wnd/hmd/slr (unlike pcp/tmp)
        for y, j, row in zip(years, julians, merged[val_cols].itertuples(index=False)):
            vals = "".join(f"{v:08.3f}" for v in row)
            fh.write(f"{y:4d}{j:03d}{vals}\n")
    return out_path


def write_tmp(
    stations: List[StationInfo],
    wthr_dir: Path,
    out_dir: Path,
    fnamestr: Optional[str] = None,
) -> List[Path]:
    """Write tmp1.tmp, tmp2.tmp, ... in 150-station chunks."""
    n_files = math.ceil(len(stations) / _MAX_STATIONS_PER_FILE)
    paths: List[Path] = []

    for file_idx in range(n_files):
        chunk = stations[
            file_idx * _MAX_STATIONS_PER_FILE : (file_idx + 1) * _MAX_STATIONS_PER_FILE
        ]

        # Load tmax / tmin for chunk
        tmax_frames: List[pd.DataFrame] = []
        tmin_frames: List[pd.DataFrame] = []
        for stn in chunk:
            df = _load_station_data(wthr_dir, stn.id, fnamestr)
            tmax = linear_gap_fill(df["tmax"]).fillna(-99.0).rename(f"tmax_{stn.id}")
            tmin = linear_gap_fill(df["tmin"]).fillna(-99.0).rename(f"tmin_{stn.id}")
            tmax_frames.append(pd.concat([df["date"], tmax], axis=1))
            tmin_frames.append(pd.concat([df["date"], tmin], axis=1))

        # Merge wide
        merged = tmax_frames[0]
        for fm in tmax_frames[1:]:
            merged = merged.merge(fm, on="date", how="outer")
        for fm in tmin_frames:
            merged = merged.merge(fm, on="date", how="outer")
        merged = merged.sort_values("date")

        years = merged["date"].dt.year
        julians = merged["date"].dt.dayofyear
        tmax_cols = [f"tmax_{s.id}" for s in chunk]
        tmin_cols = [f"tmin_{s.id}" for s in chunk]

        out_path = out_dir / f"tmp{file_idx + 1}.tmp"
        with out_path.open("w") as fh:
            fh.write(
                f"Temperature Input File tmp{file_idx + 1}.tmp  created using swat_py\n"
            )
            fh.write(_header_lati_long_elev(chunk))
            for y, j, row in zip(
                years,
                julians,
                merged[tmax_cols + tmin_cols].itertuples(index=False),
            ):
                n = len(chunk)
                tmaxs = row[:n]
                tmins = row[n:]
                vals = "".join(
                    f"{mx:05.1f}{mn:05.1f}" for mx, mn in zip(tmaxs, tmins)
                )
                fh.write(f"{y:4d}{j:03d}{vals}\n")
        paths.append(out_path)
    return paths


def write_all_weather(
    stations: List[StationInfo],
    wthr_dir: Path,
    out_dir: Path,
    fnamestr: Optional[str] = None,
) -> None:
    """Write all SWAT 2012 combined weather input files."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    write_pcp(stations, wthr_dir, out_dir, fnamestr)
    write_tmp(stations, wthr_dir, out_dir, fnamestr)
    _write_combined_single("wspd", "wnd", "Wind Input File wnd.wnd", stations, wthr_dir, out_dir, fnamestr)
    _write_combined_single("rhum", "hmd", "Relative Humidity Input File hmd.hmd", stations, wthr_dir, out_dir, fnamestr)
    _write_combined_single("rsds", "slr", "Solar Radiation Input File slr.slr", stations, wthr_dir, out_dir, fnamestr)
