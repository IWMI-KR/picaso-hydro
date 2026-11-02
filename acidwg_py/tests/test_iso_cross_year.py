"""해를 넘기는 시즌의 ISO 연도 추첨 — 범위 초과 재발 방지.

``generating_iso()`` 는 해를 넘기는 시즌(NDJ·DJF 등)에서 기온 편차 재료를
``n = n_years - 1`` 벌만 만든다. 마지막 달력 연도는 뒤따르는 1월이 없어
계절 한 벌을 이루지 못하기 때문이다. 그런데 연도 후보는 ``raw_basin_anom``
(달력 연도 ``n_years`` 행)에서 뽑혀, 마지막 해가 걸리면 색인이 범위를 벗어났다.

    index 35 is out of bounds for axis 0 with size 35
    (팔라우 2016_NDJ 30멤버, 제니토스 2026-10-20 보고)

run.py 의 재시도 루프가 오류를 삼켜 결과는 나왔지만, 로그에 traceback 이 쌓이고
**마지막 연도는 앙상블에서 구조적으로 빠졌다.**
"""
from __future__ import annotations

import numpy as np
import pytest

from acidwg_py.simulation.temperature import LEVELS, generating_iso
from acidwg_py.utils import MONTH_LENGTH

N_YEARS = 6
D = 1
NOV1 = int(sum(MONTH_LENGTH[:10]))      # 11월 1일 = 304
JAN1 = 0
MAR1 = int(sum(MONTH_LENGTH[:2]))       # 3월 1일 = 59


def _iso_args(sim_period, nov_anom):
    """연도 k 의 편차를 전부 k 로 채운 합성 입력 — 뽑힌 연도를 값으로 역추적한다.

    nov_anom : 연도별 첫 시뮬레이션 월 이상편차. 어느 해가 후보가 되는지 결정한다.
    """
    dev = np.zeros((N_YEARS, 365, D))
    for k in range(N_YEARS):
        dev[k, :, :] = k
    breaks = np.zeros((12, 4))
    breaks[:, 0], breaks[:, 1], breaks[:, 2], breaks[:, 3] = -np.inf, -1.0, 1.0, np.inf
    raw = np.zeros((N_YEARS, 12))
    raw[:, sim_period[0] - 1] = nov_anom
    return dict(
        sim_period=sim_period,
        iso_tmax_mean=np.zeros((365, D)),
        iso_tmin_mean=np.zeros((365, D)),
        iso_tmax_dev=dev,
        iso_tmin_dev=dev.copy(),
        breaks=breaks,
        length_period=len(sim_period),
        levels=LEVELS,
        prcp_scenario=np.zeros((365, 2 + D)),
        fit_mu=None,
        mean_trend=None,
        raw_basin_anom=raw,
    )


# ── 재발 방지: 마지막 연도가 후보에 들어도 터지지 않는다 ─────────────────────

def test_해넘김_마지막연도만_후보여도_오류없이_생성된다():
    """옛 코드라면 IndexError. 재료는 5벌(n=5)인데 후보가 5번(6번째)뿐인 상황."""
    # 마지막 해만 크게 따뜻함 → AN 후보 = [5] 하나뿐, 그런데 재료는 0~4 만 있다
    args = _iso_args([11, 12, 1], nov_anom=[0, 0, 0, 0, 0, 5.0])
    np.random.seed(0)
    iso = generating_iso(warmness=["AN", "AN", "AN"], **args)

    assert set(iso) == {"TMAX", "TMIN"}
    assert iso["TMAX"].shape == (365, D)
    picked_nov = float(iso["TMAX"][NOV1, 0])
    assert picked_nov in {0.0, 1.0, 2.0, 3.0, 4.0}   # 범위 안으로 되돌아왔다


def test_해넘김_범위밖_후보만_걸러내고_나머지는_그대로_쓴다():
    """후보 [0, 5] → 5는 버리고 0만 남아야 한다(결정적)."""
    args = _iso_args([11, 12, 1], nov_anom=[5.0, 0, 0, 0, 0, 5.0])
    for seed in range(20):
        np.random.seed(seed)
        iso = generating_iso(warmness=["AN", "AN", "AN"], **args)
        # 재료 k 행 = 달력연도 k 의 11·12월 + 달력연도 k+1 의 1~10월
        assert float(iso["TMAX"][NOV1, 0]) == 0.0      # 11월 → 연도 0
        assert float(iso["TMAX"][JAN1, 0]) == 1.0      # 1월  → 연도 1


def test_해넘김_마지막연도는_절대_뽑히지_않는다():
    """모든 해가 후보(NN)일 때도 n_years-1 번째는 재료가 없어 제외되어야 한다."""
    args = _iso_args([12, 1, 2], nov_anom=[0, 0, 0, 0, 0, 0])   # 전부 NN
    seen = set()
    for seed in range(300):
        np.random.seed(seed)
        iso = generating_iso(warmness=["NN", "NN", "NN"], **args)
        seen.add(float(iso["TMAX"][sum(MONTH_LENGTH[:11]), 0]))  # 12월 1일
    assert seen, "한 번도 생성되지 않았다"
    assert max(seen) <= N_YEARS - 2, f"범위 밖 연도가 뽑혔다: {sorted(seen)}"
    assert len(seen) > 1, "한 해만 반복해 뽑혔다 — 무작위성이 사라졌다"


# ── 해를 넘기지 않는 시즌은 기존 동작 그대로 ────────────────────────────────

def test_같은해_시즌은_마지막연도도_쓸_수_있다():
    """MAM 처럼 해를 넘기지 않으면 재료가 n_years 벌이라 마지막 해도 유효하다."""
    args = _iso_args([3, 4, 5], nov_anom=[0, 0, 0, 0, 0, 5.0])
    np.random.seed(0)
    iso = generating_iso(warmness=["AN", "AN", "AN"], **args)
    assert float(iso["TMAX"][MAR1, 0]) == float(N_YEARS - 1)   # 5번 = 마지막 해


def test_후보가_모두_범위밖이면_전체에서_고른다():
    """fallback 이 살아 있는지 — 값이 항상 유효 범위 안이어야 한다."""
    args = _iso_args([11, 12, 1], nov_anom=[0, 0, 0, 0, 0, 5.0])
    for seed in range(50):
        np.random.seed(seed)
        iso = generating_iso(warmness=["AN", "AN", "AN"], **args)
        assert 0.0 <= float(iso["TMAX"][NOV1, 0]) <= N_YEARS - 2


@pytest.mark.parametrize("season", [[11, 12, 1], [12, 1, 2], [10, 11, 12], [1, 2, 3]])
def test_여러_시즌에서_색인이_터지지_않는다(season):
    args = _iso_args(season, nov_anom=[0, 1.5, -1.5, 0, 2.0, 3.0])
    for w in LEVELS:
        for seed in range(10):
            np.random.seed(seed)
            iso = generating_iso(warmness=[w] * len(season), **args)
            assert np.isfinite(iso["TMAX"]).all()
            assert np.isfinite(iso["TMIN"]).all()
