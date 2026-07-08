"""저수지 가뭄예측 — 월 저수량 물수지 → 만수 대비 %(capacity_fraction)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swat_py.drought.reservoir_forecast import (
    monthly_capacity_pct,
    monthly_capacity_series,
    member_reservoir_capacity_pct,
    member_reservoir_series,
    build_reservoir_forecast_params,
    ReservoirForecastParams,
)
from swat_py.drought.stages import stage_probabilities4
from swat_py.drought.fdc import stage_thresholds


def _daily(dates, flo_in=0.0, precip=0.0, evap=0.0, seep=0.0):
    n = len(dates)
    return pd.DataFrame({
        "date": dates,
        "flo_in": [flo_in] * n, "precip": [precip] * n,
        "evap": [evap] * n, "seep": [seep] * n,
    })


# ── monthly_capacity_pct ──────────────────────────────────────────────────────────

def test_capacity_pct_withdrawal_drawdown():
    # 만수 시작, 유입 0, 취수 0.01 m³/s=864 m³/day → 월별 저하
    dates = pd.date_range("2016-01-01", "2016-03-31", freq="D")
    df = _daily(dates, flo_in=0.0)
    out = monthly_capacity_pct(df, full_m3=100000.0, init_m3=100000.0,
                           withdrawal_m3s=0.01, dead_m3=0.0)
    # Jan 31d: 100000-864*31=73216 → 73.2%
    assert out[1] == pytest.approx(73.216, abs=0.01)
    assert out[2] < out[1] and out[3] < out[2]     # 단조 저하


def test_capacity_pct_surplus_exceeds_100():
    # 유입 과다 → 잉여(월류) → %>100 (Normal)
    dates = pd.date_range("2016-01-01", "2016-01-31", freq="D")
    df = _daily(dates, flo_in=10000.0)   # 31일×10000 = 310000 유입
    out = monthly_capacity_pct(df, full_m3=100000.0, init_m3=100000.0,
                           withdrawal_m3s=0.0, dead_m3=0.0)
    assert out[1] > 100.0


def test_capacity_pct_floor_at_dead():
    dates = pd.date_range("2016-01-01", "2016-01-31", freq="D")
    df = _daily(dates, flo_in=0.0)
    out = monthly_capacity_pct(df, full_m3=100000.0, init_m3=5000.0,
                           withdrawal_m3s=0.05, dead_m3=10000.0)  # 대량 취수
    # supply < dead → dead/full = 10%
    assert out[1] == pytest.approx(10.0, abs=1e-6)


def test_capacity_pct_losses():
    dates = pd.date_range("2016-01-01", "2016-01-31", freq="D")
    df = _daily(dates, flo_in=1000.0, precip=100.0, evap=300.0, seep=50.0)
    # 월합: (1000+100-300-50)*31 = 750*31 = 23250 ; init 50000 → 73250 → 73.25%
    out = monthly_capacity_pct(df, full_m3=100000.0, init_m3=50000.0)
    assert out[1] == pytest.approx(73.25, abs=0.01)


# ── capacity_fraction 분류 방향 (만수↑ Normal · 65↓ Crisis) ───────────────────────

def test_capacity_fraction_stage_direction():
    st = stage_thresholds([], "capacity_fraction", [100, 85, 65])
    q185, q275, q355 = st["normal_watch"], st["watch_warning"], st["warning_crisis"]
    # 멤버 % 값 → 단계
    vals = np.array([110, 90, 75, 50])   # Normal, Watch, Warning, Crisis
    sp = stage_probabilities4(vals, q185, q275, q355)
    assert sp["Normal"] == pytest.approx(25.0)
    assert sp["Watch"] == pytest.approx(25.0)
    assert sp["Warning"] == pytest.approx(25.0)
    assert sp["Crisis"] == pytest.approx(25.0)


# ── member_reservoir_capacity_pct (합성 reservoir_day.txt) ────────────────────────

def _write_res_day(path, gis_id=4, year=2016):
    dates = pd.date_range(f"{year}-01-01", f"{year}-03-31", freq="D")
    hdr = "jday mon day yr unit gis_id name area flo_in precip evap seep flo_stor flo_out\n"
    lines = ["t\n", hdr, "  ha m3 m3 m3 m3 m3 m3\n"]
    for d in dates:
        lines.append(f"{d.dayofyear} {d.month} {d.day} {d.year} 1 {gis_id} res4 "
                     f"1.0 0 0 0 0 90000 0\n")   # flo_in=0
    path.write_text("".join(lines))


def test_member_reservoir_capacity_pct(tmp_path):
    run = tmp_path; _write_res_day(run / "reservoir_day.txt")
    p = ReservoirForecastParams(gis_id=4, name="ngerimel", full_m3=100000.0,
                                dead_m3=0.0, init_m3=100000.0, withdrawal_m3s=0.01)
    out = member_reservoir_capacity_pct(run, p, fyear=2016, months=[1, 2, 3],
                                    sdate="2016-01-01")
    assert set(out) == {1, 2, 3}
    assert out[1] == pytest.approx(73.216, abs=0.01)   # 취수 저하


def test_member_reservoir_missing_file(tmp_path):
    p = ReservoirForecastParams(gis_id=4, name="x", full_m3=1e5, dead_m3=0,
                                init_m3=1e5)
    assert member_reservoir_capacity_pct(tmp_path, p, fyear=2016, months=[1],
                                     sdate="2016-01-01") is None


# ── monthly_capacity_series (저수위 ft + 월말 저류량) ─────────────────────────────

def test_capacity_series_water_level_via_curve():
    from swat_py.io.reservoir import StageStorageCurve
    # 선형 곡선: 0 m³ = 0 ft, 100000 m³ = 100 ft → 저류량/1000 = 수위(ft)
    curve = StageStorageCurve(elev_ft=np.array([0.0, 100.0]),
                              storage_m3=np.array([0.0, 100000.0]))
    dates = pd.date_range("2016-01-01", "2016-01-31", freq="D")
    df = _daily(dates, flo_in=0.0)
    ser = monthly_capacity_series(df, full_m3=100000.0, init_m3=100000.0,
                                  withdrawal_m3s=0.01, dead_m3=0.0, curve=curve)
    # Jan: supply=73216 → pct 73.216, 월말 저류량 73216 → 73.216 ft
    assert ser[1]["storage_pct"] == pytest.approx(73.216, abs=0.01)
    assert ser[1]["storage_m3"] == pytest.approx(73216.0, abs=1.0)
    assert ser[1]["water_level_ft"] == pytest.approx(73.216, abs=0.01)


def test_capacity_series_no_curve_nan_level():
    dates = pd.date_range("2016-01-01", "2016-01-31", freq="D")
    ser = monthly_capacity_series(_daily(dates), full_m3=1e5, init_m3=5e4)
    assert np.isnan(ser[1]["water_level_ft"])   # curve 없으면 수위 NaN
    # storage_pct 는 monthly_capacity_pct 와 동일해야(하위호환)
    assert ser[1]["storage_pct"] == pytest.approx(
        monthly_capacity_pct(_daily(dates), full_m3=1e5, init_m3=5e4)[1])


def test_member_reservoir_series_carries_curve():
    from swat_py.io.reservoir import StageStorageCurve
    run = Path(__import__("tempfile").mkdtemp())
    _write_res_day(run / "reservoir_day.txt")
    curve = StageStorageCurve(elev_ft=np.array([0.0, 100.0]),
                              storage_m3=np.array([0.0, 100000.0]))
    p = ReservoirForecastParams(gis_id=4, name="ngerimel", full_m3=100000.0,
                                dead_m3=0.0, init_m3=100000.0, withdrawal_m3s=0.01,
                                curve=curve)
    ser = member_reservoir_series(run, p, fyear=2016, months=[1, 2, 3],
                                  sdate="2016-01-01")
    assert set(ser) == {1, 2, 3}
    assert ser[1]["water_level_ft"] == pytest.approx(73.216, abs=0.01)


def test_member_monthly_weather():
    from swat_py.drought.ensemble_flow import _member_monthly_weather
    run = Path(__import__("tempfile").mkdtemp())
    csv = run / "918430.csv"
    dates = pd.date_range("2016-04-01", "2016-06-30", freq="D")
    pd.DataFrame({"year": dates.year, "mon": dates.month, "day": dates.day,
                  "prcp": 2.0, "tmax": 30.0, "tmin": 24.0}).to_csv(csv, index=False)
    w = _member_monthly_weather(csv, 2016, [4, 5, 6])
    assert set(w) == {4, 5, 6}
    assert w[4] == pytest.approx((60.0, 30.0, 24.0))   # 4월 30일×2mm=60, 기온 평균
    assert w[6][0] == pytest.approx(60.0)              # 6월 30일×2mm


# ── build_reservoir_forecast_params (source+registry+곡선) ────────────────────

def test_build_params_from_cfg():
    from swat_py.config.env import _DroughtSource, _Reservoir
    from swat_py.io.reservoir import StageStorageCurve
    curve = StageStorageCurve(elev_ft=np.array([23.34, 45.0, 51.0]),
                              storage_m3=np.array([0.0, 100000.0, 190000.0]))
    src = _DroughtSource(name="ngerimel", type="reservoir", reservoir="ngerimel",
                         outlets={4: "ngerimel"}, threshold_method="capacity_fraction",
                         threshold_values=[100, 85, 65], init_water_level_ft=45.0,
                         measured=False)
    rcfg = _Reservoir(name="ngerimel", gis_id=4, spillway_ft=45.0, bottom_ft=23.34,
                      withdrawal_m3s=0.0438)
    p = build_reservoir_forecast_params(src, rcfg, curve)
    assert p.gis_id == 4
    assert p.full_m3 == pytest.approx(100000.0)     # 여수로 45ft
    assert p.dead_m3 == pytest.approx(0.0)          # 바닥 23.34ft
    assert p.init_m3 == pytest.approx(100000.0)     # init 45ft=만수
    assert p.withdrawal_m3s == pytest.approx(0.0438)


def test_build_params_init_default_full():
    """init_water_level_ft 미지정(NaN) → 만수(full)로 시작."""
    from swat_py.config.env import _DroughtSource, _Reservoir
    from swat_py.io.reservoir import StageStorageCurve
    curve = StageStorageCurve(elev_ft=np.array([23.34, 45.0]),
                              storage_m3=np.array([0.0, 100000.0]))
    src = _DroughtSource(name="ngerimel", type="reservoir", outlets={4: "ngerimel"})
    rcfg = _Reservoir(name="ngerimel", gis_id=4, spillway_ft=45.0, bottom_ft=23.34)
    p = build_reservoir_forecast_params(src, rcfg, curve)
    assert p.init_m3 == pytest.approx(p.full_m3)    # 만수
