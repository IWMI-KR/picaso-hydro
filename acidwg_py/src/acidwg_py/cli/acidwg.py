"""
acidwg_py 실행 CLI — APCC 계절예측 통계적 상세화

사용법
------
    # acidwg_py.yaml 자동 탐색 (cwd → 상위)
    acidwg-run

    # 명시적 설정 파일
    acidwg-run /path/to/my.yaml
    acidwg-run --config /path/to/my.yaml

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
from acidwg_py.run import acid_run


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

    season_label = next(
        (k for k, v in SEASON_MONTHS.items() if v == cfg["sim_period"]),
        str(cfg["sim_period"]),
    )

    print("=" * 62)
    print("  acidwg_py — APCC 계절예측 통계적 상세화")
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


if __name__ == "__main__":
    sys.exit(main())
