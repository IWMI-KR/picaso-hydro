"""
사용자 SWAT 영역 클립 CLI (Stage 2)

워크플로우
----------
1. ``gis/user/boundary-{area}.shp`` 파일을 사용자가 직접 배치
   (예: gis/user/boundary-rarotonga.shp)
2. 본 CLI 실행:
       util-gis-clip-to-user --area rarotonga
       util-gis-clip-to-user --all
3. 결과:
       gis/user/{area}/boundary/boundary-{area}.csv
       gis/user/{area}/dem/dem.tif + dem-epsg{N}.tif
       gis/user/{area}/landuse/landuse.tif + landuse_lookup.csv + UTM
       gis/user/{area}/soil/soil.tif (있으면) + lookup + mdb

사용법
------
    util-gis-clip-to-user                                  # 기본: --all
    util-gis-clip-to-user --area rarotonga
    util-gis-clip-to-user --area rarotonga --types dem landuse
    util-gis-clip-to-user --buffer-deg 0.1 --epsg 32705
"""

from __future__ import annotations

import argparse
import sys

from util_py.config import load_effective_config
from util_py.gis_user import (
    clip_to_all_user_areas,
    clip_to_user_area,
    discover_user_areas,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage 2: 국가 자료를 사용자 SWAT 영역으로 클립",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=None,
                        help="util_py.yaml 경로")
    parser.add_argument("--gis-root", default=None,
                        help="GIS 루트 (YAML gis.root 오버라이드)")
    parser.add_argument("--user-base", default=None,
                        help="user area 루트 (YAML gis_user.base_dir 오버라이드)")
    parser.add_argument("--area", default=None,
                        help="단일 area 명 (생략 시 --all)")
    parser.add_argument("--all", action="store_true",
                        help="발견된 모든 area 처리")
    parser.add_argument("--types", nargs="+", default=None,
                        choices=["dem", "landuse", "soil"], metavar="TYPE",
                        help="클립할 raster 종류 (기본: YAML)")
    parser.add_argument("--buffer-deg", type=float, default=None,
                        help="boundary 외측 버퍼 (도)")
    parser.add_argument("--epsg", type=int, default=None,
                        help="UTM EPSG 강제 지정 (생략 시 area 별 자동)")
    parser.add_argument("--no-lookups", action="store_true",
                        help="landuse/soil lookup CSV 복사 안 함")
    parser.add_argument("--no-mdb", action="store_true",
                        help="SWAT mdb 복사 안 함")
    parser.add_argument("--list", action="store_true",
                        help="발견된 area 만 나열하고 종료")
    args = parser.parse_args(argv)

    cfg = load_effective_config(args.config)
    gis_root = args.gis_root or cfg.gis.root
    user_base = args.user_base or cfg.gis_user.base_dir
    raster_types = args.types or cfg.gis_user.raster_types
    buffer_deg = args.buffer_deg if args.buffer_deg is not None else cfg.gis_user.swat_buffer_deg
    swat_epsg = args.epsg if args.epsg is not None else cfg.gis_user.swat_epsg
    copy_lookups = (not args.no_lookups) and cfg.gis_user.copy_lookups
    copy_mdb = (not args.no_mdb) and cfg.gis_user.copy_mdb
    pattern = cfg.gis_user.filename_pattern

    if args.list:
        areas = discover_user_areas(user_base, pattern)
        print(f"  user_base : {user_base}")
        print(f"  pattern   : {pattern}")
        print(f"  areas     : {len(areas)}")
        for a in areas:
            print(f"    - {a['area']:<20s}  ←  {a['shp'].name}")
        return 0

    if args.area:
        clip_to_user_area(
            area=args.area, gis_root=gis_root, user_base_dir=user_base,
            raster_types=raster_types, buffer_deg=buffer_deg,
            swat_epsg=swat_epsg, copy_lookups=copy_lookups, copy_mdb=copy_mdb,
            filename_pattern=pattern,
        )
    else:
        # 기본 = --all
        clip_to_all_user_areas(
            gis_root=gis_root, user_base_dir=user_base,
            raster_types=raster_types, buffer_deg=buffer_deg,
            copy_lookups=copy_lookups, copy_mdb=copy_mdb,
            filename_pattern=pattern,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
