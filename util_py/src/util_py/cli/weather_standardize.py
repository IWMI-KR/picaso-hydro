"""
기상자료 SWAT 표준 포맷 변환 CLI

표준 컬럼
----------
Daily : date, pcp_mm, tmax_c, tmin_c, tavg_c, tdew_c, hmd_pct, slr_mjm2,
        ws10_ms, ws2_ms, source
Hourly: datetime, pcp_mm, tavg_c, tdew_c, hmd_pct, slr_wm2,
        ws10_ms, ws2_ms, source

  - hmd_pct : Magnus 식 (FAO-56) tavg+tdew → 상대습도
  - ws2_ms  : FAO-56 로그 풍속 (z=10m → ≈ 0.748×u_10)
  - GSOD slr: 데이터 없음 → NaN

사용법
------
    util-weather-standardize                              # 모두 (era5+gsod+local)
    util-weather-standardize --source era5 --resolution daily
    util-weather-standardize --source gsod
    util-weather-standardize --source local --mapping mapping.yaml
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

from util_py.config import Config, find_config, load_config
from util_py.weather_std import (
    standardize_dir_era5_daily,
    standardize_dir_era5_hourly,
    standardize_dir_gsod_daily,
    standardize_local,
)


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
    return cfg


def _run_era5(cfg: Config, resolution: str) -> None:
    e = cfg.weather_std.era5
    if resolution in ("daily", "both"):
        if Path(e.raw_daily_dir).is_dir():
            n = standardize_dir_era5_daily(e.raw_daily_dir, e.std_daily_dir,
                                            wind_height_m=e.wind_height_m)
            print(f"  [ERA5 daily ] {n}개 → {e.std_daily_dir}")
        else:
            print(f"  [ERA5 daily ] raw_dir 없음 ({e.raw_daily_dir})")
    if resolution in ("hourly", "both"):
        if Path(e.raw_hourly_dir).is_dir():
            n = standardize_dir_era5_hourly(e.raw_hourly_dir, e.std_hourly_dir,
                                             wind_height_m=e.wind_height_m)
            print(f"  [ERA5 hourly] {n}개 → {e.std_hourly_dir}")
        else:
            print(f"  [ERA5 hourly] raw_dir 없음 ({e.raw_hourly_dir})")


def _run_gsod(cfg: Config) -> None:
    g = cfg.weather_std.gsod
    if Path(g.raw_dir).is_dir():
        n = standardize_dir_gsod_daily(g.raw_dir, g.std_dir,
                                        wind_height_m=g.wind_height_m)
        print(f"  [GSOD daily ] {n}개 → {g.std_dir}")
    else:
        print(f"  [GSOD daily ] raw_dir 없음 ({g.raw_dir})")


def _run_local(cfg: Config, mapping_path: str | None, resolution: str) -> None:
    lc = cfg.weather_std.local
    mapping_file = Path(mapping_path) if mapping_path else Path(lc.mapping_file)
    if not mapping_file.is_file():
        print(f"  [LOCAL]      mapping.yaml 없음 ({mapping_file}) — 변환 건너뜀")
        return
    with mapping_file.open(encoding="utf-8") as f:
        mapping = yaml.safe_load(f)

    if resolution in ("daily", "both"):
        raw_d = Path(lc.raw_daily_dir)
        if raw_d.is_dir():
            out_d = Path(lc.std_daily_dir); out_d.mkdir(parents=True, exist_ok=True)
            n = 0
            for csv in sorted(raw_d.glob("*.csv")):
                standardize_local(csv, mapping, out_d / csv.name, resolution="daily")
                n += 1
            print(f"  [LOCAL daily] {n}개 → {out_d}")
    if resolution in ("hourly", "both"):
        raw_h = Path(lc.raw_hourly_dir)
        if raw_h.is_dir():
            out_h = Path(lc.std_hourly_dir); out_h.mkdir(parents=True, exist_ok=True)
            n = 0
            for csv in sorted(raw_h.glob("*.csv")):
                standardize_local(csv, mapping, out_h / csv.name, resolution="hourly")
                n += 1
            print(f"  [LOCAL hour ] {n}개 → {out_h}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="기상자료 SWAT 표준 포맷 변환 (ERA5/GSOD/local)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=None,
                        help="util_py.yaml 경로")
    parser.add_argument("--source", choices=["era5", "gsod", "local", "all"],
                        default="all", help="자료 출처")
    parser.add_argument("--resolution", choices=["daily", "hourly", "both"],
                        default="both", help="시간 해상도")
    parser.add_argument("--mapping", default=None,
                        help="local source 매핑 YAML (YAML weather_std.local.mapping_file 오버라이드)")
    args = parser.parse_args()

    cfg = _load_or_default(args.config)

    print("=" * 64)
    print("  기상자료 SWAT 표준 포맷 변환")
    print("=" * 64)
    print(f"  source     : {args.source}")
    print(f"  resolution : {args.resolution}")
    print("=" * 64)

    if args.source in ("era5", "all"):
        _run_era5(cfg, args.resolution)
    if args.source in ("gsod", "all"):
        _run_gsod(cfg)   # GSOD 는 daily 만
    if args.source in ("local", "all"):
        _run_local(cfg, args.mapping, args.resolution)

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
