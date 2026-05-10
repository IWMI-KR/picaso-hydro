"""
ERA5 격자점 추출 모듈

ERA5 NC 파일의 격자와 폴리곤 경계(shapefile)를 교차 분석하여,
폴리곤을 터치하는 ERA5 격자점을 추출합니다.

추출 방법 (접촉 기준)
---------------------
각 ERA5 격자점 (lon, lat)에 대해 0.25° × 0.25° 셀 박스를 생성하고,
셀 박스가 폴리곤과 조금이라도 교차(intersect)하는 격자점을 모두 선택합니다.
경계를 터치만 해도 포함되므로, 폴리곤 전체를 빈틈없이 커버합니다.

출력 파일 (권장 위치 — gsod station-gsod.csv 와 일관)
-----------------------------------------------------
- grid_points-era5.shp : 격자점 포인트 레이어 (EPSG:4326)
- grid_points-era5.csv : stations.csv 형식 (Lon, Lat, Elev, ID, Ename, Syear)

  권장 폴더: $(project.root)/0_database/era5/
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


ERA5_GRID_RES = 0.25   # ERA5 격자 해상도 (도)
ERA5_HALF     = ERA5_GRID_RES / 2   # 셀 반폭 (0.125°)


def _get_era5_grid(era5_nc_dir: str):
    """era5_nc_dir에서 첫 번째 NC 파일로부터 lon/lat 격자 배열을 반환합니다."""
    import netCDF4 as nc4
    nc_files = sorted(
        p for p in Path(era5_nc_dir).iterdir()
        if p.suffix == ".nc"
    )
    if not nc_files:
        raise FileNotFoundError(f"ERA5 NC 파일이 없습니다: {era5_nc_dir}")
    ds = nc4.Dataset(str(nc_files[0]))
    try:
        lon = np.array(ds.variables["longitude"][:], dtype=float)
        lat = np.array(ds.variables["latitude"][:],  dtype=float)
    finally:
        ds.close()
    return lon, lat


def extract_era5_grid_points(
    boundary_shp: str,
    era5_nc_dir: str,
    output_shp: str,
    output_csv: str,
    grid_res: float = ERA5_GRID_RES,
    syear: int = 1979,
) -> pd.DataFrame:
    """ERA5 격자점 중 boundary_shp 폴리곤과 교차하는 점을 추출합니다.

    Parameters
    ----------
    boundary_shp : 경계 폴리곤 shapefile 경로
    era5_nc_dir  : ERA5 NC 파일 폴더 (격자 좌표 추출용)
    output_shp   : 출력 포인트 shapefile 경로
    output_csv   : 출력 CSV 파일 경로 (stations.csv 형식)
    grid_res     : ERA5 격자 해상도 (기본 0.25°)
    syear        : CSV의 Syear 열 값 (기본 1979)

    Returns
    -------
    DataFrame (Lon, Lat, Elev, ID, Ename, Syear)
    """
    import geopandas as gpd
    from shapely.geometry import Point, box

    # ── 1. 경계 폴리곤 로드 ───────────────────────────────────────────────────
    gdf_bound = gpd.read_file(boundary_shp)
    if gdf_bound.crs is None or str(gdf_bound.crs).upper() != "EPSG:4326":
        gdf_bound = gdf_bound.to_crs("EPSG:4326")
    boundary_union = gdf_bound.union_all()   # 모든 피처를 하나로 합침

    # ── 2. ERA5 격자 로드 ─────────────────────────────────────────────────────
    lon_arr, lat_arr = _get_era5_grid(era5_nc_dir)
    half = grid_res / 2

    # ── 3. 교차 검사 ─────────────────────────────────────────────────────────
    selected_lon = []
    selected_lat = []

    for lat in lat_arr:
        for lon in lon_arr:
            cell = box(lon - half, lat - half, lon + half, lat + half)
            if cell.intersects(boundary_union):
                selected_lon.append(round(float(lon), 4))
                selected_lat.append(round(float(lat), 4))

    n = len(selected_lon)
    if n == 0:
        raise RuntimeError("경계 폴리곤과 교차하는 ERA5 격자점이 없습니다.")

    print(f"  교차 격자점: {n}개 (전체 ERA5: {len(lon_arr)*len(lat_arr)}개)")

    # ── 4. ID 부여 (Lat 내림차순 → Lon 오름차순) ────────────────────────────
    df = pd.DataFrame({"Lon": selected_lon, "Lat": selected_lat})
    df = df.sort_values(["Lat", "Lon"], ascending=[False, True]).reset_index(drop=True)
    df["Elev"]  = -99
    df["ID"]    = [f"ERA{i+1:03d}" for i in range(n)]
    df["Ename"] = df["ID"]
    df["Syear"] = syear

    # ── 5. shapefile 저장 ─────────────────────────────────────────────────────
    Path(output_shp).parent.mkdir(parents=True, exist_ok=True)
    gdf_out = gpd.GeoDataFrame(
        df.copy(),
        geometry=[Point(lo, la) for lo, la in zip(df["Lon"], df["Lat"])],
        crs="EPSG:4326",
    )
    gdf_out.to_file(output_shp)
    print(f"  SHP 저장: {output_shp}")

    # ── 6. CSV 저장 ───────────────────────────────────────────────────────────
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    out_df = df[["Lon", "Lat", "Elev", "ID", "Ename", "Syear"]]
    out_df.to_csv(output_csv, index=False)
    print(f"  CSV 저장: {output_csv}")

    return out_df
