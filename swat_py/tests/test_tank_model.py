"""swat_py.tank.model — 3단 Tank 시뮬레이터 검증 (물수지·단위·경계)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.tank.model import (
    DEFAULT_BOUNDS, PARAM_ORDER, TankParams, bounds_from_config, simulate_tank,
)


def _mid_params() -> TankParams:
    x = [(lo + hi) / 2 for lo, hi in (DEFAULT_BOUNDS[k] for k in PARAM_ORDER)]
    return TankParams.from_vector(x)


def _rng_forcing(n=800, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-01", periods=n, freq="D")
    pcp = rng.gamma(0.6, 8.0, n) * (rng.random(n) < 0.5)   # 간헐 강우
    pet = 3.0 + 2.0 * np.sin(np.arange(n) / 58.0) ** 2       # 양수 계절 PET
    return dates, pcp, pet


def test_water_balance_closure():
    dates, pcp, pet = _rng_forcing()
    sim = simulate_tank(dates, pcp, pet, _mid_params(), area_km2=1.5)
    P = pcp.sum()
    Q = sim["q_mm"].sum()
    E = sim["e_mm"].sum()
    dS = sim[["s1", "s2", "s3"]].iloc[-1].sum()   # 초기저류 0
    np.testing.assert_allclose(P, Q + E + dS, rtol=0, atol=1e-6)


def test_storages_nonnegative():
    dates, pcp, pet = _rng_forcing(seed=3)
    sim = simulate_tank(dates, pcp, pet, _mid_params(), area_km2=1.0)
    assert (sim[["s1", "s2", "s3"]].to_numpy() >= -1e-9).all()
    assert (sim["q_mm"].to_numpy() >= -1e-9).all()


def test_mm_to_m3s_conversion():
    # 강수만, 증발 0, 파라미터: 1단 상단만 유출 → q_m3s = q_mm * area / 86.4
    dates = pd.date_range("2015-01-01", periods=10, freq="D")
    sim = simulate_tank(dates, [5.0] * 10, [0.0] * 10, _mid_params(), area_km2=2.0)
    np.testing.assert_allclose(sim["q_m3s"], sim["q_mm"] * 2.0 / 86.4, rtol=1e-9)


def test_no_input_decay_to_zero():
    dates = pd.date_range("2015-01-01", periods=400, freq="D")
    # 큰 초기저류에서 시작, 무강수·무증발 → 유출 감수, 저류 단조 감소
    sim = simulate_tank(dates, [0.0] * 400, [0.0] * 400, _mid_params(),
                        area_km2=1.0, s_init=(100.0, 50.0, 50.0))
    s_tot = sim[["s1", "s2", "s3"]].sum(axis=1).to_numpy()
    assert s_tot[-1] < s_tot[0]                     # 감수
    assert np.all(np.diff(s_tot) <= 1e-9)           # 단조 비증가
    assert sim["q_mm"].iloc[-1] < sim["q_mm"].iloc[0]


def test_higher_rain_more_runoff():
    dates, pcp, pet = _rng_forcing(seed=5)
    p = _mid_params()
    q_lo = simulate_tank(dates, pcp, pet, p, 1.0)["q_mm"].sum()
    q_hi = simulate_tank(dates, pcp * 2.0, pet, p, 1.0)["q_mm"].sum()
    assert q_hi > q_lo


def test_vector_roundtrip():
    p = _mid_params()
    np.testing.assert_allclose(TankParams.from_vector(p.to_vector()).to_vector(),
                               p.to_vector())


def test_bounds_from_config_override():
    b = bounds_from_config({"a1": [0.1, 0.2]})
    assert b[PARAM_ORDER.index("a1")] == (0.1, 0.2)
    assert b[PARAM_ORDER.index("a4")] == DEFAULT_BOUNDS["a4"]   # 미지정은 기본
    assert len(b) == len(PARAM_ORDER)
