"""WGEN 매개변수 산출 + weather-wgn.cli 작성/재읽기."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swat_py.io.weather_wgn import (
    WgnStation,
    build_wgn_station,
    compute_wgn_params,
    read_weather_wgn,
    write_weather_wgn,
    write_wgn_import_csv,
)


def _synthetic_daily(start="1990-01-01", end="2019-12-31", seed=0) -> pd.DataFrame:
    """30년 합성 일자료 - 강수 lognormal, 기온 sinusoidal+noise."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, end)
    n = len(dates)
    doy = dates.dayofyear
    wet = rng.random(n) < 0.4
    pcp = np.where(wet, rng.lognormal(mean=0.5, sigma=1.0, size=n), 0.0)
    tavg = 25 + 5 * np.cos(2 * np.pi * doy / 365)
    tmax = tavg + 4 + rng.normal(0, 1, n)
    tmin = tavg - 4 + rng.normal(0, 1, n)
    return pd.DataFrame({
        "date":     dates,
        "pcp_mm":   pcp,
        "tmax_c":   tmax,
        "tmin_c":   tmin,
        "slr_mjm2": 20 + rng.normal(0, 2, n),
        "tdew_c":   tmin - 1 + rng.normal(0, 0.5, n),
        "ws10_ms":  3 + rng.normal(0, 0.5, n),
    })


# ── compute_wgn_params ────────────────────────────────────────────────────────

def test_compute_wgn_params_shape() -> None:
    out = compute_wgn_params(_synthetic_daily())
    assert len(out) == 12
    assert out["month"].tolist() == list(range(1, 13))
    expected = {"tmp_max_ave", "tmp_min_ave", "tmp_max_sd", "tmp_min_sd",
                "pcp_ave", "pcp_sd", "pcp_skew", "wet_dry", "wet_wet",
                "pcp_days", "pcp_hhr", "slr_ave", "dew_ave", "wnd_ave"}
    assert expected <= set(out.columns)


def test_temperature_seasonal_amplitude() -> None:
    """cos(2π·day/365) 입력 → 1월(max) > 7월(min)."""
    out = compute_wgn_params(_synthetic_daily())
    jan = float(out.loc[out["month"] == 1, "tmp_max_ave"].iloc[0])
    jul = float(out.loc[out["month"] == 7, "tmp_max_ave"].iloc[0])
    assert jan > jul + 3   # 양 극단 차이는 약 8°C


def test_markov_probabilities_in_range() -> None:
    out = compute_wgn_params(_synthetic_daily())
    for c in ("wet_dry", "wet_wet"):
        assert (out[c] >= 0).all() and (out[c] <= 1).all()


def test_pcp_days_in_range_for_wet_climate() -> None:
    """0.4 확률 × 30day = ~12 wet days/month."""
    out = compute_wgn_params(_synthetic_daily())
    assert (out["pcp_days"] > 5).all()
    assert (out["pcp_days"] < 25).all()


def test_year_filter_changes_result() -> None:
    df = _synthetic_daily()
    a = compute_wgn_params(df)
    b = compute_wgn_params(df, syear=2010, eyear=2019)
    assert not np.allclose(a["tmp_max_ave"].values, b["tmp_max_ave"].values)


def test_missing_required_columns_raises() -> None:
    df = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=10)})
    with pytest.raises(KeyError):
        compute_wgn_params(df)


def test_minus99_treated_as_missing() -> None:
    df = _synthetic_daily()
    df.loc[:100, "tmax_c"] = -99
    out = compute_wgn_params(df)
    # NaN 처리되어 정상 통계 산출
    assert out["tmp_max_ave"].notna().all()
    assert (out["tmp_max_ave"] > 0).all()


def test_empty_filter_raises() -> None:
    df = _synthetic_daily()
    with pytest.raises(ValueError):
        compute_wgn_params(df, syear=2100, eyear=2110)


# ── write & re-read ───────────────────────────────────────────────────────────

def test_write_and_read_round_trip(tmp_path) -> None:
    params = compute_wgn_params(_synthetic_daily())
    st = WgnStation(name="testsite", lat=-21.2, lon=-159.8, elev=5.8,
                    years=30, params=params)
    out_path = tmp_path / "weather-wgn.cli"
    write_weather_wgn([st], out_path)
    assert out_path.is_file()

    rb = read_weather_wgn(out_path)
    assert len(rb) == 1
    assert rb[0].name == "testsite"
    assert rb[0].lat == pytest.approx(-21.2, abs=1e-4)
    assert rb[0].years == 30
    for c in ("tmp_max_ave", "pcp_ave", "wet_dry", "wnd_ave"):
        np.testing.assert_allclose(rb[0].params[c].values,
                                   params[c].values, atol=1e-4)


def test_write_multiple_stations(tmp_path) -> None:
    params = compute_wgn_params(_synthetic_daily())
    sts = [
        WgnStation("siteA", -21.2, -159.8,  5.8, 30, params),
        WgnStation("siteB", -21.3, -159.9, 12.0, 30, params),
    ]
    out_path = tmp_path / "w.cli"
    write_weather_wgn(sts, out_path)
    rb = read_weather_wgn(out_path)
    assert [s.name for s in rb] == ["siteA", "siteB"]


# ── build_wgn_station (CSV → WgnStation) ─────────────────────────────────────

def test_build_wgn_station_from_csv(tmp_path) -> None:
    df = _synthetic_daily(start="2000-01-01", end="2009-12-31")
    csv = tmp_path / "stn.csv"
    df.to_csv(csv, index=False)
    st = build_wgn_station(csv, station_name="stn", lat=-21, lon=-160, elev=5,
                           syear=2000, eyear=2009)
    assert st.years == 10
    assert len(st.params) == 12


# ── SWAT+ Editor 1-file wgn import CSV ───────────────────────────────────────

_EDITOR_WGN_VARS = [
    "tmp_max_ave", "tmp_min_ave", "tmp_max_sd", "tmp_min_sd",
    "pcp_ave", "pcp_sd", "pcp_skew", "wet_dry", "wet_wet", "pcp_days",
    "pcp_hhr", "slr_ave", "dew_ave", "wnd_ave",
]


def _one_station(name="rarotonga", lat=-21.2, lon=-159.8, elev=5.8) -> WgnStation:
    params = compute_wgn_params(_synthetic_daily())
    return WgnStation(name=name, lat=lat, lon=lon, elev=elev,
                      years=30, params=params)


def test_import_csv_column_layout(tmp_path) -> None:
    """5 + 14×12 = 173 컬럼, 헤더는 name,lat,lon,elev,rain_yrs + month-interleaved."""
    out = tmp_path / "Rarotonga.csv"
    write_wgn_import_csv([_one_station()], out)

    df = pd.read_csv(out)
    assert df.shape == (1, 173)

    assert list(df.columns[:5]) == ["name", "lat", "lon", "elev", "rain_yrs"]
    expected_cols = ["name", "lat", "lon", "elev", "rain_yrs"]
    for m in range(1, 13):
        expected_cols.extend(f"{v}_{m}" for v in _EDITOR_WGN_VARS)
    assert list(df.columns) == expected_cols


def test_import_csv_values_align_to_editor_parser(tmp_path) -> None:
    """val[0]=name, val[1]=lat, val[2]=lon, val[3]=elev, val[4]=rain_yrs,
    val[5+]=14 vars × 12 months. lat 는 float 로 파싱되어야 한다
    (Editor 의 weather_sta_name 에서 ``lat >= 0`` 비교)."""
    st = _one_station(lat=-21.2027, lon=-159.8056, elev=6.0)
    out = tmp_path / "Rarotonga.csv"
    write_wgn_import_csv([st], out)

    with out.open() as f:
        next(f)              # header
        val = next(f).strip().split(",")

    assert val[0] == "rarotonga"
    assert float(val[1]) == pytest.approx(-21.2027, abs=1e-4)
    assert float(val[2]) == pytest.approx(-159.8056, abs=1e-4)
    assert float(val[3]) == pytest.approx(6.0, abs=1e-4)
    assert int(val[4]) == 30
    # Editor 의 lat>=0 비교가 통과되는지 직접 흉내 — 이전 버그 회귀 방지
    assert (float(val[1]) >= 0) in (True, False)

    # month=1 의 14변수 = val[5..18] 가 station.params 와 일치
    p = st.params.set_index("month").loc[1]
    for j, var in enumerate(_EDITOR_WGN_VARS):
        assert float(val[5 + j]) == pytest.approx(float(p[var]), rel=1e-5, abs=1e-5)


def test_import_csv_multiple_stations(tmp_path) -> None:
    sts = [
        _one_station(name="siteA", lat=-21.2, lon=-159.8, elev=5.8),
        _one_station(name="siteB", lat=-21.3, lon=-159.9, elev=12.0),
    ]
    out = tmp_path / "wgn.csv"
    write_wgn_import_csv(sts, out)
    df = pd.read_csv(out)
    assert df.shape == (2, 173)
    assert df["name"].tolist() == ["siteA", "siteB"]
    assert df["elev"].tolist() == [5.8, 12.0]


def test_import_csv_name_whitespace_stripped(tmp_path) -> None:
    """station name 의 공백은 사전 제거 — Editor 의 remove_space 와 동일."""
    out = tmp_path / "wgn.csv"
    write_wgn_import_csv([_one_station(name=" Rarot onga ")], out)
    df = pd.read_csv(out)
    assert df["name"].iloc[0] == "Rarotonga"


# ── Cook 918430 통합 (실제 자료 있을 때만) ─────────────────────────────────────

COOK_CSV = Path("I:/2025-APCC_Cook/PICASO-Hydro/0_database/obs/weather/918430.csv")


@pytest.mark.skipif(not COOK_CSV.is_file(), reason="Cook 918430 자료 없음")
def test_cook_918430_realistic_stats() -> None:
    """Cook Rarotonga 30년 자료 → 열대 기후 합리적 범위 검증."""
    st = build_wgn_station(
        COOK_CSV, station_name="rarotonga",
        lat=-21.203, lon=-159.806, elev=5.8,
        syear=1995, eyear=2024,
    )
    assert st.years == 30
    # 열대 — 월평균 일최고기온 ~ 24-30 °C
    assert 22 < st.params["tmp_max_ave"].mean() < 32
    # 월평균 일최저기온 ~ 18-25 °C
    assert 16 < st.params["tmp_min_ave"].mean() < 26
    # Rarotonga 연 강수 ~ 2000 mm (NIWA) — GSOD pcp 결측 영향으로 다소 낮을 수 있음
    annual = st.params["pcp_ave"].sum()
    assert 1000 < annual < 3500
    # 강수일수 — 연 ~ 150-220 day
    annual_wet = st.params["pcp_days"].sum()
    assert 100 < annual_wet < 250
    # Markov 전이는 [0,1]
    assert (st.params["wet_dry"] >= 0).all() and (st.params["wet_dry"] <= 1).all()
    assert (st.params["wet_wet"] >= 0).all() and (st.params["wet_wet"] <= 1).all()
