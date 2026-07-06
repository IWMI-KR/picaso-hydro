"""장기 채널 일유량 → outlet별 ① 월평년 + ④ FDC 임계선.

`4_drought_risk/climatology/channel_daily_YYYY_YYYY.csv`(wide: date + outlet열)를 읽어
각 outlet의 월별 평년유량(1~12월)과 유황곡선 임계유량(Q275/Q355 등)을 산정한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from swat_py.drought.fdc import fdc_thresholds


def climatology_tag(cfg) -> str:
    """장기 기후 결과 파일명 태그 ``{출력시작}_{eyear}`` (하드코딩 대신 자동 산출).

    출력 시작연도 = ``drought.syear + warm_up_years``(웜업 기간 제외 후 출력).
    drought.syear 미설정 시 climatology_years[0] 로 하위호환.
    예) syear=1982·웜업3·eyear=2024 → ``"1985_2024"``.
    """
    dc = cfg.Drought
    warmup = int(getattr(cfg, "CioNYSKIP", 0) or 0)
    syear = dc.syear or (dc.climatology_years[0] if dc.climatology_years else 2003)
    eyear = dc.eyear or (dc.climatology_years[-1] if dc.climatology_years else 2024)
    return f"{int(syear) + warmup}_{int(eyear)}"


def climatology_flow_path(cfg):
    """장기 기후 유량 CSV 경로 — **월유량 시계열**(channel_monthly_{tag}.csv).

    climatology_run 이 시간 절약을 위해 월단위만 생산하므로 일유량 파일은 없다. 가뭄단계
    경계(fdc_exceedance)는 이 월유량 분포에서 산정된다. drought.climatology_csv 명시 시 그 값 우선.
    """
    dc = cfg.Drought
    if dc.climatology_csv:
        return Path(dc.climatology_csv)
    return (Path(cfg.PrjDir) / "4_drought_risk" / "climatology"
            / f"channel_monthly_{climatology_tag(cfg)}.csv")


# 하위호환 별칭 — 기존 호출부(dashboard_data·reclassify·run)는 이제 월유량 파일을 받는다.
climatology_daily_path = climatology_flow_path


def load_daily_flow(csv_path) -> pd.DataFrame:
    """wide 유량 CSV 로드 (date 파싱). 컬럼 = outlet 이름. (월단위 시계열)."""
    return pd.read_csv(csv_path, parse_dates=["date"])


def monthly_climatology(daily: pd.DataFrame, outlet: str) -> pd.DataFrame:
    """outlet의 월별 평년(1~12): mean·p25·p50·p75 (일유량의 월평균 후 연간 통계)."""
    s = daily[["date", outlet]].dropna().copy()
    s["year"] = s["date"].dt.year
    s["month"] = s["date"].dt.month
    # 연·월 평균 → 월별 다년 통계
    ym = s.groupby(["year", "month"])[outlet].mean().reset_index()
    g = ym.groupby("month")[outlet]
    out = pd.DataFrame({
        "month": range(1, 13),
    }).merge(
        pd.DataFrame({
            "month": g.mean().index,
            "mean": g.mean().values,
            "p25": g.quantile(0.25).values,
            "p50": g.median().values,
            "p75": g.quantile(0.75).values,
        }), on="month", how="left")
    return out


def outlet_climatology_and_thresholds(daily: pd.DataFrame, outlet: str) -> Dict:
    """outlet의 ① 월평년 + ④ FDC 임계선(dict) 반환."""
    clim = monthly_climatology(daily, outlet)
    thr = fdc_thresholds(daily[outlet].dropna().values)
    return {"outlet": outlet, "monthly": clim, "thresholds": thr}


def compute_all(daily_csv, outlets) -> Dict[str, Dict]:
    """모든 outlet에 대해 평년+임계선 산정. outlets = outlet 이름 리스트."""
    daily = load_daily_flow(daily_csv)
    return {o: outlet_climatology_and_thresholds(daily, o)
            for o in outlets if o in daily.columns}
