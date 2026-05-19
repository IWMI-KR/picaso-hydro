"""사용자 정의 SWAT 영역 (Stage 2) — 국가 자료를 user area 로 클립.

워크플로우
----------
Stage 1 (gis_download) 으로 받은 국가 전체 자료
    gis/{type}/{type}.tif         DEM, LULC, soil 등 canonical
    gis/{type}/{type}_lookup.csv  lookup
    gis/soil/QSWAT-*.mdb          QSWAT (SWAT2012) 속성 DB
    gis/soil/QSWATPlus-*.sqlite   QSWAT+ (SWAT+ Editor) 속성 DB

Stage 2 (gis_user) 로 사용자 SWAT 영역으로 클립
    1. 사용자가 ``gis/user/boundary-{area}.shp`` 배치 (예: boundary-rarotonga.shp)
    2. ``clip_to_user_area("rarotonga", ...)`` 호출
    3. 결과:
       gis/user/{area}/{type}/{type}.tif           ← boundary 클립 (EPSG:4326)
       gis/user/{area}/{type}/{type}-epsg{N}.tif   ← UTM (SWAT-ready, area 별 자동 EPSG)
       gis/user/{area}/{type}/{type}_lookup.csv    ← lookup 복사 (참조)
       gis/user/{area}/{type}/QSWAT-*.mdb          ← QSWAT 속성 DB 복사 (참조)
       gis/user/{area}/{type}/QSWATPlus-*.sqlite   ← QSWAT+ 속성 DB 복사 (참조)

규약
----
- 파일명 패턴 ``boundary-{area}.shp`` 에서 ``{area}`` 추출 → 폴더명
- 한 user area = 한 SWAT 프로젝트 = 한 폴더
- 한 국가에 여러 area 가능 (boundary-rarotonga.shp + boundary-aitutaki.shp)
- 각 area 마다 UTM EPSG 독립 산출 (라로통가→32705, 아이투타키→32704 등)
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

from util_py.gis import auto_utm_epsg, prepare_raster_for_swat


# ── area discovery ──────────────────────────────────────────────────────────

# raster type 별 처리 방식 (resampling, lookup 파일명, mdb 후보 파일명들).
# soil/mdb 는 한국(RDA)/글로벌(FAO) + 구버전(SWAT2009-Global-V1.0) 까지 모두 시도.
# QSWATPlus 의 sqlite 도 함께 복사.
_TYPE_META: Dict[str, Dict] = {
    "dem":     {"resampling": "bilinear", "lookup": None,                 "mdb": []},
    "landuse": {"resampling": "nearest",  "lookup": "landuse_lookup.csv", "mdb": []},
    "soil":    {"resampling": "nearest",  "lookup": "soil_lookup.csv",
                "mdb": ["QSWAT-Korea-RDA Soil.mdb",
                        "QSWAT-Global-FAO Soil.mdb",
                        "QSWATPlus-Korea-RDA Soil.sqlite",
                        "QSWATPlus-Global-FAO Soil.sqlite",
                        "SWAT2009-Global-V1.0.mdb",
                        "SWAT2009-Global-FAO Soil.mdb"]},
}

# 사용자 직접 배치 vector 자료 (raster 부재 시 fallback)
# 패턴: gis/{rtype}/{rtype}-swat.shp, 'val' 컬럼 필요
_USER_VECTOR_FALLBACK: Dict[str, Dict] = {
    "soil": {"shp_name": "soil-swat.shp", "val_column": "val",
             "pixel_size_m": 30.0},
}


def _parse_area_from_filename(filename: str,
                              pattern: str = "boundary-{area}.shp") -> Optional[str]:
    """``boundary-rarotonga.shp`` → ``rarotonga``.

    pattern 의 ``{area}`` 부분을 정규식 그룹으로 변환하여 매칭.
    """
    regex_pat = "^" + re.escape(pattern).replace(r"\{area\}", r"(?P<area>[\w\-]+)") + "$"
    m = re.match(regex_pat, filename)
    return m.group("area") if m else None


def discover_user_areas(
    base_dir: Union[str, Path],
    filename_pattern: str = "boundary-{area}.shp",
) -> List[Dict[str, Union[str, Path]]]:
    """``base_dir`` 에서 ``boundary-{area}.shp`` 패턴 파일들을 탐색.

    Returns
    -------
    list of dicts: [{area: str, shp: Path}, ...]
    """
    base_dir = Path(base_dir)
    if not base_dir.is_dir():
        return []

    found: List[Dict] = []
    for p in sorted(base_dir.glob("boundary-*.shp")):
        area = _parse_area_from_filename(p.name, filename_pattern)
        if area is None:
            continue
        found.append({"area": area, "shp": p})
    return found


# ── 사용자 정의 vector 자료 → UTM shp + rasterize ───────────────────────────

def _clip_reproject_rasterize_vector(
    vector_shp: Path,
    boundary_shp: Path,
    out_shp: Path,
    out_tif: Path,
    *,
    target_epsg: int,
    val_column: str = "val",
    pixel_size_m: float = 30.0,
    buffer_deg: float = 0.05,
) -> Tuple[Path, Path]:
    """사용자 직접 배치 polygon shapefile 을 boundary 로 클립 + UTM 재투영 +
    val 컬럼으로 rasterize.

    raster 토양 자료가 없거나 boundary 안 유효 픽셀이 0개일 때 (소형 도서국 등)
    사용자 정부·기관 배포 토양도 (예: ``gis/soil/soil-swat.shp``) 를 SWAT
    입력으로 활용하는 fallback 경로.

    동작
    ----
    1) vector 를 EPSG:4326 으로 통일 후 boundary(+버퍼)로 클립
    2) UTM(target_epsg) 재투영 → out_shp 저장 (.dbf/.prj/.shx/.cpg 동반)
    3) clipped UTM 의 ``val_column`` 정수값으로 rasterize → out_tif 저장
       (해상도 pixel_size_m, 0=nodata)

    Parameters
    ----------
    vector_shp   : 입력 polygon shapefile (val 컬럼 필요)
    boundary_shp : user area boundary
    out_shp      : 출력 UTM shapefile 경로 (예: soil-swat-epsg32705.shp)
    out_tif      : 출력 UTM raster 경로 (예: soil-swat-epsg32705.tif)
    target_epsg  : UTM EPSG (clip_to_user_area 에서 자동 산출됨)
    val_column   : raster 에 인코딩할 정수 속성 컬럼 (기본 'val')
    pixel_size_m : raster 해상도 (m, 기본 30 — DEM 과 일관)
    buffer_deg   : boundary 외측 버퍼 (도)
    """
    import geopandas as gpd
    import numpy as np
    import rasterio
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds

    bgdf = gpd.read_file(boundary_shp)
    if bgdf.crs is None:
        raise ValueError(f"boundary 에 CRS 없음: {boundary_shp}")
    bgdf_wgs = bgdf.to_crs("EPSG:4326")
    if buffer_deg > 0:
        bgdf_wgs = bgdf_wgs.copy()
        bgdf_wgs["geometry"] = bgdf_wgs.geometry.buffer(buffer_deg)

    vgdf = gpd.read_file(vector_shp)
    if vgdf.crs is None:
        raise ValueError(f"입력 vector 에 CRS 없음: {vector_shp}")
    if val_column not in vgdf.columns:
        raise ValueError(
            f"입력 vector 에 '{val_column}' 컬럼 없음: {vector_shp}\n"
            f"  존재 컬럼: {list(vgdf.columns)}"
        )
    vgdf_wgs = vgdf.to_crs("EPSG:4326")

    # keep_geom_type=True 로 Polygon/MultiPolygon 만 유지 (LineString/Point 부산물 제거)
    clipped = gpd.overlay(vgdf_wgs, bgdf_wgs, how="intersection",
                          keep_geom_type=True)
    # 추가 안전장치: 비-polygon 잔류물 제거
    clipped = clipped[clipped.geom_type.isin(["Polygon", "MultiPolygon"])]
    if len(clipped) == 0:
        raise ValueError(
            f"boundary 안 vector feature 0개: {vector_shp}\n"
            f"  (boundary bbox 와 vector 영역이 겹치지 않음)"
        )

    # UTM 재투영 + shp 저장
    clipped_utm = clipped.to_crs(f"EPSG:{target_epsg}")
    out_shp.parent.mkdir(parents=True, exist_ok=True)
    clipped_utm.to_file(out_shp)

    # rasterize val 컬럼 → tif
    minx, miny, maxx, maxy = clipped_utm.total_bounds
    width  = max(int(round((maxx - minx) / pixel_size_m)), 1)
    height = max(int(round((maxy - miny) / pixel_size_m)), 1)
    transform = from_bounds(minx, miny, maxx, maxy, width, height)
    shapes = ((geom, int(v)) for geom, v in
              zip(clipped_utm.geometry, clipped_utm[val_column]))
    arr = rasterize(
        shapes, out_shape=(height, width),
        transform=transform, fill=0, dtype="int32",
    )
    with rasterio.open(
        out_tif, "w", driver="GTiff",
        width=width, height=height, count=1,
        dtype="int32", crs=f"EPSG:{target_epsg}",
        transform=transform, nodata=0, compress="lzw",
    ) as dst:
        dst.write(arr, 1)

    return out_shp, out_tif


# ── core: 한 area 에 대해 모든 raster type 클립 ──────────────────────────────

def clip_to_user_area(
    area: str,
    gis_root: Union[str, Path],
    user_base_dir: Optional[Union[str, Path]] = None,
    *,
    raster_types: Optional[List[str]] = None,
    buffer_deg: float = 0.05,
    swat_epsg: Optional[int] = None,
    copy_lookups: bool = True,
    copy_mdb: bool = True,
    filename_pattern: str = "boundary-{area}.shp",
) -> Dict[str, Path]:
    """한 user area 에 대해 국가 raster 자료를 클립 + UTM 재투영.

    Parameters
    ----------
    area              : area 이름 (boundary-{area}.shp 의 {area})
    gis_root          : GIS 루트 (예: 0_database/gis)
    user_base_dir     : user area 루트 (None → ``gis_root/user``)
    raster_types      : 클립할 데이터 종류 (기본 dem/landuse/soil)
    buffer_deg        : boundary 외측 버퍼 (도)
    swat_epsg         : 목표 UTM EPSG (None → boundary bbox 중심으로 자동)
    copy_lookups      : True 면 landuse/soil lookup CSV 도 area 폴더에 복사
    copy_mdb          : True 면 SWAT mdb 도 area 폴더에 복사
    filename_pattern  : boundary 파일명 패턴

    Returns
    -------
    dict : {raster_type 또는 type-utm: Path}
    """
    raster_types = raster_types or ["dem", "landuse", "soil"]
    gis_root = Path(gis_root)
    user_base = Path(user_base_dir) if user_base_dir else (gis_root / "user")

    # boundary shapefile 위치
    boundary_shp = user_base / filename_pattern.replace("{area}", area)
    if not boundary_shp.is_file():
        raise FileNotFoundError(
            f"User boundary 없음: {boundary_shp}\n"
            f"파일을 {user_base} 에 배치하세요 (이름 패턴: {filename_pattern})."
        )

    # area 폴더
    area_dir = user_base / area
    area_dir.mkdir(parents=True, exist_ok=True)

    # boundary bbox 추출 → CSV (참조용)
    import geopandas as gpd
    bgdf = gpd.read_file(boundary_shp)
    if bgdf.crs is None:
        raise ValueError(f"boundary 에 CRS 메타가 없음: {boundary_shp}")
    bgdf_wgs = bgdf.to_crs("EPSG:4326")
    minx, miny, maxx, maxy = bgdf_wgs.total_bounds
    boundary_csv = area_dir / "boundary" / f"boundary-{area}.csv"
    boundary_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "OBJECTID": 1, "NAME": area,
        "xmin": minx, "ymin": miny, "xmax": maxx, "ymax": maxy,
    }]).to_csv(boundary_csv, index=False)

    # area UTM 자동 산출
    if swat_epsg is None:
        swat_epsg = auto_utm_epsg(bbox=(float(minx), float(miny),
                                        float(maxx), float(maxy)))

    print("=" * 64)
    print(f"  Stage 2: User area '{area}' SWAT 자료 준비")
    print("=" * 64)
    print(f"  boundary  : {boundary_shp}")
    print(f"  bbox      : ({minx:.4f}, {miny:.4f}, {maxx:.4f}, {maxy:.4f})")
    print(f"  swat_epsg : EPSG:{swat_epsg}")
    print(f"  buffer    : {buffer_deg}° (~{buffer_deg*111:.1f} km)")
    print(f"  area_dir  : {area_dir}")
    print(f"  raster_types: {raster_types}")
    print("=" * 64)
    print()

    saved: Dict[str, Path] = {"boundary_csv": boundary_csv}

    for rtype in raster_types:
        meta = _TYPE_META.get(rtype, {"resampling": "bilinear",
                                      "lookup": None, "mdb": []})
        # 국가 canonical raster
        country_tif = gis_root / rtype / f"{rtype}.tif"
        out_type_dir = area_dir / rtype
        out_type_dir.mkdir(parents=True, exist_ok=True)

        raster_done = False
        if country_tif.is_file():
            clipped = out_type_dir / f"{rtype}.tif"
            utm     = out_type_dir / f"{rtype}-epsg{swat_epsg}.tif"
            try:
                # 클립만 (canonical 파일명 보존)
                from util_py.gis import clip_raster
                clip_raster(country_tif, clipped,
                            boundary_path=boundary_shp, buffer_deg=buffer_deg)

                # 클립 결과 유효 픽셀 확인
                import numpy as np
                import rasterio
                with rasterio.open(clipped) as r:
                    arr = r.read(1)
                    nd = r.nodata if r.nodata is not None else 0
                valid = int((arr != nd).sum())
                if valid == 0:
                    clipped.unlink(missing_ok=True)
                    print(f"  [{rtype.upper():<7s}] boundary 안 유효 픽셀 0개 → raster 저장 안 함")
                else:
                    # UTM 재투영
                    prepare_raster_for_swat(
                        country_tif, boundary_shp, output_path=utm,
                        buffer_deg=buffer_deg, target_epsg=swat_epsg,
                        resampling=meta["resampling"], keep_intermediate=False,
                    )
                    print(f"  [{rtype.upper():<7s}] {clipped.name} ({clipped.stat().st_size/1e6:.2f} MB) "
                          f"+ {utm.name} ({utm.stat().st_size/1e6:.2f} MB)")
                    saved[rtype] = clipped
                    saved[f"{rtype}-utm"] = utm
                    raster_done = True
            except Exception as e:
                print(f"  [{rtype.upper():<7s}] raster 클립 실패: {e}")
        else:
            print(f"  [{rtype.upper():<7s}] 국가 canonical 없음 ({country_tif.name}) → raster 건너뜀")

        # raster 미생성 + 사용자 vector 자료 존재 시 fallback
        # (예: gis/soil/soil-swat.shp → user/{area}/soil/soil-swat-epsg{N}.shp + .tif)
        if not raster_done and rtype in _USER_VECTOR_FALLBACK:
            vfb = _USER_VECTOR_FALLBACK[rtype]
            vsrc = gis_root / rtype / vfb["shp_name"]
            if vsrc.is_file():
                stem = Path(vfb["shp_name"]).stem        # "soil-swat"
                vshp = out_type_dir / f"{stem}-epsg{swat_epsg}.shp"
                vtif = out_type_dir / f"{stem}-epsg{swat_epsg}.tif"
                try:
                    _clip_reproject_rasterize_vector(
                        vsrc, boundary_shp, vshp, vtif,
                        target_epsg=swat_epsg,
                        val_column=vfb["val_column"],
                        pixel_size_m=vfb["pixel_size_m"],
                        buffer_deg=buffer_deg,
                    )
                    print(f"  [{rtype.upper():<7s}] vector→UTM: {vshp.name} + "
                          f"{vtif.name} ({vtif.stat().st_size/1e3:.1f} KB)")
                    saved[f"{rtype}_vector_shp"] = vshp
                    saved[f"{rtype}_vector_tif"] = vtif
                except Exception as e:
                    print(f"  [{rtype.upper():<7s}] vector 변환 실패: {e}")
            else:
                print(f"  [{rtype.upper():<7s}] vector fallback 도 없음 ({vsrc.name})")

        # lookup 복사 (raster/vector 유무 무관 — 참조용)
        if copy_lookups and meta["lookup"]:
            src_lookup = gis_root / rtype / meta["lookup"]
            if src_lookup.is_file():
                dst = out_type_dir / meta["lookup"]
                shutil.copy2(src_lookup, dst)
                saved[f"{rtype}_lookup"] = dst

        # 속성 DB 복사 (raster/vector 유무 무관, 후보 파일명 모두 시도).
        # QSWAT(.mdb) + QSWATPlus(.sqlite) 가 동시에 있을 수 있으므로 모두 복사.
        if copy_mdb and meta["mdb"]:
            for cand in meta["mdb"]:
                src_mdb = gis_root / rtype / cand
                if src_mdb.is_file():
                    dst = out_type_dir / cand   # 원본 파일명 유지
                    shutil.copy2(src_mdb, dst)
                    ext_key = Path(cand).suffix.lstrip(".") or "db"
                    saved[f"{rtype}_{ext_key}"] = dst

    print()
    print("=" * 64)
    print(f"  완료 — {len(saved)}개 자산 → {area_dir}")
    print("=" * 64)
    return saved


def clip_to_all_user_areas(
    gis_root: Union[str, Path],
    user_base_dir: Optional[Union[str, Path]] = None,
    *,
    raster_types: Optional[List[str]] = None,
    buffer_deg: float = 0.05,
    copy_lookups: bool = True,
    copy_mdb: bool = True,
    filename_pattern: str = "boundary-{area}.shp",
) -> Dict[str, Dict[str, Path]]:
    """``user_base_dir`` 안 모든 ``boundary-{area}.shp`` 에 대해 클립."""
    gis_root = Path(gis_root)
    user_base = Path(user_base_dir) if user_base_dir else (gis_root / "user")
    areas = discover_user_areas(user_base, filename_pattern)
    if not areas:
        print(f"  ⚠️  {user_base} 안에 boundary-*.shp 파일이 없음.")
        return {}

    print(f"  발견된 user area: {[a['area'] for a in areas]}\n")

    results: Dict[str, Dict[str, Path]] = {}
    for entry in areas:
        results[entry["area"]] = clip_to_user_area(
            entry["area"], gis_root, user_base,
            raster_types=raster_types, buffer_deg=buffer_deg,
            copy_lookups=copy_lookups, copy_mdb=copy_mdb,
            filename_pattern=filename_pattern,
        )
        print()
    return results
