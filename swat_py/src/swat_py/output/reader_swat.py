"""SWAT 2012 output file parsers.

Mirrors output_swat.R :: Swat.Rch.Summary() and Swat.Sub.Summary().
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


# 50 column names from output.rch (R source: output_swat.R line 17)
RCH_COLS: list[str] = [
    "Type", "RCH", "GIS", "MON", "AREAkm2",
    "FLOW_INcms", "FLOW_OUTcms", "EVAPcms", "TLOSScms",
    "SED_INtons", "SED_OUTtons", "SEDCONCmg/kg",
    "ORGN_INkg", "ORGN_OUTkg", "ORGP_INkg", "ORGP_OUTkg",
    "NO3_INkg", "NO3_OUTkg", "NH4_INkg", "NH4_OUTkg",
    "NO2_INkg", "NO2_OUTkg", "MINP_INkg", "MINP_OUTkg",
    "CHLA_INkg", "CHLA_OUTkg", "CBOD_INkg", "CBOD_OUTkg",
    "DISOX_INkg", "DISOX_OUTkg",
    # columns 31-50 (optional in older SWAT versions)
    "SOLPST_INmg", "SOLPST_OUTmg", "SORPST_INmg", "SORPST_OUTmg",
    "REACTPSTmg", "VOLPSTmg", "SETTLPSTmg", "RESUSP_PSTmg",
    "DIFFUSEPSTmg", "REACBEDPSTmg", "BURYPSTmg", "BED_PSTmg",
    "BACTP_OUTct", "BACTLP_OUTct",
    "CMETAL#1kg", "CMETAL#2kg", "CMETAL#3kg",
    "TOT Nkg", "TOT Pkg", "NO3ConcMg/l", "WTMPdegc",
]


def parse_output_rch(
    path: Path,
    outlet: int,
    sdate: str,
    skip: int = 9,
) -> Optional[pd.DataFrame]:
    """Parse output.rch and return daily data for *outlet*.

    Parameters
    ----------
    path:    Path to ``output-{SimType}.rch``.
    outlet:  GIS reach ID (column 2, 0-based index 1 in R's 1-based col 2).
    sdate:   Simulation start date ``"YYYY-01-01"`` (before warm-up skip).
    skip:    Header rows to skip (default 9).

    Returns
    -------
    DataFrame with raw rch columns plus a ``date`` column.
    ``None`` if file is unreadable or outlet not found.
    """
    path = Path(path)
    if not path.exists():
        return None

    # Try multiple encodings — SWAT 2012 output files on Korean Windows use cp949
    for enc in ("utf-8", "cp949", "latin-1"):
        try:
            df = pd.read_csv(
                path,
                sep=r"\s+",
                skiprows=skip,
                header=None,
                na_values=["-99", "-99.0"],
                encoding=enc,
            )
            break
        except UnicodeDecodeError:
            continue
        except Exception:
            return None
    else:
        return None

    if df.empty:
        return None

    # Filter to target outlet (col index 1 → "RCH" in R code column 2)
    # R: file[which(file[,2]==outlet), 1:ColCnt]  (1-based → index 1)
    n_cols = min(30, df.shape[1])
    df = df[df.iloc[:, 1] == outlet].iloc[:, :n_cols].copy()
    if df.empty:
        return None

    df.columns = RCH_COLS[:n_cols]

    # Assign date sequence (one row per day)
    n_rows = len(df)
    start = pd.Timestamp(sdate)
    df["date"] = pd.date_range(start=start, periods=n_rows, freq="D")
    df = df.reset_index(drop=True)

    return df


def extract_rch_outtype(
    df: pd.DataFrame,
    outtype: str,
    ws_area_km2: Optional[float] = None,
) -> pd.DataFrame:
    """Extract derived columns for a given output type.

    Parameters
    ----------
    df:          Raw rch DataFrame from :func:`parse_output_rch`.
    outtype:     One of ``"flow"``, ``"flowd"``, ``"sed"``, ``"sedc"``,
                 ``"tn"``, ``"tnc"``, ``"tp"``, ``"tpc"``.
    ws_area_km2: Watershed area in km² (required for ``"flowd"``).
    """
    result = pd.DataFrame({"date": df["date"]})

    if outtype == "flow":
        result["flow_cms"] = df["FLOW_OUTcms"]

    elif outtype == "flowd":
        if ws_area_km2 is None:
            ws_area_km2 = float(df["AREAkm2"].iloc[0])
        result["flow_mm"] = df["FLOW_OUTcms"] * 86400 / (ws_area_km2 * 1e3)

    elif outtype == "sed":
        result["Sed_ton"] = df["SED_OUTtons"]

    elif outtype == "sedc":
        result["Sed_mgl"] = (
            df["SED_OUTtons"] * 1e6 / (df["FLOW_OUTcms"] * 86400)
        )

    elif outtype == "tn":
        result["OrgN_kg"] = df["ORGN_OUTkg"]
        result["NO3_kg"]  = df["NO3_OUTkg"]
        result["NH4_kg"]  = df["NH4_OUTkg"]
        result["NO2_kg"]  = df["NO2_OUTkg"]
        result["TN_kg"]   = (
            result["OrgN_kg"] + result["NO3_kg"]
            + result["NH4_kg"] + result["NO2_kg"]
        )

    elif outtype == "tnc":
        flow_s = df["FLOW_OUTcms"] * 86400
        result["OrgN_mgl"] = df["ORGN_OUTkg"] * 1e3 / flow_s
        result["NO3_mgl"]  = df["NO3_OUTkg"]  * 1e3 / flow_s
        result["NH4_mgl"]  = df["NH4_OUTkg"]  * 1e3 / flow_s
        result["NO2_mgl"]  = df["NO2_OUTkg"]  * 1e3 / flow_s
        result["TN_mgl"]   = (
            result["OrgN_mgl"] + result["NO3_mgl"]
            + result["NH4_mgl"] + result["NO2_mgl"]
        )

    elif outtype == "tp":
        result["OrgP_kg"] = df["ORGP_OUTkg"]
        result["MinP_kg"] = df["MINP_OUTkg"]
        result["TP_kg"]   = result["OrgP_kg"] + result["MinP_kg"]

    elif outtype == "tpc":
        flow_s = df["FLOW_OUTcms"] * 86400
        result["OrgP_mgl"] = df["ORGP_OUTkg"] * 1e3 / flow_s
        result["MinP_mgl"] = df["MINP_OUTkg"] * 1e3 / flow_s
        result["TP_mgl"]   = result["OrgP_mgl"] + result["MinP_mgl"]

    else:
        raise ValueError(
            f"Unknown outtype '{outtype}'. "
            "Use flow/flowd/sed/sedc/tn/tnc/tp/tpc."
        )

    return result
