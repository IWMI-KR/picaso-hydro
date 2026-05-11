"""다중 obs 가중 합 결합 — _normalize_metric / _combined_objective."""
from __future__ import annotations

import pytest

from swat_py.calibration.auto import _combined_objective, _normalize_metric


# ── _normalize_metric ──────────────────────────────────────────────────────

def test_normalize_nse_passthrough() -> None:
    """NSE/KGE/R² 는 그대로 (이미 max 방향)."""
    assert _normalize_metric(0.8, "NSE") == pytest.approx(0.8)
    assert _normalize_metric(0.5, "KGE") == pytest.approx(0.5)
    assert _normalize_metric(0.95, "R2") == pytest.approx(0.95)


def test_normalize_pbias_zero_to_one() -> None:
    """PBIAS 0% → 1.0 (best)."""
    assert _normalize_metric(0.0, "PBIAS") == pytest.approx(1.0)


def test_normalize_pbias_inverted() -> None:
    """|PBIAS| 50% → 0.5 (절반 좋음)."""
    assert _normalize_metric(50.0, "PBIAS") == pytest.approx(0.5)
    assert _normalize_metric(-50.0, "PBIAS") == pytest.approx(0.5)   # 절대값


def test_normalize_pbias_100_zero() -> None:
    """|PBIAS| 100% → 0.0."""
    assert _normalize_metric(100.0, "PBIAS") == pytest.approx(0.0)


def test_normalize_rmse_zero_one() -> None:
    """RMSE 0 → 1.0, ∞ → 0."""
    assert _normalize_metric(0.0, "RMSE") == pytest.approx(1.0)
    assert _normalize_metric(1.0, "RMSE") == pytest.approx(0.5)
    assert _normalize_metric(99.0, "RMSE") == pytest.approx(0.01)


def test_normalize_case_insensitive() -> None:
    assert _normalize_metric(0.7, "nse") == pytest.approx(0.7)
    assert _normalize_metric(20.0, "pbias") == pytest.approx(0.8)


# ── _combined_objective ────────────────────────────────────────────────────

class _Obs:
    """yaml.calibration.observations[] mock — id, objective, weight 만 필요."""
    def __init__(self, id, objective, weight):
        self.id = id; self.objective = objective; self.weight = weight


def test_single_obs_returns_single_metric() -> None:
    """obs 1개 + weight 1.0 → 원본 정규화값 그대로."""
    metrics = [{"nse": 0.75}]
    obs = [_Obs("a", "NSE", 1.0)]
    f, detail = _combined_objective(metrics, obs)
    assert f == pytest.approx(0.75)
    assert detail["a__nse"] == pytest.approx(0.75)
    assert detail["a__norm"] == pytest.approx(0.75)


def test_two_obs_weighted_sum() -> None:
    """flow NSE 0.8 (w=1.0) + tn PBIAS 20% (w=0.3) 결합."""
    metrics = [{"nse": 0.8}, {"pbias": 20.0}]
    obs = [_Obs("flow", "NSE", 1.0), _Obs("tn", "PBIAS", 0.3)]
    f, detail = _combined_objective(metrics, obs)
    # f = 1.0 × 0.8 + 0.3 × (1 - 20/100) = 0.8 + 0.24 = 1.04
    assert f == pytest.approx(1.04)
    assert detail["flow__nse"]   == pytest.approx(0.8)
    assert detail["tn__pbias"]   == pytest.approx(20.0)
    assert detail["flow__norm"] == pytest.approx(0.8)
    assert detail["tn__norm"]   == pytest.approx(0.8)


def test_three_obs_combined() -> None:
    metrics = [{"nse": 0.65}, {"pbias": 15.0}, {"nse": 0.40}]
    obs = [_Obs("flow", "NSE", 1.0),
           _Obs("tn",   "PBIAS", 0.3),
           _Obs("tp",   "NSE", 0.3)]
    f, _ = _combined_objective(metrics, obs)
    # 1.0×0.65 + 0.3×(1-0.15) + 0.3×0.40 = 0.65 + 0.255 + 0.12 = 1.025
    assert f == pytest.approx(1.025)


def test_unknown_metric_returns_default() -> None:
    """obs 의 objective 가 metrics dict 에 없을 때 NSE/KGE/R² → -999, else 999."""
    metrics = [{}]   # 메트릭 비어 있음
    obs = [_Obs("x", "NSE", 1.0)]
    f, _ = _combined_objective(metrics, obs)
    assert f == pytest.approx(-999.0)


def test_higher_combined_means_better_overall() -> None:
    """수질이 나쁘면 flow 만 좋아도 종합 점수 낮음."""
    # 시나리오 A: flow 적당히 좋음 + 수질 좋음
    mA = [{"nse": 0.65}, {"pbias": 10.0}]
    # 시나리오 B: flow 매우 좋음 + 수질 매우 나쁨
    mB = [{"nse": 0.80}, {"pbias": 80.0}]
    obs = [_Obs("flow", "NSE", 1.0), _Obs("tn", "PBIAS", 0.3)]
    fA, _ = _combined_objective(mA, obs)
    fB, _ = _combined_objective(mB, obs)
    # A: 0.65 + 0.3×0.9 = 0.92
    # B: 0.80 + 0.3×0.2 = 0.86
    assert fA > fB
