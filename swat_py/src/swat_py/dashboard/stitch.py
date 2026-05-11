"""Warming-up (ERA5) + Ensemble (acidwg) 기상 자료 stitching.

목적
----
운영 예보 시점 t 에서 SWAT 실행하려면:
  - 토양수분·지하수 초기화를 위한 warm-up 기간: t-N년 ~ t-1일 (실측 기상)
  - 예보 기간: t ~ t+90일 (acidwg 멤버 N)

이 두 자료를 한 *.pcp / *.tmp 파일로 결합 (member 별).

빠진 변수 (hmd/slr/wnd)
----------------------
SWAT-Plus 의 WGEN (기상발생기) 가 -99 를 만나면 자동 합성.
본 모듈은 pcp / tmax / tmin 만 stitch 하고, 다른 변수는 -99 (또는 해당 .hmd/.slr/.wnd
파일 자체 생성 생략) 으로 처리.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

import numpy as np
import pandas as pd


def stitch_weather_files(
    warm_up_dir: Union[str, Path],     # ERA5 표준 daily — date, pcp_mm, tmax_c, tmin_c
    ensemble_member_dir: Union[str, Path],  # acidwg 멤버 — date(or year/mon/day), prcp, tmax, tmin
    output_dir: Union[str, Path],
    station_id: str,
    *,
    forecast_start_date: str,           # "2025-01-01" — 이 날부터 ensemble 사용
    forecast_end_date:   str,           # "2025-03-31"
    warm_up_start_date:  Optional[str] = None,  # None 이면 ERA5 의 가장 이른 날
) -> Path:
    """단일 station × 단일 member 에 대해 ERA5 + ensemble 기상 stitching.

    Returns
    -------
    Path : station 표준 daily CSV (date, pcp_mm, tmax_c, tmin_c)
    """
    # ERA5 자료 로드
    era5_path = Path(warm_up_dir) / f"{station_id}.csv"
    if not era5_path.is_file():
        raise FileNotFoundError(f"ERA5 자료 없음: {era5_path}")
    era5 = pd.read_csv(era5_path)
    era5["date"] = pd.to_datetime(era5["date"])

    # acidwg 멤버 자료 로드
    ens_path = Path(ensemble_member_dir) / f"{station_id}.csv"
    if not ens_path.is_file():
        raise FileNotFoundError(f"앙상블 멤버 자료 없음: {ens_path}")
    ens = pd.read_csv(ens_path)
    if "date" not in ens.columns:
        # acidwg 표준 — year/mon/day 컬럼
        ens["date"] = pd.to_datetime({
            "year":  ens.get("year", 2025),
            "month": ens["mon"],
            "day":   ens["day"],
        })
    else:
        ens["date"] = pd.to_datetime(ens["date"])

    # 컬럼 표준화 (acidwg: prcp/tmax/tmin → util_py: pcp_mm/tmax_c/tmin_c)
    rename = {"prcp": "pcp_mm", "tmax": "tmax_c", "tmin": "tmin_c"}
    ens = ens.rename(columns={k: v for k, v in rename.items() if k in ens.columns})

    fcst_start = pd.to_datetime(forecast_start_date)
    fcst_end   = pd.to_datetime(forecast_end_date)
    wup_start  = pd.to_datetime(warm_up_start_date) if warm_up_start_date else era5["date"].min()

    # warm-up = ERA5 [wup_start, fcst_start - 1day]
    wu = era5[(era5["date"] >= wup_start) & (era5["date"] < fcst_start)].copy()
    # forecast = ensemble [fcst_start, fcst_end]
    fc = ens[(ens["date"] >= fcst_start) & (ens["date"] <= fcst_end)].copy()

    if len(wu) == 0:
        raise RuntimeError(
            f"warm-up 자료 비어 있음. ERA5 범위 {era5['date'].min()}~{era5['date'].max()}, "
            f"요청 {wup_start}~{fcst_start - pd.Timedelta(days=1)}"
        )
    if len(fc) == 0:
        raise RuntimeError(
            f"ensemble 자료 비어 있음. 멤버 범위 {ens['date'].min()}~{ens['date'].max()}, "
            f"요청 {fcst_start}~{fcst_end}"
        )

    keep_cols = ["date", "pcp_mm", "tmax_c", "tmin_c"]
    wu_keep = wu[[c for c in keep_cols if c in wu.columns]]
    fc_keep = fc[[c for c in keep_cols if c in fc.columns]]

    combined = pd.concat([wu_keep, fc_keep], ignore_index=True)
    combined = combined.sort_values("date").reset_index(drop=True)
    combined["date"] = combined["date"].dt.strftime("%Y-%m-%d")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{station_id}.csv"
    combined.to_csv(out_path, index=False)
    return out_path


def stitch_all_members(
    warm_up_dir:        Union[str, Path],
    ensemble_base_dir:  Union[str, Path],  # operational/2025/JFM/
    output_base_dir:    Union[str, Path],   # stitched/2025/JFM/
    station_ids:        List[str],
    *,
    forecast_start_date: str,
    forecast_end_date:   str,
    warm_up_start_date:  Optional[str] = None,
    member_pattern:      str = "member_*",
) -> int:
    """모든 멤버 × 모든 station 에 대해 stitching 일괄.

    Returns
    -------
    int : 처리된 (멤버 × station) 쌍 수
    """
    ensemble_base_dir = Path(ensemble_base_dir)
    output_base_dir   = Path(output_base_dir)

    member_dirs = sorted(ensemble_base_dir.glob(member_pattern))
    count = 0
    for mdir in member_dirs:
        out_mem = output_base_dir / mdir.name
        for sid in station_ids:
            try:
                stitch_weather_files(
                    warm_up_dir, mdir, out_mem, sid,
                    forecast_start_date=forecast_start_date,
                    forecast_end_date=forecast_end_date,
                    warm_up_start_date=warm_up_start_date,
                )
                count += 1
            except FileNotFoundError:
                continue
    return count
