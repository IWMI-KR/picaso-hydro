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

기준면 — **자(staff gauge) 눈금이 공식 기준**이다 (유진호 박사 확인 2026-11-02:
"해발고도가 아니라 23 ft 가 최대값이 되는 실측 수위 기준").
  · 입력(``init_water_level_ft`` · ``diversion_target_ft``) = **자 눈금 ft**
  · 출력(``water_level_ft``)                               = **자 눈금 ft** (만수 23.00)
  · 단계 임계(``level_fraction`` %)                        = **자 눈금 만수 대비 %**
수위-내용적 곡선(stage_storage CSV)만 측량 성과라 MSL 로 남는다. 레지스트리의
``obs_datum_offset_ft`` 가 둘을 잇는 유일한 다리다(Ngerimel −22.0; 45.00 MSL =
23.00 자 눈금). 곡선 datum 값이 필요하면 ``water_level_msl_ft`` 에 함께 남긴다.
"""
from __future__ import annotations

import calendar
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
    # 설정 초기수위를 **자 눈금 ft 그대로** 보관한다. ``init_m3`` 에서 곡선을 역으로
    # 조회하면 보간 왕복 오차(Ngerimel 22.0 ft → 22.02 ft)가 섞여, 초기수위 사전계산표
    # (init_level_sweep)에 운영값과 0.02 ft 어긋난 중복 행이 생긴다. 그 혼란을 막는 값이다.
    init_level_ft:          float = float("nan")  # 미지정(만수 출발) → NaN


def _assert_gauge_level(value: float, reservoir_cfg, offset_ft: float, *, key: str) -> None:
    """설정 수위가 **자 눈금(staff gauge)** 범위 안인지 확인한다.

    기준면을 섞어 적는 것이 이 모형에서 가장 조용하고 위험한 실수다 —
    MSL 값 44.0 을 자 눈금으로 읽으면 만수(23.0)보다 훨씬 높고, 반대로 자 눈금
    22.5 를 MSL 로 읽으면 사수위(23.34 MSL)보다 낮아 **시작하자마자 Crisis** 가
    된다. 둘 다 오류 없이 그럴듯한 숫자를 내므로 여기서 막는다.

    Raises
    ------
    ValueError : 사수위~댐마루(자 눈금) 밖이면. 옛 MSL 값으로 보이면 변환식을 알려 준다.
    """
    if reservoir_cfg is None:
        return
    bottom = float(getattr(reservoir_cfg, "bottom_ft", float("nan")))
    crest = float(getattr(reservoir_cfg, "crest_ft", float("nan")))
    if bottom != bottom or crest != crest:         # 제원이 없으면 검사 불가
        return
    lo, hi = bottom + offset_ft, crest + offset_ft           # 자 눈금 범위
    if lo <= value <= hi:
        return
    hint = ""
    if lo <= value + offset_ft <= hi:
        hint = (f"\n  → 이 값은 곡선 datum(MSL) 로 보인다. 자 눈금으로 바꿔 적을 것: "
                f"{value:.2f} + ({offset_ft:+.2f}) = {value + offset_ft:.2f}")
    raise ValueError(
        f"{key} = {value} ft 가 자(staff gauge) 눈금 범위를 벗어났다.\n"
        f"  이 값은 **현장에서 읽는 자 눈금**이어야 한다 "
        f"(사수위 {lo:.2f} ~ 댐마루 {hi:.2f} ft, 만수 "
        f"{float(getattr(reservoir_cfg, 'spillway_ft', float('nan'))) + offset_ft:.2f} ft)."
        f"{hint}")


def build_reservoir_forecast_params(source, reservoir_cfg, curve) -> ReservoirForecastParams:
    """_DroughtSource + _Reservoir(registry) + StageStorageCurve → 예측 매개변수.

    - full_m3 : 곡선상 여수로(spillway_ft) 저수량 = 만수 기준.
    - dead_m3 : 곡선상 사수위(bottom_ft) 저수량.
    - init_m3 : source.init_water_level_ft(**자 눈금 ft**) → MSL 환산 후 곡선 조회.
      미지정 시 full(만수).
    - datum_offset_ft : registry obs_datum_offset_ft. 곡선(MSL) 수위에 더하면
      자 눈금이 된다(Ngerimel: 45.00 MSL + (−22.0) = 23.00 ft 만수).
    """
    import math
    from swat_py.io.reservoir import water_level_to_storage

    spillway = reservoir_cfg.spillway_ft if reservoir_cfg else float("nan")
    bottom = reservoir_cfg.bottom_ft if reservoir_cfg else float("nan")
    full_m3 = float(curve.stage_to_storage(spillway)) if not math.isnan(spillway) \
        else float(curve.storage_m3[-1])
    dead_m3 = float(curve.stage_to_storage(bottom)) if not math.isnan(bottom) else 0.0

    off = float(getattr(reservoir_cfg, "obs_datum_offset_ft", 0.0) or 0.0) if reservoir_cfg else 0.0

    # ── 초기수위: 설정은 **자 눈금(staff gauge)**, 곡선은 MSL ──────────────────
    #  유진호 박사 확인(2026-11-02): 기준면은 해발고도가 아니라 **만수 23 ft 인
    #  실측 자 눈금**이다. 사용자가 적는 운영값은 현장에서 읽는 그 숫자여야 한다.
    #  곡선(stage_storage CSV)은 측량 성과라 MSL 그대로 두고, 여기서 변환한다.
    #      MSL = gauge − obs_datum_offset_ft      (Ngerimel: 22.0 − (−22.0) = 44.0)
    iwl_gauge = getattr(source, "init_water_level_ft", float("nan"))
    if iwl_gauge == iwl_gauge:                                   # NaN 아님
        _assert_gauge_level(iwl_gauge, reservoir_cfg, off,
                            key="drought.sources.<수원>.initial_condition.init_water_level_ft")
        init_m3 = water_level_to_storage(curve, iwl_gauge - off)
    else:
        init_m3 = full_m3                                        # 미지정 → 만수에서 시작

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
    gid = next(iter(source.outlets)) if source.outlets else (
        reservoir_cfg.gis_id if reservoir_cfg else 0)
    # 전환유입 — registry 설정을 그대로 쓴다(시나리오 덮어쓰기 대상 아님).
    dv_out = getattr(reservoir_cfg, "diversion_from_outlet", None) if reservoir_cfg else None
    # 보충 목표 수위도 **자 눈금**이다(초기수위와 같은 기준면) → 곡선용 MSL 로 변환.
    dv_tgt_gauge = float(getattr(reservoir_cfg, "diversion_target_ft", float("nan"))) \
        if reservoir_cfg else float("nan")
    if dv_tgt_gauge == dv_tgt_gauge:
        _assert_gauge_level(dv_tgt_gauge, reservoir_cfg, off,
                            key="reservoirs.<저수지>.diversion_target_ft")
        dv_tgt_m3 = float(curve.stage_to_storage(dv_tgt_gauge - off))
    else:
        dv_tgt_m3 = float("nan")
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
        init_level_ft=float(iwl_gauge) if iwl_gauge == iwl_gauge else float("nan"),
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


def daily_net_m3(daily_res: pd.DataFrame, *, use_losses: bool = True) -> pd.Series:
    """저수지 일자료(reservoir_day) → **일 순유입**(m³/일), date 색인.

    ``flo_in + precip − evap − seep`` — 저수지 물수지의 유일한 외부 강제력이며,
    우리가 후처리로 주는 초기수위와 **무관**하다(초기 저류량에 의존하는 항은 수면적을
    통한 증발·침투뿐이고, 팔라우 검보정 2018-01-01~2023-12-31 실측에서 증발은 총유입의
    0.64%, 침투는 0.00%다). 그래서 이 배열만 남겨 두면 어떤 초기수위로든 SWAT+ 재실행
    없이 물수지를 다시 풀 수 있다 — 일단위 저장의 대상이 수위가 아니라 이 값인 이유다.

    ``use_losses=False`` 면 ``flo_in`` 만 쓴다(손실 미반영 비교용).
    ★ :func:`monthly_capacity_series` 가 이 함수를 쓴다 — 식이 두 곳에 갈라지지 않게
      할 것(월 결과와 일 결과가 조용히 달라지면 추적이 매우 어렵다).
    """
    df = daily_res.copy()
    df["date"] = pd.to_datetime(df["date"])
    lc = {c.lower(): c for c in df.columns}

    def col(n):
        return (pd.to_numeric(df[lc[n]], errors="coerce").fillna(0.0)
                if n in lc else pd.Series(0.0, index=df.index))

    net = col("flo_in")
    if use_losses:
        net = net + col("precip") - col("evap") - col("seep")
    return pd.Series(net.values, index=pd.to_datetime(df["date"]).values)


def surplus_m3_from_flow(q_m3s, *, min_flow_m3s: float, max_m3s: float):
    """수원 하천 일유량(m³/s) → 그 날 **전환 가능한 잉여수**(m³/일).

    ``clip(q − min_flow, 0, max) × 86400``. 스칼라·배열·Series 모두 받는다
    (저장된 일배열에 같은 식을 다시 적용하려면 식이 한 곳에 있어야 한다)."""
    import numpy as _np
    q = _np.asarray(q_m3s, dtype=float)
    return _np.clip(q - float(min_flow_m3s), 0.0, float(max_m3s)) * _SECONDS_PER_DAY


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
    # 일 순유입은 daily_net_m3 가 단일 정의다(일단위 저장·재계산과 같은 식을 쓴다).
    df["_net"] = daily_net_m3(daily_res, use_losses=use_losses).values

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


def subtract_diversion(flow_m3s: Dict[int, float], diverted_m3: Dict[int, float],
                       month_year: Dict[int, int]) -> Dict[int, float]:
    """수원 하천의 월평균 유량에서 **저수지로 실제 가져간 물**을 뺀다.

    전환유입을 켜면 같은 물이 두 번 세어진다 — 저수지는 보충을 받아 수위가 오르는데,
    수원 하천(Ngerikiil)의 예측 유량은 SWAT+ 채널 유량 그대로라 전환분이 남아 있었다
    (제니토스 2026-10-20 지적 §4-다). 하천 단계 분류가 실제보다 후하게 나온다.

    빼는 양은 *가져갈 수 있었던 잉여수*(:func:`diversion_daily_m3`)가 아니라
    **물수지에서 실제로 가져간 양**(``monthly_capacity_series`` 의 ``diversion_m3``)이다.
    저수지가 목표 수위에 가까우면 잉여수가 있어도 조금만 가져가기 때문이다.

    Parameters
    ----------
    flow_m3s    : {월: 월평균 유량 m³/s} — 뺄 대상(수원 하천).
    diverted_m3 : {월: 그 달에 실제 전환한 물 m³}.
    month_year  : {월: 연도} — 해를 넘는 계절(NDJ·DJF)에서 2월 일수를 맞추기 위해 필요하다.

    Returns
    -------
    {월: 유량} — 음수가 되면 0 으로 자른다(하천이 마른 것으로 본다).
    """
    out = dict(flow_m3s)
    for m, vol in (diverted_m3 or {}).items():
        if m not in out or not vol:
            continue
        yr = month_year.get(m)
        if yr is None:
            continue
        days = calendar.monthrange(int(yr), int(m))[1]
        out[m] = max(0.0, float(out[m]) - float(vol) / (days * _SECONDS_PER_DAY))
    return out


def member_reservoir_full(
    run_dir: Path,
    params: ReservoirForecastParams,
    *,
    fyear: int,
    months: List[int],
    sdate: str,
    src_q: Optional[pd.Series] = None,
) -> Optional[Dict[str, object]]:
    """한 멤버 run_dir → 예측월 **월 물수지 + 일단위 강제력**. 없으면 None.

    Returns
    -------
    {"monthly": {월: {...}},                       # member_reservoir_series 와 동일
     "dates":      np.ndarray[datetime64[D]],      # 예측기간 일자
     "res_net_m3": np.ndarray[float32],            # 저수지 일 순유입 (m³/일)
     "src_q_m3s":  np.ndarray[float32] | None}     # 전환 수원 채널 일유량 (m³/s)

    일배열은 **초기수위를 바꿔도 변하지 않는 두 변수**만 담는다(:func:`daily_net_m3`
    주석의 근거). 이 둘만 남기면 저장량이 멤버당 728 B 로 줄어 1,000멤버 × 167기간을
    122 MB 에 담을 수 있다 — 원시 출력 전량 보관은 1.97 TB 라 불가능하다.
    파일은 어차피 이미 쓰이고 있으므로(``prepare_base`` 가 전환유입 프로젝트에서
    일단위 출력을 켠다) 추가 모델 실행 비용은 없다. **파싱은 여기서 한 번만** 한다.
    """
    import numpy as np

    raw = parse_reservoir_day(Path(run_dir) / "reservoir_day.txt",
                              outlet=params.gis_id, sdate=sdate)
    if raw is None:
        return None
    # 해를 넘는 계절(NDJ·DJF)은 끝월이 다음 해다 — 단일 연도로 거르면 그 달이 빠진다.
    raw = raw[in_ym(raw["date"], period_ym(fyear, months)).values]
    if raw.empty:
        return None
    # 전환 수원 일유량(원시) — 한 번만 읽어 잉여수 계산과 일배열 저장에 함께 쓴다.
    #  호출부가 이미 읽어 뒀으면(``src_q``) 그것을 쓴다 — 멤버당 5.6MB 파일을
    #  수원마다 다시 읽으면 파싱이 실행시간을 지배한다.
    q = src_q if src_q is not None else daily_source_flow_m3s(
        Path(run_dir), params, sdate=sdate)
    cap = float(getattr(params, "diversion_max_m3s", 0.0) or 0.0)
    lo = float(getattr(params, "diversion_min_flow_m3s", 0.0) or 0.0)
    div = (pd.Series(surplus_m3_from_flow(q.values, min_flow_m3s=lo, max_m3s=cap),
                     index=q.index)
           if (q is not None and cap > 0) else None)
    monthly = monthly_capacity_series(
        raw, full_m3=params.full_m3, init_m3=params.init_m3,
        withdrawal_m3s=params.withdrawal_m3s, dead_m3=params.dead_m3,
        months=months, curve=getattr(params, "curve", None),
        datum_offset_ft=getattr(params, "datum_offset_ft", 0.0),
        withdrawal_monthly_m3s=getattr(params, "withdrawal_monthly_m3s", None),
        diversion_daily_m3=div,
        diversion_target_m3=getattr(params, "diversion_target_m3", float("nan")),
    )
    dates = pd.to_datetime(raw["date"]).dt.normalize()
    net = daily_net_m3(raw).values
    # 결측일(출력 창 밖)은 0 으로 — 월 물수지(df["date"].map(div))와 같은 처리다.
    src = (dates.map(q).fillna(0.0).values.astype("float32")
           if q is not None else None)
    return {"monthly": monthly,
            "dates": dates.values.astype("datetime64[D]"),
            "res_net_m3": np.asarray(net, dtype="float32"),
            "src_q_m3s": src}


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
    (:func:`member_reservoir_full` 의 월 부분만 꺼내는 래퍼 — 식은 한 곳에 있다.)
    """
    full = member_reservoir_full(run_dir, params, fyear=fyear, months=months,
                                 sdate=sdate)
    return None if full is None else full["monthly"]


def diversion_daily_m3(run_dir: Path, params: ReservoirForecastParams, *,
                       sdate: str,
                       filename: str = "channel_sd_day.txt") -> Optional[pd.Series]:
    """수원 채널 일유량 → 그 날 전환 가능한 잉여수(m³). 미설정·자료 없으면 None.

    잉여수 = clip(유량 − ``diversion_min_flow_m3s``, 0, ``diversion_max_m3s``) × 86400.
    - min_flow : 수원 하천에 남겨야 하는 유량(하천유지유량) — 가뭄에 수원이 마르면
      잉여수가 0이 되어 보충이 끊긴다. 이것이 저수지 저하를 만드는 기제다.
    - max_m3s  : 전환 설비(펌프·도수로) 용량 상한.
    ``filename`` 이 없으면 None → 호출부는 전환유입 없이(기존 거동) 계산한다.
    검보정 분석 경로는 출력 파일명에 접미가 붙으므로(``channel_sd_day-{sim}.txt``)
    그 이름을 ``filename`` 으로 넘긴다.
    """
    cap = float(getattr(params, "diversion_max_m3s", 0.0) or 0.0)
    if cap <= 0:
        return None
    q = daily_source_flow_m3s(run_dir, params, sdate=sdate, filename=filename)
    if q is None:
        return None
    lo = float(getattr(params, "diversion_min_flow_m3s", 0.0) or 0.0)
    return pd.Series(surplus_m3_from_flow(q.values, min_flow_m3s=lo, max_m3s=cap),
                     index=q.index)


def daily_source_flow_m3s(run_dir: Path, params: ReservoirForecastParams, *,
                          sdate: str,
                          filename: str = "channel_sd_day.txt") -> Optional[pd.Series]:
    """전환 수원 채널의 **원시 일유량**(m³/s), date 색인. 미설정·자료 없으면 None.

    잉여수(clip 적용 후)가 아니라 **자르기 전 유량**이다 — 이 값을 남겨 두면
    ``diversion_min_flow_m3s``·``diversion_max_m3s`` 를 바꿔도 다시 풀 수 있고,
    같은 배열이 Ngerikiil 하천 단계 산정에도 쓰인다.
    """
    gid = getattr(params, "diversion_from_outlet", None)
    if not gid:
        return None
    f = Path(run_dir) / filename
    if not f.is_file():
        return None
    ch = parse_channel_sd_day(f, outlet=int(gid), sdate=sdate)
    if ch is None or ch.empty or "flo_out" not in ch:
        return None
    q = pd.to_numeric(ch["flo_out"], errors="coerce").fillna(0.0)
    return pd.Series(q.values, index=pd.to_datetime(ch["date"]).values)


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
