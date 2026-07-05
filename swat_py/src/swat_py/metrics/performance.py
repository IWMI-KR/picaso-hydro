"""Model performance metrics.

Mirrors output_swat.R :: Swat.Calc.Error().

All functions accept array-like inputs and return scalar floats.
NaN values in either obs or sim are excluded before computation.
"""

from __future__ import annotations

from typing import Dict, Union

import numpy as np
import pandas as pd


ArrayLike = Union[np.ndarray, pd.Series]


def _clean(obs: ArrayLike, sim: ArrayLike):
    """Return aligned numpy arrays with NaN pairs removed."""
    obs_a = np.asarray(obs, dtype=float)
    sim_a = np.asarray(sim, dtype=float)
    mask = ~(np.isnan(obs_a) | np.isnan(sim_a))
    return obs_a[mask], sim_a[mask]


def nse(obs: ArrayLike, sim: ArrayLike) -> float:
    """Nash-Sutcliffe Efficiency.

    NSE = 1 - Σ(obs-sim)² / Σ(obs-mean_obs)²

    Returns NaN if no valid pairs exist or variance of obs is zero.
    """
    o, s = _clean(obs, sim)
    if len(o) == 0:
        return float("nan")
    denom = np.sum((o - o.mean()) ** 2)
    if denom == 0:
        return float("nan")
    return float(1.0 - np.sum((o - s) ** 2) / denom)


def rmse(obs: ArrayLike, sim: ArrayLike) -> float:
    """Root Mean Square Error."""
    o, s = _clean(obs, sim)
    if len(o) == 0:
        return float("nan")
    return float(np.sqrt(np.mean((o - s) ** 2)))


def rsr(obs: ArrayLike, sim: ArrayLike) -> float:
    """RMSE / standard deviation of observations (RSR).

    RSR = RMSE / StdDev(obs)
    """
    o, s = _clean(obs, sim)
    if len(o) == 0:
        return float("nan")
    std_obs = np.std(o, ddof=0)
    if std_obs == 0:
        return float("nan")
    return float(rmse(o, s) / std_obs)


def pbias(obs: ArrayLike, sim: ArrayLike) -> float:
    """Percent bias.

    PBIAS = 100 × Σ(obs - sim) / Σ(obs)

    Returns NaN if sum of obs is zero.
    """
    o, s = _clean(obs, sim)
    if len(o) == 0:
        return float("nan")
    denom = np.sum(o)
    if denom == 0:
        return float("nan")
    return float(100.0 * np.sum(o - s) / denom)


def r2(obs: ArrayLike, sim: ArrayLike) -> float:
    """Coefficient of determination (R²) from linear regression sim ~ obs."""
    o, s = _clean(obs, sim)
    if len(o) < 2:
        return float("nan")
    corr_mat = np.corrcoef(o, s)
    return float(corr_mat[0, 1] ** 2)


def mae(obs: ArrayLike, sim: ArrayLike) -> float:
    """Mean Absolute Error."""
    o, s = _clean(obs, sim)
    if len(o) == 0:
        return float("nan")
    return float(np.mean(np.abs(o - s)))


def nof(obs: ArrayLike, sim: ArrayLike) -> float:
    """Normalized Objective Function.

    NOF = √Σ(obs-sim)² / √Σ(obs-mean_obs)²
    """
    o, s = _clean(obs, sim)
    if len(o) == 0:
        return float("nan")
    denom = np.sqrt(np.sum((o - o.mean()) ** 2))
    if denom == 0:
        return float("nan")
    return float(np.sqrt(np.sum((o - s) ** 2)) / denom)


def kge(obs: ArrayLike, sim: ArrayLike) -> float:
    """Kling-Gupta Efficiency (2009).

    KGE = 1 - √((r-1)² + (α-1)² + (β-1)²)
      r = 상관계수, α = std(sim)/std(obs), β = mean(sim)/mean(obs).
    1.0 이 최선. 관측 표준편차/평균이 0 이면 NaN.
    """
    o, s = _clean(obs, sim)
    if len(o) < 2:
        return float("nan")
    std_o = np.std(o, ddof=0)
    mean_o = o.mean()
    if std_o == 0 or mean_o == 0:
        return float("nan")
    r_mat = np.corrcoef(o, s)
    r = float(r_mat[0, 1])
    alpha = float(np.std(s, ddof=0) / std_o)
    beta = float(s.mean() / mean_o)
    return float(1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))


def calc_all(obs: ArrayLike, sim: ArrayLike) -> Dict[str, float]:
    """Compute all performance metrics at once.

    Returns
    -------
    dict with keys: ``nse``, ``kge``, ``rmse``, ``rsr``, ``pbias``, ``r2``,
    ``mae``, ``nof``.
    """
    return {
        "nse":   nse(obs, sim),
        "kge":   kge(obs, sim),
        "rmse":  rmse(obs, sim),
        "rsr":   rsr(obs, sim),
        "pbias": pbias(obs, sim),
        "r2":    r2(obs, sim),
        "mae":   mae(obs, sim),
        "nof":   nof(obs, sim),
    }
