"""GIS 자료 좌표계 + 폴더 컨벤션 유틸리티.

폴더 규약
---------
canonical 자료     :  ``{gis_root}/{data_type}/{data_type}.{ext}``
재투영 사본        :  ``{gis_root}/{data_type}/{data_type}-epsg{N}.{ext}``

기본 EPSG 는 4326 (WGS84 위경도, 수집 원본). SWAT 처럼 평면 좌표가 필요한
워크플로우는 :func:`auto_utm_epsg` 로 적합한 UTM zone 을 산출하고
:func:`reproject_to_utm` 으로 재투영 사본을 생성합니다.

CRS 의 단일 진실 원천은 파일 메타데이터(.prj, GeoTIFF tag, GeoPackage 레이어).
파일명 ``-epsg{N}`` suffix 는 사람이 즉시 알아보기 위한 보조 표시일 뿐입니다.

UTM zone 공식
-------------
::

    zone = floor((longitude + 180) / 6) + 1     # 1 ~ 60
    EPSG = 32600 + zone   (북반구, lat ≥ 0)
         = 32700 + zone   (남반구, lat <  0)

예시
----
>>> auto_utm_epsg(lon=-159.8, lat=-21.2)   # Rarotonga (Cook Islands)
32704
>>> auto_utm_epsg(lon=127.0, lat=37.5)     # 서울
32652
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Tuple, Union

import pandas as pd


# 확장자 우선순위 (canonical 파일 자동 검색 시)
_EXT_PRIORITY = {".shp": 1, ".gpkg": 2, ".tif": 3, ".tiff": 3,
                 ".geojson": 4, ".csv": 5, ".nc": 6}


# ── 1. UTM EPSG 자동 산출 ────────────────────────────────────────────────────

def auto_utm_epsg(
    lon: Optional[float] = None,
    lat: Optional[float] = None,
    *,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    boundary_csv: Optional[str] = None,
) -> int:
    """위경도 점 또는 bbox 중심으로부터 UTM zone EPSG 산출.

    Parameters
    ----------
    lon, lat     : 단일 점 (deg)
    bbox         : (xmin, ymin, xmax, ymax) — 중심을 사용
    boundary_csv : country_boundary.csv 경로 — 첫 행 bbox 중심을 사용

    셋 중 정확히 하나만 지정해야 합니다.

    Returns
    -------
    int : EPSG 코드 (32600+zone 북반구 / 32700+zone 남반구)

    Raises
    ------
    ValueError : 입력이 없거나 둘 이상 동시에 지정한 경우
    """
    sources = sum(x is not None for x in
                  [lon if lon is not None else None, bbox, boundary_csv])
    if sources != 1 and not (lon is not None and lat is not None
                             and bbox is None and boundary_csv is None):
        # (lon, lat) 한 쌍은 단일 입력으로 간주
        if not (lon is not None and lat is not None):
            raise ValueError(
                "정확히 하나 지정: (lon, lat) | bbox | boundary_csv"
            )

    if boundary_csv is not None:
        df = pd.read_csv(boundary_csv)
        if df.empty:
            raise ValueError(f"빈 boundary CSV: {boundary_csv}")
        row = df.iloc[0]
        for col in ("xmin", "ymin", "xmax", "ymax"):
            if col not in df.columns:
                raise ValueError(f"boundary CSV 에 {col} 컬럼 없음")
        bbox = (float(row["xmin"]), float(row["ymin"]),
                float(row["xmax"]), float(row["ymax"]))

    if bbox is not None:
        xmin, ymin, xmax, ymax = bbox
        lon = (xmin + xmax) / 2
        lat = (ymin + ymax) / 2

    if lon is None or lat is None:
        raise ValueError("lon, lat 모두 필요합니다.")

    # 경도를 -180 ~ 180 으로 정규화
    lon_n = ((lon + 180.0) % 360.0) - 180.0

    zone = int(math.floor((lon_n + 180.0) / 6.0) + 1)
    zone = max(1, min(60, zone))

    return (32700 if lat < 0 else 32600) + zone


# ── 2. 경로 규약 ─────────────────────────────────────────────────────────────

def gis_canonical_path(
    gis_root: Union[str, Path],
    data_type: str,
    ext: Optional[str] = None,
    name: Optional[str] = None,
) -> Path:
    """canonical GIS 파일 경로.

    규약: ``{gis_root}/{data_type}/{name or data_type}.{ext}``

    대부분의 데이터 타입은 폴더명과 파일명이 동일 (boundary/boundary.shp).
    설명적 파일명이 필요한 경우 ``name`` 으로 stem 지정
    (예: era5 폴더 안의 ``grid_points-era5.shp``).

    ``ext`` 가 None 이면 폴더에서 ``{stem}.*`` 패턴 검색
    (suffix ``-epsg{N}`` 가 붙은 사본은 제외).

    Parameters
    ----------
    gis_root  : GIS 루트 (예: ``0_database/gis``)
    data_type : 자료 종류 폴더명 (boundary, dem, landuse, soil, era5 등)
    ext       : 확장자 (".shp" 또는 "shp" 모두 허용)
    name      : 파일명 stem (None → data_type 사용)

    Examples
    --------
    >>> gis_canonical_path("/gis", "boundary", ext="shp")
    PosixPath('/gis/boundary/boundary.shp')
    >>> gis_canonical_path("/gis", "era5", ext="shp", name="grid_points-era5")
    PosixPath('/gis/era5/grid_points-era5.shp')
    """
    folder = Path(gis_root) / data_type
    stem = name if name is not None else data_type

    if ext is not None:
        return folder / f"{stem}.{ext.lstrip('.')}"

    if not folder.is_dir():
        raise FileNotFoundError(f"디렉토리 없음: {folder}")

    candidates = [
        p for p in folder.iterdir()
        if p.is_file() and p.stem == stem
    ]
    if not candidates:
        raise FileNotFoundError(
            f"canonical 파일 없음: {folder}/{stem}.*"
        )
    candidates.sort(key=lambda p: _EXT_PRIORITY.get(p.suffix.lower(), 99))
    return candidates[0]


def gis_reprojected_path(
    gis_root: Union[str, Path],
    data_type: str,
    epsg: int,
    ext: Optional[str] = None,
    name: Optional[str] = None,
) -> Path:
    """재투영 사본 파일 경로.

    규약: ``{gis_root}/{data_type}/{name or data_type}-epsg{N}.{ext}``

    ``ext`` 가 None 이면 canonical 파일에서 자동 추론.
    ``name`` 은 :func:`gis_canonical_path` 와 동일한 의미.
    """
    stem = name if name is not None else data_type
    if ext is None:
        ext = gis_canonical_path(gis_root, data_type, name=name).suffix.lstrip(".")
    return Path(gis_root) / data_type / f"{stem}-epsg{epsg}.{ext.lstrip('.')}"


# ── 3. 재투영 ────────────────────────────────────────────────────────────────

def reproject_to_utm(
    input_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    target_epsg: Optional[int] = None,
) -> Path:
    """벡터 GIS 파일을 UTM(또는 지정 EPSG)으로 재투영하여 저장.

    벡터 형식만 지원 (.shp, .gpkg, .geojson). 래스터(.tif, .nc)는 GDAL CLI 사용 권장.

    Parameters
    ----------
    input_path  : 입력 (canonical 권장)
    output_path : 출력 경로 (None → 같은 폴더에 ``-epsg{N}`` suffix 자동)
    target_epsg : 목표 EPSG (None → 입력 bbox 중심으로 :func:`auto_utm_epsg`)

    Returns
    -------
    Path : 저장된 재투영 파일 경로
    """
    try:
        import geopandas as gpd
    except ImportError as e:
        raise ImportError(
            "geopandas 가 필요합니다 (pip install geopandas)"
        ) from e

    in_path = Path(input_path)
    if not in_path.is_file():
        raise FileNotFoundError(f"입력 없음: {in_path}")

    if in_path.suffix.lower() in {".tif", ".tiff", ".nc"}:
        raise NotImplementedError(
            f"래스터는 :func:`reproject_raster` 사용. (입력: {in_path})"
        )

    gdf = gpd.read_file(in_path)
    if gdf.crs is None:
        raise ValueError(f"입력에 CRS 메타가 없음 (.prj 누락 등): {in_path}")

    if target_epsg is None:
        bounds = gdf.to_crs("EPSG:4326").total_bounds  # (xmin, ymin, xmax, ymax)
        target_epsg = auto_utm_epsg(bbox=tuple(bounds))

    if output_path is None:
        output_path = in_path.parent / f"{in_path.stem}-epsg{target_epsg}{in_path.suffix}"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    gdf.to_crs(epsg=target_epsg).to_file(output_path)
    return output_path


# ── 4. 래스터 클립 / 재투영 / SWAT 준비 ──────────────────────────────────────

# resampling 메소드 매핑 (rasterio.enums.Resampling 와 매칭)
_RESAMPLING = {
    "nearest":  "nearest",   # 범주형 (LULC, soil class)
    "bilinear": "bilinear",  # 연속 (DEM, 기온)
    "cubic":    "cubic",
    "average":  "average",
}


def clip_raster(
    src_path: Union[str, Path],
    output_path: Union[str, Path],
    *,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    boundary_path: Optional[Union[str, Path]] = None,
    buffer_deg: float = 0.0,
) -> Path:
    """래스터를 bbox 또는 boundary 폴리곤으로 클립.

    Parameters
    ----------
    src_path      : 입력 raster (예: dem.tif)
    output_path   : 출력 raster
    bbox          : (xmin, ymin, xmax, ymax) — 직사각형 클립
    boundary_path : 폴리곤 shapefile — 정밀 클립 (geometry mask)
    buffer_deg    : 버퍼 (도). bbox 는 외측 확장, 폴리곤은 geometry buffer.

    bbox 와 boundary_path 중 하나는 필수. 둘 다 주어지면 boundary_path 우선.

    Returns
    -------
    Path : 클립된 raster 경로
    """
    try:
        import rasterio
        from rasterio.mask import mask as rmask
        from rasterio.windows import from_bounds
    except ImportError as e:
        raise ImportError("rasterio 필요 (pip install rasterio)") from e

    if bbox is None and boundary_path is None:
        raise ValueError("bbox 또는 boundary_path 중 하나 필수")

    src_path = Path(src_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(src_path) as src:
        if boundary_path is not None:
            import geopandas as gpd
            gdf = gpd.read_file(boundary_path)
            if gdf.crs is None:
                raise ValueError(f"boundary 에 CRS 없음: {boundary_path}")
            if gdf.crs.to_epsg() != src.crs.to_epsg():
                gdf = gdf.to_crs(src.crs)

            if buffer_deg > 0:
                # 정확한 buffer 를 위해 UTM 으로 일시 재투영 (도 단위 buffer 는
                # 위도에 따라 거리 왜곡이 큼). 1° ≈ 111 km 환산.
                if gdf.crs.is_geographic:
                    bounds = tuple(gdf.total_bounds)
                    utm_epsg = auto_utm_epsg(bbox=bounds)
                    buffer_m = buffer_deg * 111_000.0
                    gdf_buf = (gdf.to_crs(epsg=utm_epsg)
                                  .buffer(buffer_m)
                                  .to_crs(gdf.crs))
                    geoms = gdf_buf
                else:
                    geoms = gdf.geometry.buffer(buffer_deg)
            else:
                geoms = gdf.geometry

            out_image, out_transform = rmask(
                src, list(geoms), crop=True, all_touched=True,
            )
        else:
            xmin, ymin, xmax, ymax = bbox  # type: ignore[misc]
            if buffer_deg > 0:
                xmin -= buffer_deg; ymin -= buffer_deg
                xmax += buffer_deg; ymax += buffer_deg
            window = from_bounds(xmin, ymin, xmax, ymax, src.transform)
            out_image = src.read(window=window)
            out_transform = src.window_transform(window)

        meta = src.meta.copy()
        meta.update({
            "driver":    "GTiff",
            "height":    out_image.shape[1],
            "width":     out_image.shape[2],
            "transform": out_transform,
            "compress":  "lzw",
        })
        with rasterio.open(output_path, "w", **meta) as dst:
            dst.write(out_image)

    return output_path


def reproject_raster(
    src_path: Union[str, Path],
    output_path: Union[str, Path],
    target_epsg: int,
    *,
    resampling: str = "bilinear",
    target_resolution: Optional[float] = None,
) -> Path:
    """래스터를 target_epsg 로 재투영.

    Parameters
    ----------
    src_path          : 입력 raster
    output_path       : 출력 raster
    target_epsg       : 목표 EPSG (예: 32704)
    resampling        : nearest | bilinear | cubic | average.
                        LULC 등 범주형은 반드시 ``"nearest"``.
    target_resolution : 목표 픽셀 크기 (target CRS 단위, 보통 m).
                        None 이면 자동 (기존 해상도와 등가).

    Returns
    -------
    Path : 재투영된 raster 경로
    """
    try:
        import rasterio
        from rasterio.warp import (
            Resampling as _Resampling,
            calculate_default_transform,
            reproject,
        )
    except ImportError as e:
        raise ImportError("rasterio 필요 (pip install rasterio)") from e

    if resampling not in _RESAMPLING:
        raise ValueError(f"resampling 은 {list(_RESAMPLING)} 중 하나여야 함")
    method = getattr(_Resampling, _RESAMPLING[resampling])

    src_path = Path(src_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target_crs = f"EPSG:{target_epsg}"

    with rasterio.open(src_path) as src:
        kwargs = dict(src_crs=src.crs, dst_crs=target_crs,
                      width=src.width, height=src.height, left=src.bounds.left,
                      bottom=src.bounds.bottom, right=src.bounds.right,
                      top=src.bounds.top)
        if target_resolution is not None:
            kwargs["resolution"] = target_resolution
        transform, width, height = calculate_default_transform(**kwargs)

        meta = src.meta.copy()
        meta.update({
            "crs":       target_crs,
            "transform": transform,
            "width":     width,
            "height":    height,
            "compress":  "lzw",
        })
        with rasterio.open(output_path, "w", **meta) as dst:
            for band in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, band),
                    destination=rasterio.band(dst, band),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    resampling=method,
                )

    return output_path


def prepare_raster_for_swat(
    src_path: Union[str, Path],
    boundary_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    *,
    buffer_deg: float = 0.05,
    target_epsg: Optional[int] = None,
    resampling: str = "bilinear",
    keep_intermediate: bool = False,
) -> Path:
    """SWAT 용 래스터 준비: boundary 로 클립 (+ 버퍼) → UTM 재투영 (선택).

    워크플로우
    ----------
    1. ``boundary_path`` 폴리곤 + ``buffer_deg`` 외측 확장으로 클립
    2. ``target_epsg`` 가 주어지면 해당 EPSG 로 재투영 (보통 UTM)
    3. 임시 클립 결과는 자동 삭제 (``keep_intermediate=True`` 면 보존)

    Parameters
    ----------
    src_path          : canonical raster (예: dem.tif, landuse.tif)
    boundary_path     : 폴리곤 shapefile (보통 ``gis/boundary/boundary.shp``)
    output_path       : 출력 경로
                        None 이면 ``{src_dir}/{stem}-epsg{N}.tif`` (재투영 시)
                                또는 ``{src_dir}/{stem}-clip.tif`` (재투영 생략 시)
    buffer_deg        : boundary 외측 버퍼 (도). SWAT 변두리 셀 안전 여유.
                        30m DEM 기준 0.05° ≈ 5.5 km ≈ 180 픽셀.
    target_epsg       : SWAT 평면 좌표계 EPSG. None 이면 재투영 생략.
    resampling        : DEM 등 연속 → ``"bilinear"`` (기본).
                        LULC 등 범주 → ``"nearest"`` 필수.
    keep_intermediate : True 면 클립만 한 중간 파일도 별도 저장.

    Returns
    -------
    Path : 최종 SWAT-ready raster 경로
    """
    src_path = Path(src_path)

    if output_path is None:
        suffix = f"-epsg{target_epsg}" if target_epsg else "-clip"
        output_path = src_path.parent / f"{src_path.stem}{suffix}{src_path.suffix}"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if target_epsg is None:
        return clip_raster(src_path, output_path,
                           boundary_path=boundary_path, buffer_deg=buffer_deg)

    if keep_intermediate:
        clip_path = src_path.parent / f"{src_path.stem}-clip{src_path.suffix}"
        clip_raster(src_path, clip_path,
                    boundary_path=boundary_path, buffer_deg=buffer_deg)
        reproject_raster(clip_path, output_path, target_epsg, resampling=resampling)
    else:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=src_path.suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            clip_raster(src_path, tmp_path,
                        boundary_path=boundary_path, buffer_deg=buffer_deg)
            reproject_raster(tmp_path, output_path, target_epsg,
                             resampling=resampling)
        finally:
            tmp_path.unlink(missing_ok=True)

    return output_path
