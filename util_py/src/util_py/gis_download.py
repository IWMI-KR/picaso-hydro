"""SWAT 모델링 입력 자료 자동 다운로드 (글로벌 공개 소스).

데이터 소스 (모두 무료, 무인증)
-------------------------------
DEM      : Copernicus GLO-30 (AWS S3)               — 30 m, 1°×1° tile
ADMIN    : GADM v4.1 (UC Davis)                     — ~1:50,000, ISO3 단위
SOIL     : ISRIC SoilGrids 250m (OGC WCS)           — 250 m, sand/silt/clay × 깊이
LANDUSE  : ESA WorldCover 2021 v200 (AWS S3)        — 10 m, 3°×3° tile
BASIN    : HydroSHEDS HydroBASINS lev12             — 15"  (~500 m), Pfafstetter
RIVER    : HydroSHEDS HydroRIVERS v10               — 3"   (~100 m)

각 함수는 boundary_csv (또는 직접 bbox/iso3) 로부터 영역을 추출해
``{gis.root}/{type}/`` 하위에 canonical 파일명으로 저장합니다.

라이선스 주의
-------------
- HydroSHEDS: 학술 비상업적 사용은 자유, 출처 인용 필수.
  https://www.hydrosheds.org/page/license
- ESA WorldCover: CC BY 4.0
- GADM: 학술/개인 사용 자유, 상업적 사용 별도 허가
- Copernicus DEM: 자유 재배포 (출처 인용)
- SoilGrids: CC BY 4.0
"""

from __future__ import annotations

import math
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

import pandas as pd

# ── ESA WorldCover 2021 v200 클래스 분류 + SWAT 매핑 ────────────────────────
# https://esa-worldcover.org/en/data-access  (v200 Product User Manual)
# SWAT-Plus 표준 land use code 매핑.
WORLDCOVER_LOOKUP: List[Dict[str, object]] = [
    {"val":  10, "description": "Tree cover",                  "SWAT_LU_Code": "FRST"},
    {"val":  20, "description": "Shrubland",                   "SWAT_LU_Code": "RNGB"},
    {"val":  30, "description": "Grassland",                   "SWAT_LU_Code": "RNGE"},
    {"val":  40, "description": "Cropland",                    "SWAT_LU_Code": "AGRL"},
    {"val":  50, "description": "Built-up",                    "SWAT_LU_Code": "URBN"},
    {"val":  60, "description": "Bare / sparse vegetation",    "SWAT_LU_Code": "BARR"},
    {"val":  70, "description": "Snow and ice",                "SWAT_LU_Code": "SNOW"},
    {"val":  80, "description": "Permanent water bodies",      "SWAT_LU_Code": "WATR"},
    {"val":  90, "description": "Herbaceous wetland",          "SWAT_LU_Code": "WETN"},
    {"val":  95, "description": "Mangroves",                   "SWAT_LU_Code": "WETF"},
    {"val": 100, "description": "Moss and lichen",             "SWAT_LU_Code": "RNGE"},
]


# ── 래스터 mosaic (rasterio) ─────────────────────────────────────────────────

def _merge_rasters(tile_paths: List[Path], output_path: Path,
                   compress: str = "lzw") -> Optional[Path]:
    """여러 GeoTIFF tile 을 단일 파일로 mosaic.

    Parameters
    ----------
    tile_paths : merge 할 tile 파일 경로 목록
    output_path: 저장 경로 (디렉토리 자동 생성)
    compress   : LZW (기본, 무손실) | DEFLATE | NONE

    Returns
    -------
    Path | None : 저장 경로 (tile 0개면 None)
    """
    if not tile_paths:
        return None
    try:
        import rasterio
        from rasterio.merge import merge
    except ImportError as e:
        raise ImportError(
            "rasterio 가 필요합니다 (pip install rasterio)"
        ) from e

    output_path.parent.mkdir(parents=True, exist_ok=True)

    srcs = [rasterio.open(p) for p in tile_paths]
    try:
        mosaic, transform = merge(srcs)
        meta = srcs[0].meta.copy()
        meta.update({
            "driver":    "GTiff",
            "height":    mosaic.shape[1],
            "width":     mosaic.shape[2],
            "transform": transform,
            "compress":  compress,
        })
        with rasterio.open(output_path, "w", **meta) as dst:
            dst.write(mosaic)
    finally:
        for s in srcs:
            s.close()
    return output_path


def write_worldcover_lookup(output_csv: Union[str, Path]) -> Path:
    """ESA WorldCover 분류 lookup table 을 CSV로 저장.

    컬럼: ``val, description, SWAT_LU_Code``
    """
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(WORLDCOVER_LOOKUP).to_csv(output_csv, index=False)
    return output_csv

# ── 공통 타입 ────────────────────────────────────────────────────────────────

BBox = Tuple[float, float, float, float]   # (xmin, ymin, xmax, ymax)


# ── boundary_csv 파싱 ────────────────────────────────────────────────────────

def _read_bbox_iso(boundary_csv: str) -> Tuple[BBox, str, str, str]:
    """boundary_csv → (bbox, ISO2, ISO3, NAME)."""
    df = pd.read_csv(boundary_csv)
    if df.empty:
        raise ValueError(f"빈 boundary CSV: {boundary_csv}")
    row = df.iloc[0]
    return (
        (float(row["xmin"]), float(row["ymin"]),
         float(row["xmax"]), float(row["ymax"])),
        str(row.get("ISO2", "")).strip().upper(),
        str(row.get("ISO3", "")).strip().upper(),
        str(row.get("NAME", "")),
    )


# ── HTTP / ZIP 헬퍼 ──────────────────────────────────────────────────────────

def _http_download(url: str, dest: Path,
                   timeout: int = 600,
                   show_progress: bool = True) -> Path:
    """URL → 파일 다운로드 (스트리밍, 진행률 출력)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "util_py-gis-download/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            with dest.open("wb") as f:
                downloaded = 0
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if show_progress and total > 0:
                        pct = 100 * downloaded / total
                        print(f"\r    {dest.name}  "
                              f"{downloaded/1e6:6.1f} / {total/1e6:6.1f} MB  "
                              f"({pct:5.1f}%)", end="", flush=True)
        if show_progress:
            print()
    except urllib.error.HTTPError as e:
        if dest.exists():
            dest.unlink()
        raise RuntimeError(f"HTTP {e.code} {url}") from e
    return dest


def _extract_zip_renamed(
    zip_path: Path,
    out_dir: Path,
    src_basename: str,
    dst_basename: str,
) -> List[Path]:
    """ZIP에서 ``{src_basename}.*`` 파일들을 추출하면서 ``{dst_basename}.*`` 로 재명명."""
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: List[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if Path(name).stem != src_basename:
                continue
            if name.endswith("/"):
                continue
            ext = Path(name).suffix
            dst = out_dir / f"{dst_basename}{ext}"
            with zf.open(name) as src, dst.open("wb") as out:
                shutil.copyfileobj(src, out)
            extracted.append(dst)
    if not extracted:
        raise RuntimeError(f"ZIP에 {src_basename}.* 가 없음: {zip_path}")
    return extracted


# ── HydroSHEDS region 자동 매핑 ──────────────────────────────────────────────

# 대륙별 bbox 목록 (lon_min, lat_min, lon_max, lat_max).
# 한 region 이 안티메리디안을 가로지르는 경우(au) 두 개의 bbox 로 표현.
# HydroSHEDS 공식 region: af, ar, as, au, eu, gr, na, sa, si
_HYDROSHEDS_REGIONS: List[Tuple[str, List[BBox]]] = [
    ("au", [(89, -50, 180, 5),       # Australasia: 호주, NZ, 뉴기니, 인도네시아
            (-180, -50, -130, 5)]),  # + Pacific 동부(Cook Islands, Samoa, French Polynesia)
    ("eu", [(-25, 35, 60, 75)]),     # Europe
    ("af", [(-20, -35, 55, 38)]),    # Africa
    ("as", [(25, -10, 180, 60)]),    # Asia (광역)
    ("na", [(-180, 5, -50, 60)]),    # North America (Mexico-Alaska)
    ("sa", [(-90, -60, -30, 15)]),   # South America
    ("ar", [(-180, 60, 180, 90)]),   # Arctic
]


def bbox_to_hydrosheds_region(bbox: BBox) -> str:
    """bbox 중심점이 속하는 HydroSHEDS region 코드 반환.

    "au" 는 안티메리디안을 가로지르므로 두 개의 bbox 로 정의 (호주측 + Pacific 동부).
    경계 영역에서는 가장 가까운 region 을 선택. 자동 판정이 부정확하면
    ``region`` 인자를 직접 지정하세요.
    """
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2

    for region, regions_bboxes in _HYDROSHEDS_REGIONS:
        for (xmin, ymin, xmax, ymax) in regions_bboxes:
            if xmin <= cx <= xmax and ymin <= cy <= ymax:
                return region

    # fallback: 가장 가까운 region (모든 sub-bbox 중 최소 거리)
    best, best_dist = None, float("inf")
    for region, regions_bboxes in _HYDROSHEDS_REGIONS:
        for (xmin, ymin, xmax, ymax) in regions_bboxes:
            rx = max(xmin, min(cx, xmax))
            ry = max(ymin, min(cy, ymax))
            dist = math.hypot(cx - rx, cy - ry)
            if dist < best_dist:
                best, best_dist = region, dist
    return best or "au"


# ── DEM tile 좌표 산출 (Copernicus GLO-30) ──────────────────────────────────

def _lat_to_tile_str(lat: int) -> str:
    return f"S{abs(lat):02d}" if lat < 0 else f"N{lat:02d}"


def _lon_to_tile_str(lon: int) -> str:
    return f"W{abs(lon):03d}" if lon < 0 else f"E{lon:03d}"


def bbox_to_dem_tiles(bbox: BBox) -> List[Tuple[int, int]]:
    """bbox 가 교차하는 1°×1° DEM tile 의 (lat_floor, lon_floor) 목록."""
    xmin, ymin, xmax, ymax = bbox
    lat_lo = math.floor(ymin)
    lat_hi = math.ceil(ymax)
    lon_lo = math.floor(xmin)
    lon_hi = math.ceil(xmax)
    return [(lat, lon)
            for lat in range(lat_lo, lat_hi)       # tile 좌표는 SW 코너
            for lon in range(lon_lo, lon_hi)]


# ── ESA WorldCover tile 좌표 산출 (3°×3°, 3°단위 정렬) ─────────────────────

def bbox_to_worldcover_tiles(bbox: BBox) -> List[str]:
    """bbox 가 교차하는 ESA WorldCover 3°×3° tile 코드 목록 (예: 'S21W162')."""
    xmin, ymin, xmax, ymax = bbox
    # 3°단위 정렬: floor(v / 3) * 3
    lat_lo = math.floor(ymin / 3) * 3
    lat_hi = math.ceil(ymax / 3) * 3
    lon_lo = math.floor(xmin / 3) * 3
    lon_hi = math.ceil(xmax / 3) * 3
    tiles = []
    for lat in range(lat_lo, lat_hi, 3):
        for lon in range(lon_lo, lon_hi, 3):
            tiles.append(_lat_to_tile_str(lat) + _lon_to_tile_str(lon))
    return tiles


# ── 1. GADM 행정구역 ─────────────────────────────────────────────────────────

def download_gadm(
    iso3: str,
    gis_root: Union[str, Path],
    level: int = 0,
    url_template: Optional[str] = None,
) -> Path:
    """GADM v4.1 행정구역 shapefile 다운로드.

    Parameters
    ----------
    iso3      : 3자 ISO 국가코드 (예: COK)
    gis_root  : GIS 루트 (예: 0_database/gis)
    level     : 행정 레벨 (0=국가, 1=주, 2=시도, ...). 국가별 최대 깊이 다름.
    url_template : URL 패턴 오버라이드 (생략 시 GADM 4.1 기본).

    Returns
    -------
    Path : ``{gis_root}/admin/admin.shp``
    """
    iso3 = iso3.upper()
    url_template = url_template or "https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_{iso3}_shp.zip"
    url = url_template.format(iso3=iso3)

    out_dir = Path(gis_root) / "admin"
    print(f"  [GADM]    {iso3} level={level}")
    print(f"            ← {url}")

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _http_download(url, tmp_path)
        # ZIP 안: gadm41_{iso3}_{level}.shp 등
        src = f"gadm41_{iso3}_{level}"
        out_files = _extract_zip_renamed(tmp_path, out_dir, src, "admin")
        print(f"            저장: {[f.name for f in out_files]}")
    finally:
        tmp_path.unlink(missing_ok=True)

    return out_dir / "admin.shp"


# ── 2. HydroSHEDS HydroBASINS ───────────────────────────────────────────────

def download_hydrobasins(
    gis_root: Union[str, Path],
    bbox: Optional[BBox] = None,
    region: Optional[str] = None,
    level: int = 12,
    url_template: Optional[str] = None,
    keep_continental: bool = False,
) -> Optional[Path]:
    """HydroSHEDS HydroBASINS 대륙 ZIP 다운로드 → bbox 클리핑 → ``basin.shp``.

    클리핑 결과가 0 feature 면 (예: 소형 도서국 — Cook Islands 등) **파일 저장 안 함**.

    Parameters
    ----------
    gis_root         : GIS 루트
    bbox             : (xmin, ymin, xmax, ymax) — 클리핑 + region 자동 판정용
    region           : HydroSHEDS region (au/as/eu/na/sa/af/ar) — None 이면 bbox 로 자동
    level            : 1~12 (12 가 최세분, ~10 km² 단위)
    keep_continental : True 면 대륙 원본 shp 도 별도 보관

    Returns
    -------
    Path | None : 저장 경로 (자료 없으면 ``None``)
    """
    if region is None and bbox is None:
        raise ValueError("region 또는 bbox 중 하나는 필수")
    if region is None:
        region = bbox_to_hydrosheds_region(bbox)  # type: ignore[arg-type]

    url_template = url_template or "https://data.hydrosheds.org/file/HydroBASINS/standard/hybas_{region}_lev{level}_v1c.zip"
    url = url_template.format(region=region, level=f"{level:02d}")

    out_dir = Path(gis_root) / "basin"
    print(f"  [BASIN]   region={region} level={level}")
    print(f"            ← {url}")

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _http_download(url, tmp_path)
        src = f"hybas_{region}_lev{level:02d}_v1c"
        # 대륙 전체 shp 추출 (임시)
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            extracted = _extract_zip_renamed(tmp_path, td_path, src, src)

            saved_path: Optional[Path] = None
            if bbox is None:
                out_dir.mkdir(parents=True, exist_ok=True)
                for f in extracted:
                    shutil.copy2(f, out_dir / f"basin{f.suffix}")
                print(f"            저장 (전체): {sum(f.stat().st_size for f in extracted)/1e6:.1f} MB")
                saved_path = out_dir / "basin.shp"
            else:
                clipped = _clip_vector_to_bbox(td_path / f"{src}.shp",
                                                out_dir / "basin.shp", bbox)
                if clipped is None:
                    print(f"            [정보] 클리핑 결과 0 feature → 파일 저장 안 함.")
                    print(f"            → 해당 지역에 HydroBASINS 자료가 없을 수 있음.")
                    print(f"            → 소형 도서국은 DEM 으로부터 QSWAT 위계 추출 권장.")
                else:
                    print(f"            클리핑 저장: basin.shp")
                    saved_path = clipped

            if keep_continental:
                cont_dir = out_dir / "continental"
                cont_dir.mkdir(parents=True, exist_ok=True)
                for f in extracted:
                    shutil.copy2(f, cont_dir / f.name)
                print(f"            대륙 원본 보관: {cont_dir}")
    finally:
        tmp_path.unlink(missing_ok=True)

    return saved_path


# ── 3. HydroSHEDS HydroRIVERS ───────────────────────────────────────────────

def download_hydrorivers(
    gis_root: Union[str, Path],
    bbox: Optional[BBox] = None,
    region: Optional[str] = None,
    url_template: Optional[str] = None,
    keep_continental: bool = False,
) -> Optional[Path]:
    """HydroSHEDS HydroRIVERS 다운로드 → bbox 클리핑 → ``river.shp``.

    클리핑 결과가 0 feature 면 **파일 저장 안 함** (None 반환).
    """
    if region is None and bbox is None:
        raise ValueError("region 또는 bbox 중 하나는 필수")
    if region is None:
        region = bbox_to_hydrosheds_region(bbox)  # type: ignore[arg-type]

    url_template = url_template or "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_{region}_shp.zip"
    url = url_template.format(region=region)

    out_dir = Path(gis_root) / "river"
    print(f"  [RIVER]   region={region}")
    print(f"            ← {url}")

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _http_download(url, tmp_path)
        src = f"HydroRIVERS_v10_{region}"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            extracted = _extract_zip_renamed(tmp_path, td_path, src, src)

            saved_path: Optional[Path] = None
            if bbox is None:
                out_dir.mkdir(parents=True, exist_ok=True)
                for f in extracted:
                    shutil.copy2(f, out_dir / f"river{f.suffix}")
                saved_path = out_dir / "river.shp"
            else:
                clipped = _clip_vector_to_bbox(td_path / f"{src}.shp",
                                                out_dir / "river.shp", bbox)
                if clipped is None:
                    print(f"            [정보] 클리핑 결과 0 feature → 파일 저장 안 함.")
                    print(f"            → 해당 지역에 HydroRIVERS 자료가 없을 수 있음.")
                    print(f"            → DEM 기반 하천망 추출(QSWAT) 권장.")
                else:
                    print(f"            클리핑 저장: river.shp")
                    saved_path = clipped

            if keep_continental:
                cont_dir = out_dir / "continental"
                cont_dir.mkdir(parents=True, exist_ok=True)
                for f in extracted:
                    shutil.copy2(f, cont_dir / f.name)
    finally:
        tmp_path.unlink(missing_ok=True)

    return saved_path


# ── 벡터 클리핑 (geopandas) ──────────────────────────────────────────────────

def _clip_vector_to_bbox(
    src_shp: Path,
    dst_shp: Path,
    bbox: BBox,
    buffer_deg: float = 0.0,
) -> Optional[Path]:
    """src_shp 를 bbox 로 클리핑하여 dst_shp 저장.

    Returns
    -------
    Path | None : 저장된 파일 경로. 클리핑 결과가 0 feature 면 ``None``
                  (빈 .shp 파일을 만들지 않음).
    """
    import geopandas as gpd

    xmin, ymin, xmax, ymax = bbox
    if buffer_deg > 0:
        xmin -= buffer_deg; ymin -= buffer_deg
        xmax += buffer_deg; ymax += buffer_deg
    gdf = gpd.read_file(src_shp, bbox=(xmin, ymin, xmax, ymax))
    if gdf.empty:
        return None
    dst_shp.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(dst_shp)
    return dst_shp


# ── 4. Copernicus DEM (1°×1° tile) ──────────────────────────────────────────

def download_dem(
    gis_root: Union[str, Path],
    bbox: BBox,
    url_template: Optional[str] = None,
    merge: bool = True,
) -> Path:
    """Copernicus GLO-30 DEM 의 bbox 영역 1°×1° tile 다운로드 + mosaic.

    파일 배치
    ----------
    개별 tile : ``{gis_root}/dem/download/dem_{lat_str}_{lon_str}.tif``
    병합본    : ``{gis_root}/dem/dem.tif``  (canonical)

    바다만 있는 tile 은 404 가 나며 건너뜁니다.
    merge=False 면 mosaic 생략 (개별 tile 만 보존).

    Returns
    -------
    Path : 병합본 dem.tif 경로 (merge=False 면 download/ 폴더 경로)
    """
    url_template = url_template or "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif"
    out_dir   = Path(gis_root) / "dem"
    tile_dir  = out_dir / "download"
    merged    = out_dir / "dem.tif"

    tiles = bbox_to_dem_tiles(bbox)
    print(f"  [DEM]     bbox tile 수: {len(tiles)} (Copernicus GLO-30 1°×1°)")

    saved: List[Path] = []
    skipped = 0
    for lat, lon in tiles:
        lat_s = _lat_to_tile_str(lat)
        lon_s = _lon_to_tile_str(lon)
        url = url_template.format(lat=lat_s, lon=lon_s)
        out = tile_dir / f"dem_{lat_s}_{lon_s}.tif"
        if out.exists() and out.stat().st_size > 0:
            saved.append(out)
            continue
        try:
            _http_download(url, out, show_progress=False)
            print(f"    [OK]   {out.name}  ({out.stat().st_size/1e6:.1f} MB)")
            saved.append(out)
        except RuntimeError as e:
            if "404" in str(e):
                skipped += 1
            else:
                print(f"    [WARN] {out.name}: {e}")

    print(f"  [DEM]     download/ 에 {len(saved)}개 tile, {skipped}개 건너뜀 (해양)")

    if merge and saved:
        try:
            _merge_rasters(saved, merged)
            mb = merged.stat().st_size / 1e6
            print(f"  [DEM]     mosaic 저장: {merged.name}  ({mb:.1f} MB)")
        except Exception as e:
            print(f"  [WARN]    mosaic 실패: {e}")
            return tile_dir
        return merged
    return tile_dir if not saved else merged


# ── 5. ISRIC SoilGrids 250m (WCS) ────────────────────────────────────────────

# SoilGrids 속성별 권장 layer name
_SOILGRIDS_DEPTHS = ["0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm"]


def download_soilgrids(
    gis_root: Union[str, Path],
    bbox: BBox,
    properties: Optional[List[str]] = None,
    depth: str = "0-5cm",
    wcs_url: str = "https://maps.isric.org/mapserv",
) -> List[Path]:
    """ISRIC SoilGrids 250m 토양 속성을 WCS 로 bbox 영역만 다운로드.

    Parameters
    ----------
    properties : sand, silt, clay, soc, bdod, cec, nitrogen, phh2o 등
                 (기본 = sand/silt/clay)
    depth      : 0-5cm | 5-15cm | 15-30cm | 30-60cm | 60-100cm | 100-200cm

    각 속성은 ``{gis_root}/soil/soil_{property}_{depth}.tif`` 로 저장.
    """
    if depth not in _SOILGRIDS_DEPTHS:
        raise ValueError(f"depth 는 {_SOILGRIDS_DEPTHS} 중 하나여야 함")
    properties = properties or ["sand", "silt", "clay"]

    out_dir = Path(gis_root) / "soil"
    out_dir.mkdir(parents=True, exist_ok=True)
    xmin, ymin, xmax, ymax = bbox
    saved: List[Path] = []

    print(f"  [SOIL]    properties={properties} depth={depth}")
    for prop in properties:
        coverage = f"{prop}_{depth}_mean"
        params = {
            "map":      f"/map/{prop}.map",
            "SERVICE":  "WCS",
            "VERSION":  "2.0.1",
            "REQUEST":  "GetCoverage",
            "COVERAGEID": coverage,
            "FORMAT":   "image/tiff",
            "SUBSET":   f"long({xmin},{xmax})",
            "SUBSETTINGCRS":  "http://www.opengis.net/def/crs/EPSG/0/4326",
            "OUTPUTCRS":      "http://www.opengis.net/def/crs/EPSG/0/4326",
        }
        # SUBSET 두 개 (long + lat) 처리: requests 는 list 가능. urllib 는 따로 인코딩
        query = (urllib.parse.urlencode(params, safe="(),:/")
                 + f"&SUBSET={urllib.parse.quote(f'lat({ymin},{ymax})', safe='(),')}")
        url = f"{wcs_url}?{query}"
        out = out_dir / f"soil_{prop}_{depth}.tif"
        try:
            _http_download(url, out, show_progress=False)
            if not _has_valid_soil_pixels(out):
                out.unlink(missing_ok=True)
                print(f"    [정보] {out.name} → boundary 안에 유효 SoilGrids 픽셀 없음, 저장 안 함.")
                continue
            print(f"    [OK]   {out.name}  ({out.stat().st_size/1e3:.1f} KB)")
            saved.append(out)
        except RuntimeError as e:
            print(f"    [WARN] {prop}: {e}")
    return saved


def _has_valid_soil_pixels(
    tif_path: Path,
    nodata_values: Tuple[float, ...] = (0, -9999, -32768, 65535),
) -> bool:
    """raster 에 nodata 가 아닌 픽셀이 1개 이상 있으면 True."""
    try:
        import numpy as np
        import rasterio
    except ImportError:
        return True
    with rasterio.open(tif_path) as r:
        arr = r.read(1)
        nd_set = set(nodata_values)
        if r.nodata is not None:
            nd_set.add(r.nodata)
    return bool((~np.isin(arr, list(nd_set))).any())


# ── 7. SWAT 권장 토양 (FAO DSMW + SWAT2009-Global-V1.0.mdb) ─────────────────

# 글로벌 원본은 항상 download/ 에 보관, canonical 은 boundary 클립 결과만
_SWAT_SOIL_GLOBAL_FILES = [
    "soil_global.tif",
    "soil_global.tif.aux.xml",
    "soil_global.aux",
    "soil_global.rrd",
    "Soil_global_lookup.txt",
    "SWAT2009-Global-V1.0.mdb",
]

# IWMI 사내 HTTP 저장소 — mdb / lookup txt 는 URL 에서 다운로드
# (tif / aux / rrd 는 여전히 local_dir 에서 복사)
# 서버 측 mdb 파일명은 'SWAT2009-Global-FAO Soil.mdb' 이지만
# 로컬 저장 파일명은 기존 컨벤션 유지.
_SWAT_SOIL_URLS: Dict[str, str] = {
    "SWAT2009-Global-V1.0.mdb":
        "http://shared.iwmi.kr:48080/permanent/swat_py/SWAT2009-Global-FAO%20Soil.mdb",
    "Soil_global_lookup.txt":
        "http://shared.iwmi.kr:48080/permanent/swat_py/Soil_global_lookup.txt",
}


def _convert_lookup_txt_to_csv(src_txt: Path, dst_csv: Path) -> Path:
    """``Value,NAME`` → ``val,SWAT_MUID`` (QSWAT 호환 + 일관 컬럼명)."""
    lookup = pd.read_csv(src_txt)
    lookup.columns = [c.strip() for c in lookup.columns]
    rename = {"Value": "val", "VALUE": "val",
              "NAME": "SWAT_MUID", "Name": "SWAT_MUID"}
    lookup = lookup.rename(columns={k: v for k, v in rename.items()
                                    if k in lookup.columns})
    dst_csv.parent.mkdir(parents=True, exist_ok=True)
    lookup.to_csv(dst_csv, index=False)
    return dst_csv


def _clip_swat_soil_to_boundary(
    src_global_tif: Path,
    out_canonical_tif: Path,
    boundary_path: Path,
    buffer_deg: float = 0.05,
    nodata_values: Tuple[float, ...] = (0, -9999, -32768, 65535),
) -> Optional[Path]:
    """SWAT 글로벌 soil raster 를 boundary 로 클립.

    클립 결과에 유효 픽셀(nodata 가 아닌)이 0개면 ``None`` 반환 + 파일 저장 안 함.
    임시 파일에 먼저 클립한 뒤 유효성 확인되면 canonical 위치로 이동 (atomic).

    nodata_values 디폴트는 0 외에도 sentinel 값 ``-9999, -32768, 65535`` 포함
    (DSMW raster 가 영역 밖을 ``-9999`` 로 채우는 경우 등을 안전하게 처리).
    """
    import tempfile

    try:
        import numpy as np
        import rasterio
    except ImportError as e:
        raise ImportError("rasterio 필요 (pip install rasterio)") from e

    from util_py.gis import clip_raster

    # soil_global.tif CRS 누락 → EPSG:4326 강제 (임시 파일)
    src_for_clip = src_global_tif
    crs_temp: Optional[Path] = None
    with rasterio.open(src_global_tif) as src:
        if src.crs is None:
            with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
                crs_temp = Path(tmp.name)
            meta = src.meta.copy()
            meta.update({"crs": "EPSG:4326"})
            with rasterio.open(crs_temp, "w", **meta) as dst:
                dst.write(src.read())
            src_for_clip = crs_temp

    # 1) 클립 → 임시 출력
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        clip_temp = Path(tmp.name)
    try:
        clip_raster(src_for_clip, clip_temp,
                    boundary_path=boundary_path, buffer_deg=buffer_deg)

        # 2) 유효 픽셀 검사
        with rasterio.open(clip_temp) as r:
            arr = r.read(1)
            rio_nodata = r.nodata
        nd_set = set(nodata_values)
        if rio_nodata is not None:
            nd_set.add(rio_nodata)
        valid_count = int((~np.isin(arr, list(nd_set))).sum())

        if valid_count == 0:
            # 이전(버그) 실행에서 남은 soil.tif / aux.xml 도 정리
            out_canonical_tif.unlink(missing_ok=True)
            for ext in (".aux.xml", ".tif.aux.xml"):
                Path(str(out_canonical_tif) + ext).unlink(missing_ok=True)
            return None

        # 3) atomic move → canonical
        out_canonical_tif.parent.mkdir(parents=True, exist_ok=True)
        if out_canonical_tif.exists():
            out_canonical_tif.unlink()
        shutil.move(str(clip_temp), str(out_canonical_tif))
        return out_canonical_tif
    finally:
        clip_temp.unlink(missing_ok=True)
        if crs_temp is not None:
            crs_temp.unlink(missing_ok=True)


def download_swat_soil(
    gis_root: Union[str, Path],
    *,
    source: str = "local",
    local_dir: Union[str, Path] = "S:/Database-INT/GISDB/Soils",
    boundary_path: Optional[Union[str, Path]] = None,
    bbox: Optional[BBox] = None,
    buffer_deg: float = 0.05,
) -> Dict[str, Path]:
    """SWAT 개발자 그룹 권장 토양 자료 (FAO DSMW + SWAT 속성 DB) 준비.

    SWAT-Plus / QSWAT 의 sub-basin → HRU 단계에서 토양 속성 lookup 에 직접 사용.

    원천 출처
    ----------
    soil_global.tif (raster)
        FAO Digital Soil Map of the World (DSMW) 기반 글로벌 토양 (~7.5 km).
        Texas A&M SWAT 그룹이 SWAT MUID 인코딩으로 재포맷.
        https://swat.tamu.edu/data/

    Soil_global_lookup.txt
        raster 픽셀값 → SWAT MUID 매핑.

    SWAT2009-Global-V1.0.mdb
        DSMW MUID → SWAT 파라미터(SOL_BD, SOL_AWC, SOL_K, USLE_K, SOL_CBN, ...).

    ⚠️ HWSD (Harmonized World Soil Database, FAO/IIASA/ISRIC) 는 다른 분류체계로
       SWAT2009-Global-V1.0.mdb 와 MUID 가 호환되지 않아 본 함수에서 제외.

    파일 배치
    ----------
    download/ (글로벌 원본, 항상 준비)
        gis/soil/download/soil_global.tif        local_dir 에서 복사
        gis/soil/download/Soil_global_lookup.txt IWMI URL 다운로드
        gis/soil/download/SWAT2009-Global-V1.0.mdb IWMI URL 다운로드

    canonical (boundary 안 유효 픽셀이 있을 때만)
        gis/soil/soil.tif                       boundary 클립된 raster
        gis/soil/soil_lookup.csv                ★ 항상 (val,SWAT_MUID, 참조용)
        gis/soil/SWAT2009-Global-V1.0.mdb       ★ 항상 (속성 DB, 참조용)

    원본 출처
    ---------
    mdb / lookup txt → ``http://shared.iwmi.kr:48080/permanent/swat_py/`` (IWMI 사내)
    soil_global.tif  → local_dir (기본 ``S:/Database-INT/GISDB/Soils``)

    Parameters
    ----------
    gis_root      : GIS 루트
    source        : "local" — tif 는 local_dir, mdb/txt 는 IWMI URL 자동 분기
    local_dir     : SWAT GISDB 위치 (tif/aux/rrd 만 사용)
    boundary_path : 폴리곤 shapefile (None 이면 클립 생략, 글로벌 그대로 canonical)
    bbox          : (xmin, ymin, xmax, ymax) — boundary_path 없을 때 fallback
    buffer_deg    : boundary 외측 버퍼 (도). SWAT 변두리 안전 여유.

    Returns
    -------
    dict : {파일 키: 저장 경로}. canonical soil.tif 가 빠질 수 있음.
    """
    if source != "local":
        raise NotImplementedError(
            f"source='{source}' 미구현. 현재는 'local' 만 지원 "
            "(mdb/txt 는 IWMI URL 에서, tif/aux/rrd 는 local_dir 에서 자동 분기)."
        )

    src_dir = Path(local_dir)
    # local_dir 은 tif/aux/rrd 용. URL-only 파일(mdb, txt)은 src_dir 없어도 동작.
    # tif 부재 시는 아래 루프 안에서 명시적 FileNotFoundError 로 안내.

    out_dir = Path(gis_root) / "soil"
    download_dir = out_dir / "download"
    out_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(exist_ok=True)

    print("=" * 64)
    print("  SWAT 권장 토양 자료 (FAO DSMW + SWAT 속성 DB) 준비")
    print("=" * 64)
    print(f"  source        : {source}")
    print(f"  local_dir     : {src_dir}")
    print(f"  out_dir       : {out_dir}")
    print(f"  boundary      : {boundary_path or bbox or '(없음 — 글로벌 보존)'}")
    print(f"  buffer_deg    : {buffer_deg}")
    print("=" * 64)
    print()

    saved: Dict[str, Path] = {}

    # ── 1. 글로벌 원본을 download/ 에 준비 ───────────────────────────────
    #      mdb/txt → IWMI URL, tif/aux/rrd → local_dir 복사
    print("  [글로벌 원본 → download/]")
    for fname in _SWAT_SOIL_GLOBAL_FILES:
        dst_path = download_dir / fname

        if fname in _SWAT_SOIL_URLS:
            url = _SWAT_SOIL_URLS[fname]
            try:
                _http_download(url, dst_path, show_progress=False)
            except Exception as e:
                raise RuntimeError(
                    f"URL 다운로드 실패: {fname}\n  URL: {url}\n  사유: {e}"
                ) from e
            size_mb = dst_path.stat().st_size / 1e6
            print(f"    [URL]  {fname:<32s} ({size_mb:>7.2f} MB)")
            saved[f"download:{fname}"] = dst_path
            continue

        # local_dir 에서 복사 (tif / aux / rrd)
        src_path = src_dir / fname
        if not src_path.is_file():
            if fname == "soil_global.tif":
                raise FileNotFoundError(
                    f"필수 파일 없음: {src_path}\n"
                    f"  soil_global.tif 는 현재 URL 미제공 — local_dir 필요."
                )
            print(f"    [MISS] {fname}")
            continue
        shutil.copy2(src_path, dst_path)
        size_mb = dst_path.stat().st_size / 1e6
        print(f"    [OK]   {fname:<32s} ({size_mb:>7.2f} MB)")
        saved[f"download:{fname}"] = dst_path

    # ── 2. SWAT 속성 DB 는 canonical 에도 복사 (참조용, 영역 무관) ────────
    #      이제 download/ 에 URL 다운로드 본이 있으므로 거기서 복사
    print()
    print("  [속성 DB 복사 → canonical]")
    mdb_dst = out_dir / "SWAT2009-Global-V1.0.mdb"
    shutil.copy2(download_dir / "SWAT2009-Global-V1.0.mdb", mdb_dst)
    print(f"    [OK]   {mdb_dst.name}  ({mdb_dst.stat().st_size/1e6:.2f} MB)")
    saved["mdb"] = mdb_dst

    # ── 3. lookup CSV 변환 (항상) ─────────────────────────────────────────
    csv_lookup = out_dir / "soil_lookup.csv"
    _convert_lookup_txt_to_csv(download_dir / "Soil_global_lookup.txt", csv_lookup)
    n_rows = sum(1 for _ in csv_lookup.open()) - 1
    print(f"    [OK]   {csv_lookup.name}  ({n_rows} rows, val,SWAT_MUID)")
    saved["lookup"] = csv_lookup

    # ── 4. boundary 클립 → canonical soil.tif (유효 픽셀 있을 때만) ──────
    print()
    print("  [boundary 클립 → canonical soil.tif]")
    canonical_tif = out_dir / "soil.tif"
    global_tif = download_dir / "soil_global.tif"

    if boundary_path is None and bbox is None:
        # 클립 생략 — 글로벌 raster 를 canonical 로
        shutil.copy2(global_tif, canonical_tif)
        print(f"    [OK]   {canonical_tif.name} (boundary 없음, 글로벌 그대로 복사)")
        saved["soil"] = canonical_tif
    else:
        if boundary_path is not None:
            clipped = _clip_swat_soil_to_boundary(
                global_tif, canonical_tif,
                Path(boundary_path), buffer_deg)
        else:
            # bbox fallback: 임시 폴리곤 만들어서 같은 함수 사용 — 단순화 위해 생략
            from util_py.gis import clip_raster
            clip_raster(global_tif, canonical_tif, bbox=bbox, buffer_deg=buffer_deg)
            # 유효 검사
            import numpy as np
            import rasterio
            with rasterio.open(canonical_tif) as r:
                arr = r.read(1)
                nd = r.nodata if r.nodata is not None else 0
            if (arr != nd).sum() == 0:
                canonical_tif.unlink(missing_ok=True)
                clipped = None
            else:
                clipped = canonical_tif

        if clipped is None:
            print(f"    [정보] boundary 안에 유효 토양 픽셀이 없음 → soil.tif 저장 안 함.")
            print(f"           (소형 도서국 등에서 흔함. SoilGrids 250m 또는")
            print(f"            국가 수문기관의 정밀 토양도 사용 권장.)")
        else:
            print(f"    [OK]   {canonical_tif.name}  "
                  f"({canonical_tif.stat().st_size/1e6:.2f} MB)")
            saved["soil"] = canonical_tif

    print()
    print("=" * 64)
    print(f"  완료: {len(saved)}개 파일 → {out_dir}")
    print("=" * 64)
    return saved


# ── 8. ESA WorldCover (10m, 3°×3° tile) ─────────────────────────────────────

def download_worldcover(
    gis_root: Union[str, Path],
    bbox: BBox,
    url_template: Optional[str] = None,
    year: int = 2021,
    merge: bool = True,
) -> Path:
    """ESA WorldCover 2021 v200 의 bbox 영역 3°×3° tile 다운로드 + mosaic + lookup.

    파일 배치
    ----------
    개별 tile  : ``{gis_root}/landuse/download/landuse_{tile}.tif``
    병합본     : ``{gis_root}/landuse/landuse.tif``
    분류표 CSV : ``{gis_root}/landuse/landuse_lookup.csv``
                 (val, description, SWAT_LU_Code)

    Returns
    -------
    Path : 병합본 landuse.tif 경로
    """
    url_template = url_template or "https://esa-worldcover.s3.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
    out_dir    = Path(gis_root) / "landuse"
    tile_dir   = out_dir / "download"
    merged     = out_dir / "landuse.tif"
    lookup_csv = out_dir / "landuse_lookup.csv"

    tiles = bbox_to_worldcover_tiles(bbox)
    print(f"  [LULC]    bbox tile 수: {len(tiles)} (ESA WorldCover {year} 3°×3°)")

    saved: List[Path] = []
    skipped = 0
    for tile in tiles:
        url = url_template.format(tile=tile)
        out = tile_dir / f"landuse_{tile}.tif"
        if out.exists() and out.stat().st_size > 0:
            saved.append(out)
            continue
        try:
            _http_download(url, out, show_progress=False)
            print(f"    [OK]   {out.name}  ({out.stat().st_size/1e6:.1f} MB)")
            saved.append(out)
        except RuntimeError as e:
            if "404" in str(e):
                skipped += 1
            else:
                print(f"    [WARN] {out.name}: {e}")
    print(f"  [LULC]    download/ 에 {len(saved)}개 tile, {skipped}개 건너뜀")

    # lookup table 은 항상 생성 (다른 단계와 무관)
    write_worldcover_lookup(lookup_csv)
    print(f"  [LULC]    lookup 저장: {lookup_csv.name}  ({len(WORLDCOVER_LOOKUP)} 클래스)")

    if merge and saved:
        try:
            _merge_rasters(saved, merged)
            mb = merged.stat().st_size / 1e6
            print(f"  [LULC]    mosaic 저장: {merged.name}  ({mb:.1f} MB)")
        except Exception as e:
            print(f"  [WARN]    mosaic 실패: {e}")
            return tile_dir
        return merged
    return tile_dir if not saved else merged
