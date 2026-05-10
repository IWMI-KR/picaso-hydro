"""
ERA5 격자점 기상자료 추출 CLI

설정 우선순위
-------------
    CLI 인자 > util_py.yaml > 환경변수 > smart default

사용법
------
    util-era5-extract                              # YAML 자동 탐색
    util-era5-extract --config /path/util_py.yaml
    util-era5-extract --start-year 2020 --end-year 2025
    util-era5-extract --grid 0_database/era5/grid_points-era5.shp
    util-era5-extract --utc-offset 9               # 한국 시간대
    util-era5-extract --overwrite

환경변수
---------
    PICASO_ROOT      프로젝트 루트
    UTIL_PY_CONFIG   util_py.yaml 경로
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from util_py.config import Config, find_config, load_config
from util_py.extract import extract_era5_to_grid


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
    cfg.extract.grid_file  = str(root / "0_database" / "era5" / "grid_points-era5.csv")
    cfg.extract.hourly_dir = str(root / "0_database" / "era5" / "grid_hourly")
    cfg.extract.daily_dir  = str(root / "0_database" / "era5" / "grid_daily")
    cfg.era5.output_dir    = str(root / "0_database" / "era5" / "nc_hourly")
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ERA5 NC 파일로부터 격자점별 시간·일 기상자료 추출",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=None,
                        help="util_py.yaml 경로 (생략 시 자동 탐색)")
    parser.add_argument("--grid", default=None,
                        help="격자점 파일 .csv/.shp (YAML extract.grid_file 오버라이드)")
    parser.add_argument("--era5-dir", default=None,
                        help="ERA5 NC 폴더 (YAML era5.output_dir 오버라이드)")
    parser.add_argument("--hourly-dir", default=None,
                        help="시간단위 출력 (YAML extract.hourly_dir 오버라이드)")
    parser.add_argument("--daily-dir", default=None,
                        help="일단위 출력 (YAML extract.daily_dir 오버라이드)")
    parser.add_argument("--utc-offset", type=int, default=None,
                        help="UTC → 로컬 시차 (YAML region.utc_offset 오버라이드)")
    parser.add_argument("--start-year", type=int, default=None,
                        help="추출 시작 연도 (YAML extract.start_year 오버라이드)")
    parser.add_argument("--end-year", type=int, default=None,
                        help="추출 종료 연도 (YAML extract.end_year 오버라이드)")
    parser.add_argument("--overwrite", action="store_true",
                        help="기존 파일 덮어쓰기")
    args = parser.parse_args()

    cfg = _load_or_default(args.config)

    grid       = args.grid       or cfg.extract.grid_file
    era5_dir   = args.era5_dir   or cfg.era5.output_dir
    hourly_dir = args.hourly_dir or cfg.extract.hourly_dir
    daily_dir  = args.daily_dir  or cfg.extract.daily_dir
    utc_offset = args.utc_offset if args.utc_offset is not None else cfg.region.utc_offset
    start_year = args.start_year if args.start_year is not None else cfg.extract.start_year
    end_year   = args.end_year   if args.end_year   is not None else cfg.extract.end_year

    for label, value in [
        ("grid_file",  grid),
        ("era5_dir",   era5_dir),
        ("hourly_dir", hourly_dir),
        ("daily_dir",  daily_dir),
    ]:
        if not value:
            parser.error(f"{label} 미지정: CLI 또는 util_py.yaml 필요")

    print("=" * 62)
    print("  ERA5 격자점 기상자료 추출")
    print("=" * 62)
    print(f"  설정 출처    : {args.config or find_config() or '(코드 기본값)'}")
    print(f"  격자점 파일  : {grid}")
    print(f"  ERA5 폴더    : {era5_dir}")
    print(f"  UTC 오프셋   : {utc_offset:+d}h")
    print(f"  연도 범위    : {start_year or '자동'} ~ {end_year or '자동'}")
    print(f"  시간단위 출력: {hourly_dir}")
    print(f"  일단위 출력  : {daily_dir}")
    print("=" * 62 + "\n")

    result = extract_era5_to_grid(
        grid_csv_or_shp  = grid,
        era5_nc_dir      = era5_dir,
        output_hourly_dir= hourly_dir,
        output_daily_dir = daily_dir,
        utc_offset       = utc_offset,
        start_year       = start_year,
        end_year         = end_year,
        overwrite        = args.overwrite,
    )

    print(f"\n{'='*62}")
    print(f"  완료: {result['n_hourly_written']}개 시간파일 / "
          f"{result['n_daily_written']}개 일파일 저장")
    if result["skipped"]:
        print(f"  건너뜀: {result['skipped']}")
    print(f"{'='*62}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
