"""DDS 옵티마이저 단위 테스트."""
from __future__ import annotations

import numpy as np
import pytest

from swat_py.calibration import DDSResult, dds_optimize


def test_dds_sphere_minimization() -> None:
    """f(x) = Σ x² (최소화) — 원점 [0,0,0,...] 수렴."""
    bounds = [(-10.0, 10.0)] * 5
    result = dds_optimize(
        evaluate=lambda x: float((x ** 2).sum()),
        bounds=bounds, n_iterations=300, maximize=False, seed=0,
    )
    assert isinstance(result, DDSResult)
    assert result.best_f < 1.0   # 작은 값으로 수렴
    np.testing.assert_allclose(result.best_x, np.zeros(5), atol=1.0)


def test_dds_negative_sphere_maximization() -> None:
    """f(x) = -Σ x² (최대화) — 원점 수렴."""
    result = dds_optimize(
        evaluate=lambda x: -float((x ** 2).sum()),
        bounds=[(-5.0, 5.0)] * 3, n_iterations=200, maximize=True, seed=1,
    )
    assert result.best_f > -1.0


def test_dds_reproducibility() -> None:
    """같은 seed → 같은 결과."""
    fn = lambda x: float((x ** 2).sum())
    b = [(-1.0, 1.0)] * 4
    r1 = dds_optimize(evaluate=fn, bounds=b, n_iterations=50, seed=42, maximize=False)
    r2 = dds_optimize(evaluate=fn, bounds=b, n_iterations=50, seed=42, maximize=False)
    np.testing.assert_allclose(r1.best_x, r2.best_x)
    assert r1.best_f == r2.best_f


def test_dds_initial_x() -> None:
    """initial_x 주입 — 시작점 보장."""
    result = dds_optimize(
        evaluate=lambda x: float(x[0] ** 2),
        bounds=[(-10.0, 10.0)], n_iterations=10,
        initial_x=np.array([5.0]), maximize=False, seed=0,
    )
    # 처음 평가는 [5.0]
    assert result.history[0]["x"][0] == pytest.approx(5.0)
    assert result.history[0]["f"] == pytest.approx(25.0)


def test_dds_bounds_respected() -> None:
    """모든 평가 점이 bounds 안."""
    low, high = -2.0, 3.0
    seen_x = []
    def fn(x):
        seen_x.append(x.copy())
        return float(x[0])
    dds_optimize(evaluate=fn, bounds=[(low, high)], n_iterations=100, seed=2)
    arr = np.array(seen_x)
    assert (arr >= low - 1e-9).all() and (arr <= high + 1e-9).all()


def test_dds_callback_invoked() -> None:
    cb_calls = []
    dds_optimize(
        evaluate=lambda x: float(x[0] ** 2),
        bounds=[(-1.0, 1.0)], n_iterations=20, seed=0,
        callback=lambda i, x, f, b: cb_calls.append(i),
    )
    assert cb_calls[0] == 1
    assert cb_calls[-1] == 20
    assert len(cb_calls) == 20


def test_dds_invalid_bounds_raises() -> None:
    with pytest.raises(ValueError, match="high <= low"):
        dds_optimize(evaluate=lambda x: 0.0, bounds=[(1.0, 1.0)],
                      n_iterations=5)
