"""대상 국가 국가단위 DB 일괄 다운로드 (Stage 1) + 사용자 영역 UTM 클립 (Stage 2) CLI.

개별 util-* 명령을 한 번에 순차 실행한다. 상세 동작은 util_py.national 참조.

사전 준비
  1) 0_database/gis/admin/country_boundary.csv 를 대상 국가 한 행만 남기고 편집, 또는
  2) 0_database/gis/user/boundary-{area}.shp 배치 (있으면 UTM 클립까지 자동 실행)

사용법
------
    util-download-national                          # 전 단계 (연도는 util_py.yaml)
    util-download-national --start-year 2015
    util-download-national --no-validate --no-streamflow
    util-download-national --skip weather-validate streamflow-download
    util-download-national --no-clip                # Stage 2 클립 생략
    util-download-national --continue-on-error      # 실패해도 다음 단계 진행

환경변수
---------
    UTIL_PY_CONFIG  util_py.yaml 경로
    PICASO_ROOT     프로젝트 루트
"""
from __future__ import annotations

import argparse

from util_py.national import download_national_database


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="대상 국가 국가단위 DB 일괄 다운로드 + 사용자 영역 UTM 클립(조건부)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=None,
                        help="util_py.yaml 경로 (생략 시 자동 탐색)")
    parser.add_argument("--start-year", type=int, default=None,
                        help="ERA5 다운로드 시작 연도 (생략 시 util_py.yaml era5.start_year)")
    parser.add_argument("--no-validate", action="store_true",
                        help="weather-validate(ERA5 vs 관측 검증) 생략")
    parser.add_argument("--no-streamflow", action="store_true",
                        help="streamflow-download(유량 자료) 생략")
    parser.add_argument("--no-clip", action="store_true",
                        help="사용자 shape 있어도 Stage 2 UTM 클립 생략")
    parser.add_argument("--skip", nargs="+", default=[], metavar="STEP",
                        help="건너뛸 단계 이름 (예: weather-validate streamflow-download)")
    parser.add_argument("--continue-on-error", action="store_true",
                        help="단계 실패 시에도 다음 단계 계속 진행 (기본: 첫 실패 시 중단)")
    args = parser.parse_args(argv)

    results = download_national_database(
        config=args.config,
        start_year=args.start_year,
        validate=not args.no_validate,
        streamflow=not args.no_streamflow,
        clip=not args.no_clip,
        skip=args.skip,
        continue_on_error=args.continue_on_error,
    )
    # 실패가 하나라도 있으면 비정상 종료코드
    failed = [r for r in results if r["status"].startswith(("ERROR", "rc=", "exit="))]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
