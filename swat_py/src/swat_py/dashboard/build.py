"""High-level dashboard 자료 생성 — 1000 멤버 SWAT 출력 → forecast.json + timeseries.json."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Union

import numpy as np
import pandas as pd

from swat_py.dashboard.aggregate import (
    aggregate_ensemble_monthly,
    compute_terciles,
    historical_monthly_mean,
    load_ensemble_outputs,
)
from swat_py.dashboard.json_writers import (
    write_forecast_json,
    write_timeseries_json,
)


def build_dashboard_data(
    cfg,
    *,
    year:        int,
    season:      str,
    outlet_id:   int = 1,
    location:    str = "default",
    model:       str = "swat_plus",
    period_label: str = "operational",
    obs_swat_era5_df: Optional[pd.DataFrame] = None,
    historical_obs_df: Optional[pd.DataFrame] = None,
    thresholds: Optional[Dict[str, float]] = None,
    output_root: Optional[Union[str, Path]] = None,
) -> Dict:
    """1000 멤버 SWAT 출력 → JSX 가 직접 읽는 forecast.json + timeseries.json 생성.

    Parameters
    ----------
    cfg                 : EnvConfig (yaml 로드 결과)
    year, season        : 운영 시즌 (예: 2025, "JFM")
    outlet_id           : Dashboard 가 표시할 채널 ID
    location, model     : 출력 경로 분기 (data/{period}/{location}/{model}/)
    obs_swat_era5_df    : Observed 라인용 — SWAT(ERA5) 일자료 (date, flow_m3s).
                          미제공 시 멤버 평균을 임시 obs 로 사용 (mock).
    historical_obs_df   : 역사 baseline (date, flow_m3s) — hist 라인 + tercile 임계용
    thresholds          : {watch_warning, warning_crisis} — 미명시 시 hist p75/p95 자동
    output_root         : 출력 root. 미명시 시 cfg.output_root/dashboard/

    Returns
    -------
    dict — {forecast_json, timeseries_json, ensemble_summary_csv}
    """
    # 0. 입력 폴더 — 3_swatplus/forecast/operational/{year}/{season}/runs/
    forecast_dir = (Path(cfg.ForecastDir) / period_label
                    / str(year) / season / "runs")
    if not forecast_dir.is_dir():
        # fallback: runs 가 없으면 그 자체가 멤버 폴더 부모
        forecast_dir = Path(cfg.ForecastDir) / period_label / str(year) / season

    # 1. 멤버 SWAT 출력 → DataFrame (date × member)
    ens_df = load_ensemble_outputs(
        forecast_dir, outlet_id=outlet_id,
        model_type=cfg.ModelType,
    )

    # 2. 월평균 + 분위수
    monthly = aggregate_ensemble_monthly(ens_df)
    # monthly: date, mean, p5, p25, p50, p75, p95

    # 3. 시즌 tercile (예: 시즌 평균 vs 역사 p33/p67)
    if historical_obs_df is None:
        # mock — hist baseline 이 없으면 멤버 분포 자체로 산출 (정상은 baseline)
        season_means = ens_df.resample("MS").mean().mean(axis=0).values
        hist_p33 = float(np.percentile(season_means, 33))
        hist_p67 = float(np.percentile(season_means, 67))
        hist_monthly_df = pd.DataFrame({
            "month": list(range(1, 13)),
            "mean":  [float(np.nanmean(season_means))] * 12,
            "p33":   [hist_p33] * 12, "p67": [hist_p67] * 12,
        })
    else:
        hist_monthly_df = historical_monthly_mean(historical_obs_df, "flow_m3s")
        season_months = _season_to_months(season)
        hist_season = hist_monthly_df[hist_monthly_df["month"].isin(season_months)]
        hist_p33 = float(hist_season["p33"].mean())
        hist_p67 = float(hist_season["p67"].mean())

    season_member_means = ens_df.resample("MS").mean().mean(axis=0).values
    terciles = compute_terciles(season_member_means, hist_p33, hist_p67)

    # 4. obs 라인 (SWAT(ERA5) 또는 mock = 멤버 평균)
    if obs_swat_era5_df is not None:
        obs_daily = obs_swat_era5_df.copy()
        obs_daily["date"] = pd.to_datetime(obs_daily["date"])
        # 월평균
        obs_monthly_df = (obs_daily.set_index("date")
                          .resample("MS").mean().reset_index()
                          .rename(columns={"flow_m3s": "value"}))
    else:
        # mock — ensemble 시작 12개월 전부터 멤버 평균
        ens_mean_daily = ens_df.mean(axis=1).reset_index()
        ens_mean_daily.columns = ["date", "value"]
        obs_monthly_df = (ens_mean_daily.set_index("date")
                          .resample("MS").mean().reset_index())
        # forecast 시작 이후는 obs 로 표시 안 함 (None)
        # 사실 mock 모드에서는 forecast 와 같은 시기라 obs 가 비게 됨 → keep all

    # 5. thresholds (yaml 또는 hist 기반)
    if thresholds is None:
        if historical_obs_df is not None:
            obs_clean = historical_obs_df[
                historical_obs_df["flow_m3s"].replace(-99, np.nan).notna()
            ]["flow_m3s"].values
            thresholds = {
                "watch_warning":  float(np.percentile(obs_clean, 75)),
                "warning_crisis": float(np.percentile(obs_clean, 95)),
            }
        else:
            thresholds = {
                "watch_warning":  float(np.percentile(season_member_means, 75)),
                "warning_crisis": float(np.percentile(season_member_means, 95)),
            }

    # 6. 출력
    out_root = Path(output_root) if output_root else (
        Path(cfg.output_root) / "dashboard"
        if hasattr(cfg, "output_root") else
        Path(cfg.ForecastDir).parent.parent
    )
    out_dir = (Path(out_root) / "data" / period_label / location / model)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ensemble 일자료 요약 csv (참고용)
    summary_csv = out_dir / "ensemble_monthly.csv"
    monthly.to_csv(summary_csv, index=False)

    # forecast.json
    forecast_json_path = write_forecast_json(
        out_dir / "forecast.json",
        streamflow_terciles=terciles,
    )

    # timeseries.json
    ts_obs = obs_monthly_df.rename(columns={obs_monthly_df.columns[1]: "value"})
    ts_obs = ts_obs[["date", "value"]]
    timeseries_json_path = write_timeseries_json(
        out_dir / "timeseries.json",
        hist_monthly=hist_monthly_df,
        obs_monthly=ts_obs,
        forecast_monthly=monthly,
        thresholds=thresholds,
    )

    return {
        "forecast_json":         forecast_json_path,
        "timeseries_json":       timeseries_json_path,
        "ensemble_summary_csv":  summary_csv,
        "terciles":              terciles,
        "thresholds":            thresholds,
    }


def _season_to_months(season: str) -> list:
    """JFM/FMA/.../DJF → [1,2,3] 등."""
    season_map = {
        "JFM": [1,2,3],   "FMA": [2,3,4],   "MAM": [3,4,5],
        "AMJ": [4,5,6],   "MJJ": [5,6,7],   "JJA": [6,7,8],
        "JAS": [7,8,9],   "ASO": [8,9,10],  "SON": [9,10,11],
        "OND": [10,11,12],"NDJ": [11,12,1], "DJF": [12,1,2],
    }
    return season_map.get(season.upper(), [1, 2, 3])
