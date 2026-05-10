"""
ERA5 단일 레벨 시간별 자료 다운로드 및 검증 모듈

다운로드 설명
------------
- CDS(Copernicus Climate Data Store) API를 통해 ERA5 reanalysis 자료를 연 단위로 다운로드
- 공간 범위: country_boundary.csv의 영역 + 0.25° 버퍼, ERA5 격자에 스냅
- 파일명 형식: ERA5_{var}_hourly_{year}.nc
- 현재 연도는 전월(이번 달 - 1)까지만 포함

CDS API 인증 설정 (최초 1회)
------------------------------
  1. https://cds.climate.copernicus.eu/profile 에서 API 키 확인
  2. 아래 중 하나로 설정:
     a) 파일 방식 (권장): ~/.cdsapirc 또는 %USERPROFILE%/.cdsapirc
        url: https://cds.climate.copernicus.eu/api
        key: <YOUR-API-KEY>
     b) 환경 변수: CDSAPI_URL / CDSAPI_KEY
     c) 함수 인자: download_era5_year(... url=..., key=...)

변수 매핑 (CDS 변수명 ↔ 파일 접두사 ↔ NC 내부 변수명)
------------------------------------------------------
  prcp : total_precipitation                                          → tp
  tavg : 2m_temperature                                              → t2m
  tmax : maximum_2m_temperature_since_previous_post_processing       → mx2t
  tmin : minimum_2m_temperature_since_previous_post_processing       → mn2t
  tdew : 2m_dewpoint_temperature                                     → d2m
  rsds : surface_solar_radiation_downwards                           → ssrd
  u10m : 10m_u_component_of_wind                                     → u10
  v10m : 10m_v_component_of_wind                                     → v10
"""

from __future__ import annotations

import math
import os
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# ── 변수 정의 ─────────────────────────────────────────────────────────────────

# (CDS 변수명, NC 내부 변수명)
VARIABLES: Dict[str, Tuple[str, str]] = {
    "prcp": ("total_precipitation",
             "tp"),
    "tavg": ("2m_temperature",
             "t2m"),
    "tmax": ("maximum_2m_temperature_since_previous_post_processing",
             "mx2t"),
    "tmin": ("minimum_2m_temperature_since_previous_post_processing",
             "mn2t"),
    "tdew": ("2m_dewpoint_temperature",
             "d2m"),
    "rsds": ("surface_solar_radiation_downwards",
             "ssrd"),
    "u10m": ("10m_u_component_of_wind",
             "u10"),
    "v10m": ("10m_v_component_of_wind",
             "v10"),
}

ERA5_DATASET  = "reanalysis-era5-single-levels"
ERA5_GRID_RES = 0.25    # ERA5 격자 해상도 (도)
_AREA_BUFFER  = 0.25    # 경계 버퍼 (도)

# 검증 시 기대 최소 파일 크기 (bytes) — 연간 시간별 데이터 기준
_MIN_FILE_BYTES = 1 * 1024 * 1024   # 1 MB


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _snap(value: float, direction: str, res: float = ERA5_GRID_RES) -> float:
    """값을 ERA5 격자(res 배수)로 스냅합니다."""
    if direction == "up":
        return math.ceil(round(value / res, 6)) * res
    else:
        return math.floor(round(value / res, 6)) * res


def _expected_hours(year: int, months: List[int]) -> int:
    """지정 연/월 목록의 총 시간 수 계산 (1시간 간격, 24h/일)."""
    import calendar
    return sum(calendar.monthrange(year, m)[1] * 24 for m in months)


def _months_fmt(months: List[int]) -> List[str]:
    return [f"{m:02d}" for m in months]


def _days_fmt() -> List[str]:
    return [f"{d:02d}" for d in range(1, 32)]


def _hours_fmt() -> List[str]:
    return [f"{h:02d}:00" for h in range(24)]


# ── 공개 API ──────────────────────────────────────────────────────────────────

def compute_area(
    boundary_csv: str,
    buffer: float = _AREA_BUFFER,
    grid_res: float = ERA5_GRID_RES,
) -> List[float]:
    """country_boundary.csv로부터 CDS API용 영역 [N, W, S, E]를 계산합니다.

    버퍼를 더한 후 ERA5 격자(0.25°)에 스냅합니다.

    Returns
    -------
    [north, west, south, east] (float)
    """
    df = pd.read_csv(boundary_csv)
    row = df.iloc[0]
    north = _snap(float(row["ymax"]) + buffer, "up",   grid_res)
    south = _snap(float(row["ymin"]) - buffer, "down", grid_res)
    west  = _snap(float(row["xmin"]) - buffer, "down", grid_res)
    east  = _snap(float(row["xmax"]) + buffer, "up",   grid_res)
    return [round(north, 2), round(west, 2), round(south, 2), round(east, 2)]


def download_era5_year(
    var_key: str,
    year: int,
    output_dir: str,
    boundary_csv: str,
    months: Optional[List[int]] = None,
    overwrite: bool = False,
    url: Optional[str] = None,
    key: Optional[str] = None,
    timeout: int = 3600,
    retry: int = 3,
) -> Optional[str]:
    """단일 변수 × 연도에 대해 ERA5 시간별 자료를 다운로드합니다.

    Parameters
    ----------
    var_key      : 변수 키 (prcp / tavg / tmax / tmin / tdew / rsds / u10m / v10m)
    year         : 다운로드할 연도
    output_dir   : NC 파일 저장 폴더
    boundary_csv : country_boundary.csv 경로 (공간 범위 계산에 사용)
    months       : 다운로드할 월 목록 (None → 1~12 전체)
    overwrite    : True이면 기존 파일 덮어쓰기
    url          : CDS API URL (None → .cdsapirc 또는 환경변수 사용)
    key          : CDS API 키 (None → .cdsapirc 또는 환경변수 사용)
    timeout      : CDS 요청 타임아웃(초)
    retry        : 실패 시 재시도 횟수

    Returns
    -------
    str : 저장된 파일 경로 (건너뜀 또는 실패 시 None)
    """
    if var_key not in VARIABLES:
        raise ValueError(f"지원하지 않는 변수: '{var_key}'. 가능: {list(VARIABLES)}")

    cds_var, _ = VARIABLES[var_key]

    if months is None:
        months = list(range(1, 13))

    out_path = Path(output_dir) / f"ERA5_{var_key}_hourly_{year}.nc"

    if out_path.exists() and not overwrite:
        print(f"  [SKIP] {out_path.name} (이미 존재)")
        return str(out_path)

    area = compute_area(boundary_csv)

    # CDS 요청 파라미터 (cdsapi 0.7.x 호환)
    request = {
        "product_type": ["reanalysis"],
        "variable":      [cds_var],
        "year":          [str(year)],
        "month":         _months_fmt(months),
        "day":           _days_fmt(),
        "time":          _hours_fmt(),
        "area":          area,
        "data_format":   "netcdf",
        "download_format": "unarchived",
    }

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # CDS 클라이언트 초기화
    import cdsapi
    client_kwargs: dict = {}
    if url:
        client_kwargs["url"] = url
    if key:
        client_kwargs["key"] = key

    for attempt in range(1, retry + 1):
        try:
            print(f"  [{attempt}/{retry}] 다운로드: {out_path.name} "
                  f"(months={months[0]:02d}~{months[-1]:02d})")
            client = cdsapi.Client(**client_kwargs)
            client.retrieve(ERA5_DATASET, request, str(out_path))
            print(f"  [OK] {out_path.name}  "
                  f"({out_path.stat().st_size / 1e6:.1f} MB)")
            return str(out_path)
        except Exception as exc:
            msg = str(exc)
            print(f"  [WARN] 시도 {attempt} 실패: {msg}")
            # 인증 오류는 재시도해도 의미 없음 → 즉시 중단
            if "configuration file" in msg or "Missing" in msg or "401" in msg:
                print("  [FAIL] 인증 오류 — .cdsapirc 파일 또는 --key 인자를 확인하세요.")
                return None
            if attempt < retry:
                wait = 30 * attempt
                print(f"  {wait}초 후 재시도...")
                time.sleep(wait)

    print(f"  [FAIL] {out_path.name} — {retry}회 모두 실패")
    return None


def download_era5_all(
    output_dir: str,
    boundary_csv: str,
    start_year: int = 1979,
    end_year: Optional[int] = None,
    var_keys: Optional[List[str]] = None,
    overwrite: bool = False,
    url: Optional[str] = None,
    key: Optional[str] = None,
) -> Tuple[List[str], List[str]]:
    """여러 변수 × 연도를 일괄 다운로드합니다.

    Parameters
    ----------
    output_dir   : NC 파일 저장 폴더
    boundary_csv : country_boundary.csv 경로
    start_year   : 시작 연도 (기본 1979)
    end_year     : 종료 연도 (기본 오늘 기준 현재 연도)
    var_keys     : 다운로드할 변수 키 목록 (None → 전체 8개)
    overwrite    : 기존 파일 덮어쓰기 여부
    url / key    : CDS API 인증 정보

    Returns
    -------
    (created, failed)
        created : 성공적으로 저장된 파일 경로 목록
        failed  : 실패한 "{year}_{var}" 목록
    """
    today     = date.today()
    if end_year is None:
        end_year = today.year
    if var_keys is None:
        var_keys = list(VARIABLES.keys())

    created: List[str] = []
    failed:  List[str] = []

    for year in range(start_year, end_year + 1):
        # 현재 연도는 전월까지만 (이번 달 - 1)
        if year == today.year:
            last_month = today.month - 1
            if last_month < 1:
                print(f"  [{year}] 아직 다운로드 가능한 완성된 달이 없음 — 건너뜀")
                continue
            months = list(range(1, last_month + 1))
            print(f"\n{'='*60}")
            print(f"  {year}년 (현재 연도, 1~{last_month}월)")
            print(f"{'='*60}")
        else:
            months = list(range(1, 13))
            print(f"\n{'='*60}")
            print(f"  {year}년 (전체 12개월)")
            print(f"{'='*60}")

        for var_key in var_keys:
            path = download_era5_year(
                var_key=var_key,
                year=year,
                output_dir=output_dir,
                boundary_csv=boundary_csv,
                months=months,
                overwrite=overwrite,
                url=url,
                key=key,
            )
            if path:
                created.append(path)
            else:
                failed.append(f"{year}_{var_key}")

    return created, failed


# ── 검증 ──────────────────────────────────────────────────────────────────────

def verify_era5_file(nc_path: str, var_key: str, year: int,
                     months: Optional[List[int]] = None) -> dict:
    """단일 ERA5 NC 파일을 검증하고 결과 딕셔너리를 반환합니다.

    검사 항목
    ---------
    1. 파일 존재 여부
    2. 파일 크기 (> 1 MB)
    3. netCDF4로 열기
    4. 예상 변수 포함 여부
    5. 시간 차원 크기 (기대 시간 수와 비교)
    6. 공간 범위 (격자 점 수)

    Returns
    -------
    dict with keys:
      ok (bool), path, size_mb, n_times, expected_times,
      has_var, lon_range, lat_range, messages (list of str)
    """
    import calendar
    result = {
        "ok": False, "path": nc_path, "size_mb": 0.0,
        "n_times": 0, "expected_times": 0,
        "has_var": False, "lon_range": None, "lat_range": None,
        "messages": [],
    }
    p = Path(nc_path)

    # 1. 파일 존재
    if not p.exists():
        result["messages"].append("파일 없음")
        return result

    # 2. 파일 크기
    size_bytes = p.stat().st_size
    result["size_mb"] = size_bytes / 1e6
    if size_bytes < _MIN_FILE_BYTES:
        result["messages"].append(f"파일 크기 너무 작음 ({result['size_mb']:.2f} MB)")
        return result

    # 3. netCDF4 열기
    try:
        import netCDF4 as nc
        ds = nc.Dataset(nc_path)
    except Exception as e:
        result["messages"].append(f"netCDF4 오픈 실패: {e}")
        return result

    try:
        # 4. 변수 확인
        _, nc_var = VARIABLES[var_key]
        result["has_var"] = nc_var in ds.variables
        if not result["has_var"]:
            result["messages"].append(f"변수 '{nc_var}' 없음 (존재: {list(ds.variables.keys())})")

        # 5. 시간 차원
        if months is None:
            months = list(range(1, 13))
        expected = _expected_hours(year, months)
        result["expected_times"] = expected
        time_var_name = next((n for n in ("time", "valid_time") if n in ds.variables), None)
        if time_var_name:
            result["n_times"] = len(ds.variables[time_var_name])
            if result["n_times"] != expected:
                result["messages"].append(
                    f"시간 차원 불일치: {result['n_times']} (기대 {expected})"
                )
        else:
            result["messages"].append("'time' 차원 없음")

        # 6. 공간 범위
        if "longitude" in ds.variables and "latitude" in ds.variables:
            lon = ds.variables["longitude"][:]
            lat = ds.variables["latitude"][:]
            result["lon_range"] = (float(lon.min()), float(lon.max()))
            result["lat_range"] = (float(lat.min()), float(lat.max()))
    finally:
        ds.close()

    result["ok"] = (
        result["has_var"]
        and result["n_times"] == result["expected_times"]
        and result["size_mb"] > 0
        and not result["messages"]
    )
    return result


def verify_era5_all(
    output_dir: str,
    start_year: int,
    end_year: Optional[int] = None,
    var_keys: Optional[List[str]] = None,
) -> pd.DataFrame:
    """지정 범위의 모든 ERA5 파일을 검증하고 요약 DataFrame을 반환합니다.

    Parameters
    ----------
    output_dir : NC 파일 폴더
    start_year : 시작 연도
    end_year   : 종료 연도 (기본: 오늘 연도)
    var_keys   : 검증할 변수 키 목록 (기본: 전체 8개)

    Returns
    -------
    DataFrame (year, var, ok, size_mb, n_times, expected_times, messages)
    """
    today = date.today()
    if end_year is None:
        end_year = today.year
    if var_keys is None:
        var_keys = list(VARIABLES.keys())

    rows = []
    for year in range(start_year, end_year + 1):
        months = (list(range(1, today.month))
                  if year == today.year
                  else list(range(1, 13)))

        for var_key in var_keys:
            nc_path = str(Path(output_dir) / f"ERA5_{var_key}_hourly_{year}.nc")
            r = verify_era5_file(nc_path, var_key, year, months)
            rows.append({
                "year":           year,
                "var":            var_key,
                "ok":             r["ok"],
                "size_mb":        round(r["size_mb"], 1),
                "n_times":        r["n_times"],
                "expected_times": r["expected_times"],
                "messages":       "; ".join(r["messages"]) if r["messages"] else "OK",
            })

    return pd.DataFrame(rows)
