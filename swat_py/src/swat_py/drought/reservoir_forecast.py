"""저수지(댐) 가뭄예측 — 월 저수량 물수지 → 만수 대비 % (capacity_fraction 단계 분류용).

drought.sources.type == "reservoir" 인 수원 전용. 각 앙상블 멤버의
reservoir_day.txt(일 flo_in·precip·evap·seep, m³/일)를 읽어, 사용자가 준
예측시점 초기수위(init_water_level_ft → 초기 저류량)에서 출발해 취수를 뺀
**월 물수지**로 예측월 저수량을 산출하고, 만수위 저수량 대비 %를 반환한다.

월 물수지 (예측 개월 순차):
    S_start(m) = min(S_end(m-1), full)           # 이월은 만수까지
    supply(m)  = S_start + Σ(flo_in+precip-evap-seep) − 취수(월)
    pct(m)     = max(supply, dead) / full × 100   # 잉여(월류) 월은 >100 → Normal
    S_end(m)   = clip(supply, dead, full)

capacity_fraction 임계 [100,85,65] 와 결합: %>100 Normal · 85~100 Watch ·
65~85 Warning · ≤65 Crisis (classify_stage4 와 방향 일치).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from swat_py.output.reader_swat_plus import parse_reservoir_day

_SECONDS_PER_DAY = 86400.0


@dataclass
class ReservoirForecastParams:
    """저수지 수원의 예측 물수지 매개변수 (registry+source+곡선에서 산출)."""
    gis_id:         int
    name:           str
    full_m3:        float          # 만수(여수로) 저수량 = capacity_fraction 기준
    dead_m3:        float          # 사수위 저수량(하한)
    init_m3:        float          # 예측시점 초기 저류량(init_water_level_ft 환산)
    withdrawal_m3s: float = 0.0    # 취수(상수)
    curve:          object = None  # StageStorageCurve — 저류량→수위(ft) 환산용(선택)


def build_reservoir_forecast_params(source, reservoir_cfg, curve) -> ReservoirForecastParams:
    """_DroughtSource + _Reservoir(registry) + StageStorageCurve → 예측 매개변수.

    - full_m3 : 곡선상 여수로(spillway_ft) 저수량 = 만수 기준.
    - dead_m3 : 곡선상 사수위(bottom_ft) 저수량.
    - init_m3 : source.init_water_level_ft(MSL ft) 곡선 환산. 미지정 시 full(만수).
    """
    import math
    from swat_py.io.reservoir import water_level_to_storage

    spillway = reservoir_cfg.spillway_ft if reservoir_cfg else float("nan")
    bottom = reservoir_cfg.bottom_ft if reservoir_cfg else float("nan")
    full_m3 = float(curve.stage_to_storage(spillway)) if not math.isnan(spillway) \
        else float(curve.storage_m3[-1])
    dead_m3 = float(curve.stage_to_storage(bottom)) if not math.isnan(bottom) else 0.0

    iwl = getattr(source, "init_water_level_ft", float("nan"))
    init_m3 = water_level_to_storage(curve, iwl) if (iwl == iwl) else full_m3  # NaN → 만수

    wdr = float(getattr(reservoir_cfg, "withdrawal_m3s", 0.0) or 0.0) if reservoir_cfg else 0.0
    gid = next(iter(source.outlets)) if source.outlets else (
        reservoir_cfg.gis_id if reservoir_cfg else 0)
    return ReservoirForecastParams(
        gis_id=int(gid), name=list(source.outlets.values())[0] if source.outlets else source.name,
        full_m3=full_m3, dead_m3=dead_m3, init_m3=init_m3, withdrawal_m3s=wdr,
        curve=curve,
    )


def monthly_capacity_series(
    daily_res: pd.DataFrame,
    *,
    full_m3: float,
    init_m3: float,
    withdrawal_m3s: float = 0.0,
    dead_m3: float = 0.0,
    use_losses: bool = True,
    months: Optional[List[int]] = None,
    curve: object = None,
) -> Dict[int, Dict[str, float]]:
    """저수지 일자료(reservoir_day) → 월별 물수지 상세.

    Returns {month: {"storage_pct", "storage_m3"(월말 저류량), "water_level_ft"}}.
    - storage_pct    : max(supply, dead)/full×100 (월류 월은 >100 → Normal).
    - storage_m3     : 월말 이월 저류량 clip(supply, dead, full).
    - water_level_ft : 월말 저류량에 대응하는 수위(curve 있을 때). 없으면 NaN.
    months 지정 시 그 월만 반환.
    """
    if full_m3 <= 0:
        return {}
    df = daily_res.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["ym"] = df["date"].dt.to_period("M")
    lc = {c.lower(): c for c in df.columns}

    def col(n):
        return (pd.to_numeric(df[lc[n]], errors="coerce").fillna(0.0)
                if n in lc else pd.Series(0.0, index=df.index))

    flo_in = col("flo_in")
    precip = col("precip") if use_losses else pd.Series(0.0, index=df.index)
    evap   = col("evap")   if use_losses else pd.Series(0.0, index=df.index)
    seep   = col("seep")   if use_losses else pd.Series(0.0, index=df.index)
    net = flo_in + precip - evap - seep
    df["_net"] = net

    out: Dict[int, Dict[str, float]] = {}
    S = float(init_m3)
    for ym, sub in df.groupby("ym", sort=True):
        s_start = min(S, full_m3)
        inflow = float(sub["_net"].sum())
        wdr = withdrawal_m3s * _SECONDS_PER_DAY * len(sub)
        supply = s_start + inflow - wdr
        pct = max(supply, dead_m3) / full_m3 * 100.0
        S = max(min(supply, full_m3), dead_m3)          # 월말 이월 저류량
        wl = float(curve.storage_to_stage(S)) if curve is not None else float("nan")
        out[int(ym.month)] = {"storage_pct": pct, "storage_m3": S, "water_level_ft": wl}

    if months is not None:
        out = {m: out[m] for m in months if m in out}
    return out


def monthly_capacity_pct(
    daily_res: pd.DataFrame,
    *,
    full_m3: float,
    init_m3: float,
    withdrawal_m3s: float = 0.0,
    dead_m3: float = 0.0,
    use_losses: bool = True,
    months: Optional[List[int]] = None,
) -> Dict[int, float]:
    """저수지 일자료(reservoir_day) → 월별 만수 대비 저수량 %.

    Returns {month: capacity_pct}. months 지정 시 그 월만.
    (monthly_capacity_series 의 storage_pct 만 뽑은 하위호환 래퍼.)
    """
    ser = monthly_capacity_series(
        daily_res, full_m3=full_m3, init_m3=init_m3, withdrawal_m3s=withdrawal_m3s,
        dead_m3=dead_m3, use_losses=use_losses, months=months)
    return {m: v["storage_pct"] for m, v in ser.items()}


def member_reservoir_series(
    run_dir: Path,
    params: ReservoirForecastParams,
    *,
    fyear: int,
    months: List[int],
    sdate: str,
) -> Optional[Dict[int, Dict[str, float]]]:
    """한 멤버 run_dir 의 reservoir_day.txt → 예측월 물수지 상세 dict (없으면 None).

    각 월: {"storage_pct", "storage_m3", "water_level_ft"}.
    """
    raw = parse_reservoir_day(Path(run_dir) / "reservoir_day.txt",
                              outlet=params.gis_id, sdate=sdate)
    if raw is None:
        return None
    raw = raw[(raw["date"].dt.year == fyear) & (raw["date"].dt.month.isin(months))]
    if raw.empty:
        return None
    return monthly_capacity_series(
        raw, full_m3=params.full_m3, init_m3=params.init_m3,
        withdrawal_m3s=params.withdrawal_m3s, dead_m3=params.dead_m3,
        months=months, curve=getattr(params, "curve", None),
    )


def member_reservoir_capacity_pct(
    run_dir: Path,
    params: ReservoirForecastParams,
    *,
    fyear: int,
    months: List[int],
    sdate: str,
) -> Optional[Dict[int, float]]:
    """한 멤버 run_dir 의 reservoir_day.txt → 예측월 만수대비 % dict (없으면 None)."""
    ser = member_reservoir_series(run_dir, params, fyear=fyear, months=months, sdate=sdate)
    if ser is None:
        return None
    return {m: v["storage_pct"] for m, v in ser.items()}
