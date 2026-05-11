"""합성 관측 자료 생성 — 보정 함수 기능 테스트용.

실제 관측 자료가 없거나 보정 알고리즘만 단위 시험하고 싶을 때 사용.

생성 모델
---------
flow : base + amp · sin(2π(jd - phase)/365) + AR(1) 노이즈
ss   : flow 와 양의 상관 + 임계치 hysteresis (간략)
tn   : 일정 평균 + 계절 변동 + 노이즈
tp   : tn 의 0.1~0.3 배수 + 노이즈

용도
----
- 보정 알고리즘 자동 시험 (실제 자료 부재 시)
- 단위 변환 검증
- 폴더·yaml 컨벤션 확인
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd


def generate_synthetic_flow(
    start_date: str,
    end_date: str,
    *,
    mean_m3s:        float = 1.0,
    seasonal_amp:    float = 0.5,
    phase_day:       int = 60,       # 봄철 첨두 (일 단위 jd)
    noise_std:       float = 0.15,   # AR(1) 잔차 표준편차 (m3/s)
    ar1_rho:         float = 0.7,    # 1일 후행 자기상관
    seed:            int = 0,
) -> pd.DataFrame:
    """합성 일유량 시계열 생성.

    Returns
    -------
    DataFrame with columns: date, flow_m3s (모두 양수)
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start_date, end_date, freq="D")
    n = len(dates)
    jd = np.array([d.timetuple().tm_yday for d in dates], dtype=float)

    # 결정론적 (계절 sinusoidal)
    seasonal = mean_m3s + seasonal_amp * np.sin(2.0 * np.pi * (jd - phase_day) / 365.0)

    # AR(1) 노이즈
    noise = np.zeros(n)
    eps = rng.normal(0.0, noise_std, n)
    noise[0] = eps[0]
    for i in range(1, n):
        noise[i] = ar1_rho * noise[i - 1] + eps[i]

    flow = seasonal + noise
    flow = np.maximum(flow, 0.001)   # 양수 보장

    return pd.DataFrame({
        "date":     [d.strftime("%Y-%m-%d") for d in dates],
        "flow_m3s": np.round(flow, 4),
    })


def generate_synthetic_water_quality(
    start_date: str,
    end_date: str,
    *,
    time_step:    str = "monthly",   # daily | monthly | 10day
    mean_ss_mgl:  float = 12.0,
    mean_tn_mgl:  float = 0.35,
    mean_tp_mgl:  float = 0.045,
    noise_pct:    float = 0.25,       # 평균 대비 표준편차 비율
    seed:         int = 1,
) -> pd.DataFrame:
    """합성 수질 시계열 (SS/TN/TP, mg/L).

    Returns
    -------
    DataFrame with columns: date, ss_mgl, tn_mgl, tp_mgl
    """
    rng = np.random.default_rng(seed)
    freq = {"daily": "D", "10day": "10D", "monthly": "MS"}[time_step]
    dates = pd.date_range(start_date, end_date, freq=freq)
    n = len(dates)

    def _series(mean: float) -> np.ndarray:
        # 평균 + 계절 변동 + log-normal 노이즈 (양수 보장)
        jd = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
        seasonal = mean * (1.0 + 0.3 * np.sin(2.0 * np.pi * (jd - 30) / 365.0))
        noise = rng.lognormal(0.0, noise_pct, n)
        return np.maximum(seasonal * noise, 1e-4)

    return pd.DataFrame({
        "date":   [d.strftime("%Y-%m-%d") for d in dates],
        "ss_mgl": np.round(_series(mean_ss_mgl), 3),
        "tn_mgl": np.round(_series(mean_tn_mgl), 4),
        "tp_mgl": np.round(_series(mean_tp_mgl), 5),
    })


def generate_synthetic_obs_for_calibration(
    cfg,
    *,
    seed: int = 0,
    introduce_missing_pct: float = 0.0,
) -> dict:
    """yaml.calibration.observations 의 각 항목에 대응하는 합성 자료를 생성 후 저장.

    Parameters
    ----------
    cfg                   : EnvConfig — yaml.calibration 정보 보유
    seed                  : 난수 시드 (재현성)
    introduce_missing_pct : 결측 비율 (0.0~1.0) — 일부 행을 -99 로

    Returns
    -------
    dict — {observation_id: output_path}
    """
    out_paths = {}
    start = cfg.CalPeriodStart or cfg.SimStartDate
    end   = cfg.ValPeriodEnd   or cfg.SimEndDate
    if not start or not end:
        raise ValueError(
            "yaml 에 calibration.period 또는 simulation.start_date / end_date 필요"
        )

    rng = np.random.default_rng(seed)
    for i, obs in enumerate(cfg.Observations):
        if obs.variable == "flow":
            df = generate_synthetic_flow(start, end, seed=seed + i)
            df = df.rename(columns={"flow_m3s": obs.obs_column}) \
                   if obs.obs_column != "flow_m3s" else df
        elif obs.variable in ("ss", "tn", "tp"):
            df = generate_synthetic_water_quality(
                start, end, time_step=obs.time_step, seed=seed + i + 100
            )
            df = df[["date", f"{obs.variable}_mgl"]]
            if obs.obs_column != f"{obs.variable}_mgl":
                df = df.rename(columns={f"{obs.variable}_mgl": obs.obs_column})
        else:
            continue

        # 결측 일부 주입 (선택)
        if introduce_missing_pct > 0:
            val_col = [c for c in df.columns if c != "date"][0]
            mask = rng.random(len(df)) < introduce_missing_pct
            df.loc[mask, val_col] = -99

        out_path = Path(obs.obs_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        out_paths[obs.id] = out_path

    return out_paths
