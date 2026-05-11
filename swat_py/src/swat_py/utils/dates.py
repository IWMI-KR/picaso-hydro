"""Date utility functions — julian day, yearmon helpers, leap-year logic."""

from __future__ import annotations

import datetime
from typing import Union

import pandas as pd


def to_julian(date: Union[datetime.date, str]) -> int:
    """Return 1-based day-of-year (julian day) for *date*."""
    if isinstance(date, str):
        date = datetime.date.fromisoformat(date)
    return date.timetuple().tm_yday


def is_leap_year(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def year_end_jday(year: int) -> int:
    """Return 365 or 366 depending on whether *year* is a leap year."""
    return 366 if is_leap_year(year) else 365


def add_date_parts(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Add year, month, yearmon columns derived from a date column.

    Mirrors R's Obs.Fill.Date().
    """
    df = df.copy()
    dates = pd.to_datetime(df[date_col])
    df["year"] = dates.dt.year
    df["month"] = dates.dt.month
    df["yearmon"] = dates.dt.strftime("%Y-%m")
    return df
