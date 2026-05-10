"""utils.py — Julian day, season_naming, calendar, 거리/차이 함수 검증."""
from __future__ import annotations

import numpy as np
import pytest

from acidwg_py.utils import (
    MONTH_LENGTH,
    build_daily_jd,
    difference,
    distance,
    get_julian_day,
    jd_to_md,
    make_calendar,
    nearest_month_by_jd,
    season_naming,
)


# ── 월별 일수 상수 ───────────────────────────────────────────────────────────

def test_month_length_total_is_365() -> None:
    assert int(MONTH_LENGTH.sum()) == 365


def test_month_length_february_no_leap() -> None:
    # 윤년 미고려 (R의 month.length 동일)
    assert MONTH_LENGTH[1] == 28


# ── get_julian_day ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "month, day, jd",
    [
        (1,  1,   1),
        (1,  31,  31),
        (2,  1,   32),
        (2,  28,  59),
        (2,  29,  60),    # 비윤년 기준 = Mar 1
        (3,  1,   60),    # Feb 29 와 동일
        (12, 31,  365),
        (6,  30,  31+28+31+30+31+30),  # 181
    ],
)
def test_get_julian_day(month: int, day: int, jd: int) -> None:
    assert get_julian_day(month, day) == jd


# ── jd_to_md ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "jd, month, day",
    [
        (1,   1,  1),
        (31,  1,  31),
        (32,  2,  1),
        (60,  3,  1),     # 비윤년에서 Feb 29 자리는 Mar 1
        (365, 12, 31),
    ],
)
def test_jd_to_md(jd: int, month: int, day: int) -> None:
    assert jd_to_md(jd) == (month, day)


def test_jd_to_md_round_trip() -> None:
    """get_julian_day → jd_to_md 라운드트립."""
    for m in range(1, 13):
        for d in range(1, MONTH_LENGTH[m - 1] + 1):
            jd = get_julian_day(m, d)
            assert jd_to_md(jd) == (m, d), f"({m},{d}) round-trip 실패"


# ── distance: 원형 거리 ──────────────────────────────────────────────────────

def test_distance_symmetric() -> None:
    """distance(a, b) == distance(b, a)."""
    for a, b in [(1, 100), (50, 200), (1, 365), (180, 270)]:
        assert distance(a, b) == distance(b, a)


def test_distance_zero_when_same() -> None:
    assert distance(123, 123) == 0


def test_distance_max_is_half_year() -> None:
    """원형이므로 최대 거리는 floor(365/2) = 182."""
    assert distance(1, 183) == 182    # abs=182, 365-182=183, min=182
    assert distance(1, 184) == 182    # abs=183, 365-183=182, min=182
    # 1과 365: abs=364, 365-364=1, min=1
    assert distance(1, 365) == 1


def test_distance_wraps_around_year_end() -> None:
    """12월 31일(365)과 1월 1일(1) — 거리 1."""
    assert distance(1, 365) == 1


# ── difference: 부호 있는 원형 차이 ──────────────────────────────────────────

def test_difference_zero_when_same() -> None:
    assert difference(50, 50) == 0


def test_difference_short_path_sign() -> None:
    """짧은 경로면 단순 부호 차이."""
    # jd=10, pivot=20: 짧은 경로 (10 → 20 거꾸로 가는게 더 가까움?)
    # |10-20|=10, 365-10=355 → 짧은 건 10. jd-pivot = -10
    assert difference(10, 20) == -10
    assert difference(20, 10) == 10


# ── season_naming ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "months, label",
    [
        ([6, 7, 8],   "JJA"),
        ([1, 2, 3],   "JFM"),
        ([11, 12, 1], "NDJ"),
        ([12, 1, 2],  "DJF"),
        ([6, 7],      "Jun-Jul"),    # 3개월 미만은 풀 이름 + 하이픈
        ([3],         "Mar"),
    ],
)
def test_season_naming(months, label) -> None:
    assert season_naming(months) == label


# ── make_calendar / build_daily_jd ───────────────────────────────────────────

def test_make_calendar_total_days_matches_month_lengths() -> None:
    # JFM = 31 + 28 + 31 = 90 일
    cal = make_calendar([1, 2, 3])
    assert cal.shape == (90, 2)
    # 첫 행 = (1, 1)
    assert tuple(cal[0]) == (1, 1)
    # 마지막 행 = (3, 31)
    assert tuple(cal[-1]) == (3, 31)


def test_build_daily_jd_strictly_increasing_within_month() -> None:
    jd = build_daily_jd([1, 2, 3])  # JFM
    # JFM은 연도 경계 안 넘어가므로 단조증가
    assert all(jd[i] < jd[i + 1] for i in range(len(jd) - 1))


def test_build_daily_jd_djf_wraps() -> None:
    """DJF = Dec(31) + Jan(31) + Feb(28) = 90일. 연도 경계 넘으면 jd가 365 → 1로 점프."""
    jd = build_daily_jd([12, 1, 2])
    # 12월 31일 jd=365, 다음(1월 1일) jd=1
    idx_dec31 = MONTH_LENGTH[11] - 1  # 30
    assert jd[idx_dec31] == 365
    assert jd[idx_dec31 + 1] == 1


# ── nearest_month_by_jd ──────────────────────────────────────────────────────

def test_nearest_month_by_jd_includes_target_month() -> None:
    """sim_period 안의 월 중심에 해당하는 jd는 그 월을 포함해야 함."""
    # JJA 중 7월 15일에 해당하는 jd
    jd = get_julian_day(7, 15)
    months = nearest_month_by_jd(jd, [6, 7, 8], window=15)
    assert 7 in months
