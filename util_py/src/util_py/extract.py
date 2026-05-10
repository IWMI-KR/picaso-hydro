"""
ERA5 격자점 기상자료 추출 모듈

ERA5 NC 파일로부터 격자점별 시간단위 및 일단위 기상자료를 추출합니다.
UTC 기준의 ERA5 자료를 utc_offset 시차만큼 보정하여 로컬 시간 기준으로 저장합니다.

출력 헤더 정의
--------------
[시간단위 — grid_hourly/{ID}.csv]
  datetime   : 로컬 시간 (YYYY-MM-DD HH:MM)
  prcp_mm    : 시간 강수량 (mm hr⁻¹)         ← ERA5 tp × 1000, 음수는 0으로 처리
  tavg_c     : 2m 기온 순간값 (°C)
  tmax_c     : 이전 처리 이후 최고 2m 기온 (°C)
  tmin_c     : 이전 처리 이후 최저 2m 기온 (°C)
  tdew_c     : 2m 이슬점 온도 (°C)
  rsds_wm2   : 지표 하향 단파복사 (W m⁻²)    ← ERA5 ssrd ÷ 3600
  u10_ms     : 10m 동서풍 성분 (m s⁻¹)
  v10_ms     : 10m 남북풍 성분 (m s⁻¹)
  ws10_ms    : 10m 풍속 √(u²+v²) (m s⁻¹)

[일단위 — grid_daily/{ID}.csv]
  date       : 로컬 날짜 (YYYY-MM-DD)
  prcp_mm    : 일 강수량 (mm day⁻¹)           ← 시간값 합계
  tavg_c     : 일 평균 기온 (°C)
  tmax_c     : 일 최고 기온 (°C)              ← hourly tmax_c의 max
  tmin_c     : 일 최저 기온 (°C)              ← hourly tmin_c의 min
  tdew_c     : 일 평균 이슬점 온도 (°C)
  rsds_mjm2  : 일 하향 단파복사 (MJ m⁻² day⁻¹) ← sum(ssrd J/m²) ÷ 1e6
  ws10_ms    : 일 평균 풍속 (m s⁻¹)

헤더 명명 규칙
--------------
  {변수명}_{단위약어} 형식 — 단위가 컬럼명에 포함되어 자기 설명적.
  향후 변수 추가 시 동일 규칙 적용 권장 (예: rh_pct, sp_hpa, vpd_kpa).

UTC 오프셋 예시
--------------
  쿡 아일랜드 : utc_offset = -10  (CIST = UTC−10)
  한국        : utc_offset = +9
  인도        : utc_offset = +5   (정수 근사; 실제 UTC+5:30)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ── 변수 메타데이터 ────────────────────────────────────────────────────────────
# (nc_var_name, unit_conversion_fn, hourly_col_name)
_VAR_META: Dict[str, Tuple[str, callable, str]] = {
    "prcp": ("tp",   lambda v: np.clip(v * 1000, 0.0, None), "prcp_mm"),
    "tavg": ("t2m",  lambda v: v - 273.15,                   "tavg_c"),
    "tmax": ("mx2t", lambda v: v - 273.15,                   "tmax_c"),
    "tmin": ("mn2t", lambda v: v - 273.15,                   "tmin_c"),
    "tdew": ("d2m",  lambda v: v - 273.15,                   "tdew_c"),
    "rsds": ("ssrd", lambda v: v / 3600.0,                   "rsds_wm2"),
    "u10m": ("u10",  lambda v: v,                            "u10_ms"),
    "v10m": ("v10",  lambda v: v,                            "v10_ms"),
}

HOURLY_COLS = [
    "datetime", "prcp_mm", "tavg_c", "tmax_c", "tmin_c",
    "tdew_c", "rsds_wm2", "u10_ms", "v10_ms", "ws10_ms",
]
DAILY_COLS = [
    "date", "prcp_mm", "tavg_c", "tmax_c", "tmin_c",
    "tdew_c", "rsds_mjm2", "ws10_ms",
]


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _load_grid_points(path: str) -> pd.DataFrame:
    """CSV 또는 SHP로부터 격자점 (ID, Lon, Lat)을 로드합니다."""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        return df[["ID", "Lon", "Lat"]].copy()
    else:
        import geopandas as gpd
        gdf = gpd.read_file(path)
        if "Lon" not in gdf.columns:
            gdf["Lon"] = gdf.geometry.x
            gdf["Lat"] = gdf.geometry.y
        return gdf[["ID", "Lon", "Lat"]].copy()


def _get_time_var(ds) -> object:
    """NC Dataset에서 시간 변수를 반환합니다 (구 포맷: 'time', 신 포맷: 'valid_time')."""
    for name in ("time", "valid_time"):
        if name in ds.variables:
            return ds.variables[name]
    raise KeyError(f"시간 변수를 찾을 수 없습니다. 변수 목록: {list(ds.variables.keys())}")


def _parse_times(nc_path: str) -> pd.DatetimeIndex:
    """NC 파일 time 변수를 UTC DatetimeIndex로 변환합니다."""
    import netCDF4 as nc4
    ds = nc4.Dataset(nc_path)
    try:
        tv = _get_time_var(ds)
        times = nc4.num2date(
            tv[:], tv.units,
            calendar=getattr(tv, "calendar", "standard"),
            only_use_cftime_datetimes=False,
            only_use_python_datetimes=True,
        )
    finally:
        ds.close()
    return pd.DatetimeIndex(times, tz="UTC")


def _read_points_from_nc(
    nc_path: str,
    nc_var: str,
    lat_idx: np.ndarray,
    lon_idx: np.ndarray,
) -> Tuple[pd.DatetimeIndex, np.ndarray]:
    """NC 파일에서 지정 격자점들의 시계열 (n_times × n_pts)을 추출합니다."""
    import netCDF4 as nc4
    ds = nc4.Dataset(nc_path)
    try:
        tv = _get_time_var(ds)
        times = nc4.num2date(
            tv[:], tv.units,
            calendar=getattr(tv, "calendar", "standard"),
            only_use_cftime_datetimes=False,
            only_use_python_datetimes=True,
        )
        times_idx = pd.DatetimeIndex(times, tz="UTC")

        var = ds.variables[nc_var]
        raw = np.array(var[:], dtype=float)
        # 마스킹 처리
        if isinstance(raw, np.ma.MaskedArray):
            raw = raw.filled(np.nan)
        # 특정 fill value 처리
        fv = getattr(var, "_FillValue", None)
        if fv is not None:
            raw[raw == float(fv)] = np.nan

        # (n_times, n_lat, n_lon) → (n_times, n_pts) 추출
        data_pts = raw[:, lat_idx, lon_idx]
    finally:
        ds.close()
    return times_idx, data_pts


def _find_idx(arr: np.ndarray, values: List[float]) -> np.ndarray:
    """배열에서 각 값에 가장 가까운 인덱스를 numpy 배열로 반환합니다."""
    return np.array([np.argmin(np.abs(arr - v)) for v in values], dtype=int)


# ── 공개 API ──────────────────────────────────────────────────────────────────

def extract_era5_to_grid(
    grid_csv_or_shp: str,
    era5_nc_dir: str,
    output_hourly_dir: str,
    output_daily_dir: str,
    utc_offset: int = 0,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    overwrite: bool = False,
) -> dict:
    """ERA5 NC 파일로부터 격자점별 시간·일 단위 기상자료를 추출합니다.

    Parameters
    ----------
    grid_csv_or_shp   : 격자점 파일 (.csv 또는 .shp). 컬럼: ID, Lon, Lat
    era5_nc_dir       : ERA5 NC 파일 폴더 (파일명: ERA5_{var}_hourly_{year}.nc)
    output_hourly_dir : 시간단위 출력 폴더
    output_daily_dir  : 일단위 출력 폴더
    utc_offset        : UTC → 로컬 시간 차이(시간). 예: 쿡 아일랜드 = -10
    start_year        : 추출 시작 연도 (기본: 사용 가능한 첫 연도)
    end_year          : 추출 종료 연도 (기본: 사용 가능한 마지막 연도)
    overwrite         : True이면 기존 파일 덮어쓰기

    Returns
    -------
    dict: n_points, n_hourly_written, n_daily_written, skipped
    """
    nc_dir = Path(era5_nc_dir)
    out_h  = Path(output_hourly_dir)
    out_d  = Path(output_daily_dir)
    out_h.mkdir(parents=True, exist_ok=True)
    out_d.mkdir(parents=True, exist_ok=True)

    # ── 1. 격자점 로드 ────────────────────────────────────────────────────────
    pts     = _load_grid_points(grid_csv_or_shp)
    pt_ids  = pts["ID"].tolist()
    pt_lons = pts["Lon"].tolist()
    pt_lats = pts["Lat"].tolist()
    n_pts   = len(pts)
    print(f"  격자점 수: {n_pts}개  |  UTC 오프셋: {utc_offset:+d}h")

    # ── 2. 사용 가능 연도 탐색 (prcp 기준) ────────────────────────────────────
    avail = sorted(
        int(p.stem.split("_")[-1])
        for p in nc_dir.glob("ERA5_prcp_hourly_*.nc")
    )
    if not avail:
        raise FileNotFoundError(f"ERA5 NC 파일 없음: {nc_dir}")
    y0 = start_year or avail[0]
    y1 = end_year   or avail[-1]
    years = [y for y in avail if y0 <= y <= y1]
    print(f"  대상 연도: {years[0]}~{years[-1]} ({len(years)}개)\n")

    # ── 3. 격자 인덱스 파악 ───────────────────────────────────────────────────
    import netCDF4 as nc4
    first_nc = next(nc_dir.glob("ERA5_prcp_hourly_*.nc"))
    ds = nc4.Dataset(str(first_nc))
    lat_arr = np.array(ds.variables["latitude"][:],  dtype=float)
    lon_arr = np.array(ds.variables["longitude"][:], dtype=float)
    ds.close()
    lat_idx = _find_idx(lat_arr, pt_lats)
    lon_idx = _find_idx(lon_arr, pt_lons)

    # ── 4. 연도×변수별 데이터 추출 ────────────────────────────────────────────
    # frames[(var_key, year)] = (times_utc, data_2d)  data_2d: (n_t, n_pts)
    frames: Dict[Tuple[str, int], Tuple] = {}

    for year in years:
        print(f"  [{year}] ", end="", flush=True)
        for var_key, (nc_var, conv, _) in _VAR_META.items():
            nc_path = nc_dir / f"ERA5_{var_key}_hourly_{year}.nc"
            if not nc_path.exists():
                print(f"{var_key}✗ ", end="", flush=True)
                continue
            try:
                times_idx, data_pts = _read_points_from_nc(
                    str(nc_path), nc_var, lat_idx, lon_idx
                )
                frames[(var_key, year)] = (times_idx, conv(data_pts))
                print(f"{var_key}✓ ", end="", flush=True)
            except Exception as e:
                print(f"{var_key}✗({e}) ", end="", flush=True)
        print()

    if not frames:
        raise RuntimeError("추출 가능한 데이터가 없습니다.")

    # ── 5. 변수별 전체 시계열 결합 ────────────────────────────────────────────
    # var_df[var_key]: DataFrame(n_total_times × n_pts), UTC DatetimeIndex
    var_df: Dict[str, Optional[pd.DataFrame]] = {}
    ref_times = None

    for var_key in _VAR_META:
        parts = [(t, d) for (vk, yr), (t, d) in frames.items() if vk == var_key]
        if not parts:
            var_df[var_key] = None
            continue
        times_cat = pd.DatetimeIndex(
            np.concatenate([p[0].values for p in parts])
        ).tz_localize(None)   # naive UTC
        data_cat  = np.vstack([p[1] for p in parts])
        order     = np.argsort(times_cat)
        df_v = pd.DataFrame(
            data_cat[order, :],
            index=times_cat[order],
        )
        var_df[var_key] = df_v
        if ref_times is None:
            ref_times = df_v.index

    # 공통 인덱스 재정렬
    for var_key, df_v in var_df.items():
        if df_v is not None and not df_v.index.equals(ref_times):
            var_df[var_key] = df_v.reindex(ref_times)

    print(f"\n  총 시간 스텝: {len(ref_times)}")

    # ── 6. 격자점별 시간·일 파일 저장 ────────────────────────────────────────
    n_hourly = 0
    n_daily  = 0
    skipped  = []

    for i, pt_id in enumerate(pt_ids):
        h_path = out_h / f"{pt_id}.csv"
        d_path = out_d / f"{pt_id}.csv"

        if h_path.exists() and d_path.exists() and not overwrite:
            skipped.append(pt_id)
            continue

        # 각 변수 배열 추출
        def col(var_key):
            return (var_df[var_key].iloc[:, i].values
                    if var_df[var_key] is not None
                    else np.full(len(ref_times), np.nan))

        prcp  = col("prcp")
        tavg  = col("tavg")
        tmax  = col("tmax")
        tmin  = col("tmin")
        tdew  = col("tdew")
        rsds  = col("rsds")   # W/m²
        u10   = col("u10m")
        v10   = col("v10m")
        ws10  = np.sqrt(u10**2 + v10**2)

        # ── 로컬 시간 인덱스 ───────────────────────────────────────────────
        local_times = ref_times + pd.Timedelta(hours=utc_offset)

        # ── 시간단위 CSV ───────────────────────────────────────────────────
        df_h = pd.DataFrame({
            "datetime": local_times.strftime("%Y-%m-%d %H:%M"),
            "prcp_mm":  np.round(prcp, 3),
            "tavg_c":   np.round(tavg, 2),
            "tmax_c":   np.round(tmax, 2),
            "tmin_c":   np.round(tmin, 2),
            "tdew_c":   np.round(tdew, 2),
            "rsds_wm2": np.round(rsds, 2),
            "u10_ms":   np.round(u10,  3),
            "v10_ms":   np.round(v10,  3),
            "ws10_ms":  np.round(ws10, 3),
        })
        df_h.to_csv(h_path, index=False)
        n_hourly += 1

        # ── 일단위 집계 (로컬 날짜 기준) ──────────────────────────────────
        df_tmp = pd.DataFrame({
            "prcp_mm":  prcp,
            "tavg_c":   tavg,
            "tmax_c":   tmax,
            "tmin_c":   tmin,
            "tdew_c":   tdew,
            "rsds_wm2": rsds,   # W/m²
            "ws10_ms":  ws10,
        }, index=local_times)

        daily = df_tmp.groupby(df_tmp.index.date).agg({
            "prcp_mm":  "sum",
            "tavg_c":   "mean",
            "tmax_c":   "max",
            "tmin_c":   "min",
            "tdew_c":   "mean",
            "rsds_wm2": "sum",   # sum(W/m² per hr) × 3600 s = J/m²/day → /1e6 = MJ/m²
            "ws10_ms":  "mean",
        })
        daily["rsds_mjm2"] = np.round(daily.pop("rsds_wm2") * 3600 / 1e6, 3)
        daily = daily.round({"prcp_mm": 3, "tavg_c": 2, "tmax_c": 2,
                             "tmin_c": 2, "tdew_c": 2, "ws10_ms": 3})
        daily.index.name = "date"
        daily = daily.reset_index()
        daily["date"] = daily["date"].astype(str)
        daily[DAILY_COLS].to_csv(d_path, index=False)
        n_daily += 1

    print(f"  시간단위: {n_hourly}개 저장  |  일단위: {n_daily}개 저장"
          + (f"  |  건너뜀: {len(skipped)}개" if skipped else ""))

    return {
        "n_points":         n_pts,
        "n_hourly_written": n_hourly,
        "n_daily_written":  n_daily,
        "skipped":          skipped,
    }
