"""Linear gap-fill utility — mirrors zoo::na.approx from R."""

from __future__ import annotations

import pandas as pd


def linear_gap_fill(series: pd.Series) -> pd.Series:
    """Linearly interpolate NaN values in *series*.

    Mirrors R's ``zoo::na.approx(x, na.rm=FALSE)`` (default rule=1):
      - Gaps between valid values → linear interpolation.
      - Leading NaN (before first valid value) → left as NaN.
      - Trailing NaN (after last valid value) → left as NaN.

    The caller is responsible for filling remaining NaN with -99
    (which tells SWAT to use its internal weather generator for
    those periods, as intended by the rSWAT design).

    Returns the original series unchanged when ALL values are NaN.
    """
    if series.isna().all():
        return series
    # limit_area="inside" fills ONLY gaps between valid values;
    # leading / trailing NaN are left untouched — matches R na.approx(rule=1).
    return series.interpolate(method="linear", limit_area="inside")
