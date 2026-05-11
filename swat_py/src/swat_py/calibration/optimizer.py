"""DDS (Dynamically Dimensioned Search) — Tolson & Shoemaker (2007).

수문 모형 자동 보정에 가장 효율적 (SCE-UA 의 1/10 평가 횟수).

알고리즘
--------
1. θ_best = uniform_sample(bounds)
2. f_best = evaluate(θ_best)
3. for i = 1 to N:
4.     p = 1 - log(i)/log(N)              # 차원 축소 확률
5.     mask = (rand(n_dim) < p)             # 변경할 인자 선택
6.     θ_new = θ_best + N(0, r·(b-a)) · mask  # Gaussian perturbation
7.     reflect θ_new on bounds              # [a, b] 안 보장
8.     if evaluate(θ_new) is better than f_best: 갱신
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

import numpy as np


@dataclass
class DDSResult:
    """DDS 보정 결과."""
    best_x:      np.ndarray              # 최적 인자 벡터
    best_f:      float                    # 최적 목적함수 값
    history:     List[dict] = field(default_factory=list)
    # history[i] = {iter, x, f, is_best, n_dims_changed}


def dds_optimize(
    evaluate:     Callable[[np.ndarray], float],
    bounds:       Sequence[tuple],         # [(low, high), ...]
    n_iterations: int = 300,
    *,
    r:           float = 0.20,             # perturbation factor (Tolson 권장)
    maximize:    bool = True,                # NSE/KGE → True, |PBIAS|/RMSE → False
    seed:        Optional[int] = None,
    initial_x:   Optional[np.ndarray] = None,
    callback:    Optional[Callable[[int, np.ndarray, float, bool], None]] = None,
) -> DDSResult:
    """DDS 알고리즘으로 evaluate 함수를 최적화.

    Parameters
    ----------
    evaluate     : θ (ndarray) → 목적함수 값 (float)
    bounds       : 인자별 (low, high) 튜플 리스트
    n_iterations : 평가 횟수 (200~500 권장)
    r            : perturbation factor (Tolson 0.20 기본)
    maximize     : True 면 큰 값이 좋음, False 면 작은 값
    seed         : 재현성 시드
    initial_x    : 초기 해 (None 이면 random uniform)
    callback     : (iter, x, f, is_best) 호출 — 진행률·로깅

    Returns
    -------
    DDSResult
    """
    rng = np.random.default_rng(seed)
    bounds = np.array(bounds, dtype=float)
    n_dim = len(bounds)
    low, high = bounds[:, 0], bounds[:, 1]
    span = high - low

    if np.any(span <= 0):
        raise ValueError("bounds 중 high <= low 인 항목이 있습니다.")

    # 초기 해
    if initial_x is None:
        x_best = low + rng.random(n_dim) * span
    else:
        x_best = np.array(initial_x, dtype=float)
        if x_best.shape != (n_dim,):
            raise ValueError(f"initial_x shape != ({n_dim},)")
        x_best = np.clip(x_best, low, high)

    f_best = float(evaluate(x_best))
    history = [{
        "iter": 1, "x": x_best.copy(), "f": f_best,
        "is_best": True, "n_dims_changed": n_dim,
    }]
    if callback:
        callback(1, x_best, f_best, True)

    better = (lambda a, b: a > b) if maximize else (lambda a, b: a < b)

    log_N = math.log(n_iterations) if n_iterations > 1 else 1.0
    for i in range(2, n_iterations + 1):
        # 차원 축소 확률
        p = 1.0 - math.log(i) / log_N
        # 최소 1개 차원은 변경
        mask = rng.random(n_dim) < p
        if not mask.any():
            j = rng.integers(0, n_dim)
            mask[j] = True

        # Gaussian perturbation (mask 된 차원만)
        perturb = rng.normal(0.0, r * span) * mask
        x_new = x_best + perturb

        # 경계 반사
        x_new = _reflect_on_bounds(x_new, low, high)

        f_new = float(evaluate(x_new))
        is_best = better(f_new, f_best)
        if is_best:
            x_best = x_new
            f_best = f_new

        history.append({
            "iter": i, "x": x_new.copy(), "f": f_new,
            "is_best": is_best, "n_dims_changed": int(mask.sum()),
        })
        if callback:
            callback(i, x_new, f_new, is_best)

    return DDSResult(best_x=x_best, best_f=f_best, history=history)


def _reflect_on_bounds(x: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """경계 [low, high] 를 벗어나면 반사 — 항상 [low, high] 안 반환."""
    out = x.copy()
    span = high - low
    # under low
    under = out < low
    if under.any():
        out[under] = low[under] + (low[under] - out[under])
        # 반사 후에도 high 초과면 clip
        out[under] = np.minimum(out[under], high[under])
    # over high
    over = out > high
    if over.any():
        out[over] = high[over] - (out[over] - high[over])
        out[over] = np.maximum(out[over], low[over])
    return out
