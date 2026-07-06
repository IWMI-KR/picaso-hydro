"""
acidwg_py 실행 CLI — APCC 계절예측 통계적 상세화

사용법
------
    # 공통 예측연월 (기본·권장) — picaso-hydro.yaml forecast.period 로 단일 실행
    acidwg-run                                       # 인자 없이: forecast.period(예 2016_AMJ)
    acidwg-run --forecast 2020_JFM                   # 예측연월 직접 지정(덮어쓰기)
    #   연도 ≤ 관측 eyear → hindcast, 이후 → operational 자동 분기
    #   (picaso-hydro.yaml 이 없거나 forecast.period 미설정 시 아래 operational 기본값 사용)

    # operational — acidwg_py.yaml operational.year/season 단일 (year, season)
    acidwg-run --seasons all                         # operational 일괄(공통값 무시)
    acidwg-run /path/to/my.yaml
    acidwg-run --config /path/to/my.yaml

    # operational 일괄 — 한 해의 여러 시즌 (yaml.operational.year 유지)
    acidwg-run --seasons all                         # 12 계절 모두
    acidwg-run --seasons JFM FMA MAM                 # 일부 계절만

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
    parser.add_argument("--forecast", default=None, metavar="YYYY_SSS",
                        help="예측연월 단일 실행 (기본: picaso-hydro.yaml forecast.period). "
                             "연도 ≤ 관측 eyear 이면 hindcast, 이후면 operational 자동 분기")
    parser.add_argument("--hindcast", action="store_true",
                        help="hindcast 모드 — yaml 의 hindcast 블록 일괄 실행")
    parser.add_argument("--years", nargs="+", type=int, default=None,
                        metavar="YEAR",
                        help="hindcast: 처리할 연도 일부 (yaml 범위 안에서)")
    parser.add_argument("--seasons", nargs="+", default=None,
                        metavar="SEASON",
                        help="처리할 계절 — operational: yaml.year 의 여러 시즌 일괄, "
                             "hindcast: yaml.hindcast.seasons 안에서 일부. "
                             "'all' 또는 코드 리스트 (JFM FMA ...)")
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

    # 인자 없이 실행 시 공통 예측연월(picaso-hydro.yaml forecast.period) 우선 — SSOT.
    #   --forecast 명시 시 항상 사용. 암시(공통값)일 땐 operational 일괄(--seasons)이 없을 때만.
    forecast = args.forecast or (None if args.seasons else cfg.get("forecast_period"))
    if forecast:
        return _run_forecast_period(cfg, config_path, forecast)

    return _run_operational(cfg, config_path, args)


def _resolve_op_seasons(args_seasons, default_season_code: str) -> list:
    """operational 모드의 처리할 계절 리스트 결정.

    - args.seasons 미지정: yaml 의 단일 season (default_season_code) 만
    - 'all': 12 계절 모두
    - 리스트: 명시 (대소문자 무관) — 잘못된 코드는 SystemExit
    """
    if not args_seasons:
        return [default_season_code]
    if len(args_seasons) == 1 and args_seasons[0].lower() == "all":
        return list(SEASON_MONTHS.keys())
    out = []
    for s in args_seasons:
        s_up = s.upper()
        if s_up not in SEASON_MONTHS:
            raise SystemExit(
                f"오류: 지원하지 않는 계절 코드 '{s}'\n"
                f"  사용 가능: {list(SEASON_MONTHS.keys())} 또는 'all'"
            )
        out.append(s_up)
    return out


def _run_operational(cfg, config_path, args) -> int:
    from pathlib import Path

    default_season = next(
        (k for k, v in SEASON_MONTHS.items() if v == cfg["sim_period"]),
        None,
    )
    if default_season is None:
        # months 직접 지정 케이스 — batch 와 호환 안 됨
        if args.seasons:
            raise SystemExit(
                "오류: yaml.operational 에 'months' 를 직접 지정한 경우 "
                "--seasons 일괄 모드를 사용할 수 없습니다. "
                "season 코드(JFM 등)로 변경하거나 --seasons 빼고 단발 실행하세요."
            )
        # 단발 실행 (기존 동작)
        return _run_operational_single(cfg, config_path,
                                        cfg["sim_period"], None)

    season_codes = _resolve_op_seasons(args.seasons, default_season)
    year = cfg["forecast_year"]

    if len(season_codes) == 1:
        # 단발 실행 (기존 동작과 동일 출력)
        sim_period = SEASON_MONTHS[season_codes[0]]
        return _run_operational_single(cfg, config_path, sim_period,
                                        season_codes[0])

    # 일괄 실행
    print("=" * 62)
    print(f"  acidwg_py — operational 일괄 ({year} × {len(season_codes)} 시즌)")
    print("=" * 62)
    print(f"  설정 파일    : {config_path}")
    print(f"  관측 기간    : {cfg['syear_obs']} ~ {cfg['eyear_obs']}")
    print(f"  예보 연도    : {year}")
    print(f"  처리 시즌    : {season_codes}")
    print(f"  앙상블 수    : {cfg['n_ensemble']}")
    print(f"  picaso_dir   : {cfg['picaso_dir']}")
    print(f"  출력 root    : {cfg['output_root']}/forecast/")
    print("=" * 62)
    print()

    if args.dry_run:
        for s in season_codes:
            fc = Path(cfg["picaso_dir"]) / f"{year}_{s}_picaso.csv"
            mark = "✓" if fc.is_file() else "MISS"
            print(f"  [PLAN {mark}] {year} {s}  →  "
                  f"{cfg['output_root']}/forecast/{year}_{s}/")
        return 0

    out_paths = []
    skipped = []
    for s in season_codes:
        sim_period = SEASON_MONTHS[s]
        fc_csv = Path(cfg["picaso_dir"]) / f"{year}_{s}_picaso.csv"
        if not fc_csv.is_file():
            skipped.append((year, s, "forecast CSV 없음"))
            print(f"  [SKIP] {year} {s}: forecast CSV 없음 ({fc_csv.name})")
            continue
        out_dir = Path(cfg["output_root"]) / "forecast"   # acid_run 이 {year}_{season} 부여
        print(f"\n>>> {year} {s} 시작 <<<")
        out = acid_run(
            station_csv   = cfg["station_csv"],
            obs_dir       = cfg["obs_dir"],
            output_dir    = str(out_dir),
            sim_period    = sim_period,
            syear_obs     = cfg["syear_obs"],
            eyear_obs     = cfg["eyear_obs"],
            forecast_csv  = str(fc_csv),
            n_ensemble    = cfg["n_ensemble"],
            model_file    = cfg["model_file"],
            retrieve      = cfg["retrieve"],
            forecast_year = year,
        )
        out_paths.append(out)

    print()
    print("=" * 62)
    print(f"  operational 일괄 완료: {len(out_paths)} 시즌 처리 "
          f"(건너뜀 {len(skipped)})")
    print("=" * 62)
    return 0


def _run_operational_single(cfg, config_path, sim_period, season_code) -> int:
    season_label = season_code or str(sim_period)
    print("=" * 62)
    print("  acidwg_py — operational (단일 year × season)")
    print("=" * 62)
    print(f"  설정 파일    : {config_path}")
    print(f"  관측 기간    : {cfg['syear_obs']} ~ {cfg['eyear_obs']}")
    print(f"  예보 계절    : {season_label}  {sim_period}")
    print(f"  예보 연도    : {cfg['forecast_year']}")
    print(f"  앙상블 수    : {cfg['n_ensemble']}")
    print(f"  난수 시드    : {cfg['random_seed']}")
    print(f"  Forecast 파일: {cfg['forecast_csv']}")
    _leaf = f"{cfg['forecast_year']}_{season_code}" if season_code else str(sim_period)
    print(f"  출력 경로    : {cfg['output_dir']}/{_leaf}")
    print("=" * 62)

    out_path = acid_run(
        station_csv   = cfg["station_csv"],
        obs_dir       = cfg["obs_dir"],
        output_dir    = cfg["output_dir"],
        sim_period    = sim_period,
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


def _parse_forecast(spec: str):
    """'YYYY_SSS' → (year:int, season:str). 형식·계절코드 검증 포함."""
    try:
        y, s = str(spec).split("_", 1)
        year, season = int(y), s.upper()
    except (ValueError, AttributeError):
        raise SystemExit(f"오류: forecast 형식은 'YYYY_SSS' 여야 함: {spec!r}")
    if season not in SEASON_MONTHS:
        raise SystemExit(f"오류: 지원하지 않는 계절 코드 '{season}'\n"
                         f"  사용 가능: {list(SEASON_MONTHS.keys())}")
    return year, season


def _run_forecast_period(cfg, config_path, forecast: str) -> int:
    """공통 예측연월(picaso-hydro.yaml forecast.period 또는 --forecast) 단일 실행.

    연도 ≤ 관측 eyear 이면 hindcast(검증, observation_eyear_cap), 이후면 operational 로
    자동 분기 — 통합 파이프라인(swat_py.drought.run)과 동일 규칙.
    """
    fyear, season = _parse_forecast(forecast)
    mode = "hindcast" if fyear <= int(cfg["eyear_obs"]) else "operational"
    print("=" * 62)
    print(f"  acidwg_py — forecast.period 단일 실행 ({forecast}, {mode})")
    print("=" * 62)
    print(f"  설정 파일    : {config_path}")
    print(f"  관측 기간    : {cfg['syear_obs']} ~ {cfg['eyear_obs']}")
    print(f"  앙상블 수    : {cfg['n_ensemble']}")

    # 통합 레이아웃: 두 모드 모두 acidwg_root/forecast/{year}_{season} 로 저장
    out_dir = Path(cfg["acidwg_root"]) / "forecast" / f"{fyear}_{season}"
    if mode == "hindcast":
        print(f"  출력 경로    : {out_dir}")
        print("=" * 62)
        acid_run_hindcast(
            station_csv=cfg["station_csv"], obs_dir=cfg["obs_dir"],
            picaso_dir=cfg["picaso_dir"], output_root=cfg["acidwg_root"],
            syear_obs=cfg["syear_obs"], eyear_obs=cfg["eyear_obs"],
            years=[fyear], seasons=[season], n_ensemble=cfg["n_ensemble"],
            model_file=cfg["model_file"], retrieve=cfg["retrieve"],
            observation_eyear_cap=True,
        )
    else:                                          # operational (관측기간 이후 연도)
        fc_csv = Path(cfg["picaso_dir"]) / f"{fyear}_{season}_picaso.csv"
        print(f"  Forecast 파일: {fc_csv}")
        print(f"  출력 경로    : {out_dir}")
        print("=" * 62)
        acid_run(
            station_csv=cfg["station_csv"], obs_dir=cfg["obs_dir"],
            output_dir=str(Path(cfg["acidwg_root"]) / "forecast"),
            sim_period=SEASON_MONTHS[season],
            syear_obs=cfg["syear_obs"], eyear_obs=cfg["eyear_obs"],
            forecast_csv=str(fc_csv), n_ensemble=cfg["n_ensemble"],
            model_file=cfg["model_file"], retrieve=cfg["retrieve"],
            forecast_year=fyear,
        )
    print(f"\n완료! 출력: {out_dir}")
    return 0


def _run_hindcast(cfg, config_path, args) -> int:
    hc = cfg.get("hindcast")
    if not hc:
        print("오류: --hindcast 사용했으나 yaml 에 hindcast 블록이 없습니다.",
              file=sys.stderr)
        return 1

    years   = args.years   or hc["years"]
    seasons = hc["seasons"]
    if args.years:
        invalid = set(args.years) - set(hc["years"])
        if invalid:
            print(f"경고: yaml hindcast.years 범위 밖 연도 무시: {sorted(invalid)}",
                  file=sys.stderr)
            years = [y for y in args.years if y in hc["years"]]
    if args.seasons:
        # 'all' 또는 코드 리스트 (대소문자 무관)
        if len(args.seasons) == 1 and args.seasons[0].lower() == "all":
            cli_seasons = list(SEASON_MONTHS.keys())
        else:
            cli_seasons = []
            for s in args.seasons:
                s_up = s.upper()
                if s_up not in SEASON_MONTHS:
                    raise SystemExit(
                        f"오류: 지원하지 않는 계절 코드 '{s}'\n"
                        f"  사용 가능: {list(SEASON_MONTHS.keys())} 또는 'all'"
                    )
                cli_seasons.append(s_up)
        invalid = set(cli_seasons) - set(hc["seasons"])
        if invalid:
            print(f"경고: yaml hindcast.seasons 범위 밖 계절 무시: {sorted(invalid)}",
                  file=sys.stderr)
        seasons = [s for s in cli_seasons if s in hc["seasons"]]

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
    print(f"  출력 root    : {cfg['output_root']}/forecast/")
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
