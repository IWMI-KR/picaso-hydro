"""대시보드 series 의 연-월(ym) — 연속 12개월 창 (회귀 방지).

예전 series 는 달력 1~12월 **고정**이었다. 그래서
  · 예측 계절이 NDJ·DJF 면 1·2월이 어느 해인지 알 수 없고,
  · 관측(observed)은 "전년도 달"을 표현할 자리가 없고,
  · 그림은 월 번호를 x 좌표로 써서 해가 바뀌면 선이 뒤로 접혔다.

APCC 요청(최기섭 2026-10-02): series 를 **예측 시즌을 품은 연속 12개월**로
만들고 각 칸에 연-월을 붙이는 ``ym`` 배열을 넣어 달라
(구간 = 예측 시작 6개월 전 ~ 예측 끝 3개월 뒤).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.drought.dashboard_data import _series_frame
from swat_py.drought.figure import _month_label, _x_axis
from swat_py.drought.season import (
    SEASON_MONTHS,
    following_ym,
    period_ym,
    preceding_ym,
    series_ym,
    ym_labels,
)

# ── season.series_ym — 창 산술 ────────────────────────────────────────────────

def test_series_ym_window_for_ndj() -> None:
    """2025_NDJ(2025-11~2026-01) → 2025-05 ~ 2026-04."""
    assert ym_labels(series_ym(2025, [11, 12, 1])) == [
        "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10",
        "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04"]


def test_series_ym_window_for_fma() -> None:
    """2026_FMA(2026-02~04) → 2025-08 ~ 2026-07. 한 해 안 계절도 전년도를 포함한다."""
    labels = ym_labels(series_ym(2026, [2, 3, 4]))
    assert labels[0] == "2025-08" and labels[-1] == "2026-07"


@pytest.mark.parametrize("season,months", list(SEASON_MONTHS.items()))
def test_series_ym_is_12_consecutive_months(season, months) -> None:
    """어느 계절이든 12칸이고, 칸 사이가 정확히 한 달씩이며, 예측 3개월을 품는다."""
    yms = series_ym(2025, months)
    assert len(yms) == 12, season
    ts = [pd.Timestamp(y, m, 1) for y, m in yms]
    gaps = {(b.year * 12 + b.month) - (a.year * 12 + a.month) for a, b in zip(ts, ts[1:])}
    assert gaps == {1}, (season, gaps)
    assert set(period_ym(2025, months)) <= set(yms), season


@pytest.mark.parametrize("season,months", list(SEASON_MONTHS.items()))
def test_series_ym_month_numbers_unique(season, months) -> None:
    """월 번호를 dict 키로 쓰므로 창 안에서 중복되면 안 된다(평년·관측·예측 매핑)."""
    nums = [m for _, m in series_ym(2025, months)]
    assert len(set(nums)) == 12, season


def test_series_ym_composition() -> None:
    """창 = 직전 6개월 + 예측 3개월 + 이후 3개월."""
    assert series_ym(2025, [12, 1, 2]) == (
        preceding_ym(2025, [12, 1, 2], 6) + period_ym(2025, [12, 1, 2])
        + following_ym(2025, [12, 1, 2], 3))


def test_series_ym_rejects_window_over_12() -> None:
    with pytest.raises(ValueError, match="12개월"):
        series_ym(2025, [11, 12, 1], before=9, after=3)


def test_following_ym_crosses_year() -> None:
    assert following_ym(2025, [11, 12, 1], 3) == [(2026, 2), (2026, 3), (2026, 4)]
    assert following_ym(2025, [10, 11, 12], 2) == [(2026, 1), (2026, 2)]


# ── dashboard_data._series_frame — series 바탕 틀 ─────────────────────────────

def test_series_frame_has_ym_and_month() -> None:
    f = _series_frame(2025, [11, 12, 1])
    assert list(f.columns) == ["ym", "month"]          # ym 이 첫 열
    assert f["ym"].iloc[6] == "2025-11"                # 예측 첫 달
    assert f["month"].tolist() == [5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3, 4]


def test_series_frame_month_key_still_maps() -> None:
    """월 번호 키 매핑(평년·예측)이 창이 바뀐 뒤에도 그대로 작동한다."""
    f = _series_frame(2025, [12, 1, 2])
    f["forecast_mean"] = f["month"].map({12: 1.0, 1: 2.0, 2: 3.0})
    got = dict(zip(f["ym"], f["forecast_mean"]))
    assert got["2025-12"] == 1.0 and got["2026-01"] == 2.0 and got["2026-02"] == 3.0
    assert f["forecast_mean"].notna().sum() == 3        # 예측월만 채워짐


# ── figure — x 좌표·눈금 라벨 ────────────────────────────────────────────────

def test_x_axis_is_monotonic_across_year_change() -> None:
    """옛 코드는 x = series["month"] 라 1월에서 좌표가 되돌아갔다."""
    x, labels = _x_axis(_series_frame(2025, [11, 12, 1]))
    assert list(x) == list(range(12))
    assert all(b > a for a, b in zip(x, x[1:]))
    assert labels[0] == "May\n2025"                    # 첫 칸에 연도
    assert labels[8] == "Jan\n2026"                    # 해가 바뀌는 칸에 연도
    assert labels[9] == "Feb"                          # 그 밖은 월 이름만


def test_x_axis_without_ym_column_still_works() -> None:
    """ym 열이 없는 옛 series.csv 하위호환."""
    x, labels = _x_axis(pd.DataFrame({"month": range(1, 13)}))
    assert list(x) == list(range(12))
    assert labels[0] == "Jan" and labels[-1] == "Dec"


def test_forecast_rows_align_with_x_positions() -> None:
    """예측 행을 골라낸 뒤에도 행 번호가 x 좌표로 맞는다(그림이 쓰는 방식)."""
    f = _series_frame(2025, [11, 12, 1])
    f["forecast_mean"] = f["month"].map({11: 1.0, 12: 2.0, 1: 3.0})
    fc = f.dropna(subset=["forecast_mean"])
    assert list(fc.index.values) == [6, 7, 8]
    _, labels = _x_axis(f)
    assert [labels[i].split("\n")[0] for i in fc.index] == ["Nov", "Dec", "Jan"]


def test_month_label_uses_ym_when_present() -> None:
    assert _month_label(pd.Series({"month": 1, "ym": "2026-01"})) == "2026-01 (Jan)"
    assert _month_label(pd.Series({"month": 1})) == "1월 (Jan)"
    assert _month_label(pd.Series({"month": 1, "ym": np.nan})) == "1월 (Jan)"
