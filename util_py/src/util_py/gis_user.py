"""사용자 정의 SWAT 영역 (Stage 2) — 국가 자료를 user area 로 클립.

워크플로우
----------
Stage 1 (gis_download) 으로 받은 국가 전체 자료
    gis/{type}/{type}.tif        DEM, LULC, soil 등 canonical
    gis/{type}/{type}_lookup.csv lookup
    gis/{type}/SWAT2009-...mdb   속성 DB

Stage 2 (gis_user) 로 사용자 SWAT 영역으로 클립
    1. 사용자가 ``gis/user/boundary-{area}.shp`` 배치 (예: boundary-rarotonga.shp)
    2. ``clip_to_user_area("rarotonga", ...)`` 호출
    3. 결과:
       gis/user/{area}/{type}/{type}.tif          ← boundary 클립 (EPSG:4326)
       gis/user/{area}/{type}/{type}-epsg{N}.tif  ← UTM (SWAT-ready, area 별 자동 EPSG)
       gis/user/{area}/{type}/{type}_lookup.csv   ← lookup 복사 (참조)
       gis/user/{area}/{type}/SWAT2009-...mdb     ← mdb 복사 (참조)

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

# raster type 별 처리 방식 (resampling, lookup 파일명, mdb 파일명)
_TYPE_META: Dict[str, Dict] = {
    "dem":     {"resampling": "bilinear", "lookup": None,                 "mdb": None},
    "landuse": {"resampling": "nearest",  "lookup": "landuse_lookup.csv", "mdb": None},
    "soil":    {"resampling": "nearest",  "lookup": "soil_lookup.csv",
                "mdb": "SWAT2009-Global-V1.0.mdb"},
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
        meta = _TYPE_META.get(rtype, {"resampling": "bilinear", "lookup": None, "mdb": None})
        # 국가 canonical raster
        country_tif = gis_root / rtype / f"{rtype}.tif"
        out_type_dir = area_dir / rtype
        out_type_dir.mkdir(parents=True, exist_ok=True)

        if not country_tif.is_file():
            print(f"  [{rtype.upper():<7s}] 국가 canonical 없음 ({country_tif.name}) → 건너뜀")
            print(f"           (Stage 1 에서 boundary 안 자료 없거나 미실행)")
            continue

        # 클립만 (canonical 파일명 보존)
        clipped = out_type_dir / f"{rtype}.tif"
        # SWAT-ready (UTM)
        utm = out_type_dir / f"{rtype}-epsg{swat_epsg}.tif"

        try:
            # 클립만
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
                print(f"  [{rtype.upper():<7s}] boundary 안 유효 픽셀 0개 → 저장 안 함")
                continue

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
        except Exception as e:
            print(f"  [{rtype.upper():<7s}] 클립 실패: {e}")
            continue

        # lookup 복사
        if copy_lookups and meta["lookup"]:
            src_lookup = gis_root / rtype / meta["lookup"]
            if src_lookup.is_file():
                dst = out_type_dir / meta["lookup"]
                shutil.copy2(src_lookup, dst)
                saved[f"{rtype}_lookup"] = dst

        # mdb 복사
        if copy_mdb and meta["mdb"]:
            src_mdb = gis_root / rtype / meta["mdb"]
            if src_mdb.is_file():
                dst = out_type_dir / meta["mdb"]
                shutil.copy2(src_mdb, dst)
                saved[f"{rtype}_mdb"] = dst

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
