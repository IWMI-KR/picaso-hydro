"""관측 항목(observed) — 창 12개월 전체 + 저수지 실측 수위 (P3-C, 회귀 방지).

슬라이드 3(제니토스 구현 화면)의 범례에 `Observed` 가 있는데 선이 비어 있었다.
  · 하천: `observed` 는 **관측기상으로 구동한 SWAT+ 모의**값이다(실측 아님).
    예전에는 예측 **직전 6개월**만 채워서, 예측 3개월 구간이 늘 비었다.
  · 저수지: 늘 NaN 이었다. 연·월별 모의 산출물이 저장되지 않기 때문인데,
    **실측 수위 관측**(팔라우 Ngerimel 2018-01~2023-08)이 있으므로 그것을 쓴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.drought.dashboard_data import (
    _observed_monthly,
    _observed_reservoir_monthly,
    _series_frame,
)
from swat_py.drought.reservoir_forecast import ReservoirForecastParams
from swat_py.drought.season import series_ym

OFFSET = -22.0


def _curve():
    from swat_py.io.reservoir import StageStorageCurve
    return StageStorageCurve(elev_ft=np.array([23.34, 45.0]),
                             storage_m3=np.array([0.0, 103242.0]))


# ── ① 하천 observed — 창 12개월 전체 ─────────────────────────────────────────

def _daily_flow(start, end, outlet="avana", value=1.0):
    d = pd.date_range(start, end, freq="D")
    return pd.DataFrame({"date": d, outlet: np.full(len(d), value)})


def test_observed_covers_whole_window() -> None:
    """예전에는 직전 6개월만 채웠다 — 이제 예측월·이후월도 자료가 있으면 채운다."""
    win = series_ym(2016, [11, 12, 1])              # 2016-05 ~ 2017-04
    daily = _daily_flow("2016-01-01", "2017-12-31")
    got = _observed_monthly(daily, "avana", win)
    assert len(got) == 12                            # 창 12칸 모두
    assert set(got) == {m for _, m in win}


def test_observed_blank_when_data_ends() -> None:
    """운영 예측(미래)처럼 자료가 끊기면 그 뒤는 자연히 빈칸이 된다."""
    win = series_ym(2016, [11, 12, 1])              # 2016-05 ~ 2017-04
    daily = _daily_flow("2016-01-01", "2016-12-31")  # 2016 말까지만
    got = _observed_monthly(daily, "avana", win)
    assert set(got) == {5, 6, 7, 8, 9, 10, 11, 12}   # 2017-01~04 없음
    f = _series_frame(2016, [11, 12, 1])
    f["observed"] = f["month"].map(got)
    assert f["observed"].notna().sum() == 8
    assert f["observed"].iloc[-4:].isna().all()      # 창 끝 4칸은 비어 있다


def test_observed_separates_years_in_window() -> None:
    """같은 월 번호가 창 안에 한 번만 나오므로 연도 혼선이 없다."""
    win = series_ym(2016, [12, 1, 2])               # 2016-06 ~ 2017-05
    d1 = _daily_flow("2016-06-01", "2016-12-31", value=1.0)
    d2 = _daily_flow("2017-01-01", "2017-05-31", value=9.0)
    daily = pd.concat([d1, d2], ignore_index=True)
    got = _observed_monthly(daily, "avana", win)
    assert got[12] == pytest.approx(1.0)             # 2016-12
    assert got[1] == pytest.approx(9.0)              # 2017-01


# ── ② 저수지 observed — 실측 수위 ───────────────────────────────────────────

def _palau_params():
    return ReservoirForecastParams(
        gis_id=4, name="ngerimel", full_m3=103242.0, dead_m3=0.0,
        init_m3=103242.0, curve=_curve(), datum_offset_ft=OFFSET)


def _cfg_with_obs(tmp_path, rows):
    """cfg.Observations 에 wlevel 관측 1건을 둔 최소 설정 스텁."""
    csv = tmp_path / "ngerimel.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    obs = type("O", (), {"variable": "wlevel", "outlet_id": 4,
                         "obs_file": str(csv), "obs_column": "wlevel_ft"})()
    return type("C", (), {"Observations": [obs], "ObservedDataDir": str(tmp_path),
                          "PrjDir": str(tmp_path)})()


def test_reservoir_observed_from_gauge(tmp_path) -> None:
    """저수지는 늘 NaN 이었다 — 실측 수위를 월평균으로 채운다."""
    d = pd.date_range("2021-11-01", "2022-01-31", freq="D")
    cfg = _cfg_with_obs(tmp_path, {"date": d, "wlevel_ft": np.where(
        d.month == 11, 22.0, np.where(d.month == 12, 18.0, 14.0))})
    win = series_ym(2021, [11, 12, 1])
    got = _observed_reservoir_monthly(cfg, _palau_params(), win, level_based=True)
    assert got[11] == pytest.approx(22.0)
    assert got[12] == pytest.approx(18.0)
    assert got[1] == pytest.approx(14.0)      # 2022-01 — 해를 넘긴 달


def test_reservoir_observed_converts_to_pct_when_not_level(tmp_path) -> None:
    """저수량% 기준 대시보드면 곡선으로 % 환산해서 준다."""
    d = pd.date_range("2021-11-01", "2021-11-30", freq="D")
    cfg = _cfg_with_obs(tmp_path, {"date": d, "wlevel_ft": 23.0})   # 만수
    win = series_ym(2021, [11, 12, 1])
    got = _observed_reservoir_monthly(cfg, _palau_params(), win, level_based=False)
    assert got[11] == pytest.approx(100.0, abs=0.01)   # 만수 → 100%


def test_reservoir_observed_empty_outside_period(tmp_path) -> None:
    """관측 기간 밖(예: 2016)이면 빈 dict — 화면에 선이 안 그려진다."""
    d = pd.date_range("2021-11-01", "2022-01-31", freq="D")
    cfg = _cfg_with_obs(tmp_path, {"date": d, "wlevel_ft": 20.0})
    win = series_ym(2016, [11, 12, 1])
    assert _observed_reservoir_monthly(cfg, _palau_params(), win, level_based=True) == {}


def test_reservoir_observed_no_params_or_file(tmp_path) -> None:
    cfg = type("C", (), {"Observations": [], "ObservedDataDir": str(tmp_path),
                         "PrjDir": str(tmp_path)})()
    win = series_ym(2021, [11, 12, 1])
    assert _observed_reservoir_monthly(cfg, _palau_params(), win, level_based=True) == {}
    assert _observed_reservoir_monthly(cfg, None, win, level_based=True) == {}
