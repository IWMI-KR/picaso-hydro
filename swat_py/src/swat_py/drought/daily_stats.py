"""일단위 앙상블 통계 — 요청 1·2·3번(유진호 박사 2026-11-12 메일 Palau) 해결 엔진.

이 모듈은 :mod:`swat_py.drought.daily_store` 가 남긴 **일단위 강제력**(저수지 일 순유입,
수원 하천 일유량)만으로 다음을 만든다. SWAT+ 재실행이 없다.

1번 — 모두 Normal 로만 보인다
    월말 한 점의 최빈값(mode)만 화면에 띄우면 분포가 가려진다(2016-04 실제 분포는
    Normal 50.4 · Watch 6.9 · Warning 5.3 · **Crisis 37.4** 인데 "Normal" 로만 보였다).
    → :func:`cumulative_table` 이 **누적확률**(Watch 이상 / Warning 이상 / Crisis)을 낸다.
2번 — 월말 기준이라 월 중 저하를 놓친다
    → :func:`day_count_table` 이 요청 문구 그대로 **단계별 일수 / 월 총일수(%)** 를 낸다.
      :func:`daily_quantile_table` 은 일별 수위 분위를 내어 "월 중간에 줄었다 다시 오른"
      경로를 그림으로 보이게 한다.
3번 — 초기수위를 바꿔도 선만 바뀐다
    → :func:`init_level_sweep` 이 초기수위 전구간(기본 0.1 ft 간격)에 대해 위 통계를
      미리 계산해 표로 낸다. 화면은 슬라이더 값에 해당하는 **행 하나를 읽으면** 끝이고,
      "hydrology model 재실행 버튼" 이 필요 없다.

물수지 식은 :func:`swat_py.drought.reservoir_forecast.monthly_capacity_series` 의
일 단위 분기와 **동일**하다(여기서 벡터화해 멤버 축으로 한꺼번에 푼다). 같은 초기수위를
주면 월말 값이 기존 ``stage_prob.csv`` 와 정확히 일치해야 한다 — 회귀 검증의 기준이다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

from swat_py.drought.season import SEASON_MONTHS
from swat_py.drought.stages import STAGES4

_SECONDS_PER_DAY = 86400.0

#: 일자 묶음 — 저장소에서 꺼내면 ``np.ndarray[datetime64[D]]``, 손으로 만들면
#: ``DatetimeIndex`` 다. 둘 다 받는다(한쪽만 적어 두면 표기가 실제와 어긋난다).
Dates = Union[Sequence[Any], np.ndarray]
#: 누적 단계 열 이름 — STAGES4 의 1·2·3번(Watch·Warning·Crisis) 이상
CUM_COLS = ("watch_or_worse", "warning_or_worse", "crisis")


# ── 단계 분류(벡터) ──────────────────────────────────────────────────────────────

def classify_stage_index(values: Any, nw: float, ww: float, wc: float, *,
                         top_inclusive: bool = False) -> np.ndarray:
    """값 배열 → 단계 index 배열 (0=Normal … 3=Crisis). NaN 은 -1.

    :func:`swat_py.drought.stages.classify_stage4` 와 **같은 경계 처리**를 벡터로 한 것이다
    (``top_inclusive`` 는 저수지 수위용 — 수위는 만수에서 물리적으로 잘려 ``> 만수`` 가
    영영 성립하지 않으므로 상한 경계를 이상(>=)으로 본다).
    """
    v = np.asarray(values, dtype=float)
    idx = np.full(v.shape, 3, dtype=np.int8)            # Crisis
    idx = np.where(v > wc, 2, idx)                      # Warning
    idx = np.where(v > ww, 1, idx)                      # Watch
    idx = np.where((v >= nw) if top_inclusive else (v > nw), 0, idx)
    out: np.ndarray = np.where(np.isnan(v), -1, idx).astype(np.int8)
    return out


# ── 저수지 일 물수지(벡터) ───────────────────────────────────────────────────────

def simulate_daily_storage(net_m3: np.ndarray, avail_m3: Optional[np.ndarray], *,
                           init_m3: float, full_m3: float, dead_m3: float,
                           wdr_day_m3: np.ndarray,
                           target_m3: float = float("nan")) -> Dict[str, np.ndarray]:
    """일 단위 운영 물수지를 멤버 축으로 한꺼번에 푼다.

    Parameters
    ----------
    net_m3     : (M, D) 일 순유입 m³/일.
    avail_m3   : (M, D) 그 날 전환 가능 잉여수 m³. None 이면 전환유입 없음.
    wdr_day_m3 : (D,)   그 날 취수량 m³/일 (월별 취수를 일로 펼친 것).
    target_m3  : 보충 목표 저류량. NaN → 만수.

    Returns
    -------
    {"storage_m3": (M, D), "take_m3": (M, D)}

    식은 ``monthly_capacity_series`` 의 ``use_div`` 분기와 글자 그대로 같다 —
    유입·취수를 적용한 뒤(여기서는 아직 자르지 않는다) 목표 미달이면 그날 잉여수
    한도까지 보충하고, 그 다음에 사수위~만수로 자른다(월류는 그 자리에서 유실).
    """
    net = np.asarray(net_m3, dtype=float)
    n_mem, n_day = net.shape
    tgt = float(target_m3) if target_m3 == target_m3 else float(full_m3)
    tgt = max(min(tgt, full_m3), dead_m3)
    # 전환유입이 없으면 0 배열을 쓴다 — Optional 을 루프 안에서 인덱싱하지 않는다.
    use_div = avail_m3 is not None
    av = (np.asarray(avail_m3, dtype=float) if avail_m3 is not None
          else np.zeros_like(net))
    wdr = np.asarray(wdr_day_m3, dtype=float)

    S = np.minimum(np.full(n_mem, float(init_m3)), float(full_m3))
    stor = np.empty((n_mem, n_day), dtype=float)
    take = np.zeros((n_mem, n_day), dtype=float)
    for d in range(n_day):
        S = S + net[:, d] - wdr[d]
        if use_div:
            need = tgt - S
            t = np.where((need > 0.0) & (av[:, d] > 0.0),
                         np.minimum(need, av[:, d]), 0.0)
            S = S + t
            take[:, d] = t
        S = np.clip(S, dead_m3, full_m3)
        stor[:, d] = S
    return {"storage_m3": stor, "take_m3": take}


def withdrawal_per_day(dates: Dates, *, withdrawal_m3s: float = 0.0,
                       withdrawal_monthly_m3s: Optional[List[float]] = None
                       ) -> np.ndarray:
    """일자 배열 → 그 날 취수량 m³/일. 월별 취수가 있으면 그것이 우선."""
    mon = pd.DatetimeIndex(pd.to_datetime(dates)).month.values
    if withdrawal_monthly_m3s:
        w = np.asarray(withdrawal_monthly_m3s, dtype=float)
        if len(w) != 12:
            raise ValueError(f"withdrawal_monthly_m3s 는 12개여야 한다: {len(w)}개")
        return np.asarray(w[mon - 1] * _SECONDS_PER_DAY, dtype=float)
    return np.full(len(mon), float(withdrawal_m3s) * _SECONDS_PER_DAY)


def storage_to_level_ft(storage_m3: np.ndarray, *, curve, datum_offset_ft: float = 0.0
                        ) -> np.ndarray:
    """저류량 (M, D) → **자 눈금** 수위 ft (M, D). 곡선이 없으면 전부 NaN."""
    st = np.asarray(storage_m3, dtype=float)
    if curve is None:
        return np.full(st.shape, np.nan)
    msl = np.asarray(curve.storage_to_stage(st.ravel()), dtype=float)
    return msl.reshape(st.shape) + float(datum_offset_ft)


# ── 통계 표 ─────────────────────────────────────────────────────────────────────

def _month_slices(dates: Dates, months: Sequence[int]) -> List[tuple]:
    """[(월, "YYYY-MM", 그 달에 해당하는 열 인덱스 배열)] — months 순서를 지킨다."""
    di = pd.DatetimeIndex(pd.to_datetime(dates))
    out = []
    for m in months:
        sel = np.where(di.month.values == int(m))[0]
        if len(sel) == 0:
            continue
        out.append((int(m), f"{di[sel[0]].year}-{int(m):02d}", sel))
    return out


def day_count_table(stage_idx: np.ndarray, dates: Dates,
                    months: Sequence[int]) -> pd.DataFrame:
    """단계 index (M, D) → 월별 **단계별 일수 비율 %** (요청 2번).

    각 멤버에서 "그 단계에 든 일수 / 월 총일수" 를 구하고 앙상블 평균을 낸다.
    합은 100 이다. ``most_likely`` 는 그 중 가장 큰 단계(= 그 달 대표 단계).
    """
    rows = []
    for m, ym, sel in _month_slices(dates, months):
        sub = stage_idx[:, sel]
        nd = sub.shape[1]
        valid = sub >= 0
        frac = {}
        for k, name in enumerate(STAGES4):
            # 멤버별 일수 비율 → 앙상블 평균
            per_mem = (sub == k).sum(axis=1) / np.maximum(valid.sum(axis=1), 1)
            frac[name] = round(float(np.nanmean(per_mem)) * 100.0, 1)
        rows.append({"month": m, "ym": ym, **frac,
                     "most_likely": max(STAGES4, key=lambda s: frac[s]),
                     "n_days": nd, "n": int(sub.shape[0])})
    return pd.DataFrame(rows)


def cumulative_table(stage_idx_month: np.ndarray, stage_idx_daily: Optional[np.ndarray],
                     dates: Dates, months: Sequence[int], *,
                     month_basis: str = "monthend") -> pd.DataFrame:
    """**누적확률** 표 (요청 1번) — Watch 이상 / Warning 이상 / Crisis.

    두 기준을 한 표에 담는다.
      · ``basis = month_basis`` (기본 "monthend") — 월 대표값 1개가 그 단계 **이상**인
        멤버 비율 %. 기존 ``stage_prob.csv`` 와 같은 자료를 누적으로 다시 읽은 것이다.
      · ``basis = "daycount"`` — 멤버별 "그 단계 이상에 든 일수 / 월 총일수" 의 앙상블 평균.

    최빈값만 보던 화면에서 가려졌던 위험(2016-04 Crisis 37.4%)이 이 표에서는 보인다.

    Parameters
    ----------
    stage_idx_month : (M, 월수) 월 대표값의 단계 index — months 순서.
    stage_idx_daily : (M, D) 일별 단계 index. None 이면 daycount 행을 내지 않는다.
    """
    rows = []
    for j, (m, ym, sel) in enumerate(_month_slices(dates, months)):
        col = np.asarray(stage_idx_month)[:, j]
        col = col[col >= 0]
        n = len(col)
        rows.append({"basis": month_basis, "month": m, "ym": ym,
                     **{c: (round(float((col >= k).mean()) * 100.0, 1) if n else np.nan)
                        for k, c in enumerate(CUM_COLS, start=1)},
                     "n": n})
        if stage_idx_daily is not None:
            sub = stage_idx_daily[:, sel]
            valid = np.maximum((sub >= 0).sum(axis=1), 1)
            rows.append({"basis": "daycount", "month": m, "ym": ym,
                         **{c: round(float(np.nanmean(
                             ((sub >= k) & (sub >= 0)).sum(axis=1) / valid)) * 100.0, 1)
                            for k, c in enumerate(CUM_COLS, start=1)},
                         "n": int(sub.shape[0])})
    return pd.DataFrame(rows)


def daily_quantile_table(values: np.ndarray, stage_idx: np.ndarray, dates: Dates, *,
                         value_name: str = "level_ft",
                         qlevels: Sequence[float] = (0.05, 0.25, 0.50, 0.75, 0.95)
                         ) -> pd.DataFrame:
    """일별 앙상블 분위 + 그날 각 단계에 든 멤버 수 (요청 2번의 그림용).

    "월 중간에 level 이 줄었다가 다시 올라가는 case" 가 월말 한 점에서는 사라지지만
    이 표에서는 경로로 남는다.
    """
    v = np.asarray(values, dtype=float)
    df = pd.DataFrame({"date": pd.to_datetime(dates).astype("datetime64[ns]")})
    df["variable"] = value_name
    for q in qlevels:
        df[f"p{int(round(q * 100))}"] = np.nanquantile(v, q, axis=0)
    df["mean"] = np.nanmean(v, axis=0)
    for k, name in enumerate(STAGES4):
        df[f"{name}_n"] = (np.asarray(stage_idx) == k).sum(axis=0)
    df["n"] = int(v.shape[0])
    return df


# ── 저수지: 한 초기수위에 대한 전체 통계 ─────────────────────────────────────────

def reservoir_stats_for_init(daily: Dict[str, np.ndarray], *, params,
                             thresholds: Dict[str, float], months: Sequence[int],
                             init_ft: Optional[float] = None,
                             top_inclusive: bool = True,
                             with_daily: bool = True) -> Dict[str, Any]:
    """저장된 일배열 + 초기수위 → 월말·일수 기준 통계 한 묶음.

    Parameters
    ----------
    daily      : :func:`daily_store.load_daily` 결과 (dates, res_net_m3, src_q_m3s).
    params     : ReservoirForecastParams (만수·사수위·곡선·취수·전환 설정).
    thresholds : {"normal_watch", "watch_warning", "warning_crisis"} — 수위 ft.
    init_ft    : 초기수위(**자 눈금** ft). None 이면 params.init_m3 를 그대로 쓴다.
    with_daily : False 면 일별 분위표(``daily``)를 만들지 않는다. 초기수위를 수백 개
                 훑을 때는 이 표 생성이 전체 시간을 지배한다.

    Returns
    -------
    {"month_end": DataFrame, "day_count": DataFrame, "cumulative": DataFrame,
     "daily": DataFrame, "level_ft": (M,D), "storage_m3": (M,D)}
    """
    from swat_py.drought.reservoir_forecast import surplus_m3_from_flow
    from swat_py.drought.stages import stage_probabilities4

    dates = daily["dates"]
    net = daily["res_net_m3"]
    cap = float(getattr(params, "diversion_max_m3s", 0.0) or 0.0)
    avail = None
    if cap > 0 and daily.get("src_q_m3s") is not None:
        avail = surplus_m3_from_flow(
            daily["src_q_m3s"], min_flow_m3s=float(
                getattr(params, "diversion_min_flow_m3s", 0.0) or 0.0), max_m3s=cap)

    curve: Any = getattr(params, "curve", None)
    off = float(getattr(params, "datum_offset_ft", 0.0) or 0.0)
    if init_ft is None:
        init_m3 = float(params.init_m3)
    else:
        # 설정·슬라이더 값은 자 눈금 — 곡선은 MSL 이다(기준면을 섞으면 조용히 틀린다).
        init_m3 = float(curve.stage_to_storage(float(init_ft) - off))

    sim = simulate_daily_storage(
        net, avail, init_m3=init_m3, full_m3=float(params.full_m3),
        dead_m3=float(params.dead_m3),
        wdr_day_m3=withdrawal_per_day(
            dates, withdrawal_m3s=float(getattr(params, "withdrawal_m3s", 0.0) or 0.0),
            withdrawal_monthly_m3s=getattr(params, "withdrawal_monthly_m3s", None)),
        target_m3=float(getattr(params, "diversion_target_m3", float("nan"))))
    level = storage_to_level_ft(sim["storage_m3"], curve=curve, datum_offset_ft=off)
    nw, ww, wc = (thresholds["normal_watch"], thresholds["watch_warning"],
                  thresholds["warning_crisis"])
    st_day = classify_stage_index(level, nw, ww, wc, top_inclusive=top_inclusive)

    # 월말 기준 — 그 달 **마지막 날**의 수위. 기존 stage_prob.csv 와 같은 정의다.
    slices = _month_slices(dates, months)
    me_level = np.column_stack([level[:, sel[-1]] for _, _, sel in slices]) \
        if slices else np.empty((level.shape[0], 0))
    me_rows = []
    for j, (m, ym, _sel) in enumerate(slices):
        sp = stage_probabilities4(me_level[:, j], nw, ww, wc,
                                  top_inclusive=top_inclusive)
        me_rows.append({"month": m, "ym": ym, **sp})
    st_month = classify_stage_index(me_level, nw, ww, wc, top_inclusive=top_inclusive)

    return {
        "month_end": pd.DataFrame(me_rows),
        "day_count": day_count_table(st_day, dates, months),
        "cumulative": cumulative_table(st_month, st_day, dates, months,
                                       month_basis="monthend"),
        "daily": (daily_quantile_table(level, st_day, dates,
                                       value_name="water_level_ft")
                  if with_daily else None),
        "level_ft": level, "storage_m3": sim["storage_m3"],
        "take_m3": sim["take_m3"], "init_m3": init_m3,
    }


def init_level_sweep(daily: Dict[str, np.ndarray], *, params,
                     thresholds: Dict[str, float], months: Sequence[int],
                     levels_ft: Optional[Sequence[float]] = None,
                     step_ft: float = 0.1,
                     anchors_ft: Optional[Sequence[float]] = None,
                     top_inclusive: bool = True) -> pd.DataFrame:
    """초기수위 전구간에 대한 월별 통계표 (요청 3번).

    화면 슬라이더가 이 표에서 ``init_ft`` 가 가장 가까운 행들을 읽으면 그만이다 —
    SWAT+ 재실행도, GUI 쪽 계산도 필요 없다.

    ``levels_ft`` 미지정이면 사수위~만수를 ``step_ft`` 간격으로 훑는다. 격자는
    **step_ft 의 정수배에 맞춘다** — 사수위(1.34 ft)에서 더해 올라가면 격자가
    1.34·1.44·… 가 되어 만수 23.00 과 운영값 22.00 이 격자에서 빠지고, 화면
    슬라이더가 집어낼 수 있는 값이 하나도 없게 된다.
    ``anchors_ft`` 로 준 값(사수위·만수·단계 경계·설정 초기수위)은 격자와 무관하게
    **항상 포함**한다 — 경계값에서의 거동을 확인할 수 없으면 표의 쓸모가 반감된다.

    열 접두 ``me_`` = 월말 기준, ``dc_`` = 일수 기준.
    """
    curve: Any = getattr(params, "curve", None)
    off = float(getattr(params, "datum_offset_ft", 0.0) or 0.0)
    lo = float(curve.storage_to_stage(params.dead_m3)) + off
    hi = float(curve.storage_to_stage(params.full_m3)) + off
    if levels_ft is None:
        st = float(step_ft)
        k0 = int(np.ceil(lo / st - 1e-9))
        k1 = int(np.floor(hi / st + 1e-9))
        grid = np.round(np.arange(k0, k1 + 1) * st, 4)
    else:
        grid = np.asarray(levels_ft, dtype=float)
    extra = [lo, hi] + [float(a) for a in (anchors_ft or [])]
    levels = np.unique(np.round(np.concatenate([
        grid,
        np.asarray([a for a in extra if lo - 1e-9 <= a <= hi + 1e-9], dtype=float)]), 4))
    rows = []
    for ift in levels:
        r = reservoir_stats_for_init(daily, params=params, thresholds=thresholds,
                                     months=months, init_ft=float(ift),
                                     top_inclusive=top_inclusive, with_daily=False)
        me = r["month_end"].set_index("month")
        dc = r["day_count"].set_index("month")
        cum = r["cumulative"]
        for m in me.index:
            row = {"init_ft": round(float(ift), 2), "month": int(m),
                   "ym": me.loc[m, "ym"]}
            row.update({f"me_{s}": me.loc[m, s] for s in STAGES4})
            row["me_most_likely"] = me.loc[m, "most_likely"]
            row.update({f"dc_{s}": dc.loc[m, s] for s in STAGES4})
            row["dc_most_likely"] = dc.loc[m, "most_likely"]
            for basis, pre in (("monthend", "me"), ("daycount", "dc")):
                sel = cum[(cum["basis"] == basis) & (cum["month"] == m)]
                if not sel.empty:
                    row.update({f"{pre}_{c}": float(sel.iloc[0][c]) for c in CUM_COLS})
            row["n"] = int(me.loc[m, "n"])
            rows.append(row)
    return pd.DataFrame(rows)


# ── 하천: 일단위 단계 통계 ───────────────────────────────────────────────────────

def stream_daily_stats(daily: Dict[str, np.ndarray], *, thresholds: Dict[str, float],
                       months: Sequence[int], var: str = "q_m3s") -> Dict[str, Any]:
    """하천 일유량 배열 → 월평균 기준·일수 기준 단계 통계.

    쿡과 같은 Q70/Q90/Q95 경계를 **일유량**에 적용한다. 월평균 하나로 보면 월 중
    갈수 구간이 평균에 묻히는데(저수지 2번과 같은 문제), 일수 기준은 그것을 드러낸다.
    """
    from swat_py.drought.stages import stage_probabilities4

    dates, q = daily["dates"], np.asarray(daily[var], dtype=float)
    nw, ww, wc = (thresholds["normal_watch"], thresholds["watch_warning"],
                  thresholds["warning_crisis"])
    st_day = classify_stage_index(q, nw, ww, wc)
    slices = _month_slices(dates, months)
    mm = np.column_stack([np.nanmean(q[:, sel], axis=1) for _, _, sel in slices]) \
        if slices else np.empty((q.shape[0], 0))
    rows = [{"month": m, "ym": ym,
             **stage_probabilities4(mm[:, j], nw, ww, wc)}
            for j, (m, ym, _s) in enumerate(slices)]
    st_month = classify_stage_index(mm, nw, ww, wc)
    return {
        "month_mean": pd.DataFrame(rows),
        "day_count": day_count_table(st_day, dates, months),
        "cumulative": cumulative_table(st_month, st_day, dates, months,
                                       month_basis="monthmean"),
        "daily": daily_quantile_table(q, st_day, dates, value_name="flo_m3s"),
    }


# ── 산출물 기록 ─────────────────────────────────────────────────────────────────

_ENC = "utf-8-sig"


def write_reservoir_outputs(out_dir, daily: Dict[str, np.ndarray], *, params,
                            thresholds: Dict[str, float], months: Sequence[int],
                            sweep_ft: Optional[Sequence[float]] = None,
                            step_ft: float = 0.1,
                            top_inclusive: bool = True) -> Dict[str, str]:
    """저수지 수원의 일단위 산출물 4종을 ``out_dir`` 에 쓴다 → {이름: 파일명}.

    ``stage_prob_days.csv``  월별 단계별 **일수 비율 %** (요청 2번)
    ``stage_prob_cum.csv``   월말·일수 기준 **누적확률** (요청 1번)
    ``level_daily.csv``      일별 수위 분위 + 그날 단계별 멤버 수 (요청 2번 그림)
    ``init_level_sweep.csv`` 초기수위 전구간 사전계산 (요청 3번)

    기존 ``stage_prob.csv``(월말 기준)는 **건드리지 않는다** — 확인된 방침대로
    월말 기준을 유지하고 일수 기준을 병기한다.
    """
    from pathlib import Path as _Path
    out_dir = _Path(out_dir)
    r = reservoir_stats_for_init(daily, params=params, thresholds=thresholds,
                                 months=months, init_ft=None,
                                 top_inclusive=top_inclusive)
    written: Dict[str, str] = {}
    r["day_count"].to_csv(out_dir / "stage_prob_days.csv", index=False, encoding=_ENC)
    written["day_count"] = "stage_prob_days.csv"
    r["cumulative"].to_csv(out_dir / "stage_prob_cum.csv", index=False, encoding=_ENC)
    written["cumulative"] = "stage_prob_cum.csv"
    r["daily"].to_csv(out_dir / "level_daily.csv", index=False, encoding=_ENC)
    written["daily"] = "level_daily.csv"
    if getattr(params, "curve", None) is not None:
        # 앵커 — 단계 경계 3개 + 설정 초기수위. 사수위·만수는 init_level_sweep 이 넣는다.
        anchors = [thresholds["normal_watch"], thresholds["watch_warning"],
                   thresholds["warning_crisis"]]
        try:
            anchors.append(float(params.curve.storage_to_stage(params.init_m3))
                           + float(getattr(params, "datum_offset_ft", 0.0) or 0.0))
        except Exception:                      # noqa: BLE001 — 앵커는 보조
            pass
        sw = init_level_sweep(daily, params=params, thresholds=thresholds,
                              months=months, levels_ft=sweep_ft, step_ft=step_ft,
                              anchors_ft=anchors, top_inclusive=top_inclusive)
        sw.to_csv(out_dir / "init_level_sweep.csv", index=False, encoding=_ENC)
        written["sweep"] = "init_level_sweep.csv"
    return written


def write_stream_outputs(out_dir, daily: Dict[str, np.ndarray], *,
                         thresholds: Dict[str, float], months: Sequence[int],
                         var: str = "q_m3s") -> Dict[str, str]:
    """하천 수원의 일단위 산출물 3종을 ``out_dir`` 에 쓴다 → {이름: 파일명}.

    ``stage_prob_days.csv`` · ``stage_prob_cum.csv`` · ``flow_daily.csv``.
    기존 ``stage_prob.csv``(월평균 기준)는 그대로 둔다.
    """
    from pathlib import Path as _Path
    out_dir = _Path(out_dir)
    if daily.get(var) is None:
        return {}
    r = stream_daily_stats(daily, thresholds=thresholds, months=months, var=var)
    r["day_count"].to_csv(out_dir / "stage_prob_days.csv", index=False, encoding=_ENC)
    r["cumulative"].to_csv(out_dir / "stage_prob_cum.csv", index=False, encoding=_ENC)
    r["daily"].to_csv(out_dir / "flow_daily.csv", index=False, encoding=_ENC)
    return {"day_count": "stage_prob_days.csv", "cumulative": "stage_prob_cum.csv",
            "daily": "flow_daily.csv"}


def sweep_levels_from_cfg(cfg_values: Optional[Sequence[float]]) -> tuple:
    """config ``init_level_sweep_ft`` → (levels_ft|None, step_ft).

    ``[최소, 최대, 간격]`` 을 주면 그 격자를, 비어 있으면 (None, 0.1) 을 돌려
    호출부가 사수위~만수를 0.1 ft 간격으로 자동 산정하게 한다.
    """
    v = list(cfg_values or [])
    if len(v) >= 3 and v[2] > 0:
        n = int(round((v[1] - v[0]) / v[2])) + 1
        return np.round(v[0] + np.arange(max(n, 1)) * v[2], 4), float(v[2])
    return None, 0.1


# ── 재계산 CLI — SWAT+ 재실행 없이 저장된 일배열에서 통계만 다시 만든다 ──────────

def recompute(cfg, forecast: str, *, init_ft: Optional[float] = None,
              step_ft: Optional[float] = None) -> Dict[str, Any]:
    """저장된 일배열(NPZ)로 한 예측기간의 일단위 산출물을 다시 만든다.

    ``init_ft`` 를 주면 **그 초기수위로** 월말·일수 통계를 다시 계산해
    ``stage_prob_days.csv``·``stage_prob_cum.csv``·``level_daily.csv`` 를 갱신한다
    (``stage_prob.csv`` 는 월말 기준 정본이라 건드리지 않는다). 단계 경계나 스윕
    격자만 바꿀 때도 쓴다 — :mod:`swat_py.drought.reclassify` 와 같은 역할이다.

    SWAT+ 는 다시 돌지 않는다. 1,000멤버 × 91일 물수지를 넘파이로 푸는 것이 전부다.

    실행:
      ``python -m swat_py.drought.daily_stats --forecast 2016_AMJ [--init-ft 18.5]``
    """
    from pathlib import Path

    from swat_py.drought.daily_store import load_daily
    from swat_py.drought.fdc import is_level_method, stage_thresholds
    from swat_py.drought.reservoir_forecast import (
        build_reservoir_forecast_params,
        full_level_ft,
    )
    from swat_py.io.reservoir import load_stage_storage

    dc = cfg.Drought
    prj = Path(cfg.PrjDir)
    label = f"{forecast}{dc.forecast_suffix() if dc else ''}"
    swat_fc = prj / "3_swatplus" / "forecast" / label
    out_root = prj / "4_drought_risk" / "forecast" / label
    if not swat_fc.is_dir():
        raise SystemExit(f"일단위 자료 폴더 없음: {swat_fc}\n"
                         f"  → 먼저 dashboard_data.build(cfg, '{forecast}') 로 생성하세요.")
    months = SEASON_MONTHS[forecast.split("_")[1]]
    step = float(step_ft) if step_ft else sweep_levels_from_cfg(
        getattr(dc, "init_level_sweep_ft", None))[1]
    sweep_ft = None if step_ft else sweep_levels_from_cfg(
        getattr(dc, "init_level_sweep_ft", None))[0]

    outs: List[str] = []
    done: Dict[str, Any] = {"out_root": str(out_root), "outlets": outs}
    for s in (dc.sources or []):
        for gid, nm in (s.outlets or {}).items():
            d = load_daily(swat_fc, nm)
            if d is None:
                continue
            out_dir = out_root / nm
            if not out_dir.is_dir():
                continue
            thr_method, thr_values = dc.threshold_for(gid)
            if s.type == "reservoir":
                rcfg = (getattr(cfg, "Reservoirs", {}) or {}).get(s.reservoir)
                if not (rcfg and rcfg.stage_storage_file and is_level_method(thr_method)):
                    continue
                rp = build_reservoir_forecast_params(
                    s, rcfg, load_stage_storage(rcfg.stage_storage_file,
                                                name=s.reservoir))
                st = stage_thresholds([], thr_method, thr_values,
                                      full_level_ft=full_level_ft(rp))
                thr = {k: st[k] for k in ("normal_watch", "watch_warning",
                                          "warning_crisis")}
                if init_ft is not None:
                    # 사용자가 준 초기수위로 갈아 끼운다(자 눈금 → 곡선 MSL).
                    off = float(getattr(rp, "datum_offset_ft", 0.0) or 0.0)
                    cv: Any = rp.curve
                    rp.init_m3 = float(cv.stage_to_storage(float(init_ft) - off))
                w = write_reservoir_outputs(out_dir, d, params=rp, thresholds=thr,
                                            months=months, sweep_ft=sweep_ft,
                                            step_ft=step, top_inclusive=True)
            else:
                from swat_py.drought.climatology import (
                    climatology_daily_path,
                    load_daily_flow,
                )
                clim = load_daily_flow(dc.climatology_csv or climatology_daily_path(cfg))
                if nm not in clim.columns:
                    continue
                st = stage_thresholds(clim[nm].dropna().values, thr_method, thr_values)
                thr = {k: st[k] for k in ("normal_watch", "watch_warning",
                                          "warning_crisis")}
                w = write_stream_outputs(out_dir, d, thresholds=thr, months=months)
            if w:
                outs.append(nm)
                print(f"  ✔ {nm}: {', '.join(sorted(w.values()))}")
    return done


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="swat_py.drought.daily_stats",
        description="저장된 일단위 자료로 통계 재계산(SWAT+ 재실행 없음)")
    ap.add_argument("--config", default="config/swat_py.yaml")
    ap.add_argument("--forecast", default=None, help="예측연월 (기본: yaml drought.forecast)")
    ap.add_argument("--init-ft", type=float, default=None,
                    help="저수지 초기수위(자 눈금 ft)로 다시 계산")
    ap.add_argument("--step-ft", type=float, default=None,
                    help="초기수위 스윕 간격 ft (기본: yaml 또는 0.1)")
    a = ap.parse_args(argv)
    from swat_py.config import load_config
    cfg = load_config(a.config)
    fc = a.forecast or cfg.Drought.forecast
    print(f"[daily_stats] {fc} 재계산"
          + (f" — 초기수위 {a.init_ft} ft" if a.init_ft is not None else ""))
    r = recompute(cfg, fc, init_ft=a.init_ft, step_ft=a.step_ft)
    print(f"✔ 완료 — 수원 {len(r['outlets'])}종 → {r['out_root']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
