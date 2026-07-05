"""swat_py.tank.pet — 3종 PET 산정 검증."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.tank.pet import METHODS, compute_pet


def _synthetic_year(lat=-21.2):
    dates = pd.date_range("2016-01-01", periods=366, freq="D")
    j = dates.dayofyear.to_numpy()
    tavg = 25.0 + 3.0 * np.cos(2 * np.pi * (j - 15) / 365.0)   # 남반구 계절
    return pd.DataFrame({
        "date": dates,
        "tmax_c": tavg + 4.0,
        "tmin_c": tavg - 4.0,
        "tavg_c": tavg,
        "slr_mjm2": 20.0 + 6.0 * np.cos(2 * np.pi * (j - 15) / 365.0),
    })


@pytest.mark.parametrize("method", METHODS)
def test_pet_positive_and_finite(method):
    df = _synthetic_year()
    pet = compute_pet(df, method, lat_deg=-21.2)
    assert len(pet) == len(df)
    assert np.all(np.isfinite(pet.to_numpy()))
    assert np.all(pet.to_numpy() >= 0)
    assert pet.mean() > 0


@pytest.mark.parametrize("method", METHODS)
def test_pet_plausible_magnitude(method):
    # 열대 유역 일 PET 연평균은 대략 1~10 mm/day 범위
    pet = compute_pet(_synthetic_year(), method, lat_deg=-21.2)
    assert 1.0 < pet.mean() < 10.0


@pytest.mark.parametrize("method", METHODS)
def test_pet_has_seasonality(method):
    pet = compute_pet(_synthetic_year(), method, lat_deg=-21.2)
    assert pet.std() > 0                       # 계절 변동 존재


def test_invalid_method_raises():
    with pytest.raises(ValueError, match="pet_method"):
        compute_pet(_synthetic_year(), "penman", lat_deg=-21.2)


def test_missing_columns_raises():
    df = _synthetic_year().drop(columns=["tmax_c", "tmin_c", "tavg_c"])
    with pytest.raises(ValueError, match="필요한 컬럼"):
        compute_pet(df, "hargreaves", lat_deg=-21.2)


def test_tavg_fallback_from_tmax_tmin():
    df = _synthetic_year().drop(columns=["tavg_c"])
    pet = compute_pet(df, "hamon", lat_deg=-21.2)   # tavg 없어도 tmax/tmin 로 대체
    assert np.all(np.isfinite(pet.to_numpy()))
