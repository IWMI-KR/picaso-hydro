"""가뭄 급수단계 분류 및 앙상블 확률.

★ 4단계(권장 기본) — FDC 유황 3기준(평수 Q185·저수 Q275·갈수 Q355) 활용:
  flow > Q185(평수량)            → Normal   (정상, 녹)
  Q275 < flow ≤ Q185             → Watch    (주의, 황)
  Q355 < flow ≤ Q275             → Warning  (경계, 주황)
  flow ≤ Q355(갈수량)            → Crisis   (심각, 빨강)
3단계(하위호환) — Watch(>Q275)/Warning/Crisis(≤Q355).
⑤ 앙상블: 각 예측월에서 멤버 유량이 어느 단계에 떨어지는지 비율 = 확률.
"""
from __future__ import annotations

from typing import Dict, Sequence

import numpy as np

# 4단계(기본) — 심각도 순(왼→오른). 색: 녹-황-주-적.
STAGES4 = ("Normal", "Watch", "Warning", "Crisis")
STAGE_COLORS = {"Normal": "#2ca02c", "Watch": "#f5c518",
                "Warning": "#ff7f0e", "Crisis": "#d62728"}
# 게이지 바늘용 심각도 점수(0=안전 … 1=위기)
STAGE_SCORE = {"Normal": 0.0, "Watch": 1 / 3, "Warning": 2 / 3, "Crisis": 1.0}

# 3단계(하위호환)
STAGES = ("Watch", "Warning", "Crisis")


def classify_stage4(flow: float, q185: float, q275: float, q355: float) -> str:
    """단일 유량 → 4단계 급수단계 (Normal>Watch>Warning>Crisis 순 유량)."""
    if np.isnan(flow):
        return "NA"
    if flow > q185:
        return "Normal"
    if flow > q275:
        return "Watch"
    if flow > q355:
        return "Warning"
    return "Crisis"


def stage_probabilities4(values: Sequence[float], q185: float, q275: float,
                         q355: float) -> Dict:
    """앙상블 유량 → 4단계 확률(%) + 최빈 단계.

    Returns {"Normal":%, "Watch":%, "Warning":%, "Crisis":%, "most_likely":str, "n":int}
    """
    vals = np.asarray(values, dtype=float)
    vals = vals[~np.isnan(vals)]
    n = len(vals)
    if n == 0:
        return {s: 0.0 for s in STAGES4} | {"most_likely": "NA", "n": 0}
    counts = {s: 0 for s in STAGES4}
    for v in vals:
        counts[classify_stage4(v, q185, q275, q355)] += 1
    probs = {s: round(counts[s] / n * 100.0, 1) for s in STAGES4}
    probs["most_likely"] = max(STAGES4, key=lambda s: counts[s])
    probs["n"] = n
    return probs


def stage_probabilities4_from_quantiles(q_levels: Sequence[float],
                                        q_values: Sequence[float],
                                        q185: float, q275: float, q355: float) -> Dict:
    """저장된 분위(p5..p95)로부터 4단계 확률 재구성 (원시 멤버 없이 근사).

    경험적 CDF F(x)=P(flow≤x) 를 (q_values→q_levels) 단조 보간으로 추정.
    exact 카운트(stage_probabilities4)의 대체 — 앙상블 원시 유량이 없을 때 사용.
    """
    lv = np.asarray(q_levels, float); qv = np.asarray(q_values, float)
    ok = ~np.isnan(qv)
    lv, qv = lv[ok], qv[ok]
    if len(qv) < 2:
        return {s: float("nan") for s in STAGES4} | {"most_likely": "NA", "n": 0}
    order = np.argsort(qv); qv, lv = qv[order], lv[order]

    def _cdf(x):
        return float(np.interp(x, qv, lv, left=0.0, right=1.0))

    f185, f275, f355 = _cdf(q185), _cdf(q275), _cdf(q355)
    probs = {
        "Normal":  round((1 - f185) * 100, 1),
        "Watch":   round((f185 - f275) * 100, 1),
        "Warning": round((f275 - f355) * 100, 1),
        "Crisis":  round(f355 * 100, 1),
    }
    probs["most_likely"] = max(STAGES4, key=lambda s: probs[s])
    probs["n"] = 0                       # 근사(분위 기반)
    return probs


# ── 3단계(하위호환) ──────────────────────────────────────────────────────────

def classify_stage(flow: float, q275: float, q355: float) -> str:
    """3단계: flow>Q275→Watch, Q355<flow≤Q275→Warning, ≤Q355→Crisis."""
    if np.isnan(flow):
        return "NA"
    if flow > q275:
        return "Watch"
    if flow > q355:
        return "Warning"
    return "Crisis"


def stage_probabilities(values: Sequence[float], q275: float, q355: float) -> Dict:
    """3단계 확률(%) + 최빈 단계 (하위호환)."""
    vals = np.asarray(values, dtype=float)
    vals = vals[~np.isnan(vals)]
    n = len(vals)
    if n == 0:
        return {"Watch": 0.0, "Warning": 0.0, "Crisis": 0.0, "most_likely": "NA", "n": 0}
    counts = {s: 0 for s in STAGES}
    for v in vals:
        counts[classify_stage(v, q275, q355)] += 1
    probs = {s: round(counts[s] / n * 100.0, 1) for s in STAGES}
    probs["most_likely"] = max(STAGES, key=lambda s: counts[s])
    probs["n"] = n
    return probs
