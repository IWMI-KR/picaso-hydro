"""저수지 수위 목적 Tank 검보정 — 물수지·datum 순수함수 검증."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.io.reservoir import StageStorageCurve
from swat_py.tank.reservoir_calibrate import _reservoir_level, _load_obs_msl, _metrics


def _curve():
    # 선형: 0 m³=23.34ft(bottom), 100000 m³=45ft(spillway)
    return StageStorageCurve(elev_ft=np.array([23.34, 45.0]),
                             storage_m3=np.array([0.0, 100000.0]))


def test_reservoir_level_drawdown_and_full():
    curve = _curve()
    full = float(curve.stage_to_storage(45.0)); dead = float(curve.stage_to_storage(23.34))
    dates = pd.date_range("2018-01-02", "2018-03-31", freq="D")
    # 저유입(0.001 m³/s) < 취수(0.05 m³/s=4320 m³/일) → 저수위 하강
    simq = pd.DataFrame({"date": dates, "q_m3s": 0.001})
    lv = _reservoir_level(simq, curve=curve, full_m3=full, dead_m3=dead,
                          withdrawal_m3s=0.05, init_m3=full, obs_start="2018-01-02")
    assert lv["level_msl"].iloc[0] < 45.0            # 첫날부터 하강
    assert (lv["level_msl"].diff().dropna() <= 1e-9).all()   # 단조 하강
    assert lv["level_msl"].min() >= 23.34 - 1e-6     # 사수위 하한
    # 고유입(1 m³/s) ≫ 취수 → 만수(여수로) 유지
    simq2 = pd.DataFrame({"date": dates, "q_m3s": 1.0})
    lv2 = _reservoir_level(simq2, curve=curve, full_m3=full, dead_m3=dead,
                           withdrawal_m3s=0.05, init_m3=full, obs_start="2018-01-02")
    assert lv2["level_msl"].max() <= 45.0 + 1e-6
    assert lv2["level_msl"].iloc[-1] == pytest.approx(45.0)


def test_load_obs_msl_datum(tmp_path):
    csv = tmp_path / "res.csv"
    pd.DataFrame({"date": pd.date_range("2018-01-01", periods=4, freq="D"),
                  "wlevel_ft": [23.0, 0.0, 22.0, 23.0]}).to_csv(csv, index=False)
    df = _load_obs_msl(csv, "wlevel_ft", -22.0)      # MSL = obs - (-22) = obs+22
    assert len(df) == 3                              # staff 0 제외
    assert df["obs_msl"].iloc[0] == pytest.approx(45.0)   # 23 → 45(만수)


def test_metrics_period_filter():
    dates = pd.date_range("2018-01-01", periods=100, freq="D")
    obs = np.linspace(40, 45, 100)
    m = _metrics(dates, obs, dates, obs, period=("2018-01-01", "2018-02-01"))
    assert m["nse"] == pytest.approx(1.0, abs=1e-6)  # 완전 일치
    assert m["n"] == 32
