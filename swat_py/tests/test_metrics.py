"""Tests for performance metrics."""

import numpy as np
import pytest

from swat_py.metrics.performance import nse, rmse, rsr, pbias, r2, mae, calc_all


def test_nse_perfect():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    assert nse(obs, obs) == pytest.approx(1.0)


def test_nse_with_nan():
    obs = np.array([1.0, np.nan, 3.0])
    sim = np.array([1.0, 2.0, 3.0])
    result = nse(obs, sim)
    assert not np.isnan(result)


def test_rmse_zero():
    obs = np.array([1.0, 2.0, 3.0])
    assert rmse(obs, obs) == pytest.approx(0.0)


def test_pbias_sign():
    obs = np.array([10.0, 10.0])
    sim = np.array([12.0, 12.0])   # over-prediction
    assert pbias(obs, sim) < 0     # PBIAS = (obs-sim)/obs*100 → negative


def test_r2_perfect():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    assert r2(obs, obs) == pytest.approx(1.0)


def test_kge_perfect():
    from swat_py.metrics.performance import kge
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert kge(obs, obs) == pytest.approx(1.0)


def test_kge_below_one_when_biased():
    from swat_py.metrics.performance import kge
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert kge(obs, obs * 0.5) < 1.0   # 크기 편의 → KGE 저하


def test_calc_all_keys():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    sim = np.array([1.1, 2.1, 2.9, 4.2])
    result = calc_all(obs, sim)
    assert set(result.keys()) == {"nse", "kge", "rmse", "rsr", "pbias", "r2", "mae", "nof"}


def test_empty_returns_nan():
    obs = np.array([np.nan, np.nan])
    sim = np.array([1.0, 2.0])
    assert np.isnan(nse(obs, sim))
