"""SWAT-Plus output file parsers.

Mirrors output_swat_plus.R :: Swat.Cha.Summary.Plus() and
Swat.Wb.Summary.Plus().
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from swat_py.output.aggregator import aggregate_output, add_date_parts


# ── channel_sd_day.txt parser ──────────────────────────────────────────────────

def _detect_colnames(path: Path) -> list[str]:
    """Scan file lines for the header row containing 'gis_id'."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "gis_id" in line.lower():
                parts = line.strip().split()
                return parts
    raise ValueError(f"Column header with 'gis_id' not found in {path}")


def parse_channel_sd_day(
    path: Path,
    outlet: int,
    sdate: str,
    skip: int = 3,
) -> Optional[pd.DataFrame]:
    """Parse channel_sd_day.txt and return daily data for *outlet*.

    Parameters
    ----------
    path:    Full path to ``channel_sd_day-{SimType}.txt``.
    outlet:  Channel GIS id (value in the ``gis_id`` column). QSWAT+ 채널 번호.
    sdate:   Simulation start date string ``"YYYY-01-01"`` (before warm-up skip).
    skip:    Header rows to skip (default 3).

    Returns
    -------
    DataFrame with columns: date, flo_out, sed_out, orgn_out, no3_out,
    nh3_out, no2_out, sedp_out, solp_out, ... (all raw channel output columns).
    Returns ``None`` if file cannot be read or outlet has no data.
    """
    path = Path(path)
    if not path.exists():
        return None

    colnames = _detect_colnames(path)

    try:
        df = pd.read_csv(
            path,
            sep=r"\s+",
            skiprows=skip,
            header=None,
            na_values=["-99", "-99.0"],
        )
    except Exception:
        return None

    if df.empty:
        return None

    # Filter on the gis_id column, located dynamically from the header row.
    # (열 순서: jday mon day yr unit gis_id name ... — gis_id 는 보통 index 5,
    #  단 하드코딩하지 않고 헤더에서 위치를 찾아 SWAT+ 버전 차이에 견고하게 대응.)
    try:
        gis_idx = [c.lower() for c in colnames].index("gis_id")
    except ValueError:
        return None
    if gis_idx >= df.shape[1]:
        return None
    df = df[df.iloc[:, gis_idx] == outlet].copy()
    if df.empty:
        return None

    n_cols = min(len(colnames), df.shape[1])
    df = df.iloc[:, :n_cols].copy()
    df.columns = colnames[:n_cols]

    # Assign date sequence
    n_rows = len(df)
    start = pd.Timestamp(sdate)
    df["date"] = pd.date_range(start=start, periods=n_rows, freq="D")
    df = df.reset_index(drop=True)

    return df


# ── outtype extraction ─────────────────────────────────────────────────────────

def extract_cha_outtype(df: pd.DataFrame, outtype: str) -> pd.DataFrame:
    """Extract and compute derived columns for a given output type.

    Parameters
    ----------
    df:       Raw channel DataFrame from :func:`parse_channel_sd_day`.
    outtype:  One of ``"flow"``, ``"sedc"``, ``"tnc"``, ``"tpc"``.

    Returns
    -------
    DataFrame with ``date`` plus outtype-specific columns.
    """
    result = pd.DataFrame({"date": df["date"]})

    if outtype == "flow":
        result["flow_cms"] = df["flo_out"]

    elif outtype == "sedc":
        result["Sed_mgl"] = (
            (df["sed_out"] * 1e6) / (df["flo_out"] * 86400)
        )

    elif outtype == "tnc":
        flow_s = df["flo_out"] * 86400
        result["OrgN_mgl"] = df["orgn_out"] * 1e3 / flow_s
        result["NO3_mgl"]  = df["no3_out"]  * 1e3 / flow_s
        result["NH4_mgl"]  = df["nh3_out"]  * 1e3 / flow_s
        result["NO2_mgl"]  = df["no2_out"]  * 1e3 / flow_s
        result["TN_mgl"]   = (
            result["OrgN_mgl"] + result["NO3_mgl"]
            + result["NH4_mgl"] + result["NO2_mgl"]
        )

    elif outtype == "tpc":
        flow_s = df["flo_out"] * 86400
        result["OrgP_mgl"] = df["sedp_out"] * 1e3 / flow_s
        result["MinP_mgl"] = df["solp_out"] * 1e3 / flow_s
        result["TP_mgl"]   = result["OrgP_mgl"] + result["MinP_mgl"]

    else:
        raise ValueError(f"Unknown outtype '{outtype}'. Use flow/sedc/tnc/tpc.")

    return result


# ── basin water-balance parser ─────────────────────────────────────────────────

def parse_basin_wb_day(
    path: Path,
    sdate: str,
    ws_area_km2: Optional[float] = None,
    skip: int = 9,
) -> Optional[pd.DataFrame]:
    """Parse basin_wb_day.txt.

    Returns a raw DataFrame; further extraction mirrors
    Swat.Wb.Summary.Plus().
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, sep=r"\s+", skiprows=skip, header=None)
    except Exception:
        return None

    if df.empty:
        return None

    n_rows = len(df)
    start = pd.Timestamp(sdate)
    df["date"] = pd.date_range(start=start, periods=n_rows, freq="D")
    return df
