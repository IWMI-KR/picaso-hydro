"""취수 시나리오 — 사용자 변경 입력 + 월별 취수 (회귀 방지).

배경: 팔라우 Ngerimel 은 모의 건기 수위가 실측보다 낮게 떨어지는 해가 있다
(2020: 모의 19.39 / 실측 22.76). 취수를 **상수**로 빼기 때문인데,
실제로는 수위가 낮아지면 취수를 줄이거나 Ngerikiil 양수로 돌린다.

그래서 두 가지를 둔다.
  ① 시나리오 취수(`drought.sources.*.initial_condition.withdrawal_m3s`) —
     레지스트리 물리 제원을 덮어쓰고, 결과 폴더에 꼬리표를 붙여 보존한다.
  ② 월별 취수(`withdrawal_monthly_m3s`) — 설정 파서는 예전부터 읽었지만
     **예측·평년 경로가 무시**하고 상수만 썼다(조용한 오동작).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.config.env import _DroughtCfg, _DroughtSource
from swat_py.drought.reservoir_forecast import (
    build_reservoir_forecast_params,
    monthly_capacity_series,
)

FULL, OFFSET = 103242.0, -22.0


def _curve():
    from swat_py.io.reservoir import StageStorageCurve
    return StageStorageCurve(elev_ft=np.array([23.34, 45.0]),
                             storage_m3=np.array([0.0, FULL]))


def _daily(start, end):
    d = pd.date_range(start, end, freq="D")
    return pd.DataFrame({"date": d, "flo_in": 0.0, "precip": 0.0,
                         "evap": 0.0, "seep": 0.0})


def _registry(wdr=0.0438, wmon=None):
    return type("R", (), {"spillway_ft": 45.0, "bottom_ft": 23.34, "gis_id": 4,
                          "withdrawal_m3s": wdr, "withdrawal_monthly_m3s": wmon,
                          "obs_datum_offset_ft": OFFSET})()


def _source(**kw):
    return _DroughtSource(name="ngerimel", type="reservoir", reservoir="ngerimel",
                          outlets={4: "ngerimel"}, **kw)


# ── ① 시나리오 취수가 레지스트리를 덮어쓴다 ─────────────────────────────────

def test_scenario_withdrawal_overrides_registry() -> None:
    p = build_reservoir_forecast_params(_source(withdrawal_m3s=0.03),
                                        _registry(0.0438), _curve())
    assert p.withdrawal_m3s == pytest.approx(0.03)


def test_registry_used_when_no_scenario() -> None:
    p = build_reservoir_forecast_params(_source(), _registry(0.0438), _curve())
    assert p.withdrawal_m3s == pytest.approx(0.0438)
    assert p.withdrawal_monthly_m3s is None


def test_scenario_monthly_overrides_everything() -> None:
    wmon = [0.01] * 3 + [0.0438] * 9
    p = build_reservoir_forecast_params(_source(withdrawal_m3s=0.03,
                                                withdrawal_monthly_m3s=wmon),
                                        _registry(0.0438), _curve())
    assert p.withdrawal_monthly_m3s == wmon          # 월별이 상수보다 우선


def test_registry_monthly_is_now_honoured() -> None:
    """예전에는 레지스트리의 월별 취수를 예측 경로가 조용히 무시했다."""
    wmon = [0.01] * 12
    p = build_reservoir_forecast_params(_source(), _registry(0.0438, wmon), _curve())
    assert p.withdrawal_monthly_m3s == wmon


# ── 결과 폴더 꼬리표 — 시나리오끼리 덮어쓰지 않는다 ─────────────────────────

def test_suffix_includes_withdrawal() -> None:
    cfg = _DroughtCfg(sources=[_source(init_water_level_ft=44.0,
                                       withdrawal_m3s=0.03)])
    assert cfg.forecast_suffix() == "__ic44.0ft-scn_wdr0.0300"


def test_suffix_monthly_tag() -> None:
    cfg = _DroughtCfg(sources=[_source(init_water_level_ft=44.0,
                                       withdrawal_monthly_m3s=[0.01] * 12)])
    assert cfg.forecast_suffix() == "__ic44.0ft-scn_wdrmon"


def test_suffix_unchanged_without_scenario() -> None:
    """취수 시나리오가 없으면 기존 폴더명 그대로 — 기존 산출물과 호환."""
    cfg = _DroughtCfg(sources=[_source(init_water_level_ft=44.0)])
    assert cfg.forecast_suffix() == "__ic44.0ft-scn"
    assert _DroughtCfg(sources=[_DroughtSource(name="avana")]).forecast_suffix() == ""


def test_two_withdrawal_scenarios_get_different_folders() -> None:
    a = _DroughtCfg(sources=[_source(init_water_level_ft=44.0, withdrawal_m3s=0.0438)])
    b = _DroughtCfg(sources=[_source(init_water_level_ft=44.0, withdrawal_m3s=0.0200)])
    assert a.forecast_suffix() != b.forecast_suffix()


# ── ② 월별 취수가 물수지에 실제로 쓰인다 ───────────────────────────────────

def test_monthly_withdrawal_changes_water_balance() -> None:
    df = _daily("2026-01-01", "2026-03-31")
    const = monthly_capacity_series(df, full_m3=FULL, init_m3=FULL,
                                    withdrawal_m3s=0.0438, dead_m3=0.0,
                                    curve=_curve(), datum_offset_ft=OFFSET)
    mon = monthly_capacity_series(df, full_m3=FULL, init_m3=FULL,
                                  withdrawal_m3s=0.0438, dead_m3=0.0,
                                  curve=_curve(), datum_offset_ft=OFFSET,
                                  withdrawal_monthly_m3s=[0.01] * 3 + [0.0438] * 9)
    assert const[1]["water_level_ft"] == pytest.approx(1.34, abs=0.01)   # 고갈
    assert mon[1]["water_level_ft"] > const[1]["water_level_ft"]         # 덜 빠짐
    assert mon[3]["water_level_ft"] > const[3]["water_level_ft"]


def test_monthly_equal_to_constant_matches() -> None:
    """월별 12개를 모두 같은 값으로 주면 상수와 같은 결과."""
    df = _daily("2026-01-01", "2026-02-28")
    a = monthly_capacity_series(df, full_m3=FULL, init_m3=FULL, withdrawal_m3s=0.02,
                                dead_m3=0.0, curve=_curve(), datum_offset_ft=OFFSET)
    b = monthly_capacity_series(df, full_m3=FULL, init_m3=FULL, withdrawal_m3s=0.0,
                                dead_m3=0.0, curve=_curve(), datum_offset_ft=OFFSET,
                                withdrawal_monthly_m3s=[0.02] * 12)
    assert a[1]["storage_pct"] == pytest.approx(b[1]["storage_pct"])


def test_monthly_must_have_12_values() -> None:
    with pytest.raises(ValueError, match="12개"):
        monthly_capacity_series(_daily("2026-01-01", "2026-01-31"), full_m3=FULL,
                                init_m3=FULL, withdrawal_monthly_m3s=[0.01, 0.02])
