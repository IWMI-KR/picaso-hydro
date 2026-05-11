"""SWAT-Plus weather input writers.

Mirrors input_swat_plus.R :: Swat.Write.Weather.Input.MultiStations.Plus().

Output files per station:
  {stnid}.pcp  — precipitation (mm)
  {stnid}.tmp  — tmax / tmin (°C)
  {stnid}.wnd  — wind speed (m/s)
  {stnid}.hmd  — relative humidity (fraction 0-1)
  {stnid}.slr  — solar radiation (MJ/m²)

Index files:
  pcp.cli / tmp.cli / wnd.cli / hmd.cli / slr.cli

weather-sta.cli updater:
  write_weather_sta_cli() — replaces "sim" entries with measured station files
"""

from __future__ import annotations

import fnmatch
import math
from pathlib import Path
from typing import List, Optional

import pandas as pd

from swat_py.io.station import StationInfo, load_station_csv
from swat_py.utils.interpolate import linear_gap_fill


# ── helpers ────────────────────────────────────────────────────────────────────

def _load_station_data(
    wthr_dir: Path,
    stn_id: str,
    fnamestr: Optional[str],
) -> pd.DataFrame:
    """Load a daily weather CSV for one station.

    Supports two file naming conventions:
      - With scenario tag:  ``*{stn_id}_*{fnamestr}.csv``
      - Without tag:        ``*{stn_id}.csv``

    Handles two CSV formats:
      - **12-column format** (standard): year, mon, day, prcp, tmax, tmin,
        wspd, rhum, rsds, sshine, cloud, tavg
      - **7-column format** (compact): Year, Pcp(mm), Tmax(c), Tmin(c),
        WSpeed(m/s), RHumidity(fr), SRad(MJ/m2)  — dates are inferred from
        the Year column and sequential row order.

    Returns a DataFrame with columns:
        date, prcp, tmax, tmin, wspd, rhum, rsds
    """
    pattern = (
        f"*{stn_id}_*{fnamestr}.csv" if fnamestr else f"*{stn_id}.csv"
    )
    matches = [f for f in wthr_dir.iterdir() if fnmatch.fnmatch(f.name, pattern)]
    if not matches:
        raise FileNotFoundError(
            f"No weather file for station '{stn_id}' in {wthr_dir} "
            f"(pattern: {pattern})"
        )
    df = pd.read_csv(
        matches[0],
        na_values=["-99.00", "-99.0", "-99", -99.0, -99],
    )

    # Normalise column names (case-insensitive, strip units in parentheses)
    raw_cols = df.columns.tolist()
    clean = [c.lower().split("(")[0].strip() for c in raw_cols]

    if df.shape[1] == 12:
        # Standard 12-column format: year mon day prcp tmax tmin wspd rhum rsds ...
        df.columns = [
            "year", "mon", "day",
            "prcp", "tmax", "tmin", "wspd", "rhum", "rsds",
            "sshine", "cloud", "tavg",
        ]
        df["date"] = pd.to_datetime(
            df[["year", "mon", "day"]].rename(columns={"mon": "month"})
        )

    elif df.shape[1] == 7 and "year" in clean and "mon" not in clean:
        # Compact 7-column format: Year Pcp Tmax Tmin WSpeed RHumidity SRad
        # Dates inferred from Year column (sequential days within each year).
        df.columns = ["year", "prcp", "tmax", "tmin", "wspd", "rhum", "rsds"]
        start_date = pd.Timestamp(f"{int(df['year'].iloc[0])}-01-01")
        df["date"] = pd.date_range(start=start_date, periods=len(df), freq="D")

    else:
        # Best-effort mapping by lowercased column name
        rename_map: dict[str, str] = {}
        for raw, c in zip(raw_cols, clean):
            if c == "year":          rename_map[raw] = "year"
            elif c in ("mon", "month"): rename_map[raw] = "mon"
            elif c == "day":         rename_map[raw] = "day"
            elif c in ("prcp", "pcp", "rain", "precip"): rename_map[raw] = "prcp"
            elif c == "tmax":        rename_map[raw] = "tmax"
            elif c == "tmin":        rename_map[raw] = "tmin"
            elif c in ("wspd", "wsp", "wspd", "wind", "wspeed", "wdspd"):
                rename_map[raw] = "wspd"
            elif c in ("rhum", "rh", "humidity", "humid"):
                rename_map[raw] = "rhum"
            elif c in ("rsds", "slr", "srad", "solar", "sr"):
                rename_map[raw] = "rsds"
        df = df.rename(columns=rename_map)
        if "date" not in df.columns:
            df["date"] = pd.to_datetime(
                df[["year", "mon", "day"]].rename(columns={"mon": "month"})
            )

    for col in ("prcp", "tmax", "tmin", "wspd", "rhum", "rsds"):
        if col not in df.columns:
            df[col] = float("nan")

    return df[["date", "prcp", "tmax", "tmin", "wspd", "rhum", "rsds"]].copy()


def _station_header(stn: StationInfo, n_years: int) -> str:
    """One-line data header + metadata row (SWAT-Plus per-station format)."""
    return (
        " nbyr       tstep          lat          lon         elev\n"
        f"{n_years:5d}           0     {stn.lat:8.3f}     {stn.lon:8.3f}     {stn.elev:8.3f}\n"
    )


# ── per-variable writers ───────────────────────────────────────────────────────

def _write_single_var(
    stn: StationInfo,
    df: pd.DataFrame,
    var_col: str,
    ext: str,
    out_dir: Path,
    var_label: str,
) -> Path:
    """Write a single-value-per-day station file (.pcp / .wnd / .hmd / .slr).

    Format matches R's ``sprintf("%4d  %3d   %8.5f", year, julian, value)``.
    Missing values (-99) tell SWAT-Plus to use the weather generator (wgen).
    """
    series = linear_gap_fill(df[var_col].copy())
    series = series.fillna(-99.0)

    years = df["date"].dt.year
    julians = df["date"].dt.dayofyear
    n_years = years.nunique()

    out_path = out_dir / f"{stn.id}.{ext}"
    with out_path.open("w") as fh:
        fh.write(f"{stn.id}.{ext}: {var_label} - file written by swat_py\n")
        fh.write(_station_header(stn, n_years))
        for y, j, v in zip(years, julians, series):
            fh.write(f"{y:4d}  {j:3d}   {v:8.5f}\n")
    return out_path


def _write_tmp(
    stn: StationInfo,
    df: pd.DataFrame,
    out_dir: Path,
) -> Path:
    """Write a two-column temperature file (.tmp).

    Format: ``%4d  %3d   %8.5f   %8.5f`` (year, julian, tmax, tmin).
    """
    tmax = linear_gap_fill(df["tmax"].copy()).fillna(-99.0)
    tmin = linear_gap_fill(df["tmin"].copy()).fillna(-99.0)

    years = df["date"].dt.year
    julians = df["date"].dt.dayofyear
    n_years = years.nunique()

    out_path = out_dir / f"{stn.id}.tmp"
    with out_path.open("w") as fh:
        fh.write(f"{stn.id}.tmp: Temperature data - file written by swat_py\n")
        fh.write(_station_header(stn, n_years))
        for y, j, mx, mn in zip(years, julians, tmax, tmin):
            fh.write(f"{y:4d}  {j:3d}   {mx:8.5f}   {mn:8.5f}\n")
    return out_path


# ── CLI index writers ──────────────────────────────────────────────────────────

_CLI_LABELS = {
    "pcp": ("pcp.cli", "Precipitation file names"),
    "tmp": ("tmp.cli", "Temperature file names"),
    "wnd": ("wnd.cli", "Wind speed file names"),
    "hmd": ("hmd.cli", "Relative humidity file names"),
    "slr": ("slr.cli", "Solar radiation file names"),
}


def write_cli_index(variable: str, station_ids: List[str], out_dir: Path) -> Path:
    """Write a .cli index file listing station weather files.

    Parameters
    ----------
    variable:
        One of ``pcp``, ``tmp``, ``wnd``, ``hmd``, ``slr``.
    station_ids:
        List of station IDs (filenames will be ``{id}.{variable}``).
    out_dir:
        Directory to write the .cli file.
    """
    fname, label = _CLI_LABELS[variable]
    out_path = out_dir / fname
    with out_path.open("w") as fh:
        fh.write(f"{fname}: {label} - file written by swat_py\n")
        fh.write("filename\n")
        for stn_id in station_ids:
            fh.write(f"{stn_id}.{variable}\n")
    return out_path


# ── weather-sta.cli updater ────────────────────────────────────────────────────

def write_weather_sta_cli(
    wdir: Path,
    stations: List[StationInfo],
) -> None:
    """Update weather-sta.cli to use measured station files.

    Replaces ``"sim"`` entries with actual per-station weather filenames.

    Assignment strategy
    -------------------
    Each grid row in weather-sta.cli is assigned to the **nearest** station
    in *stations* by Euclidean distance in (lat, lon).  For a single station,
    all grid rows are assigned to that station.

    If weather-sta.cli already has non-``"sim"`` entries for all variables,
    the file is left unchanged (existing setup respected).

    Parameters
    ----------
    wdir:     SWAT-Plus TxtInOut directory containing weather-sta.cli.
    stations: Station metadata (id, lat, lon, elev) to assign.
    """
    path = Path(wdir) / "weather-sta.cli"
    if not path.exists():
        raise FileNotFoundError(f"weather-sta.cli not found in {wdir}")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(lines) < 3:
        return  # malformed file

    # Identify column positions from header line
    header_line = lines[1]
    # Find indices of pcp, tmp, slr, hmd, wnd columns
    header_cols = header_line.split()
    # Typical order: name, wgn, pcp, tmp, slr, hmd, wnd, wnd_dir, atmo_dep
    try:
        idx_pcp = header_cols.index("pcp")
        idx_tmp = header_cols.index("tmp")
        idx_slr = header_cols.index("slr")
        idx_hmd = header_cols.index("hmd")
        idx_wnd = header_cols.index("wnd")
    except ValueError:
        # Non-standard header; fall back to fixed positions 2,3,4,5,6
        idx_pcp, idx_tmp, idx_slr, idx_hmd, idx_wnd = 2, 3, 4, 5, 6

    def _nearest(grid_name: str) -> StationInfo:
        """Return closest station to the grid point encoded in grid_name."""
        if len(stations) == 1:
            return stations[0]
        # Parse grid lat/lon from name like "s36762n127293e" (lat*1000, lon*1000)
        try:
            # Name pattern: s{lat*1000}n{lon*1000}e  (degrees × 1000)
            import re
            m = re.match(r"s(\d+)n(\d+)e", grid_name.lower())
            if m:
                g_lat = int(m.group(1)) / 1000.0
                g_lon = int(m.group(2)) / 1000.0
            else:
                return stations[0]
        except Exception:
            return stations[0]

        dists = [
            math.sqrt((s.lat - g_lat) ** 2 + (s.lon - g_lon) ** 2)
            for s in stations
        ]
        return stations[dists.index(min(dists))]

    new_lines: List[str] = []
    for idx, line in enumerate(lines):
        if idx < 2:
            new_lines.append(line)
            continue

        parts = line.split()
        if not parts:
            new_lines.append(line)
            continue

        # Check if any weather variable is still "sim"
        has_sim = any(
            len(parts) > i and parts[i].lower() == "sim"
            for i in (idx_pcp, idx_tmp, idx_slr, idx_hmd, idx_wnd)
        )

        if not has_sim:
            # Already configured with actual files
            new_lines.append(line)
            continue

        stn = _nearest(parts[0])
        # Replace sim entries; preserve other columns as-is
        while len(parts) <= max(idx_pcp, idx_tmp, idx_slr, idx_hmd, idx_wnd):
            parts.append("null")

        parts[idx_pcp] = f"{stn.id}.pcp"
        parts[idx_tmp] = f"{stn.id}.tmp"
        parts[idx_slr] = f"{stn.id}.slr"
        parts[idx_hmd] = f"{stn.id}.hmd"
        parts[idx_wnd] = f"{stn.id}.wnd"

        # Rebuild line with consistent spacing (preserve original alignment)
        # Use fixed-width columns matching SWAT-Plus editor format
        name_col = f"{parts[0]:<30}"
        wgn_col  = f"{parts[1]:<30}"
        weather_cols = "  ".join(f"{p:<26}" for p in parts[2:])
        new_lines.append(f"{name_col}  {wgn_col}  {weather_cols}\n")

    path.write_text("".join(new_lines), encoding="utf-8")


# ── main entry point ───────────────────────────────────────────────────────────

def write_all_weather_plus(
    stations: List[StationInfo],
    wthr_dir: Path,
    out_dir: Path,
    fnamestr: Optional[str] = None,
    update_weather_sta: bool = True,
) -> None:
    """Write all SWAT-Plus weather input files for *stations*.

    Steps
    -----
    1. Write per-station data files (``{id}.pcp``, ``.tmp``, ``.wnd``,
       ``.hmd``, ``.slr``) to *out_dir*.
    2. Write CLI index files (``pcp.cli`` etc.) in *out_dir*.
    3. Optionally update ``weather-sta.cli`` to reference measured files
       instead of ``"sim"`` (``update_weather_sta=True``).

    Parameters
    ----------
    stations:
        Station metadata list.
    wthr_dir:
        Directory containing raw daily CSV files.
    out_dir:
        Destination directory (SWAT-Plus TxtInOut or equivalent).
    fnamestr:
        Optional scenario suffix to locate CSV files (e.g. ``"historical"``).
    update_weather_sta:
        If ``True`` and ``weather-sta.cli`` exists in *out_dir*, update it
        to replace ``"sim"`` entries with actual station file references.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stn_ids = [s.id for s in stations]

    # 1. Write per-station data files
    for stn in stations:
        df = _load_station_data(Path(wthr_dir), stn.id, fnamestr)

        _write_single_var(stn, df, "prcp", "pcp", out_dir, "Precipitation data")
        _write_tmp(stn, df, out_dir)
        _write_single_var(stn, df, "wspd", "wnd", out_dir, "Wind speed data")
        _write_single_var(stn, df, "rhum", "hmd", out_dir, "Relative humidity data")
        _write_single_var(stn, df, "rsds", "slr", out_dir, "Solar radiation data")

    # 2. Write CLI index files
    for var in ("pcp", "tmp", "wnd", "hmd", "slr"):
        write_cli_index(var, stn_ids, out_dir)

    # 3. Update weather-sta.cli if requested
    if update_weather_sta and (out_dir / "weather-sta.cli").exists():
        write_weather_sta_cli(out_dir, stations)
