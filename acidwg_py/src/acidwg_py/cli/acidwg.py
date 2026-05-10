"""
acidwg_py 실행 CLI — APCC 계절예측 통계적 상세화

사용법
------
    # operational (기본) — 단일 (year, season)
    acidwg-run                                       # acidwg_py.yaml 자동 탐색
    acidwg-run /path/to/my.yaml
    acidwg-run --config /path/to/my.yaml

    # hindcast — yaml 의 hindcast 블록 일괄 실행
    acidwg-run --hindcast
    acidwg-run --hindcast --years 2010 2015          # 연도 일부만
    acidwg-run --hindcast --seasons JFM FMA          # 계절 일부만
    acidwg-run --hindcast --dry-run                  # 처리 대상 목록만 출력

환경변수
---------
    ACIDWG_PY_CONFIG  acidwg_py.yaml 경로 강제 지정
    PICASO_ROOT       프로젝트 루트
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

from acidwg_py.config import SEASON_MONTHS, find_config, load_config
from acidwg_py.run import acid_run, acid_run_hindcast


def main() -> int:
    parser = argparse.ArgumentParser(
        description="acidwg_py — APCC 계절예측 통계적 상세화 (1000-멤버 앙상블)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("config_file", nargs="?", default=None,
                        help="설정 YAML 경로 (생략 시 --config 또는 자동 탐색)")
    parser.add_argument("--config", default=None, dest="config_opt",
                        help="설정 YAML 경로 (위치 인자와 동일)")
    parser.add_argument("--hindcast", action="store_true",
                        help="hindcast 모드 — yaml 의 hindcast 블록 일괄 실행")
    parser.add_argument("--years", nargs="+", type=int, default=None,
                        metavar="YEAR",
                        help="hindcast: 처리할 연도 일부 (yaml 범위 안에서)")
    parser.add_argument("--seasons", nargs="+", default=None,
                        choices=list(SEASON_MONTHS.keys()), metavar="SEASON",
                        help="hindcast: 처리할 계절 일부 (yaml 범위 안에서)")
    parser.add_argument("--dry-run", action="store_true",
                        help="hindcast: 실행 없이 처리 대상 목록만 출력")
    args = parser.parse_args()

    config_path: Path | str | None = args.config_file or args.config_opt
    if config_path is None:
        found = find_config()
        if found is None:
            parser.error(
                "설정 파일을 찾을 수 없음.\n"
                "  - acidwg_py.yaml 을 cwd 또는 상위 디렉토리에 두세요\n"
                "  - 또는 환경변수 ACIDWG_PY_CONFIG 또는 위치 인자/--config 사용"
            )
        config_path = found

    cfg = load_config(str(config_path))

    if cfg["random_seed"] is not None:
        np.random.seed(cfg["random_seed"])

    if args.hindcast:
        return _run_hindcast(cfg, config_path, args)
    else:
        return _run_operational(cfg, config_path)


def _run_operational(cfg, config_path) -> int:
    season_label = next(
        (k for k, v in SEASON_MONTHS.items() if v == cfg["sim_period"]),
        str(cfg["sim_period"]),
    )

    print("=" * 62)
    print("  acidwg_py — operational (단일 year × season)")
    print("=" * 62)
    print(f"  설정 파일    : {config_path}")
    print(f"  관측 기간    : {cfg['syear_obs']} ~ {cfg['eyear_obs']}")
    print(f"  예보 계절    : {season_label}  {cfg['sim_period']}")
    print(f"  예보 연도    : {cfg['forecast_year']}")
    print(f"  앙상블 수    : {cfg['n_ensemble']}")
    print(f"  난수 시드    : {cfg['random_seed']}")
    print(f"  Forecast 파일: {cfg['forecast_csv']}")
    print(f"  출력 경로    : {cfg['output_dir']}")
    print("=" * 62)

    out_path = acid_run(
        station_csv   = cfg["station_csv"],
        obs_dir       = cfg["obs_dir"],
        output_dir    = cfg["output_dir"],
        sim_period    = cfg["sim_period"],
        syear_obs     = cfg["syear_obs"],
        eyear_obs     = cfg["eyear_obs"],
        forecast_csv  = cfg["forecast_csv"],
        n_ensemble    = cfg["n_ensemble"],
        model_file    = cfg["model_file"],
        retrieve      = cfg["retrieve"],
        forecast_year = cfg["forecast_year"],
    )

    print(f"\n완료! 시나리오 파일: {out_path}")
    files = sorted(os.listdir(out_path))
    print(f"파일 수: {len(files)}개  (처음 6개)")
    for f in files[:6]:
        print(f"  {f}")
    return 0


def _run_hindcast(cfg, config_path, args) -> int:
    hc = cfg.get("hindcast")
    if not hc:
        print("오류: --hindcast 사용했으나 yaml 에 hindcast 블록이 없습니다.",
              file=sys.stderr)
        return 1

    years   = args.years   or hc["years"]
    seasons = args.seasons or hc["seasons"]
    if args.years:
        invalid = set(args.years) - set(hc["years"])
        if invalid:
            print(f"경고: yaml hindcast.years 범위 밖 연도 무시: {sorted(invalid)}",
                  file=sys.stderr)
            years = [y for y in args.years if y in hc["years"]]
    if args.seasons:
        invalid = set(args.seasons) - set(hc["seasons"])
        if invalid:
            print(f"경고: yaml hindcast.seasons 범위 밖 계절 무시: {sorted(invalid)}",
                  file=sys.stderr)
            seasons = [s for s in args.seasons if s in hc["seasons"]]

    print("=" * 62)
    print("  acidwg_py — hindcast (일괄)")
    print("=" * 62)
    print(f"  설정 파일    : {config_path}")
    print(f"  관측 기간    : {cfg['syear_obs']} ~ {cfg['eyear_obs']} "
          f"(eyear_cap={hc['observation_eyear_cap']})")
    print(f"  hindcast 연도: {years[0]}~{years[-1]} (총 {len(years)})")
    print(f"  hindcast 계절: {seasons}")
    print(f"  앙상블 수    : {cfg['n_ensemble']}")
    print(f"  picaso_dir   : {cfg['picaso_dir']}")
    print(f"  출력 root    : {cfg['output_root']}/hindcast/")
    print("=" * 62)

    out_paths = acid_run_hindcast(
        station_csv = cfg["station_csv"],
        obs_dir     = cfg["obs_dir"],
        picaso_dir  = cfg["picaso_dir"],
        output_root = cfg["output_root"],
        syear_obs   = cfg["syear_obs"],
        eyear_obs   = cfg["eyear_obs"],
        years       = years,
        seasons     = seasons,
        n_ensemble  = cfg["n_ensemble"],
        model_file  = cfg["model_file"],
        retrieve    = cfg["retrieve"],
        observation_eyear_cap = hc["observation_eyear_cap"],
        dry_run     = args.dry_run,
    )

    if not args.dry_run:
        print(f"\n완료! {len(out_paths)} (year × season) 작업 처리됨.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
