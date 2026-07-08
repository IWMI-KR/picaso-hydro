"""swat_py.drought.fdc / stages 검증."""
from __future__ import annotations

import numpy as np
import pytest

from swat_py.drought.fdc import flow_duration_curve, q_at, fdc_thresholds, stage_thresholds
from swat_py.drought.stages import (
    classify_stage, stage_probabilities, classify_stage4, stage_probabilities4,
)


def test_fdc_sorted_descending():
    q = [1, 5, 3, 2, 4]
    fdc = flow_duration_curve(q)
    assert list(fdc["flow"]) == [5, 4, 3, 2, 1]           # 내림차순
    assert fdc["exceed_pct"].is_monotonic_increasing      # 초과확률 증가


def test_q_at_monotonic():
    q = np.arange(1, 366)                                  # 1..365
    fdc = flow_duration_curve(q)
    # 낮은 초과확률(자주 초과=큰값) > 높은 초과확률(드물게=작은값)
    assert q_at(10, fdc) > q_at(90, fdc)


def test_thresholds_q275_ge_q355():
    rng = np.random.default_rng(0)
    q = rng.gamma(2.0, 1.0, 4000)
    t = fdc_thresholds(q)
    assert t["Q95d"] >= t["Q185d"] >= t["Q275d"] >= t["Q355d"]   # 유황 순서
    assert t["watch_warning"] == t["Q275d"]
    assert t["warning_crisis"] == t["Q355d"]


def test_thresholds_empty():
    t = fdc_thresholds([])
    assert np.isnan(t["Q275d"])


def test_classify_stage_boundaries():
    q275, q355 = 1.0, 0.4
    assert classify_stage(1.5, q275, q355) == "Watch"     # > Q275
    assert classify_stage(0.7, q275, q355) == "Warning"   # Q355<..<=Q275
    assert classify_stage(0.2, q275, q355) == "Crisis"    # <= Q355
    assert classify_stage(1.0, q275, q355) == "Warning"   # 경계: Q275 이하
    assert classify_stage(float("nan"), q275, q355) == "NA"


def test_stage_probabilities_sum_100():
    vals = [1.5, 1.2, 0.7, 0.6, 0.2, 0.1]                  # Watch2 Warning2 Crisis2
    sp = stage_probabilities(vals, q275=1.0, q355=0.4)
    assert sp["Watch"] + sp["Warning"] + sp["Crisis"] == pytest.approx(100.0, abs=0.5)
    assert sp["n"] == 6
    assert sp["most_likely"] in ("Watch", "Warning", "Crisis")


def test_stage_probabilities_empty():
    sp = stage_probabilities([], 1.0, 0.4)
    assert sp["most_likely"] == "NA" and sp["n"] == 0


# ── 4단계 (권장 기본): Normal/Watch/Warning/Crisis, 경계 Q185/Q275/Q355 ──────

def test_classify_stage4_boundaries():
    q185, q275, q355 = 2.0, 1.0, 0.4
    assert classify_stage4(3.0, q185, q275, q355) == "Normal"    # > Q185
    assert classify_stage4(1.5, q185, q275, q355) == "Watch"     # Q275<..<=Q185
    assert classify_stage4(0.7, q185, q275, q355) == "Warning"   # Q355<..<=Q275
    assert classify_stage4(0.2, q185, q275, q355) == "Crisis"    # <= Q355
    assert classify_stage4(2.0, q185, q275, q355) == "Watch"     # 경계 Q185 이하
    assert classify_stage4(float("nan"), q185, q275, q355) == "NA"


def test_stage_probabilities4_sum_and_keys():
    vals = [3.0, 2.5, 1.5, 0.7, 0.2]     # Normal2 Watch1 Warning1 Crisis1
    sp = stage_probabilities4(vals, q185=2.0, q275=1.0, q355=0.4)
    assert set(("Normal", "Watch", "Warning", "Crisis")) <= set(sp)
    assert sum(sp[s] for s in ("Normal", "Watch", "Warning", "Crisis")) == pytest.approx(100.0, abs=0.5)
    assert sp["most_likely"] == "Normal" and sp["n"] == 5


def test_stage4_thresholds_ordered():
    # Q185 >= Q275 >= Q355 → 4단계 경계가 유황 순서와 일치
    rng = np.random.default_rng(1)
    t = fdc_thresholds(rng.gamma(2.0, 1.0, 4000))
    assert t["normal_watch"] >= t["watch_warning"] >= t["warning_crisis"]


def test_stage_thresholds_methods_consistent():
    rng = np.random.default_rng(2)
    q = rng.gamma(2.0, 1.0, 5000)
    # fdc_exceedance Q70/Q90/Q95 (기본 권고) — 경계 고→저 순
    st = stage_thresholds(q, "fdc_exceedance", [70, 90, 95])
    assert st["normal_watch"] > st["watch_warning"] > st["warning_crisis"]
    # nonexceed_percentile [30,10,5] 은 fdc_exceedance [70,90,95] 와 동일 경계여야 함
    sp = stage_thresholds(q, "nonexceed_percentile", [30, 10, 5])
    for k in ("normal_watch", "watch_warning", "warning_crisis"):
        assert st[k] == pytest.approx(sp[k], rel=0.03)
    # fixed_flow 는 값 그대로
    sf = stage_thresholds(q, "fixed_flow", [3.0, 1.0, 0.5])
    assert (sf["normal_watch"], sf["watch_warning"], sf["warning_crisis"]) == (3.0, 1.0, 0.5)


def test_stage_thresholds_invalid():
    with pytest.raises(ValueError):
        stage_thresholds([1, 2, 3], "bogus", [70, 90, 95])
    with pytest.raises(ValueError):
        stage_thresholds([1, 2, 3], "fdc_exceedance", [70, 90])   # 3개 아님


# ── 저수지 capacity_fraction (만수위 저수량 대비 %) ───────────────────────────────

def test_capacity_fraction_percent_no_capacity():
    # capacity 미지정 → % 경계 그대로 (저수량-% 계열 분류용)
    st = stage_thresholds([], "capacity_fraction", [100, 85, 65])
    assert (st["normal_watch"], st["watch_warning"], st["warning_crisis"]) == (100.0, 85.0, 65.0)
    assert st["normal_watch"] > st["watch_warning"] > st["warning_crisis"]


def test_capacity_fraction_absolute_with_capacity():
    cap = 103242.0   # 만수위 저수량(m³)
    st = stage_thresholds([], "capacity_fraction", [100, 85, 65], capacity=cap)
    assert st["normal_watch"] == pytest.approx(cap)
    assert st["watch_warning"] == pytest.approx(0.85 * cap)
    assert st["warning_crisis"] == pytest.approx(0.65 * cap)


def test_capacity_fraction_aliases():
    for name in ("capacity_fraction", "capacity_fraction", "fill_fraction"):
        st = stage_thresholds([], name, [100, 85, 65])
        assert st["warning_crisis"] == 65.0
