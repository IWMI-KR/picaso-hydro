"""weather_std — 단위 변환, Magnus RH, FAO-56 wind, ERA5/GSOD/local 변환 검증."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from util_py.weather_std import (
    STD_DAILY_COLUMNS,
    STD_HOURLY_COLUMNS,
    fahrenheit_to_celsius,
    inches_to_mm,
    knots_to_ms,
    magnus_rh,
    saturation_vapor_pressure,
    standardize_era5_daily,
    standardize_era5_hourly,
    standardize_gsod_daily,
    standardize_local,
    wind_to_2m_fao56,
)


# ── 단위 변환 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("f, c", [
    (32.0, 0.0), (212.0, 100.0), (-40.0, -40.0), (98.6, 37.0),
])
def test_fahrenheit_to_celsius(f, c) -> None:
    assert float(fahrenheit_to_celsius(pd.Series([f])).iloc[0]) == pytest.approx(c, abs=0.01)


def test_fahrenheit_missing_to_nan() -> None:
    s = fahrenheit_to_celsius(pd.Series([9999.9, 32.0]))
    assert pd.isna(s.iloc[0])
    assert s.iloc[1] == pytest.approx(0.0, abs=0.01)


def test_inches_to_mm() -> None:
    s = inches_to_mm(pd.Series([1.0, 2.5, 99.99, 0.0]))
    assert s.iloc[0] == pytest.approx(25.4)
    assert s.iloc[1] == pytest.approx(63.5)
    assert pd.isna(s.iloc[2])
    assert s.iloc[3] == pytest.approx(0.0)


def test_knots_to_ms() -> None:
    s = knots_to_ms(pd.Series([1.0, 10.0, 999.9]))
    assert s.iloc[0] == pytest.approx(0.5144)
    assert s.iloc[1] == pytest.approx(5.144)
    assert pd.isna(s.iloc[2])


# ── Magnus RH ────────────────────────────────────────────────────────────────

def test_saturation_vapor_pressure_known_values() -> None:
    """Magnus 식 검증값 (참조: FAO-56 표 2.1)."""
    es = saturation_vapor_pressure(pd.Series([0.0, 10.0, 25.0, 35.0]))
    # 0 °C ≈ 6.108, 10 °C ≈ 12.27, 25 °C ≈ 31.67, 35 °C ≈ 56.18 (hPa)
    assert es.iloc[0] == pytest.approx(6.108, abs=0.05)
    assert es.iloc[1] == pytest.approx(12.27, abs=0.1)
    assert es.iloc[2] == pytest.approx(31.67, abs=0.5)
    assert es.iloc[3] == pytest.approx(56.18, abs=1.0)


def test_magnus_rh_when_tavg_equals_tdew_is_100() -> None:
    """이슬점 = 기온 → 포화 (100%)."""
    rh = magnus_rh(pd.Series([20.0, 0.0, -5.0]),
                   pd.Series([20.0, 0.0, -5.0]))
    for v in rh:
        assert v == pytest.approx(100.0)


def test_magnus_rh_typical_range() -> None:
    """T=25 °C, Td=15 °C → ≈ 53 %"""
    rh = magnus_rh(pd.Series([25.0]), pd.Series([15.0]))
    assert rh.iloc[0] == pytest.approx(53.4, abs=1.0)


def test_magnus_rh_clipped_to_100() -> None:
    """이슬점 > 기온 (이상값) → 100 % 클립."""
    rh = magnus_rh(pd.Series([10.0]), pd.Series([15.0]))
    assert rh.iloc[0] == 100.0


# ── FAO-56 풍속 2m ───────────────────────────────────────────────────────────

def test_wind_to_2m_factor_at_10m() -> None:
    """z=10m 환산 인자 ≈ 0.748."""
    factor = 4.87 / math.log(67.8 * 10 - 5.42)
    assert factor == pytest.approx(0.748, abs=0.001)


def test_wind_to_2m_known_values() -> None:
    u10 = pd.Series([5.0, 10.0, 0.0])
    u2 = wind_to_2m_fao56(u10, z=10.0)
    assert u2.iloc[0] == pytest.approx(5.0 * 0.748, abs=0.01)
    assert u2.iloc[1] == pytest.approx(10.0 * 0.748, abs=0.01)
    assert u2.iloc[2] == pytest.approx(0.0)


def test_wind_to_2m_at_2m_no_change() -> None:
    """z=2m 이면 환산 인자 ≈ 1.0."""
    u2_in = pd.Series([3.0])
    u2_out = wind_to_2m_fao56(u2_in, z=2.0)
    # factor = 4.87 / ln(67.8*2 - 5.42) = 4.87 / ln(130.18) = 4.87 / 4.869 ≈ 1.0
    assert u2_out.iloc[0] == pytest.approx(3.0, abs=0.01)


def test_wind_to_2m_invalid_height_raises() -> None:
    with pytest.raises(ValueError):
        wind_to_2m_fao56(pd.Series([5.0]), z=0)


# ── ERA5 일자료 변환 ─────────────────────────────────────────────────────────

def _make_era5_daily_csv(path: Path) -> Path:
    pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02"],
        "prcp_mm": [10.5, 0.0],
        "tavg_c": [25.0, 24.5],
        "tmax_c": [29.0, 28.5],
        "tmin_c": [21.0, 20.5],
        "tdew_c": [20.0, 19.5],
        "rsds_mjm2": [22.5, 20.1],
        "ws10_ms": [4.0, 3.5],
    }).to_csv(path, index=False)
    return path


def test_standardize_era5_daily(tmp_path) -> None:
    raw = _make_era5_daily_csv(tmp_path / "ERA001.csv")
    out = tmp_path / "out" / "ERA001.csv"
    standardize_era5_daily(raw, out)

    df = pd.read_csv(out)
    assert list(df.columns) == STD_DAILY_COLUMNS
    assert df["pcp_mm"].iloc[0]   == pytest.approx(10.5)
    assert df["tmax_c"].iloc[0]   == pytest.approx(29.0)
    assert df["slr_mjm2"].iloc[0] == pytest.approx(22.5)
    # FAO-56 ws2 = 4.0 × 0.748
    assert df["ws2_ms"].iloc[0] == pytest.approx(4.0 * 0.748, abs=0.01)
    # Magnus rh: T=25, Td=20 → ≈ 73.8%
    assert df["hmd_pct"].iloc[0] == pytest.approx(73.8, abs=1.0)
    assert df["source"].iloc[0]  == "ERA5"


# ── GSOD 일자료 변환 ─────────────────────────────────────────────────────────

def _make_gsod_csv(path: Path) -> Path:
    pd.DataFrame({
        "STATION": ["91843099999"] * 2,
        "DATE": ["2024-01-01", "2024-01-02"],
        "TEMP": [80.0, 9999.9],   # 80 °F → 26.67 °C, missing
        "DEWP": [70.0, 65.0],     # 70 °F → 21.11 °C
        "MAX":  [85.0, 84.0],
        "MIN":  [75.0, 9999.9],
        "WDSP": [10.0, 999.9],    # 10 knots → 5.144 m/s, missing
        "PRCP": [0.10, 99.99],    # 0.1 inch → 2.54 mm, missing
    }).to_csv(path, index=False)
    return path


def test_standardize_gsod_daily(tmp_path) -> None:
    raw = _make_gsod_csv(tmp_path / "usgs.csv")
    out = tmp_path / "out" / "usgs.csv"
    standardize_gsod_daily(raw, out)

    df = pd.read_csv(out)
    assert list(df.columns) == STD_DAILY_COLUMNS
    assert df["tavg_c"].iloc[0]  == pytest.approx(26.67, abs=0.05)
    assert pd.isna(df["tavg_c"].iloc[1])  # 9999.9 → NaN
    assert df["tmax_c"].iloc[0]  == pytest.approx(29.44, abs=0.05)
    assert df["pcp_mm"].iloc[0]  == pytest.approx(2.54, abs=0.05)
    assert pd.isna(df["pcp_mm"].iloc[1])  # 99.99 → NaN
    assert df["ws10_ms"].iloc[0] == pytest.approx(5.144, abs=0.01)
    assert pd.isna(df["ws10_ms"].iloc[1])  # 999.9 → NaN
    assert df["ws2_ms"].iloc[0]  == pytest.approx(5.144 * 0.748, abs=0.01)
    assert pd.isna(df["slr_mjm2"]).all()   # GSOD 무
    assert df["source"].iloc[0]  == "GSOD"


# ── local 변환 (mapping) ─────────────────────────────────────────────────────

def test_standardize_local_with_unit_conversion(tmp_path) -> None:
    """mm/inch + C/F + ms/knots/kmh 변환 동작."""
    raw = tmp_path / "raw.csv"
    pd.DataFrame({
        "관측일자": ["2024-01-01", "2024-01-02"],
        "강수량_in": [0.10, 0.20],            # inch
        "최고기온_F": [85.0, 86.0],            # F
        "최저기온_F": [70.0, 72.0],
        "평균기온_F": [78.0, 79.0],
        "이슬점_F":   [65.0, 67.0],
        "풍속_kmh":   [18.0, 14.4],            # km/h → m/s = 5.0, 4.0
    }).to_csv(raw, index=False)

    mapping = {
        "columns": {
            "date": "관측일자",
            "pcp_mm": "강수량_in",
            "tmax_c": "최고기온_F",
            "tmin_c": "최저기온_F",
            "tavg_c": "평균기온_F",
            "tdew_c": "이슬점_F",
            "ws10_ms": "풍속_kmh",
        },
        "units": {"pcp": "inch", "temp": "F", "wind": "kmh"},
        "wind_height_m": 10.0,
    }
    out = tmp_path / "std.csv"
    standardize_local(raw, mapping, out, resolution="daily")

    df = pd.read_csv(out)
    assert list(df.columns) == STD_DAILY_COLUMNS
    assert df["pcp_mm"].iloc[0]  == pytest.approx(2.54, abs=0.01)    # 0.1 inch
    assert df["tmax_c"].iloc[0]  == pytest.approx(29.44, abs=0.05)   # 85 °F
    assert df["ws10_ms"].iloc[0] == pytest.approx(5.0, abs=0.01)     # 18 km/h
    assert df["ws2_ms"].iloc[0]  == pytest.approx(5.0 * 0.748, abs=0.01)
    assert df["source"].iloc[0]  == "USER"


def test_standardize_local_hourly(tmp_path) -> None:
    raw = tmp_path / "raw.csv"
    pd.DataFrame({
        "datetime": ["2024-01-01 00:00", "2024-01-01 01:00"],
        "rain_mm": [0.0, 1.5],
        "T_C": [20.0, 19.5],
        "Td_C": [15.0, 14.5],
        "wind_ms": [3.0, 2.5],
        "rad_wm2": [200.0, 250.0],
    }).to_csv(raw, index=False)

    mapping = {
        "columns": {
            "datetime": "datetime",
            "pcp_mm": "rain_mm",
            "tavg_c": "T_C",
            "tdew_c": "Td_C",
            "ws10_ms": "wind_ms",
            "slr_wm2": "rad_wm2",
        },
        "units": {"pcp": "mm", "temp": "C", "wind": "ms"},
        "wind_height_m": 10.0,
    }
    out = tmp_path / "std.csv"
    standardize_local(raw, mapping, out, resolution="hourly")

    df = pd.read_csv(out)
    assert list(df.columns) == STD_HOURLY_COLUMNS
    assert df["pcp_mm"].iloc[1]  == pytest.approx(1.5)
    assert df["slr_wm2"].iloc[0] == pytest.approx(200.0)
    assert df["hmd_pct"].iloc[0] == pytest.approx(magnus_rh(pd.Series([20.0]),
                                                             pd.Series([15.0])).iloc[0],
                                                   abs=0.5)
