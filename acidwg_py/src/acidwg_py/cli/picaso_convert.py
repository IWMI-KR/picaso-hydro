"""
PICASO 힌드캐스트 예보 확률 → acidwg_py 입력 파일 일괄 변환 CLI

사용법
------
    # PICASO-Hydro 자동 인식 (cwd 위로 올라가며 0_database/ 검색)
    acidwg-picaso-convert

    # 특정 계절만
    acidwg-picaso-convert --seasons JFM DJF NDJ

    # 특정 연도만
    acidwg-picaso-convert --years 2014 2015 2016

    # 다른 프로젝트
    set PICASO_ROOT=D:/MyProject
    acidwg-picaso-convert

기본 경로 (PICASO_ROOT 기준)
----------------------------
    원본 자료 : 0_database/picaso/
    관측소 CSV: 0_database/obs/weather/stations-acidwg.csv  (ID 컬럼만 사용)
    출력 폴더 : 1_acidwg/picaso/
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from acidwg_py.config import SEASON_MONTHS
from acidwg_py.picaso import build_all_picaso_forecasts


def _picaso_root() -> Path:
    """PICASO_ROOT 환경변수 또는 cwd 위로 0_database/ 가 있는 폴더."""
    if env := os.environ.get("PICASO_ROOT"):
        return Path(env)
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / "0_database").is_dir():
            return parent
    return cwd


def _defaults() -> tuple[Path, Path, Path]:
    root = _picaso_root()
    return (
        root / "0_database" / "picaso",
        # 관측소 목록 — ID 컬럼만 사용하므로 공통 stations-acidwg.csv 를 그대로 사용.
        root / "0_database" / "obs" / "weather" / "stations-acidwg.csv",
        root / "1_acidwg" / "picaso",
    )


def main() -> int:
    default_picaso, default_stations, default_output = _defaults()

    parser = argparse.ArgumentParser(
        description="PICASO 예보 확률 → acidwg_py 입력 CSV 일괄 변환",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--picaso-dir", default=str(default_picaso),
                        help=f"PICASO 원본 자료 루트 (기본: {default_picaso})")
    parser.add_argument("--stations-csv", default=str(default_stations),
                        help=f"관측소 목록 CSV (기본: {default_stations})")
    parser.add_argument("--output-dir", default=str(default_output),
                        help=f"출력 폴더 (기본: {default_output})")
    parser.add_argument("--seasons", nargs="+", default=None,
                        choices=list(SEASON_MONTHS.keys()), metavar="SEASON",
                        help="변환할 계절 코드 (기본: 전체 12개). 예: JFM DJF NDJ")
    parser.add_argument("--years", nargs="+", type=int, default=None,
                        metavar="YEAR",
                        help="변환할 연도 (기본: 자동 감지). 예: 2014 2015 2016")
    parser.add_argument("--overwrite", action="store_true",
                        help="이미 있는 출력 파일도 다시 만든다 "
                             "(기본: 있으면 건너뜀)")
    args = parser.parse_args()

    print("=" * 62)
    print("  PICASO → acidwg_py 입력 파일 변환")
    print("=" * 62)
    print(f"  원본 자료  : {args.picaso_dir}")
    print(f"  관측소 CSV : {args.stations_csv}")
    print(f"  출력 폴더  : {args.output_dir}")
    print(f"  계절       : {args.seasons or '전체 12개'}")
    print(f"  연도       : {args.years or '자동 감지'}")
    print(f"  기존 파일  : {'다시 생성' if args.overwrite else '건너뜀'}")
    print("=" * 62)

    created, missing, existing = build_all_picaso_forecasts(
        picaso_dir   = args.picaso_dir,
        stations_csv = args.stations_csv,
        output_dir   = args.output_dir,
        seasons      = args.seasons,
        years        = args.years,
        overwrite    = args.overwrite,
    )

    print(f"\n변환 완료: {len(created)}개 파일 생성")
    for path in created:
        print(f"  [OK] {os.path.basename(path)}")

    if existing:
        print(f"\n건너뜀 (이미 있음 — 다시 만들려면 --overwrite): {len(existing)}개")
        for tag in existing[:10]:
            print(f"  [SKIP] {tag}")
        if len(existing) > 10:
            print(f"  ... 외 {len(existing) - 10}개")

    if missing:
        print(f"\n건너뜀 (원본 파일 미존재): {len(missing)}개")
        for tag in missing[:10]:
            print(f"  [MISS] {tag}")
        if len(missing) > 10:
            print(f"  ... 외 {len(missing) - 10}개")

    # 새로 만든 게 없어도 기존 파일로 충족돼 있으면 정상 종료
    return 0 if (created or existing) else 1


if __name__ == "__main__":
    sys.exit(main())
