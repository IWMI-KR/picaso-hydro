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

수위(ft) 는 두 가지 기준면으로 나온다 — **곡선 datum(MSL)** 과 **관측 눈금(staff
gauge)**. 레지스트리의 ``obs_datum_offset_ft`` 가 그 차이다(Ngerimel −22.0).
현장 운영자가 보는 자 눈금이 기준이므로 ``water_level_ft`` 는 **관측 눈금**으로
내보내고(만수 45.00 MSL → 23.00 ft), 곡선 datum 값은 ``water_level_msl_ft`` 에
함께 남긴다(요청: 유진호 2026-08-26 "현지 실측 23 m 가 만수위이니 22 를 빼서").
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from swat_py.drought.season import in_ym, period_ym
from swat_py.output.reader_swat_plus import parse_channel_sd_day, parse_reservoir_day

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
    withdrawal_monthly_m3s: Optional[List[float]] = None  # 월별(1~12월) 취수, 상수보다 우선
    curve:          object = None  # StageStorageCurve — 저류량→수위(ft) 환산용(선택)
    datum_offset_ft: float = 0.0   # 곡선(MSL) → 관측 눈금 보정. 모델 수위에 **더한다**
    # 전환유입(diversion) — 설정 시 **일 단위** 물수지로 전환된다. 미설정이면 기존 월 단위.
    diversion_from_outlet: Optional[int] = None   # 전환 수원 채널 gis_id
    diversion_max_m3s:      float = 0.0           # 전환 상한(펌프 용량)
    diversion_min_flow_m3s: float = 0.0           # 수원 하천에 남길 유량
    diversion_target_m3:    float = float("nan")  # 보충 목표 저류량. NaN → 만수


def build_reservoir_forecast_params(source, reservoir_cfg, curve) -> ReservoirForecastParams:
    """_DroughtSource + _Reservoir(registry) + StageStorageCurve → 예측 매개변수.

    - full_m3 : 곡선상 여수로(spillway_ft) 저수량 = 만수 기준.
    - dead_m3 : 곡선상 사수위(bottom_ft) 저수량.
    - init_m3 : source.init_water_level_ft(MSL ft) 곡선 환산. 미지정 시 full(만수).
    - datum_offset_ft : registry obs_datum_offset_ft. 곡선(MSL) 수위에 더하면
      관측 눈금이 된다(Ngerimel: 45.00 MSL + (−22.0) = 23.00 ft 만수).
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

    # 취수: 시나리오(source.initial_condition)가 있으면 레지스트리 물리 제원을 덮어쓴다.
    wdr = float(getattr(reservoir_cfg, "withdrawal_m3s", 0.0) or 0.0) if reservoir_cfg else 0.0
    wmon = (list(getattr(reservoir_cfg, "withdrawal_monthly_m3s", None) or [])
            if reservoir_cfg else []) or None
    s_wdr = getattr(source, "withdrawal_m3s", None)
    s_wmon = getattr(source, "withdrawal_monthly_m3s", None)
    if s_wmon:
        wmon = [float(x) for x in s_wmon]
    elif s_wdr is not None:
        wdr, wmon = float(s_wdr), None
    off = float(getattr(reservoir_cfg, "obs_datum_offset_ft", 0.0) or 0.0) if reservoir_cfg else 0.0
    gid = next(iter(source.outlets)) if source.outlets else (
        reservoir_cfg.gis_id if reservoir_cfg else 0)
    # 전환유입 — registry 설정을 그대로 쓴다(시나리오 덮어쓰기 대상 아님).
    dv_out = getattr(reservoir_cfg, "diversion_from_outlet", None) if reservoir_cfg else None
    dv_tgt_ft = float(getattr(reservoir_cfg, "diversion_target_ft", float("nan"))) \
        if reservoir_cfg else float("nan")
    dv_tgt_m3 = (float(curve.stage_to_storage(dv_tgt_ft))
                 if (dv_tgt_ft == dv_tgt_ft) else float("nan"))
    return ReservoirForecastParams(
        gis_id=int(gid), name=list(source.outlets.values())[0] if source.outlets else source.name,
        full_m3=full_m3, dead_m3=dead_m3, init_m3=init_m3, withdrawal_m3s=wdr,
        withdrawal_monthly_m3s=wmon, curve=curve, datum_offset_ft=off,
        diversion_from_outlet=(int(dv_out) if dv_out else None),
        diversion_max_m3s=float(getattr(reservoir_cfg, "diversion_max_m3s", 0.0) or 0.0)
        if reservoir_cfg else 0.0,
        diversion_min_flow_m3s=float(getattr(reservoir_cfg, "diversion_min_flow_m3s", 0.0) or 0.0)
        if reservoir_cfg else 0.0,
        diversion_target_m3=dv_tgt_m3,
    )


def full_level_ft(params: Optional[ReservoirForecastParams]) -> float:
    """만수(여수로) 수위 — **관측 눈금** ft. 곡선이 없으면 NaN.

    ``level_fraction`` 임계([100,85,65]%)를 ft 로 환산하는 기준이다
    (Ngerimel: 45.00 MSL + (−22.0) = 23.00 ft → 23.00 / 19.55 / 14.95).
    """
    if params is None or params.curve is None:
        return float("nan")
    return (float(params.curve.storage_to_stage(params.full_m3))
            + float(params.datum_offset_ft))


def capacity_pct_to_level_ft(pct: float,
                             params: Optional[ReservoirForecastParams]) -> float:
    """만수대비 저수량 % → 수위(ft, 관측 눈금). 곡선 없으면 NaN.

    저수지 **평년**은 저수량%로 저장돼 있다(climatology 산출물). 수위 기준
    대시보드의 평년선을 그리려면 같은 곡선으로 되돌려야 한다 — 곡선이 직선이
    아니므로 "85%" 를 수위 85% 로 읽으면 안 된다.
    """
    if params is None or params.curve is None or pct != pct:
        return float("nan")
    s_m3 = max(min(float(pct) / 100.0 * params.full_m3, params.full_m3),
               params.dead_m3)
    return float(params.curve.storage_to_stage(s_m3)) + float(params.datum_offset_ft)


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
    datum_offset_ft: float = 0.0,
    withdrawal_monthly_m3s: Optional[List[float]] = None,
    diversion_daily_m3: Optional[pd.Series] = None,
    diversion_target_m3: float = float("nan"),
) -> Dict[int, Dict[str, float]]:
    """저수지 일자료(reservoir_day) → 월별 물수지 상세.

    Returns {month: {"storage_pct", "storage_m3", "water_level_ft",
    "water_level_msl_ft"}}.
    - storage_pct        : max(supply, dead)/full×100 (월류 월은 >100 → Normal).
    - storage_m3         : 월말 이월 저류량 clip(supply, dead, full).
    - water_level_msl_ft : 월말 저류량에 대응하는 곡선 datum 수위. 곡선 없으면 NaN.
    - water_level_ft     : 거기에 ``datum_offset_ft`` 를 더한 **관측 눈금** 수위.
      현장 운영자가 보는 값이다(Ngerimel 만수 45.00 MSL → 23.00 ft).
    months 지정 시 그 월만 반환.

    ``withdrawal_monthly_m3s`` (1~12월 12개)를 주면 **달마다 다른 취수**를 쓴다
    (상수보다 우선). 건기에 취수를 줄이는 운영을 표현할 수 있다.

    ``diversion_daily_m3`` (date 색인, 그 날 전환 가능한 수원 잉여수 m³)를 주면
    **일 단위 운영 물수지**로 바뀐다 — 매일 유입·취수를 적용하고, 저류가
    ``diversion_target_m3``(NaN → 만수) 아래면 부족분을 그날 잉여수 한도까지 보충한 뒤
    만수에서 자른다(월류는 그 자리에서 유실). 운영 저수지(Ngerimel: 평상시 여수로 마루
    유지, 수위 저하 시 Ngerikiil 전환)를 표현하기 위한 것이다. 주지 않으면 **기존 월 단위
    물수지 그대로**다 — 전환유입을 설정하지 않은 프로젝트(쿡)의 동작은 바뀌지 않는다.
    """
    wmon = list(withdrawal_monthly_m3s) if withdrawal_monthly_m3s else None
    if wmon is not None and len(wmon) != 12:
        raise ValueError(f"withdrawal_monthly_m3s 는 12개여야 한다: {len(wmon)}개")
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
    use_div = diversion_daily_m3 is not None
    if use_div:
        # 목표 저류량 — 미지정이면 만수(= 평상시 여수로 마루 유지 운영)
        tgt = float(diversion_target_m3) if diversion_target_m3 == diversion_target_m3 \
            else float(full_m3)
        tgt = max(min(tgt, full_m3), dead_m3)
        div = pd.to_numeric(diversion_daily_m3, errors="coerce").fillna(0.0).clip(lower=0.0)
        df["_div"] = df["date"].map(div).fillna(0.0).values
    for ym, sub in df.groupby("ym", sort=True):
        w_m3s = wmon[int(ym.month) - 1] if wmon is not None else withdrawal_m3s
        if use_div:
            # 일 단위 운영 물수지 — 유입·취수 → 목표 미달 시 전환 보충 → 월류 즉시 유실.
            wdr_day = w_m3s * _SECONDS_PER_DAY
            S = min(S, full_m3)
            div_sum = 0.0
            for net, avail in zip(sub["_net"].values, sub["_div"].values):
                S = S + float(net) - wdr_day
                if S < tgt and avail > 0.0:
                    take = min(tgt - S, float(avail))
                    S += take
                    div_sum += take
                S = max(min(S, full_m3), dead_m3)
            supply = S                       # 일 단위에서는 월류·하한이 이미 반영됨
            pct = S / full_m3 * 100.0
        else:
            s_start = min(S, full_m3)
            inflow = float(sub["_net"].sum())
            wdr = w_m3s * _SECONDS_PER_DAY * len(sub)
            supply = s_start + inflow - wdr
            pct = max(supply, dead_m3) / full_m3 * 100.0
            S = max(min(supply, full_m3), dead_m3)      # 월말 이월 저류량
        msl = float(curve.storage_to_stage(S)) if curve is not None else float("nan")
        row = {"storage_pct": pct, "storage_m3": S,
               "water_level_msl_ft": msl,
               "water_level_ft": msl + float(datum_offset_ft)}
        if use_div:
            row["diversion_m3"] = div_sum
        out[int(ym.month)] = row

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
    전환유입이 설정돼 있으면 같은 run_dir 의 ``channel_sd_day.txt`` 에서 수원 채널의
    일유량을 읽어 전환 가능 잉여수로 넘긴다(일 단위 운영 물수지).
    """
    raw = parse_reservoir_day(Path(run_dir) / "reservoir_day.txt",
                              outlet=params.gis_id, sdate=sdate)
    if raw is None:
        return None
    # 해를 넘는 계절(NDJ·DJF)은 끝월이 다음 해다 — 단일 연도로 거르면 그 달이 빠진다.
    raw = raw[in_ym(raw["date"], period_ym(fyear, months)).values]
    if raw.empty:
        return None
    return monthly_capacity_series(
        raw, full_m3=params.full_m3, init_m3=params.init_m3,
        withdrawal_m3s=params.withdrawal_m3s, dead_m3=params.dead_m3,
        months=months, curve=getattr(params, "curve", None),
        datum_offset_ft=getattr(params, "datum_offset_ft", 0.0),
        withdrawal_monthly_m3s=getattr(params, "withdrawal_monthly_m3s", None),
        diversion_daily_m3=diversion_daily_m3(Path(run_dir), params, sdate=sdate),
        diversion_target_m3=getattr(params, "diversion_target_m3", float("nan")),
    )


def diversion_daily_m3(run_dir: Path, params: ReservoirForecastParams, *,
                       sdate: str) -> Optional[pd.Series]:
    """수원 채널 일유량 → 그 날 전환 가능한 잉여수(m³). 미설정·자료 없으면 None.

    잉여수 = clip(유량 − ``diversion_min_flow_m3s``, 0, ``diversion_max_m3s``) × 86400.
    - min_flow : 수원 하천에 남겨야 하는 유량(하천유지유량) — 가뭄에 수원이 마르면
      잉여수가 0이 되어 보충이 끊긴다. 이것이 저수지 저하를 만드는 기제다.
    - max_m3s  : 전환 설비(펌프·도수로) 용량 상한.
    ``channel_sd_day.txt`` 가 없으면 None → 호출부는 기존 월 단위 물수지로 돌아간다.
    """
    gid = getattr(params, "diversion_from_outlet", None)
    cap = float(getattr(params, "diversion_max_m3s", 0.0) or 0.0)
    if not gid or cap <= 0:
        return None
    f = Path(run_dir) / "channel_sd_day.txt"
    if not f.is_file():
        return None
    ch = parse_channel_sd_day(f, outlet=int(gid), sdate=sdate)
    if ch is None or ch.empty or "flo_out" not in ch:
        return None
    lo = float(getattr(params, "diversion_min_flow_m3s", 0.0) or 0.0)
    q = pd.to_numeric(ch["flo_out"], errors="coerce").fillna(0.0)
    surplus = (q - lo).clip(lower=0.0).clip(upper=cap) * _SECONDS_PER_DAY
    return pd.Series(surplus.values, index=pd.to_datetime(ch["date"]).values)


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
