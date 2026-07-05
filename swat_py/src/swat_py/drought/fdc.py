"""유황곡선(Flow Duration Curve) 및 가뭄 임계유량 산정.

과거 일유량을 큰 값→작은 값으로 정렬해 초과확률(Weibull)을 부여하고, 임의 초과확률의
유량을 보간한다. 한국 유황 대표유량(풍수 Q95d·평수 Q185d·저수 Q275d·갈수 Q355d)을
제공하며, 대시보드 ④ 단계경계선은 **Q275(Watch→Warning)·Q355(Warning→Crisis)**.

출처 이식: 0_database/obs/weather/analysis/hydrology_frequency/hydro_analysis.py (단일지점)
→ 채널 무관 순수함수로 일반화.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

# 유황 대표유량: 이름 → 초과일수(365일 기준) → 초과확률(%)
FLOW_REGIME_DAYS = {"Q95d": 95, "Q185d": 185, "Q275d": 275, "Q355d": 355}
FLOW_REGIME_LABELS = {"Q95d": "풍수량", "Q185d": "평수량", "Q275d": "저수량", "Q355d": "갈수량"}


def flow_duration_curve(daily_q) -> pd.DataFrame:
    """일유량 → 유황곡선 DataFrame[exceed_pct, flow] (내림차순 정렬).

    Weibull plotting position: exceed = rank/(n+1)*100 (rank 1=최대유량).
    """
    q = np.asarray(daily_q, dtype=float)
    q = q[~np.isnan(q)]
    q_sorted = np.sort(q)[::-1]
    n = len(q_sorted)
    if n == 0:
        return pd.DataFrame({"exceed_pct": [], "flow": []})
    exceed = np.arange(1, n + 1) / (n + 1) * 100.0
    return pd.DataFrame({"exceed_pct": exceed, "flow": q_sorted})


def q_at(exceed_pct: float, fdc: pd.DataFrame) -> float:
    """초과확률(%)에서의 유량 보간. fdc = flow_duration_curve() 결과."""
    if fdc.empty:
        return float("nan")
    # exceed 오름차순으로 interp (flow는 감소)
    return float(np.interp(exceed_pct, fdc["exceed_pct"].values, fdc["flow"].values))


def fdc_thresholds(daily_q) -> Dict[str, float]:
    """일유량 → 유황 대표유량 dict (Q95d·Q185d·Q275d·Q355d) + 편의 별칭.

    반환 키: 'Q95d','Q185d','Q275d','Q355d' 및 대시보드용 'watch_warning'(=Q275d),
    'warning_crisis'(=Q355d).
    """
    fdc = flow_duration_curve(daily_q)
    out: Dict[str, float] = {}
    for name, days in FLOW_REGIME_DAYS.items():
        out[name] = q_at(days / 365.0 * 100.0, fdc)
    # 4단계 경계(권장): Normal|Watch=Q185(평수), Watch|Warning=Q275(저수), Warning|Crisis=Q355(갈수)
    out["normal_watch"] = out["Q185d"]
    out["watch_warning"] = out["Q275d"]
    out["warning_crisis"] = out["Q355d"]
    return out


# ── 설정 가능한 4단계 경계유량 ────────────────────────────────────────────────
#  method 별 values[0..2] = [Normal|Watch, Watch|Warning, Warning|Crisis] 경계.
#   fdc_exceedance      : 초과확률(%). 값↑=저유량. 기본 [70, 90, 95] (USDM D0/D2/D3, WMO Q95).
#   nonexceed_percentile: 비초과 백분위(%). 값↑=고유량 → 내림차순 권장(예 [30,10,5]=Q70/Q90/Q95).
#   fixed_flow          : 절대 경계유량(m³/s) 직접 지정.
# 권장 기본(문헌): Q70(D0 Normal|Watch)·Q90(D2 Watch|Warning)·Q95(D3 Warning|Crisis).
#   근거: 4_drought_risk/가뭄단계_임계값_산정_방법_보고서.md (USDM·WMO·Van Loon).
DEFAULT_STAGE_EXCEEDANCE = [70.0, 90.0, 95.0]


def stage_thresholds(daily_q, method: str = "fdc_exceedance",
                     values=None) -> Dict[str, float]:
    """설정에 따라 4단계 경계유량 {normal_watch, watch_warning, warning_crisis} 산정.

    반환 유량은 항상 normal_watch ≥ watch_warning ≥ warning_crisis (고→저) 순.
    """
    v = list(values) if values else DEFAULT_STAGE_EXCEEDANCE
    if len(v) != 3:
        raise ValueError(f"thresholds.values 는 3개여야 함(Normal|Watch, Watch|Warning, Warning|Crisis): {v}")
    m = str(method).lower()
    if m in ("fdc_exceedance", "fdc", "exceedance"):
        fdc = flow_duration_curve(daily_q)
        nw, ww, wc = (q_at(x, fdc) for x in v)
    elif m in ("nonexceed_percentile", "percentile"):
        q = np.asarray(daily_q, float); q = q[~np.isnan(q)]
        nw, ww, wc = (float(np.percentile(q, x)) if q.size else float("nan") for x in v)
    elif m in ("fixed_flow", "fixed"):
        nw, ww, wc = (float(x) for x in v)
    else:
        raise ValueError(f"미지원 threshold method '{method}' "
                         "(fdc_exceedance | nonexceed_percentile | fixed_flow)")
    return {"normal_watch": nw, "watch_warning": ww, "warning_crisis": wc}
