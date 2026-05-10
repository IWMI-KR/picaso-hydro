"""SWAT 표준 기상자료 포맷 변환 (ERA5 / GSOD / local_user).

표준 컬럼 (Daily — SWAT 주 입력)
--------------------------------
date, pcp_mm, tmax_c, tmin_c, tavg_c, tdew_c, hmd_pct, slr_mjm2,
ws10_ms, ws2_ms, source

표준 컬럼 (Hourly — ERA5/local 시간단위)
----------------------------------------
datetime, pcp_mm, tavg_c, tdew_c, hmd_pct, slr_wm2,
ws10_ms, ws2_ms, source

상대습도 — Magnus 식 (FAO-56 Allen et al. 1998 부합)
----------------------------------------------------
e_s(T) = 6.1078 × exp(17.27·T / (T + 237.3))    [hPa]
hmd    = 100 × e_s(tdew) / e_s(tavg)             [%]

풍속 2 m 환산 — FAO-56 로그 풍속 프로파일
------------------------------------------
u_2 = u_z × 4.87 / ln(67.8·z − 5.42)
z=10 m → factor ≈ 0.748
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Union

import numpy as np
import pandas as pd

# ── 표준 컬럼 ────────────────────────────────────────────────────────────────

STD_DAILY_COLUMNS = [
    "date", "pcp_mm", "tmax_c", "tmin_c", "tavg_c", "tdew_c",
    "hmd_pct", "slr_mjm2", "ws10_ms", "ws2_ms", "source",
]

STD_HOURLY_COLUMNS = [
    "datetime", "pcp_mm", "tavg_c", "tdew_c", "hmd_pct",
    "slr_wm2", "ws10_ms", "ws2_ms", "source",
]


# ── 단위 변환 (NaN 처리 통합) ───────────────────────────────────────────────

def _drop_missing(s: pd.Series, missing: Optional[float]) -> pd.Series:
    if missing is None:
        return s
    return s.where(np.abs(s - missing) > 0.001, np.nan)


def fahrenheit_to_celsius(f, missing: Optional[float] = 9999.9) -> pd.Series:
    """°F → °C. ``missing`` sentinel 은 NaN 으로 변환."""
    s = pd.Series(f, dtype="float64")
    s = _drop_missing(s, missing)
    return (s - 32.0) * 5.0 / 9.0


def inches_to_mm(inches, missing: Optional[float] = 99.99) -> pd.Series:
    """inch → mm (1 inch = 25.4 mm)."""
    s = pd.Series(inches, dtype="float64")
    s = _drop_missing(s, missing)
    return s * 25.4


def knots_to_ms(knots, missing: Optional[float] = 999.9) -> pd.Series:
    """knots → m/s (1 knot = 0.5144 m/s)."""
    s = pd.Series(knots, dtype="float64")
    s = _drop_missing(s, missing)
    return s * 0.5144


def kmh_to_ms(kmh) -> pd.Series:
    """km/h → m/s."""
    return pd.Series(kmh, dtype="float64") / 3.6


def mph_to_ms(mph) -> pd.Series:
    """mph → m/s."""
    return pd.Series(mph, dtype="float64") * 0.44704


# ── 상대습도 (Magnus 식) ─────────────────────────────────────────────────────

def saturation_vapor_pressure(t_c) -> pd.Series:
    """Magnus 식 포화수증기압 e_s(T) [hPa]."""
    t = pd.Series(t_c, dtype="float64")
    return 6.1078 * np.exp(17.27 * t / (t + 237.3))


def magnus_rh(tavg_c, tdew_c) -> pd.Series:
    """기온·이슬점 → 상대습도 % (0–100). Magnus / FAO-56."""
    e_s = saturation_vapor_pressure(tavg_c)
    e_a = saturation_vapor_pressure(tdew_c)
    rh = 100.0 * e_a / e_s
    return rh.clip(lower=0.0, upper=100.0)


# ── 풍속 2 m 환산 (FAO-56) ──────────────────────────────────────────────────

def wind_to_2m_fao56(u_z, z: float = 10.0) -> pd.Series:
    """``u_z`` (m/s, 측정 고도 z) → 2 m 환산 풍속 (FAO-56)."""
    if z <= 0:
        raise ValueError(f"측정 고도는 양수여야 함: {z}")
    factor = 4.87 / np.log(67.8 * z - 5.42)
    return pd.Series(u_z, dtype="float64") * factor


# ── ERA5 변환 ────────────────────────────────────────────────────────────────

# extract.py 출력 컬럼:
#   daily : date, prcp_mm, tavg_c, tmax_c, tmin_c, tdew_c, rsds_mjm2, ws10_ms
#   hourly: datetime, prcp_mm, tavg_c, tmax_c, tmin_c, tdew_c, rsds_wm2,
#           u10_ms, v10_ms, ws10_ms

def standardize_era5_daily(
    raw_csv: Union[str, Path],
    output_csv: Union[str, Path],
    *,
    wind_height_m: float = 10.0,
) -> Path:
    """ERA5 grid_daily CSV → 표준 일자료."""
    raw_csv = Path(raw_csv)
    output_csv = Path(output_csv)
    df = pd.read_csv(raw_csv, parse_dates=["date"])

    out = pd.DataFrame()
    out["date"]     = df["date"].dt.strftime("%Y-%m-%d")
    out["pcp_mm"]   = df["prcp_mm"]
    out["tmax_c"]   = df["tmax_c"]
    out["tmin_c"]   = df["tmin_c"]
    out["tavg_c"]   = df["tavg_c"]
    out["tdew_c"]   = df["tdew_c"]
    out["hmd_pct"]  = magnus_rh(df["tavg_c"], df["tdew_c"]).round(2)
    out["slr_mjm2"] = df["rsds_mjm2"]
    out["ws10_ms"]  = df["ws10_ms"]
    out["ws2_ms"]   = wind_to_2m_fao56(df["ws10_ms"], z=wind_height_m).round(3)
    out["source"]   = "ERA5"

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    out[STD_DAILY_COLUMNS].to_csv(output_csv, index=False)
    return output_csv


def standardize_era5_hourly(
    raw_csv: Union[str, Path],
    output_csv: Union[str, Path],
    *,
    wind_height_m: float = 10.0,
) -> Path:
    """ERA5 grid_hourly CSV → 표준 시간자료."""
    raw_csv = Path(raw_csv)
    output_csv = Path(output_csv)
    df = pd.read_csv(raw_csv, parse_dates=["datetime"])

    out = pd.DataFrame()
    out["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d %H:%M")
    out["pcp_mm"]   = df["prcp_mm"]
    out["tavg_c"]   = df["tavg_c"]
    out["tdew_c"]   = df["tdew_c"]
    out["hmd_pct"]  = magnus_rh(df["tavg_c"], df["tdew_c"]).round(2)
    out["slr_wm2"]  = df["rsds_wm2"]
    out["ws10_ms"]  = df["ws10_ms"]
    out["ws2_ms"]   = wind_to_2m_fao56(df["ws10_ms"], z=wind_height_m).round(3)
    out["source"]   = "ERA5"

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    out[STD_HOURLY_COLUMNS].to_csv(output_csv, index=False)
    return output_csv


# ── GSOD 변환 ────────────────────────────────────────────────────────────────

# GSOD 컬럼 (daily, °F · inch · knots)
#   STATION, DATE, LATITUDE, LONGITUDE, ELEVATION, NAME,
#   TEMP, DEWP, SLP, STP, VISIB, WDSP, MXSPD, GUST, MAX, MIN,
#   PRCP, SNDP, FRSHTT, ...
# Missing sentinels:
#   TEMP/DEWP/MAX/MIN/SLP/STP/VISIB : 9999.9
#   WDSP/MXSPD/GUST                 : 999.9
#   PRCP                            : 99.99

def standardize_gsod_daily(
    raw_csv: Union[str, Path],
    output_csv: Union[str, Path],
    *,
    wind_height_m: float = 10.0,
) -> Path:
    """GSOD 관측소 CSV → 표준 일자료."""
    raw_csv = Path(raw_csv)
    output_csv = Path(output_csv)
    df = pd.read_csv(raw_csv, parse_dates=["DATE"])

    tavg = fahrenheit_to_celsius(df["TEMP"])
    tmax = fahrenheit_to_celsius(df["MAX"])
    tmin = fahrenheit_to_celsius(df["MIN"])
    tdew = fahrenheit_to_celsius(df["DEWP"])
    ws10 = knots_to_ms(df["WDSP"])

    out = pd.DataFrame()
    out["date"]     = df["DATE"].dt.strftime("%Y-%m-%d")
    out["pcp_mm"]   = inches_to_mm(df["PRCP"]).round(2)
    out["tmax_c"]   = tmax.round(2)
    out["tmin_c"]   = tmin.round(2)
    out["tavg_c"]   = tavg.round(2)
    out["tdew_c"]   = tdew.round(2)
    out["hmd_pct"]  = magnus_rh(tavg, tdew).round(2)
    out["slr_mjm2"] = np.nan          # GSOD 에는 일사량 없음
    out["ws10_ms"]  = ws10.round(3)
    out["ws2_ms"]   = wind_to_2m_fao56(ws10, z=wind_height_m).round(3)
    out["source"]   = "GSOD"

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    out[STD_DAILY_COLUMNS].to_csv(output_csv, index=False)
    return output_csv


# ── local_user 변환 ──────────────────────────────────────────────────────────

# 매핑 YAML 예시:
#   resolution:      daily
#   columns:                          # raw column → standard column
#     date:    "관측일자"
#     pcp_mm:  "강수량"
#     tmax_c:  "최고기온"
#     tmin_c:  "최저기온"
#     tavg_c:  "평균기온"
#     tdew_c:  "이슬점"
#     hmd_pct: "상대습도"             # 직접 제공되면 magnus 생략
#     ws10_ms: "풍속"
#     slr_mjm2:"일사량"
#   units:
#     pcp:   "mm"                     # mm | inch
#     temp:  "C"                      # C  | F
#     wind:  "ms"                     # ms | kmh | knots | mph
#   wind_height_m:   10.0
#   date_format:     "%Y-%m-%d"
#   missing_value:   -999             # raw 결측 sentinel

def standardize_local(
    raw_csv: Union[str, Path],
    mapping: Dict,
    output_csv: Union[str, Path],
    *,
    resolution: str = "daily",
) -> Path:
    """사용자 정의 매핑 기반 변환."""
    raw_csv = Path(raw_csv)
    output_csv = Path(output_csv)
    df = pd.read_csv(raw_csv)

    cols  = mapping.get("columns") or {}
    units = mapping.get("units") or {}
    wind_h = float(mapping.get("wind_height_m", 10.0))
    date_fmt = mapping.get("date_format")
    missing = mapping.get("missing_value")

    out = pd.DataFrame()

    # date / datetime
    if resolution == "daily" and "date" in cols:
        out["date"] = pd.to_datetime(df[cols["date"]],
                                      format=date_fmt).dt.strftime("%Y-%m-%d")
    elif resolution == "hourly" and "datetime" in cols:
        out["datetime"] = pd.to_datetime(df[cols["datetime"]],
                                          format=date_fmt).dt.strftime("%Y-%m-%d %H:%M")
    else:
        raise ValueError(f"매핑에 {'date' if resolution=='daily' else 'datetime'} 컬럼 필요")

    # pcp
    if "pcp_mm" in cols:
        s = pd.Series(df[cols["pcp_mm"]], dtype="float64")
        s = _drop_missing(s, missing)
        out["pcp_mm"] = (s * 25.4) if units.get("pcp") == "inch" else s

    # temperature
    temp_unit = units.get("temp", "C")
    for std in ("tmax_c", "tmin_c", "tavg_c", "tdew_c"):
        if std in cols:
            s = pd.Series(df[cols[std]], dtype="float64")
            s = _drop_missing(s, missing)
            out[std] = (s - 32.0) * 5.0 / 9.0 if temp_unit == "F" else s

    # wind
    wind_unit = units.get("wind", "ms")
    if "ws10_ms" in cols:
        s = pd.Series(df[cols["ws10_ms"]], dtype="float64")
        s = _drop_missing(s, missing)
        if   wind_unit == "knots": s = s * 0.5144
        elif wind_unit == "kmh":   s = s / 3.6
        elif wind_unit == "mph":   s = s * 0.44704
        out["ws10_ms"] = s.round(3)
        out["ws2_ms"]  = wind_to_2m_fao56(s, z=wind_h).round(3)

    # solar
    if resolution == "daily" and "slr_mjm2" in cols:
        out["slr_mjm2"] = pd.Series(df[cols["slr_mjm2"]], dtype="float64")
    if resolution == "hourly" and "slr_wm2" in cols:
        out["slr_wm2"] = pd.Series(df[cols["slr_wm2"]], dtype="float64")

    # humidity: 직접 제공 또는 Magnus 식 계산
    if "hmd_pct" in cols:
        out["hmd_pct"] = pd.Series(df[cols["hmd_pct"]], dtype="float64")
    elif "tavg_c" in out.columns and "tdew_c" in out.columns:
        out["hmd_pct"] = magnus_rh(out["tavg_c"], out["tdew_c"]).round(2)

    out["source"] = "USER"

    # 표준 순서 정렬 + 빠진 컬럼은 NaN
    target = STD_DAILY_COLUMNS if resolution == "daily" else STD_HOURLY_COLUMNS
    for c in target:
        if c not in out.columns:
            out[c] = np.nan
    out = out[target]

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_csv, index=False)
    return output_csv


# ── 일괄 변환 (디렉토리 단위) ────────────────────────────────────────────────

def standardize_dir_era5_daily(
    raw_dir: Union[str, Path],
    out_dir: Union[str, Path],
    *,
    wind_height_m: float = 10.0,
) -> int:
    """ERA5 grid_daily 폴더 일괄 변환. 처리 파일 수 반환."""
    raw_dir = Path(raw_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for csv in sorted(raw_dir.glob("*.csv")):
        standardize_era5_daily(csv, out_dir / csv.name, wind_height_m=wind_height_m)
        n += 1
    return n


def standardize_dir_era5_hourly(
    raw_dir: Union[str, Path],
    out_dir: Union[str, Path],
    *,
    wind_height_m: float = 10.0,
) -> int:
    raw_dir = Path(raw_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for csv in sorted(raw_dir.glob("*.csv")):
        standardize_era5_hourly(csv, out_dir / csv.name, wind_height_m=wind_height_m)
        n += 1
    return n


def standardize_dir_gsod_daily(
    raw_dir: Union[str, Path],
    out_dir: Union[str, Path],
    *,
    wind_height_m: float = 10.0,
) -> int:
    """GSOD daily 폴더 (관측소별 CSV) 일괄 변환."""
    raw_dir = Path(raw_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for csv in sorted(raw_dir.glob("*.csv")):
        try:
            standardize_gsod_daily(csv, out_dir / csv.name, wind_height_m=wind_height_m)
            n += 1
        except Exception as e:
            print(f"  [WARN] {csv.name}: {e}")
    return n


# ── hourly → daily 집계 (표준 포맷 안에서) ──────────────────────────────────

def aggregate_std_hourly_to_daily(
    hourly_csv: Union[str, Path],
    daily_csv: Union[str, Path],
) -> Path:
    """std hourly CSV → std daily CSV 집계.

    집계 규칙:
      pcp_mm   : 일 합계
      tmax_c   : 일 중 tavg_c 의 max
      tmin_c   : 일 중 tavg_c 의 min
      tavg_c   : 일 평균
      tdew_c   : 일 평균
      hmd_pct  : 일 평균 (또는 daily tavg/tdew 로 재계산해도 무방)
      slr_mjm2 : Σ(slr_wm2 × 3600s) / 1e6 = MJ/m²/day
      ws10_ms  : 일 평균
      ws2_ms   : 일 평균 (FAO-56 인자가 선형이라 평균 후 적용해도 동일)
    """
    hourly_csv = Path(hourly_csv)
    daily_csv = Path(daily_csv)

    df = pd.read_csv(hourly_csv, parse_dates=["datetime"])
    df["date"] = df["datetime"].dt.date

    g = df.groupby("date")
    daily = pd.DataFrame({
        "date":     pd.to_datetime(g.size().index),
        "pcp_mm":   g["pcp_mm"].sum().values,
        "tmax_c":   g["tavg_c"].max().values,
        "tmin_c":   g["tavg_c"].min().values,
        "tavg_c":   g["tavg_c"].mean().values,
        "tdew_c":   g["tdew_c"].mean().values,
        "hmd_pct":  g["hmd_pct"].mean().values,
        "slr_mjm2": (g["slr_wm2"].sum().values * 3600.0 / 1e6),
        "ws10_ms":  g["ws10_ms"].mean().values,
        "ws2_ms":   g["ws2_ms"].mean().values,
    })
    daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")
    daily["source"] = df["source"].iloc[0] if "source" in df.columns else ""

    daily_csv.parent.mkdir(parents=True, exist_ok=True)
    daily[STD_DAILY_COLUMNS].to_csv(daily_csv, index=False)
    return daily_csv


def aggregate_dir_hourly_to_daily(
    hourly_dir: Union[str, Path],
    daily_dir: Union[str, Path],
) -> int:
    """std hourly 폴더 → std daily 폴더 일괄 집계."""
    hourly_dir = Path(hourly_dir)
    daily_dir = Path(daily_dir)
    daily_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for csv in sorted(hourly_dir.glob("*.csv")):
        aggregate_std_hourly_to_daily(csv, daily_dir / csv.name)
        n += 1
    return n
