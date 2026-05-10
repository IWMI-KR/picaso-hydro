"""run.py — determine_monthly_ch 결합분포 샘플링 검증 (시드 고정)."""
from __future__ import annotations

import numpy as np
import pytest

from acidwg_py.run import determine_monthly_ch


# ── 결정적(deterministic) 입력 ───────────────────────────────────────────────

def test_all_weight_on_AN_prcp_forces_AN_wetness() -> None:
    """prob_prec[AN]=1, 나머지=0 → 모든 월의 sf_wetness = 'AN'."""
    n = 3
    prob_prec = np.zeros((3, n))
    prob_prec[0, :] = 1.0     # row 0 = AN
    # prob_t2m도 결정적으로 두지만 영향은 sf_warmness만
    prob_t2m = np.zeros((3, n))
    prob_t2m[1, :] = 1.0      # row 1 = NN

    np.random.seed(0)
    out = determine_monthly_ch(prob_prec, prob_t2m)
    assert out["sf_wetness"]  == ["AN"] * n
    assert out["sf_warmness"] == ["NN"] * n


def test_all_weight_on_BN_t2m_forces_BN_warmness() -> None:
    n = 5
    prob_prec = np.zeros((3, n)); prob_prec[1, :] = 1.0   # NN
    prob_t2m  = np.zeros((3, n)); prob_t2m[2, :]  = 1.0   # BN

    np.random.seed(0)
    out = determine_monthly_ch(prob_prec, prob_t2m)
    assert out["sf_wetness"]  == ["NN"] * n
    assert out["sf_warmness"] == ["BN"] * n


# ── 시드 재현성 ──────────────────────────────────────────────────────────────

def test_same_seed_yields_same_result() -> None:
    n = 10
    prob_prec = np.full((3, n), 1.0 / 3)
    prob_t2m  = np.full((3, n), 1.0 / 3)

    np.random.seed(42)
    out1 = determine_monthly_ch(prob_prec, prob_t2m)
    np.random.seed(42)
    out2 = determine_monthly_ch(prob_prec, prob_t2m)

    assert out1 == out2


def test_different_seeds_yield_different_results() -> None:
    """균등 확률이라도 시드가 다르면 다른 결과."""
    n = 30      # 충분히 길게 하여 우연 일치 회피
    prob_prec = np.full((3, n), 1.0 / 3)
    prob_t2m  = np.full((3, n), 1.0 / 3)

    np.random.seed(0)
    out1 = determine_monthly_ch(prob_prec, prob_t2m)
    np.random.seed(123)
    out2 = determine_monthly_ch(prob_prec, prob_t2m)

    assert out1 != out2


# ── 음수/0 처리 (uniform fallback) ───────────────────────────────────────────

def test_negative_probs_clipped_to_zero() -> None:
    """음수 확률은 0으로 클립. 합계 0이면 균등 샘플링."""
    n = 1
    prob_prec = np.array([[-1.0], [-1.0], [-1.0]])
    prob_t2m  = np.array([[-1.0], [-1.0], [-1.0]])

    # uniform fallback이 적용되어 ValueError 없이 통과되어야 함
    np.random.seed(0)
    out = determine_monthly_ch(prob_prec, prob_t2m)
    assert out["sf_wetness"][0]  in {"AN", "NN", "BN"}
    assert out["sf_warmness"][0] in {"AN", "NN", "BN"}


# ── 출력 길이 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n_months", [1, 3, 6, 12])
def test_output_length_matches_n_months(n_months: int) -> None:
    prob_prec = np.full((3, n_months), 1.0 / 3)
    prob_t2m  = np.full((3, n_months), 1.0 / 3)

    np.random.seed(0)
    out = determine_monthly_ch(prob_prec, prob_t2m)
    assert len(out["sf_wetness"])  == n_months
    assert len(out["sf_warmness"]) == n_months


def test_output_categories_are_valid() -> None:
    """모든 출력값이 AN/NN/BN 중 하나."""
    n_months = 50
    rng = np.random.default_rng(0)
    # 임의의 정규화된 확률
    prob_prec = rng.random((3, n_months))
    prob_prec /= prob_prec.sum(axis=0, keepdims=True)
    prob_t2m  = rng.random((3, n_months))
    prob_t2m  /= prob_t2m.sum(axis=0, keepdims=True)

    np.random.seed(0)
    out = determine_monthly_ch(prob_prec, prob_t2m)
    valid = {"AN", "NN", "BN"}
    assert all(v in valid for v in out["sf_wetness"])
    assert all(v in valid for v in out["sf_warmness"])
