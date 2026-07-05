"""분할표본(split-sample) 기간 슬라이싱 — _parse_period / _compute_metrics_paired.

배경: calibration.period / validation 값이 목적함수에 실제 반영되는지 검증.
(2026-07-04 관측자료 가용기간 재산정에 따라 추가된 기능)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.calibration.auto import _compute_metrics_paired, _parse_period


# ── _parse_period ───────────────────────────────────────────────────────────

def test_parse_period_both_empty_returns_none() -> None:
    """둘 다 비면 None → 전체 기간 평가(하위호환)."""
    assert _parse_period("", "") is None
    assert _parse_period(None, None) is None


def test_parse_period_full() -> None:
    s, e = _parse_period("2015-01-01", "2017-12-31")
    assert s == pd.Timestamp("2015-01-01")
    assert e == pd.Timestamp("2017-12-31")


def test_parse_period_one_sided() -> None:
    """한쪽만 지정하면 그쪽만 경계."""
    s, e = _parse_period("2015-01-01", "")
    assert s == pd.Timestamp("2015-01-01") and e is None
    s2, e2 = _parse_period("", "2020-12-31")
    assert s2 is None and e2 == pd.Timestamp("2020-12-31")


# ── _compute_metrics_paired 기간 필터 ───────────────────────────────────────

def _series(start, days):
    dates = pd.date_range(start, periods=days, freq="D")
    return dates


def test_period_filters_pairs() -> None:
    """지정 기간 밖의 관측·모의 쌍은 메트릭에서 제외된다."""
    dates = _series("2015-01-01", 2000)          # 2015~2020 초반
    obs = np.linspace(1.0, 5.0, len(dates))
    sim = obs.copy()                              # 완전 일치 → NSE=1
    # 검증기간(2018~2020)만 sim 을 교란 → 그 구간만 성능 저하
    val_mask = dates >= pd.Timestamp("2018-01-01")
    sim_bad = sim.copy()
    sim_bad[val_mask] = sim_bad[val_mask] + 3.0

    cal = _compute_metrics_paired(dates.values, obs, dates.values, sim_bad,
                                  period=(pd.Timestamp("2015-01-01"),
                                          pd.Timestamp("2017-12-31")))
    val = _compute_metrics_paired(dates.values, obs, dates.values, sim_bad,
                                  period=(pd.Timestamp("2018-01-01"),
                                          pd.Timestamp("2020-12-31")))
    # 보정기간은 교란 없음 → NSE≈1, 검증기간은 교란 → NSE 낮음
    assert cal["nse"] == pytest.approx(1.0, abs=1e-6)
    assert val["nse"] < 0.9
    # 각 기간의 표본 수가 실제로 분리됐는지
    assert cal["n"] < len(dates)
    assert val["n"] < len(dates)


def test_period_none_uses_full_range() -> None:
    """period=None 이면 전체 sim∩obs 평가(기존 동작)."""
    dates = _series("2015-01-01", 1000)
    obs = np.linspace(1.0, 5.0, len(dates))
    sim = obs.copy()
    m = _compute_metrics_paired(dates.values, obs, dates.values, sim, period=None)
    assert m["n"] == len(dates)
    assert m["nse"] == pytest.approx(1.0, abs=1e-6)


def test_period_below_min_pairs_flagged() -> None:
    """기간 내 쌍이 5개 미만이면 안전값(-999) 반환."""
    dates = _series("2015-01-01", 1000)
    obs = np.linspace(1.0, 5.0, len(dates))
    sim = obs.copy()
    m = _compute_metrics_paired(dates.values, obs, dates.values, sim,
                                period=(pd.Timestamp("2019-01-01"),
                                        pd.Timestamp("2019-01-03")))
    assert m["nse"] == -999.0
    assert m["n"] < 5
