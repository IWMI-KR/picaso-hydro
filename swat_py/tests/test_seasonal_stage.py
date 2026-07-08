"""계절(3개월 평균) 단일 리스크 — _seasonal_stage_row + make_season_pie."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swat_py.drought.dashboard_data import _seasonal_stage_row
from swat_py.drought.figure import make_season_pie


def _mem(rows):
    """rows: list of [m4, m5, m6] per member → DataFrame[member × month]."""
    return pd.DataFrame(rows, columns=[4, 5, 6])


def test_seasonal_uses_3month_mean_per_member():
    # 멤버별 3개월 평균: A=110(Normal), B=90(Watch), C=75(Warning), D=50(Crisis)
    mem = _mem([[110, 110, 110], [90, 90, 90], [75, 75, 75], [50, 50, 50]])
    row = _seasonal_stage_row(mem, [4, 5, 6], 100, 85, 65, "AMJ")
    assert row["season"] == "AMJ"
    assert row["Normal"] == pytest.approx(25.0)
    assert row["Watch"] == pytest.approx(25.0)
    assert row["Warning"] == pytest.approx(25.0)
    assert row["Crisis"] == pytest.approx(25.0)


def test_seasonal_mean_differs_from_monthly():
    """월별로는 Crisis가 최빈이라도 3개월 평균이 높으면 계절은 Normal일 수 있음(양극 상쇄)."""
    # 멤버 각자 한 달만 매우 낮고 두 달 높음 → 월별 분포엔 저값 있으나 3개월 평균은 높음
    mem = _mem([[150, 150, 0], [150, 0, 150], [0, 150, 150]])  # 평균 각 100
    row = _seasonal_stage_row(mem, [4, 5, 6], 100, 85, 65, "AMJ")
    # 3개월 평균=100 → >85, ≤100 → Watch (경계: >q185=100 False → Watch)
    assert row["most_likely"] == "Watch"


def test_seasonal_none_when_no_mem():
    assert _seasonal_stage_row(None, [4, 5, 6], 100, 85, 65, "AMJ") is None


def test_seasonal_dropna():
    mem = _mem([[110, 110, 110], [np.nan, np.nan, np.nan], [50, 50, 50]])
    row = _seasonal_stage_row(mem, [4, 5, 6], 100, 85, 65, "AMJ")
    # NaN 멤버 제외 → 2멤버(Normal, Crisis)
    assert row["Normal"] == pytest.approx(50.0)
    assert row["Crisis"] == pytest.approx(50.0)


def test_make_season_pie(tmp_path):
    d = tmp_path / "ngerimel"; d.mkdir()
    pd.DataFrame([{"season": "AMJ", "Normal": 30, "Watch": 5, "Warning": 5,
                   "Crisis": 60, "most_likely": "Crisis"}]).to_csv(
        d / "stage_prob_season.csv", index=False)
    out = make_season_pie(d)
    assert out is not None and out.is_file() and out.stat().st_size > 0
    assert out.name == "dashboard_ngerimel_season_pie.png"


def test_make_season_pie_missing(tmp_path):
    d = tmp_path / "x"; d.mkdir()
    assert make_season_pie(d) is None


# ── 그림: 4-panel 파이 + 표 평균 행 ────────────────────────────────────────────

def _full_outlet_dir(tmp_path, with_season=True):
    import numpy as np
    d = tmp_path / "ngerikiil"; d.mkdir()
    pd.DataFrame({"month": range(1, 13), "hist_mean": np.linspace(1, 3, 12),
                  "observed": [np.nan]*12,
                  "forecast_mean": [np.nan]*3+[2.0, 1.5, 1.0]+[np.nan]*6,
                  "p5": [np.nan]*3+[0.5, 0.3, 0.2]+[np.nan]*6,
                  "p25": [np.nan]*3+[1.0, 0.8, 0.5]+[np.nan]*6,
                  "p50": [np.nan]*3+[2.0, 1.5, 1.0]+[np.nan]*6,
                  "p75": [np.nan]*3+[2.5, 2.0, 1.5]+[np.nan]*6,
                  "p95": [np.nan]*3+[3.0, 2.5, 2.0]+[np.nan]*6}).to_csv(d/"series.csv", index=False)
    pd.DataFrame([{"method": "fdc_exceedance", "nw_input": 70, "ww_input": 90,
                   "wc_input": 95, "n_ensemble": 900, "normal_watch": 2.0,
                   "watch_warning": 1.0, "warning_crisis": 0.5,
                   "Q95d": 0.5, "Q185d": 2.0, "Q275d": 1.0, "Q355d": 0.5}]).to_csv(d/"thresholds.csv", index=False)
    pd.DataFrame([{"month": 4, "Normal": 40, "Watch": 30, "Warning": 20, "Crisis": 10, "most_likely": "Normal"},
                  {"month": 5, "Normal": 20, "Watch": 30, "Warning": 30, "Crisis": 20, "most_likely": "Watch"},
                  {"month": 6, "Normal": 10, "Watch": 20, "Warning": 30, "Crisis": 40, "most_likely": "Crisis"}]).to_csv(d/"stage_prob.csv", index=False)
    if with_season:
        pd.DataFrame([{"season": "AMJ", "Normal": 20, "Watch": 30, "Warning": 30,
                       "Crisis": 20, "most_likely": "Watch"}]).to_csv(d/"stage_prob_season.csv", index=False)
    return d


def test_stage_pie_has_4_panels_with_season(tmp_path):
    from swat_py.drought.figure import make_stage_pie, _season_panel
    d = _full_outlet_dir(tmp_path, with_season=True)
    assert _season_panel(d) is not None                  # 계절 패널 존재
    out = make_stage_pie(d)
    assert out.is_file() and out.stat().st_size > 0      # 4-panel 파이 생성


def test_stage_pie_3_panels_without_season(tmp_path):
    from swat_py.drought.figure import make_stage_pie, _season_panel
    d = _full_outlet_dir(tmp_path, with_season=False)
    assert _season_panel(d) is None                      # 계절 없음 → 월별만
    out = make_stage_pie(d)
    assert out.is_file()


def test_outlet_figure_table_with_season_row(tmp_path):
    from swat_py.drought.figure import make_outlet_figure
    d = _full_outlet_dir(tmp_path, with_season=True)
    out = make_outlet_figure(d)                          # 표에 3개월평균 행 포함
    assert out.is_file() and out.stat().st_size > 0
