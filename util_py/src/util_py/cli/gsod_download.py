"""
NOAA GSOD 일자료 다운로드 CLI

설정 우선순위
-------------
    CLI 인자 > util_py.yaml > 코드 기본값

사용법
------
    util-gsod-download                                  # YAML 자동 탐색
    util-gsod-download --config /path/util_py.yaml
    util-gsod-download --start-year 1990 --end-year 2024
    util-gsod-download --country-code KR --no-bbox      # 국가 코드 직접 지정
    util-gsod-download --overwrite

환경변수
---------
    UTIL_PY_CONFIG  util_py.yaml 경로 강제 지정
    PICASO_ROOT     프로젝트 루트
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from util_py.config import Config, find_config, load_config
from util_py.gsod import download_gsod_country


def _picaso_root() -> Path:
    if env := os.environ.get("PICASO_ROOT"):
        return Path(env)
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / "0_database").is_dir():
            return parent
    return cwd


def _load_or_default(config_path: str | None) -> Config:
    if config_path:
        return load_config(config_path)
    found = find_config()
    if found:
        return load_config(found)
    cfg = Config()
    root = _picaso_root()
    cfg.project.root = str(root)
    cfg.region.boundary_csv = str(root / "0_database" / "gis" / "admin" / "country_boundary.csv")
    cfg.gsod.obs_dir     = str(root / "0_database" / "gsod" / "daily")
    cfg.gsod.station_csv = str(root / "0_database" / "gsod" / "station-gsod.csv")
    cfg.gsod.station_shp = str(root / "0_database" / "gis" / "gsod" / "station-gsod.shp")
    cfg.gsod.archive_dir = "I:/2025-APCC_Cook/Database/GSOD/archive"
    return cfg


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="NOAA GSOD 일자료 다운로드 (boundary_csv 기준 국가 + bbox 필터)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=None,
                        help="util_py.yaml 경로 (생략 시 자동 탐색)")
    parser.add_argument("--boundary-csv", default=None,
                        help="경계 CSV (YAML region.boundary_csv 오버라이드)")
    parser.add_argument("--obs-dir", default=None,
                        help="관측소별 통합 CSV 출력 (YAML gsod.obs_dir)")
    parser.add_argument("--station-csv", default=None,
                        help="관측소 메타 CSV (YAML gsod.station_csv)")
    parser.add_argument("--station-shp", default=None,
                        help="관측소 위치 shapefile (YAML gsod.station_shp). 빈 문자열이면 생성 안 함")
    parser.add_argument("--archive-dir", default=None,
                        help="로컬 .tar.gz 보관 폴더 (YAML gsod.archive_dir)")
    parser.add_argument("--start-year", type=int, default=None,
                        help="시작 연도 (YAML gsod.start_year 오버라이드)")
    parser.add_argument("--end-year", type=int, default=None,
                        help="종료 연도 (YAML gsod.end_year 오버라이드)")
    parser.add_argument("--country-code", default=None,
                        help="ISO2 또는 FIPS 코드 직접 지정")
    parser.add_argument("--no-bbox", action="store_true",
                        help="bbox 추가 필터 비활성화 (국가 코드만 사용)")
    parser.add_argument("--overwrite", action="store_true",
                        help="기존 통합 CSV 덮어쓰기")
    args = parser.parse_args(argv)

    cfg = _load_or_default(args.config)

    boundary_csv  = args.boundary_csv  or cfg.region.boundary_csv
    obs_dir       = args.obs_dir       or cfg.gsod.obs_dir
    station_csv   = args.station_csv   or cfg.gsod.station_csv
    # station_shp: 명시적 빈 문자열은 비활성화로 해석
    if args.station_shp is not None:
        station_shp = args.station_shp or None
    else:
        station_shp = cfg.gsod.station_shp or None
    archive_dir   = args.archive_dir   or cfg.gsod.archive_dir or None
    start_year    = args.start_year if args.start_year is not None else cfg.gsod.start_year
    end_year      = args.end_year   if args.end_year   is not None else cfg.gsod.end_year
    country_code  = args.country_code or cfg.gsod.country_code
    use_bbox      = (not args.no_bbox) and cfg.gsod.use_bbox_filter

    for label, value in [
        ("boundary_csv", boundary_csv),
        ("obs_dir",      obs_dir),
        ("station_csv",  station_csv),
    ]:
        if not value:
            parser.error(f"{label} 미지정: CLI 또는 util_py.yaml 필요")

    download_gsod_country(
        boundary_csv     = boundary_csv,
        obs_dir          = obs_dir,
        station_csv      = station_csv,
        station_shp      = station_shp,
        archive_dir      = archive_dir,
        start_year       = start_year,
        end_year         = end_year,
        country_code     = country_code,
        use_bbox_filter  = use_bbox,
        isd_history_url  = cfg.gsod.isd_history_url,
        gsod_access_url  = cfg.gsod.gsod_access_url,
        overwrite        = args.overwrite,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
