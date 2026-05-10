"""Output aggregation — daily → monthly → annual.

Mirrors the aggregate() calls in output_swat.R and output_swat_plus.R.
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from swat_py.utils.dates import add_date_parts as _add_date_parts


def add_date_parts(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Add year, month, yearmon columns to *df*."""
    return _add_date_parts(df, date_col)


def _value_cols(df: pd.DataFrame) -> list[str]:
    """Return all non-date, non-grouping columns."""
    return [
        c for c in df.columns
        if c not in ("date", "year", "month", "yearmon")
    ]


def aggregate_output(
    df: pd.DataFrame,
    funtype: str = "mean",
    sdate2: Optional[str] = None,
    edate2: Optional[str] = None,
) -> Dict[str, pd.DataFrame]:
    """Aggregate a daily DataFrame to monthly, annual, and yearmon cadences.

    Parameters
    ----------
    df:
        Daily DataFrame with a ``date`` column and one or more value columns.
        Must already have ``year``, ``month``, ``yearmon`` added via
        :func:`add_date_parts`.
    funtype:
        Aggregation function name: ``"mean"``, ``"sum"``, ``"max"``,
        ``"min"``, ``"std"``, or ``"count"``.
    sdate2:
        Optional start date for the output period (warm-up skip).
    edate2:
        Optional end date for the output period.

    Returns
    -------
    dict with keys ``"daily"``, ``"monthly"``, ``"annual"``, ``"yearmon"``.
    """
    if "year" not in df.columns:
        df = add_date_parts(df)

    # Apply date range filter
    if sdate2:
        df = df[df["date"] >= pd.Timestamp(sdate2)]
    if edate2:
        df = df[df["date"] <= pd.Timestamp(edate2)]

    val_cols = _value_cols(df)
    agg_func = _resolve_func(funtype)

    # yearmon aggregation
    ymdata = df.groupby("yearmon")[val_cols].agg(agg_func).reset_index()
    ymdata["count"] = df.groupby("yearmon")[val_cols[0]].count().values

    # monthly (all years combined)
    mdata = df.groupby("month")[val_cols].agg(agg_func).reset_index()
    mdata["count"] = df.groupby("month")[val_cols[0]].count().values

    # annual
    ydata = df.groupby("year")[val_cols].agg(agg_func).reset_index()
    ydata["count"] = df.groupby("year")[val_cols[0]].count().values

    return {
        "daily": df.reset_index(drop=True),
        "monthly": mdata,
        "annual": ydata,
        "yearmon": ymdata,
    }


def _resolve_func(funtype: str):
    """Map R aggregate function name to pandas-compatible callable."""
    mapping = {
        "mean":   "mean",
        "sum":    "sum",
        "max":    "max",
        "min":    "min",
        "sd":     "std",
        "std":    "std",
        "length": "count",
        "count":  "count",
    }
    if funtype not in mapping:
        raise ValueError(
            f"Unknown funtype '{funtype}'. "
            "Use mean/sum/max/min/sd/std/length/count."
        )
    return mapping[funtype]
