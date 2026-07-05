"""잠재증발산(PET) 산정 — Hamon · Hargreaves · Priestley-Taylor.

3단 Tank 모형의 증발 입력을 위해 일 PET(mm/day)를 계산한다. 가용 기상변수에 따라
방법을 선택한다(config `tank.pet_method`):

  - hargreaves        : tmax_c, tmin_c (+위도)         ★ 기본
  - hamon             : tavg_c (+위도, 일장)
  - priestley_taylor  : slr_mjm2, tavg_c

모든 함수는 표준 일자료 DataFrame(`io.load_std_daily` 산출: date·pcp_mm·tmax_c·
tmin_c·tavg_c·slr_mjm2 …)과 위도(deg)를 받아 date-indexed Series(mm/day)를 반환한다.
천문 복사·일장은 FAO-56 표준식으로 산정한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_GSC = 0.0820          # 태양상수 (MJ/m²/min)
_LAMBDA = 2.45         # 잠열 (MJ/kg) → 1 mm = 2.45 MJ/m²
_ALPHA_PT = 1.26       # Priestley-Taylor α
_GAMMA = 0.066         # 건습계 상수 (kPa/°C, 해면 근사)
_ALBEDO = 0.23         # 기준 작물 알베도

METHODS = ("hargreaves", "hamon", "priestley_taylor")


def _astro(jday: np.ndarray, lat_deg: float):
    """FAO-56 천문량 — (Ra[mm/day], 일장 N[hr]) 반환."""
    phi = np.deg2rad(lat_deg)
    j = jday.astype(float)
    dr = 1.0 + 0.033 * np.cos(2 * np.pi / 365.0 * j)          # 지구-태양 거리 보정
    dec = 0.409 * np.sin(2 * np.pi / 365.0 * j - 1.39)         # 태양 적위
    x = np.clip(-np.tan(phi) * np.tan(dec), -1.0, 1.0)
    ws = np.arccos(x)                                          # 일몰 시각각
    ra_mj = (24 * 60 / np.pi) * _GSC * dr * (
        ws * np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.sin(ws)
    )
    ra_mm = 0.408 * ra_mj                                      # MJ/m²/day → mm/day
    daylight = 24.0 / np.pi * ws                               # 일장 (hr)
    return np.maximum(ra_mm, 0.0), daylight


def _sat_vapor_pressure(tc: np.ndarray) -> np.ndarray:
    """포화수증기압 es(kPa) — Tetens 식."""
    return 0.6108 * np.exp(17.27 * tc / (tc + 237.3))


def hargreaves(df: pd.DataFrame, lat_deg: float) -> pd.Series:
    """Hargreaves-Samani: ET0 = 0.0023·Ra·(Tavg+17.8)·√(Tmax-Tmin)."""
    jday = df["date"].dt.dayofyear.to_numpy()
    ra_mm, _ = _astro(jday, lat_deg)
    tmax = df["tmax_c"].to_numpy(float)
    tmin = df["tmin_c"].to_numpy(float)
    tavg = df["tavg_c"].to_numpy(float) if "tavg_c" in df else (tmax + tmin) / 2.0
    dt = np.clip(tmax - tmin, 0.0, None)
    pet = 0.0023 * ra_mm * (tavg + 17.8) * np.sqrt(dt)
    return pd.Series(np.maximum(pet, 0.0), index=df["date"].values, name="pet_mm")


def hamon(df: pd.DataFrame, lat_deg: float) -> pd.Series:
    """Hamon: PET = 0.1651·(N/12)·RHOSAT, RHOSAT=216.7·es/(Tavg+273.3)."""
    jday = df["date"].dt.dayofyear.to_numpy()
    _, daylight = _astro(jday, lat_deg)
    tavg = df["tavg_c"].to_numpy(float) if "tavg_c" in df else (
        (df["tmax_c"].to_numpy(float) + df["tmin_c"].to_numpy(float)) / 2.0)
    es = _sat_vapor_pressure(tavg)                            # kPa
    rhosat = 216.7 * (es * 10.0) / (tavg + 273.3)             # kPa→hPa(mb)
    pet = 0.1651 * (daylight / 12.0) * rhosat
    return pd.Series(np.maximum(pet, 0.0), index=df["date"].values, name="pet_mm")


def priestley_taylor(df: pd.DataFrame, lat_deg: float) -> pd.Series:
    """Priestley-Taylor: PET = α·Δ/(Δ+γ)·Rn/λ (Rn≈(1-albedo)·Rs, 근사)."""
    tavg = df["tavg_c"].to_numpy(float) if "tavg_c" in df else (
        (df["tmax_c"].to_numpy(float) + df["tmin_c"].to_numpy(float)) / 2.0)
    rs = df["slr_mjm2"].to_numpy(float)                       # 입사 단파복사
    es = _sat_vapor_pressure(tavg)
    delta = 4098.0 * es / (tavg + 237.3) ** 2                 # Δ (kPa/°C)
    rn = (1.0 - _ALBEDO) * rs                                 # 순복사 근사(장파 무시)
    pet = _ALPHA_PT * (delta / (delta + _GAMMA)) * rn / _LAMBDA
    return pd.Series(np.maximum(pet, 0.0), index=df["date"].values, name="pet_mm")


_DISPATCH = {
    "hargreaves": hargreaves,
    "hamon": hamon,
    "priestley_taylor": priestley_taylor,
}


def compute_pet(df: pd.DataFrame, method: str, lat_deg: float) -> pd.Series:
    """방법명으로 PET Series(mm/day) 산정.

    Parameters
    ----------
    df      : 표준 일자료 DataFrame (date + 기상변수). io.load_std_daily 산출.
    method  : 'hargreaves' | 'hamon' | 'priestley_taylor'
    lat_deg : 위도 (deg, 남반구 음수)
    """
    m = str(method).lower().strip()
    if m not in _DISPATCH:
        raise ValueError(f"미지원 pet_method '{method}'. 가능: {METHODS}")
    # 필요한 컬럼 확인 (친절한 오류)
    need = {"hargreaves": ["tmax_c", "tmin_c"],
            "hamon": ["tavg_c"],
            "priestley_taylor": ["slr_mjm2", "tavg_c"]}[m]
    miss = [c for c in need if c not in df.columns and
            not (c == "tavg_c" and {"tmax_c", "tmin_c"} <= set(df.columns))]
    if miss:
        raise ValueError(f"pet_method '{m}' 에 필요한 컬럼 없음: {miss}")
    return _DISPATCH[m](df, lat_deg)
