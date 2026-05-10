"""
CMIP6 글로벌 NC 파일 영역 추출 모듈

country_boundary.csv의 바운딩 박스를 기준으로
S:/Database-INT/CMIP6/Global_Services_V2 의 글로벌 NC 파일에서
해당 영역 자료를 추출하여 원본과 동일한 파일명으로 저장합니다.

연관 Skill: util_py/cmip6
입력 NC 규격 (CMIP6 Global_Services_V2)
-----------------------------------------
  차원 : time, lat(144), lon(192), bnds
  lon  : 0 ~ 360° (degrees_east)  ← country_boundary.csv는 -180/180 사용
  변수 : pr (kg m-2 s-1), hurs (%) 등

country_boundary.csv 위치
--------------------------
  {project_root}/0_database/gis/boundary/country_boundary.csv
  컬럼: OBJECTID, NAME, ISO3, ISO2, xmin, ymin, xmax, ymax
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _read_boundary(boundary_csv: str) -> Dict[str, float]:
    """country_boundary.csv 에서 바운딩 박스를 읽어 반환합니다.

    Returns
    -------
    dict: xmin, ymin, xmax, ymax  (경도는 -180/180 기준)
    """
    df = pd.read_csv(boundary_csv)
    row = df.iloc[0]
    return {
        "xmin": float(row["xmin"]),
        "ymin": float(row["ymin"]),
        "xmax": float(row["xmax"]),
        "ymax": float(row["ymax"]),
    }


def _lon_to_0360(lon_deg: float) -> float:
    """경도를 0~360° 범위로 변환합니다."""
    return lon_deg % 360.0


def _find_lat_idx(lat_arr: np.ndarray, ymin: float, ymax: float) -> np.ndarray:
    """위도 배열에서 [ymin, ymax] 범위의 인덱스를 반환합니다."""
    mask = (lat_arr >= ymin) & (lat_arr <= ymax)
    idx = np.where(mask)[0]
    if len(idx) == 0:
        raise ValueError(
            f"바운딩 박스 위도 [{ymin}, {ymax}]에 해당하는 격자점이 없습니다."
        )
    return idx


def _find_lon_idx(lon_arr: np.ndarray, xmin_360: float, xmax_360: float) -> np.ndarray:
    """0~360° 기준 경도 배열에서 [xmin_360, xmax_360] 범위의 인덱스를 반환합니다.

    날짜변경선(0°/360° 경계) 걸침은 현재 미지원.
    """
    mask = (lon_arr >= xmin_360) & (lon_arr <= xmax_360)
    idx = np.where(mask)[0]
    if len(idx) == 0:
        raise ValueError(
            f"바운딩 박스 경도 [{xmin_360:.3f}, {xmax_360:.3f}]°(0-360) 에 "
            f"해당하는 격자점이 없습니다."
        )
    return idx


def _extract_one_nc(
    src_path: Path,
    dst_path: Path,
    lat_idx: np.ndarray,
    lon_idx: np.ndarray,
    lat_dim: str = "lat",
    lon_dim: str = "lon",
) -> None:
    """단일 NC 파일에서 공간 서브셋을 추출하여 dst_path에 저장합니다.

    Parameters
    ----------
    src_path : 원본 NC 파일 경로
    dst_path : 출력 NC 파일 경로
    lat_idx  : 추출할 위도 인덱스 배열
    lon_idx  : 추출할 경도 인덱스 배열
    lat_dim  : NC 파일의 위도 차원명 (기본 'lat')
    lon_dim  : NC 파일의 경도 차원명 (기본 'lon')
    """
    import netCDF4 as nc4

    with nc4.Dataset(str(src_path), "r") as src:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        with nc4.Dataset(str(dst_path), "w", format=src.file_format) as dst:

            # ── 1. 전역 속성 복사 ─────────────────────────────────────────────
            dst.setncatts({a: getattr(src, a) for a in src.ncattrs()})

            # ── 2. 차원 생성 ──────────────────────────────────────────────────
            n_lat = len(lat_idx)
            n_lon = len(lon_idx)
            for dim_name, dim in src.dimensions.items():
                if dim_name == lat_dim:
                    dst.createDimension(dim_name, n_lat)
                elif dim_name == lon_dim:
                    dst.createDimension(dim_name, n_lon)
                else:
                    # time 등 무제한 차원 포함
                    dst.createDimension(dim_name, None if dim.isunlimited() else len(dim))

            # ── 3. 변수 생성 및 자료 복사 ────────────────────────────────────
            for var_name, src_var in src.variables.items():
                dims = src_var.dimensions

                # 청크/압축 설정 (원본과 동일하게 유지하되 chunksizes 재계산)
                kwargs: dict = {
                    "datatype": src_var.dtype,
                    "dimensions": dims,
                }
                # zlib 압축 여부 확인 (filters()가 None을 반환하는 경우 무시)
                if hasattr(src_var, "filters"):
                    filt = src_var.filters()
                    if filt and filt.get("zlib"):
                        kwargs["zlib"] = True
                        kwargs["complevel"] = filt.get("complevel", 4)

                dst_var = dst.createVariable(var_name, **kwargs)

                # 변수 속성 복사 (_FillValue는 createVariable 이후 설정하면 오류 발생하므로 제외)
                attrs = {
                    a: getattr(src_var, a)
                    for a in src_var.ncattrs()
                    if a != "_FillValue"
                }
                dst_var.setncatts(attrs)

                # 자료 복사 (lat/lon 차원이 있는 변수는 슬라이싱)
                has_lat = lat_dim in dims
                has_lon = lon_dim in dims

                if not has_lat and not has_lon:
                    # 공간 차원 없음 (time, bnds 등)
                    dst_var[:] = src_var[:]
                elif has_lat and not has_lon:
                    lat_pos = dims.index(lat_dim)
                    slices = [slice(None)] * len(dims)
                    slices[lat_pos] = lat_idx
                    dst_var[:] = np.array(src_var[tuple(slices)])
                elif not has_lat and has_lon:
                    lon_pos = dims.index(lon_dim)
                    slices = [slice(None)] * len(dims)
                    slices[lon_pos] = lon_idx
                    dst_var[:] = np.array(src_var[tuple(slices)])
                else:
                    # 위도·경도 모두 포함 (주 기상 변수)
                    lat_pos = dims.index(lat_dim)
                    lon_pos = dims.index(lon_dim)
                    slices = [slice(None)] * len(dims)
                    slices[lat_pos] = lat_idx
                    slices[lon_pos] = lon_idx
                    data = np.array(src_var[tuple(slices)])
                    dst_var[:] = data


# ── 공개 API ──────────────────────────────────────────────────────────────────

def extract_cmip6_region(
    boundary_csv: str,
    cmip6_nc_dir: str,
    output_nc_dir: str,
    variables: Optional[List[str]] = None,
    overwrite: bool = False,
) -> Dict[str, int]:
    """CMIP6 글로벌 NC 파일에서 country_boundary.csv 영역을 추출합니다.

    Parameters
    ----------
    boundary_csv  : country_boundary.csv 경로. 컬럼: xmin, ymin, xmax, ymax
    cmip6_nc_dir  : 글로벌 NC 파일 디렉토리 (예: S:/Database-INT/CMIP6/Global_Services_V2)
    output_nc_dir : 추출 결과 저장 디렉토리 (원본 파일명 그대로 저장)
    variables     : 추출할 변수 접두어 목록 (예: ['pr', 'hurs']).
                    None이면 디렉토리 내 모든 NC 파일 처리.
    overwrite     : True이면 이미 존재하는 파일도 덮어씀 (기본 False)

    Returns
    -------
    dict: written, skipped, failed 파일 수
    """
    import netCDF4 as nc4

    # ── 1. 바운딩 박스 읽기 ──────────────────────────────────────────────────
    bbox = _read_boundary(boundary_csv)
    xmin_360 = _lon_to_0360(bbox["xmin"])
    xmax_360 = _lon_to_0360(bbox["xmax"])
    ymin = bbox["ymin"]
    ymax = bbox["ymax"]

    print(f"  바운딩 박스:")
    print(f"    위도: {ymin:.4f} ~ {ymax:.4f}°N")
    print(f"    경도: {bbox['xmin']:.4f} ~ {bbox['xmax']:.4f}° "
          f"(0-360 변환: {xmin_360:.4f} ~ {xmax_360:.4f}°)")

    # ── 2. 대상 NC 파일 목록 ─────────────────────────────────────────────────
    src_dir = Path(cmip6_nc_dir)
    nc_files = sorted(src_dir.glob("*.nc"))
    if variables:
        nc_files = [f for f in nc_files if any(f.name.startswith(v + "_") for v in variables)]

    if not nc_files:
        raise FileNotFoundError(
            f"NC 파일을 찾을 수 없습니다: {src_dir}"
            + (f" (변수 필터: {variables})" if variables else "")
        )
    print(f"\n  대상 NC 파일 수: {len(nc_files)}개")

    # ── 3. 격자별 인덱스 캐시 (해상도가 다른 모델 대응) ─────────────────────
    # {(lat_n, lon_n): (lat_dim, lon_dim, lat_idx, lon_idx)}
    _grid_cache: Dict[tuple, tuple] = {}

    def _get_grid_idx(ds) -> tuple:
        """DS의 격자 크기별로 인덱스를 계산하고 캐시합니다."""
        ld = "lat" if "lat" in ds.dimensions else "latitude"
        lod = "lon" if "lon" in ds.dimensions else "longitude"
        key = (len(ds.dimensions[ld]), len(ds.dimensions[lod]))
        if key not in _grid_cache:
            la = np.array(ds.variables[ld][:], dtype=float)
            lo = np.array(ds.variables[lod][:], dtype=float)
            li = _find_lat_idx(la, ymin, ymax)
            loi = _find_lon_idx(lo, xmin_360, xmax_360)
            print(f"\n  [새 격자 {key[0]}×{key[1]}]"
                  f" lat {len(li)}개{list(la[li])}"
                  f" lon {len(loi)}개{list(lo[loi])}")
            _grid_cache[key] = (ld, lod, li, loi)
        return _grid_cache[key]

    # ── 4. 파일별 추출 ───────────────────────────────────────────────────────
    out_dir = Path(output_nc_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    failed: List[str] = []

    for i, src_path in enumerate(nc_files, 1):
        dst_path = out_dir / src_path.name
        prefix = f"  [{i:4d}/{len(nc_files)}] {src_path.name}"

        if dst_path.exists() and not overwrite:
            print(f"{prefix} → 건너뜀 (이미 존재)")
            skipped += 1
            continue

        try:
            with nc4.Dataset(str(src_path), "r") as ds:
                lat_dim, lon_dim, lat_idx, lon_idx = _get_grid_idx(ds)
            _extract_one_nc(src_path, dst_path, lat_idx, lon_idx, lat_dim, lon_dim)
            print(f"{prefix} → 완료")
            written += 1
        except Exception as exc:
            print(f"{prefix} → 실패: {exc}")
            failed.append(src_path.name)
            if dst_path.exists():
                try:
                    dst_path.unlink()  # 불완전한 파일 제거
                except Exception:
                    pass  # 다른 프로세스가 점유 중이면 무시

    print(
        f"\n  완료: {written}개 저장 | {skipped}개 건너뜀"
        + (f" | {len(failed)}개 실패" if failed else "")
    )
    if failed:
        print("  실패 목록:", failed)

    return {"written": written, "skipped": skipped, "failed": len(failed)}
