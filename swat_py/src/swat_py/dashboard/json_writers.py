"""forecast.json / timeseries.json — Dashboard (React) 가 직접 읽는 형식.

JSX 코드 (PicasoHydrology.jsx) 의 loadForecast / loadTimeseries 가 받는 구조.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd


_MONTH_ABB = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def write_forecast_json(
    output_path: Union[str, Path],
    *,
    streamflow_terciles: Dict[str, float],   # {below, normal, above}
    water_supply_terciles: Optional[Dict[str, float]] = None,
    picaso_forecast_terciles: Optional[Dict[str, float]] = None,
    narratives: Optional[Dict[str, str]] = None,
) -> Path:
    """forecast.json — Streamflow Forecast + Water Supply + 내러티브.

    JSX 의 ForecastTable 이 받는 형식:
        streamflow_forecast: [{below: 30, normal: 40, above: 30}]
    (각 카드 한 줄 — 단일 obs 기준; 다중 obs 면 multi-row 도 가능)
    """
    data: Dict = {
        "streamflow_forecast": [streamflow_terciles],
    }
    if water_supply_terciles:
        data["water_supply_forecast"] = [water_supply_terciles]
    if picaso_forecast_terciles:
        data["picaso_forecast"] = [picaso_forecast_terciles]
    if narratives:
        data["narratives"] = narratives

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return output_path


def write_timeseries_json(
    output_path: Union[str, Path],
    *,
    hist_monthly:     pd.DataFrame,    # month(1-12), mean
    obs_monthly:      pd.DataFrame,    # date, value — 최근 12개월
    forecast_monthly: pd.DataFrame,    # date, mean, p5, p25, p50, p75, p95
    thresholds: Optional[Dict[str, float]] = None,  # {watch_warning, warning_crisis}
) -> Path:
    """timeseries.json — TimeSeriesChart 가 읽는 시계열 데이터.

    JSX 의 형식:
        data: [
          {m: "Jan", hist: 1.2, obs: 1.5, fc: null,    p5: null, p25: null, p50: null, p75: null, p95: null},
          {m: "Feb", hist: 1.0, obs: 1.3, fc: null,    ...},
          {m: "Mar", hist: 0.9, obs: null, fc: 1.4,    p5: 0.7, p25: 1.1, p50: 1.4, p75: 1.7, p95: 2.1},
          ...
        ],
        thresholds: {watch_warning: 5.0, warning_crisis: 10.0}

    obs 와 fc 의 시점은 보통 분리 — 같은 month 에 둘 다 있을 수 있음 (예보 시작 시점).
    """
    # 12 month 라벨 순서로 정렬 — 가장 최근 12개월 (obs) + 다음 3개월 (forecast) 묶음
    obs_monthly = obs_monthly.copy()
    obs_monthly["date"] = pd.to_datetime(obs_monthly["date"])
    forecast_monthly = forecast_monthly.copy()
    forecast_monthly["date"] = pd.to_datetime(forecast_monthly["date"])

    # 결합된 month index 만들기
    all_dates = sorted(set(
        list(obs_monthly["date"]) + list(forecast_monthly["date"])
    ))

    rows: List[Dict] = []
    # hist 는 월 (1~12) 기반 — 같은 month 면 같은 hist 값
    hist_by_month = {int(r["month"]): float(r["mean"])
                      for _, r in hist_monthly.iterrows()}

    obs_by_date = {d: float(v) for d, v in
                    zip(obs_monthly["date"], obs_monthly.iloc[:, 1])}
    fc_by_date = {d: r for d, r in zip(forecast_monthly["date"],
                                         forecast_monthly.to_dict("records"))}

    for d in all_dates:
        rec: Dict = {
            "m":    _MONTH_ABB[d.month - 1],
            "date": d.strftime("%Y-%m-%d"),
            "hist": hist_by_month.get(d.month),
            "obs":  obs_by_date.get(d),
            "fc":   None,
            "p5":   None, "p25":  None, "p50":  None,
            "p75":  None, "p95":  None,
        }
        if d in fc_by_date:
            fr = fc_by_date[d]
            rec["fc"]  = float(fr.get("mean", np.nan)) if not pd.isna(fr.get("mean", np.nan)) else None
            for q in ("p5", "p25", "p50", "p75", "p95"):
                v = fr.get(q, np.nan)
                rec[q] = None if pd.isna(v) else float(v)
        rows.append(rec)

    out_data: Dict = {
        "data":       rows,
        "thresholds": thresholds or {},
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2, default=_json_safe)
    return output_path


def _json_safe(obj):
    if isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    raise TypeError(f"JSON 직렬화 불가: {type(obj)}")
