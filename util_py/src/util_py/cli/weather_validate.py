"""
ERA5 vs 관측소 산점 검증 CLI

각 ERA5 격자점에 대해 가장 가까운 관측소(GSOD 또는 local)를 선정,
같은 날짜 데이터로 변수별 1:1 산점도 + 통계 테이블 생성.

사용법
------
    util-weather-validate                              # source=gsod 기본
    util-weather-validate --source local
    util-weather-validate --variables pcp_mm tmax_c tmin_c
    util-weather-validate --regression                 # 그래프에 회귀선 추가

출력
----
    {analysis_dir}/era5_vs_{source}/
      nearest_pairs.csv
      statistics.csv
      plots/{variable}/{era5_id}__{obs_id}.png
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from util_py.config import Config, find_config, load_config
from util_py.weather_validation import scatter_compare_era5_obs


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
    cfg.weather_validation.output_base = str(root / "0_database" / "analysis")
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ERA5 격자점 vs 관측소 산점 검증",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=None, help="util_py.yaml 경로")
    parser.add_argument("--source", choices=["gsod", "local"], default="gsod",
                        help="비교 대상 obs (기본 gsod)")
    parser.add_argument("--variables", nargs="+", default=None,
                        help="비교 변수 (기본: YAML 또는 SWAT 7개)")
    parser.add_argument("--regression", action="store_true",
                        help="그래프에 회귀선 추가")
    parser.add_argument("--radius-km", type=float, default=None,
                        help="매칭 반경(km). 이내 station 모두 채택, 없으면 nearest 1개")
    parser.add_argument("--no-per-variable", action="store_true",
                        help="변수별 단일 PNG (plots/{var}/) 생략")
    parser.add_argument("--no-combined", action="store_true",
                        help="다변수 통합 PNG (plots/combined/) 생략")
    parser.add_argument("--combined-ncols", type=int, default=None,
                        help="combined plot 의 subplot 열 수 (기본 4)")
    parser.add_argument("--output-dir", default=None,
                        help="출력 폴더 (YAML weather_validation.output_base 오버라이드)")
    args = parser.parse_args()

    cfg = _load_or_default(args.config)

    out_base = Path(args.output_dir or cfg.weather_validation.output_base)
    out_dir = out_base / f"era5_vs_{args.source}"

    variables = args.variables or cfg.weather_validation.variables
    show_reg  = args.regression  or cfg.weather_validation.show_regression

    # 입력 경로
    era5_grid_pts = cfg.extract.grid_file       # gis/era5/grid_points-era5.csv
    era5_std_dir  = cfg.weather_std.era5.std_daily_dir

    if args.source == "gsod":
        obs_station_csv = cfg.gsod.station_csv
        obs_std_dir     = cfg.weather_std.gsod.std_dir
        obs_id_col      = "STATION_ID"
        obs_lat_col     = "LAT"
        obs_lon_col     = "LON"
    else:  # local
        obs_station_csv = str(Path(cfg.weather_std.local.raw_daily_dir).parent /
                              "stations.csv")
        obs_std_dir     = cfg.weather_std.local.std_daily_dir
        obs_id_col      = "ID"
        obs_lat_col     = "Lat"
        obs_lon_col     = "Lon"
        if not Path(obs_station_csv).is_file():
            parser.error(f"local stations 메타 CSV 없음: {obs_station_csv}\n"
                         f"  (Lon, Lat, ID 컬럼 필요)")

    radius_km = (args.radius_km if args.radius_km is not None
                 else cfg.weather_validation.radius_km)
    write_per_var = (not args.no_per_variable) and cfg.weather_validation.write_per_variable
    write_comb    = (not args.no_combined)     and cfg.weather_validation.write_combined
    n_cols = args.combined_ncols or cfg.weather_validation.combined_ncols

    scatter_compare_era5_obs(
        era5_grid_points_csv=era5_grid_pts,
        era5_std_dir=era5_std_dir,
        obs_station_csv=obs_station_csv,
        obs_std_dir=obs_std_dir,
        output_dir=out_dir,
        variables=variables,
        obs_source=args.source.upper(),
        obs_id_col=obs_id_col,
        obs_lat_col=obs_lat_col,
        obs_lon_col=obs_lon_col,
        radius_km=radius_km,
        show_regression=show_reg,
        write_per_variable=write_per_var,
        write_combined=write_comb,
        combined_ncols=n_cols,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
