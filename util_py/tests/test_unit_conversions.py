"""extract.py의 _VAR_META 단위 변환 람다 검증."""
from __future__ import annotations

import numpy as np
import pytest

from util_py.extract import _VAR_META  # type: ignore[attr-defined]


def _conv(var_key: str, value):
    """_VAR_META[var_key]의 변환 함수를 적용한 결과 반환."""
    _, fn, _ = _VAR_META[var_key]
    return fn(value)


# ── 강수: tp(m, ERA5는 m/hour 누적) → mm, 음수 클립 ──────────────────────

def test_prcp_meter_to_mm() -> None:
    arr = np.array([0.000, 0.001, 0.005, 0.010])
    result = _conv("prcp", arr)
    np.testing.assert_allclose(result, [0.0, 1.0, 5.0, 10.0])


def test_prcp_negative_is_clipped_to_zero() -> None:
    """ERA5 tp는 양수만 의미가 있어 음수는 0으로 클립."""
    arr = np.array([-0.001, -1e-9, 0.0, 0.005])
    result = _conv("prcp", arr)
    np.testing.assert_allclose(result, [0.0, 0.0, 0.0, 5.0])


# ── 기온/이슬점: K → °C ─────────────────────────────────────────────────

@pytest.mark.parametrize("var", ["tavg", "tmax", "tmin", "tdew"])
def test_temperature_kelvin_to_celsius(var: str) -> None:
    arr = np.array([273.15, 283.15, 300.00, 250.00])
    result = _conv(var, arr)
    np.testing.assert_allclose(result, [0.0, 10.0, 26.85, -23.15])


# ── 단파복사: J/m² (1시간 누적) → W/m² ───────────────────────────────────

def test_rsds_j_per_m2_to_w_per_m2() -> None:
    """ssrd ÷ 3600 → W/m². 1 MJ/m² 누적이 1시간이면 ≈ 277.78 W/m²."""
    arr = np.array([0.0, 1_000_000.0, 3_600_000.0])
    result = _conv("rsds", arr)
    np.testing.assert_allclose(result, [0.0, 1_000_000.0 / 3600.0, 1000.0])


# ── 풍성분: 통과 (변환 없음) ─────────────────────────────────────────────

@pytest.mark.parametrize("var", ["u10m", "v10m"])
def test_wind_components_passthrough(var: str) -> None:
    arr = np.array([-5.5, 0.0, 3.2, 8.7])
    result = _conv(var, arr)
    np.testing.assert_array_equal(result, arr)


# ── 메타 무결성 ──────────────────────────────────────────────────────────

def test_var_meta_has_all_eight_variables() -> None:
    expected = {"prcp", "tavg", "tmax", "tmin", "tdew", "rsds", "u10m", "v10m"}
    assert set(_VAR_META.keys()) == expected


def test_var_meta_hourly_col_names_match_convention() -> None:
    """hourly 컬럼명이 {var}_{unit} 규칙을 따르는지."""
    expected = {
        "prcp": "prcp_mm",
        "tavg": "tavg_c", "tmax": "tmax_c", "tmin": "tmin_c", "tdew": "tdew_c",
        "rsds": "rsds_wm2",
        "u10m": "u10_ms", "v10m": "v10_ms",
    }
    for var, exp_col in expected.items():
        _, _, col = _VAR_META[var]
        assert col == exp_col, f"{var}: {col} != {exp_col}"
