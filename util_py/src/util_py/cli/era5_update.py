"""ERA5 현재시점 자동 업데이트 CLI — grid_daily_std 최신화 (운영 예보 warm-up용).

증분 다운로드(기존 월 skip) → 격자점 추출 → SWAT 표준 daily_std. 상세는 util_py.era5_update.

사용법
------
    util-era5-update                        # config 기본 시작연도 ~ 오늘까지 증분
    util-era5-update --start-year 2010
    util-era5-update --no-standardize        # 다운로드·추출만(표준화 생략)

환경변수
---------
    UTIL_PY_CONFIG  util_py.yaml 경로
    PICASO_ROOT     프로젝트 루트
"""
from __future__ import annotations

import argparse

from util_py.era5_update import era5_update_to_present


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="ERA5 를 현재시점까지 증분 업데이트하고 grid_daily_std 최신화",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=None,
                        help="util_py.yaml 경로 (생략 시 자동 탐색)")
    parser.add_argument("--start-year", type=int, default=None,
                        help="다운로드 시작 연도 (생략 시 config 기본값; 종료=오늘)")
    parser.add_argument("--no-standardize", action="store_true",
                        help="weather-standardize 생략 (다운로드·추출만)")
    args = parser.parse_args(argv)

    era5_update_to_present(config=args.config, start_year=args.start_year,
                           standardize=not args.no_standardize)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
