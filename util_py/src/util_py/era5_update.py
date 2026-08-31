"""ERA5 자료를 현재시점까지 자동 업데이트 → 표준 daily(grid_daily_std) 최신화.

운영 예보의 warm-up 자료는 예보 직전월까지 최신 관측이 필요하다. 이 함수는 ERA5 를
현재시점(오늘 기준, ERA5 지연 반영)까지 **증분** 다운로드하고 격자점 daily 로 추출·표준화한다.
    다운로드(증분·기존월 skip) → 격자점 추출 → SWAT 표준 daily_std

내부적으로 기존 util CLI(era5-download·era5-extract·weather-standardize)를 순차 호출한다.
현재 연도는 **월 단위 파일**(ERA5_{var}_hourly_{YYYYMM}.nc)로 관리되므로 재실행하면
빠진 달만 새로 받고, 이어서 격자점 추출을 `--overwrite` 로 다시 써서 기간을 늘린다.
(연 단위로 저장하면 "파일 있음"으로 skip 되어 진행 중인 연도가 갱신되지 않는다.)

프로그램:  from util_py import era5_update_to_present; era5_update_to_present()
CLI:       util-era5-update [--start-year 2010] [--config ...] [--no-standardize]
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def _std_coverage(config: Optional[str]) -> Optional[str]:
    """grid_daily_std 의 최신 커버리지 날짜(대표 격자점) — 없으면 None.

    폴더 위치는 util_py.yaml (weather_std.era5.std_daily_dir) 에서 읽는다.
    """
    import pandas as pd

    from util_py.config import load_effective_config
    std_dir = Path(load_effective_config(config).weather_std.era5.std_daily_dir)
    files = sorted(std_dir.glob("*.csv")) if std_dir.is_dir() else []
    if not files:
        return None
    try:
        df = pd.read_csv(files[0])
        return str(pd.to_datetime(df["date"]).max().date())
    except Exception:
        return None


def era5_update_to_present(config: Optional[str] = None, *,
                           start_year: Optional[int] = None,
                           standardize: bool = True) -> Optional[str]:
    """ERA5 를 현재시점까지 증분 업데이트하고 grid_daily_std 를 최신화한다.

    Parameters
    ----------
    config       : util_py.yaml 경로 (생략 시 자동 탐색)
    start_year   : 다운로드 시작 연도 (생략 시 config 기본값; 종료연도는 항상 오늘)
    standardize  : True 면 weather-standardize(--source era5)까지 실행해 grid_daily_std 갱신

    Returns
    -------
    최신 grid_daily_std 커버리지 날짜(문자열) 또는 None.
    """
    from util_py.cli import era5_download, era5_extract, weather_standardize

    argv = ["--config", config] if config else []
    before = _std_coverage(config)
    print("=" * 64)
    print("  ERA5 현재시점 자동 업데이트")
    print(f"  갱신 전 grid_daily_std 최신: {before or '(없음)'}")
    print("=" * 64)

    # ① 증분 다운로드 (기존 월 skip, 종료=오늘·현재연도는 지난달까지)
    era5_download.main(argv + ["--no-extract"]
                       + (["--start-year", str(start_year)] if start_year else []))
    # ② 격자점 daily 추출 — 기존 격자점 CSV 를 새 기간으로 다시 써야 하므로 --overwrite
    era5_extract.main(argv + ["--overwrite"])
    # ③ SWAT 표준 daily_std 갱신 (ERA5 소스)
    if standardize:
        weather_standardize.main(argv + ["--source", "era5"])

    after = _std_coverage(config)
    print("=" * 64)
    print(f"  갱신 후 grid_daily_std 최신: {after or '(없음)'}")
    print("=" * 64)
    return after
