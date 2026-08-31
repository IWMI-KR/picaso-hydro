"""
SWAT 입력 GIS 자료 자동 다운로드 CLI

지원 데이터셋
-------------
    admin   : GADM v4.1 행정구역
    basin   : HydroSHEDS HydroBASINS lev12
    river   : HydroSHEDS HydroRIVERS v10
    dem     : Copernicus GLO-30 (1°×1° tile, 다중 가능)
    soil    : ISRIC SoilGrids 250m (sand/silt/clay × 깊이)
    landuse : ESA WorldCover 2021 v200 (3°×3° tile, 다중 가능)
    all     : 위 6개 모두

사용법
------
    util-gis-download                              # YAML 자동 탐색, 모든 자료
    util-gis-download --datasets admin basin river   # 일부만
    util-gis-download --datasets dem soil
    util-gis-download --boundary-csv /path/x.csv

환경변수
---------
    UTIL_PY_CONFIG  util_py.yaml 경로
    PICASO_ROOT     프로젝트 루트
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from util_py.config import load_effective_config
from util_py.gis_download import (
    _read_bbox_iso,
    download_dem,
    download_gadm,
    download_hydrobasins,
    download_hydrorivers,
    download_soilgrids,
    download_swat_soil,
    download_worldcover,
)


_DATASETS = ["admin", "basin", "river", "dem", "soil", "swat_soil", "landuse"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="SWAT 입력 GIS 자료 다운로드 (글로벌 공개 소스)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=None,
                        help="util_py.yaml 경로 (생략 시 자동 탐색)")
    parser.add_argument("--boundary-csv", default=None,
                        help="경계 CSV (YAML region.boundary_csv 오버라이드)")
    parser.add_argument("--gis-root", default=None,
                        help="GIS 루트 (YAML gis.root 오버라이드)")
    parser.add_argument("--datasets", nargs="+", default=["all"],
                        choices=_DATASETS + ["all"],
                        help=f"다운로드할 자료 종류 (기본 all). 가능: {_DATASETS + ['all']}")
    parser.add_argument("--keep-continental", action="store_true",
                        help="HydroSHEDS 대륙 원본도 보관")
    args = parser.parse_args(argv)

    cfg = load_effective_config(args.config)
    boundary_csv = args.boundary_csv or cfg.region.boundary_csv
    gis_root     = args.gis_root     or cfg.gis.root
    if not boundary_csv or not gis_root:
        parser.error("boundary_csv 또는 gis_root 미지정")

    bbox, iso2, iso3, name = _read_bbox_iso(boundary_csv)

    targets = _DATASETS if "all" in args.datasets else args.datasets

    print("=" * 64)
    print("  SWAT 입력 GIS 자료 다운로드")
    print("=" * 64)
    print(f"  국가      : {name}  (ISO3={iso3}, ISO2={iso2})")
    print(f"  bbox      : lon [{bbox[0]:.3f}, {bbox[2]:.3f}],  "
          f"lat [{bbox[1]:.3f}, {bbox[3]:.3f}]")
    print(f"  gis_root  : {gis_root}")
    print(f"  대상      : {targets}")
    print("=" * 64)
    print()

    summary: List[str] = []

    if "admin" in targets:
        try:
            p = download_gadm(iso3=iso3, gis_root=gis_root,
                              level=cfg.gis_download.gadm.level,
                              url_template=cfg.gis_download.gadm.url_template)
            summary.append(f"admin   ✓  {p}")
        except Exception as e:
            summary.append(f"admin   ✗  {e}")

    if "basin" in targets:
        try:
            p = download_hydrobasins(
                gis_root=gis_root, bbox=bbox,
                region=cfg.gis_download.hydrobasins.region,
                level=cfg.gis_download.hydrobasins.level,
                url_template=cfg.gis_download.hydrobasins.url_template,
                keep_continental=args.keep_continental)
            if p is None:
                summary.append("basin   —  자료 없음 (파일 저장 안 함)")
            else:
                summary.append(f"basin   ✓  {p}")
        except Exception as e:
            summary.append(f"basin   ✗  {e}")

    if "river" in targets:
        try:
            p = download_hydrorivers(
                gis_root=gis_root, bbox=bbox,
                region=cfg.gis_download.hydrorivers.region,
                url_template=cfg.gis_download.hydrorivers.url_template,
                keep_continental=args.keep_continental)
            if p is None:
                summary.append("river   —  자료 없음 (파일 저장 안 함)")
            else:
                summary.append(f"river   ✓  {p}")
        except Exception as e:
            summary.append(f"river   ✗  {e}")

    if "dem" in targets:
        try:
            p = download_dem(
                gis_root=gis_root, bbox=bbox,
                url_template=cfg.gis_download.dem.url_template)
            summary.append(f"dem     ✓  {p}")
        except Exception as e:
            summary.append(f"dem     ✗  {e}")

    if "soil" in targets:
        try:
            paths = download_soilgrids(
                gis_root=gis_root, bbox=bbox,
                properties=cfg.gis_download.soilgrids.properties,
                depth=cfg.gis_download.soilgrids.depth,
                wcs_url=cfg.gis_download.soilgrids.wcs_url)
            summary.append(f"soil    ✓  {len(paths)}개 속성")
        except Exception as e:
            summary.append(f"soil    ✗  {e}")

    if "swat_soil" in targets:
        try:
            # 국가 boundary = gis/admin/admin.shp (GADM). ISO3 로 한국(RDA) /
            # 그 외(글로벌 FAO) 자동 분기.
            admin_shp = Path(gis_root) / "admin" / "admin.shp"
            paths = download_swat_soil(
                gis_root=gis_root,
                base_url=cfg.gis_download.swat_soil.base_url,
                boundary_path=str(admin_shp) if admin_shp.is_file() else None,
                bbox=bbox if not admin_shp.is_file() else None,
                buffer_deg=cfg.gis.swat_buffer_deg,
                iso3=iso3)
            soil_saved = "soil" in paths
            summary.append(f"swat_soil {'✓' if soil_saved else '—'}  "
                           f"{len(paths)}개 파일{' (canonical 저장)' if soil_saved else ' (canonical 미저장: 자료 없음)'}")
        except Exception as e:
            summary.append(f"swat_soil ✗  {e}")

    if "landuse" in targets:
        try:
            p = download_worldcover(
                gis_root=gis_root, bbox=bbox,
                url_template=cfg.gis_download.worldcover.url_template,
                year=cfg.gis_download.worldcover.year)
            summary.append(f"landuse ✓  {p}")
        except Exception as e:
            summary.append(f"landuse ✗  {e}")

    print()
    print("=" * 64)
    print("  요약")
    print("=" * 64)
    for line in summary:
        print(f"  {line}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
