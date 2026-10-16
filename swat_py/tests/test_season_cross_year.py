"""해를 넘기는 계절(NDJ·DJF) 지원 — 회귀 방지.

예전에는 예측 3개월이 **같은 해 안에 있다고 가정**해서, NDJ·DJF 는
  · time.sim 종료일이 시작보다 앞서고
  · 연중일 범위 비교(jday0 <= jd <= jday1)가 뒤집혀 한 행도 고르지 못하고
  · 결과 추출이 fyear 한 해만 봐서 다음 해 달이 빠졌다.
결과적으로 12월은 비고 1·2월은 전 멤버가 같은 값이 됐다(확률 100% 고정).

APCC 요청(최기섭 2026-10-02): 예측 구간을 (연도, 월) 쌍 목록으로 다룰 것.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from swat_py.drought.ensemble_flow import (
    _member_coverage,
    _member_forcing,
    _member_monthly_weather,
    _overwrite_forecast_rows,
)
from swat_py.drought.season import (
    SEASON_MONTHS,
    daykey_month,
    in_ym,
    period_end,
    period_end_year,
    period_start,
    period_ym,
    preceding_ym,
    season_months,
)

CROSS_YEAR = ["NDJ", "DJF"]
SAME_YEAR = [s for s in SEASON_MONTHS if s not in CROSS_YEAR]


# ── (연도, 월) 산술 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("season,fyear,expected", [
    ("NDJ", 2025, [(2025, 11), (2025, 12), (2026, 1)]),
    ("DJF", 2025, [(2025, 12), (2026, 1), (2026, 2)]),
    ("FMA", 2026, [(2026, 2), (2026, 3), (2026, 4)]),
    ("OND", 2025, [(2025, 10), (2025, 11), (2025, 12)]),
])
def test_period_ym(season, fyear, expected) -> None:
    assert period_ym(fyear, season_months(season)) == expected


@pytest.mark.parametrize("season", list(SEASON_MONTHS))
def test_period_never_reversed(season) -> None:
    """어떤 계절이든 끝이 시작보다 뒤여야 한다 — 이것이 깨져서 생긴 사고다."""
    months = season_months(season)
    assert period_start(2025, months) < period_end(2025, months)


@pytest.mark.parametrize("season", CROSS_YEAR)
def test_cross_year_end_is_next_year(season) -> None:
    months = season_months(season)
    assert period_end_year(2025, months) == 2026
    assert period_end(2025, months).year == 2026


@pytest.mark.parametrize("season", SAME_YEAR)
def test_same_year_season_unchanged(season) -> None:
    """한 해 안의 계절은 동작이 바뀌지 않아야 한다(퇴행 방지)."""
    months = season_months(season)
    assert period_end_year(2025, months) == 2025
    assert [m for _, m in period_ym(2025, months)] == months


def test_period_end_handles_leap_february() -> None:
    assert period_end(2027, [12, 1, 2]).day == 29      # 2028-02-29
    assert period_end(2025, [12, 1, 2]).day == 28      # 2026-02-28


# ── 관측 직전월 (step 4) ─────────────────────────────────────────────────────

def test_preceding_ym_crosses_into_previous_year() -> None:
    """APCC 예시: JFM 의 observed 는 전년 7~12월."""
    assert preceding_ym(2026, [1, 2, 3], n=6) == [
        (2025, 7), (2025, 8), (2025, 9), (2025, 10), (2025, 11), (2025, 12)]


def test_preceding_ym_never_overlaps_forecast() -> None:
    """직전 6개월과 예측 3개월은 겹치지 않는다 — 월 번호를 키로 써도 안전."""
    for season, months in SEASON_MONTHS.items():
        fm = set(months)
        pm = {m for _, m in preceding_ym(2025, months, n=6)}
        assert not (fm & pm), season


# ── 날짜 조회표 / 마스크 ─────────────────────────────────────────────────────

def test_daykey_month_separates_years() -> None:
    """DJF 에서 '그 해 1월'은 들어오면 안 된다 — 연도가 키의 일부다."""
    dk = daykey_month(period_ym(2025, [12, 1, 2]))
    assert dk[(2025, 335)] == 12          # 2025-12-01
    assert dk[(2026, 1)] == 1             # 2026-01-01
    assert (2025, 1) not in dk            # 2025-01-01 은 예측기간이 아니다
    assert len(dk) == 31 + 31 + 28


def test_in_ym_selects_across_year_boundary() -> None:
    dates = pd.Series(pd.date_range("2025-11-01", "2026-03-31", freq="D"))
    mask = in_ym(dates, period_ym(2025, [12, 1, 2]))
    picked = dates[mask.values]
    assert set(zip(picked.dt.year, picked.dt.month)) == {(2025, 12), (2026, 1), (2026, 2)}


# ── 멤버 forcing 주입 (step 3-㉡) ────────────────────────────────────────────

def _write_member(csv: Path, ym) -> None:
    """acidwg 멤버 CSV — (연도, 월) 쌍대로 한 달치씩."""
    rows = []
    for y, m in ym:
        for d in pd.date_range(pd.Timestamp(y, m, 1),
                               pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0), freq="D"):
            rows.append({"year": d.year, "mon": d.month, "day": d.day,
                         "prcp": 5.0, "tmax": 31.0, "tmin": 23.0})
    pd.DataFrame(rows).to_csv(csv, index=False)


def _write_pcp_tmp(d: Path, first_year: int, last_year: int) -> None:
    pcp, tmp = d / "918430.pcp", d / "918430.tmp"
    prng = pd.date_range(f"{first_year}-01-01", f"{last_year}-12-31", freq="D")
    head = "t\nnbyr tstep lat lon elev\n  %d 0 0.0 0.0 0.0\n" % (last_year - first_year + 1)
    pcp.write_text(head + "\n".join(
        f"  {x.year:4d} {x.dayofyear:5d} {0.0:9.3f}" for x in prng) + "\n")
    tmp.write_text(head + "\n".join(
        f"  {x.year:4d} {x.dayofyear:5d} {0.0:9.3f} {0.0:9.3f}" for x in prng) + "\n")


def test_overwrite_injects_rows_for_cross_year_season(tmp_path) -> None:
    """DJF: 12월·다음해 1·2월 모두 멤버 값으로 덮여야 한다."""
    ym = period_ym(2025, [12, 1, 2])
    _write_member(tmp_path / "918430.csv", ym)
    _write_pcp_tmp(tmp_path, 2024, 2026)

    forcing = _member_forcing(tmp_path / "918430.csv")
    daykeys = daykey_month(ym)
    n = _overwrite_forecast_rows(tmp_path, forcing, daykeys)
    assert n == (31 + 31 + 28) * 2        # .pcp + .tmp

    written = {}
    for ln in (tmp_path / "918430.pcp").read_text().splitlines()[3:]:
        y, jd, v = ln.split()
        d = pd.Timestamp(int(y), 1, 1) + pd.Timedelta(days=int(jd) - 1)
        written[(d.year, d.month, d.day)] = float(v)
    assert written[(2025, 12, 1)] == 5.0
    assert written[(2026, 1, 15)] == 5.0          # 다음 해 1월도 주입
    assert written[(2026, 2, 28)] == 5.0
    assert written[(2025, 1, 15)] == 0.0          # 같은 해 1월은 건드리지 않는다
    assert written[(2026, 3, 1)] == 0.0           # 예측기간 밖


def test_overwrite_is_noop_for_wrong_year_member(tmp_path) -> None:
    """연도가 틀린 옛 멤버 CSV(전 행 2025)는 1·2월을 못 덮는다 → 사전에 잡힌다."""
    ym = period_ym(2025, [12, 1, 2])
    csv = tmp_path / "918430.csv"
    rows = []
    for _, m in ym:                                # 전 행을 2025 로 — 옛 버그 재현
        for d in pd.date_range(pd.Timestamp(2025, m, 1),
                               pd.Timestamp(2025, m, 1) + pd.offsets.MonthEnd(0), freq="D"):
            rows.append({"year": 2025, "mon": m, "day": d.day,
                         "prcp": 5.0, "tmax": 31.0, "tmin": 23.0})
    pd.DataFrame(rows).to_csv(csv, index=False)

    short = _member_coverage(_member_forcing(csv), daykey_month(ym), ym)
    assert len(short) == 2 and "2026-01" in short[0] and "2026-02" in short[1]


def test_member_coverage_ok_for_correct_member(tmp_path) -> None:
    ym = period_ym(2025, [12, 1, 2])
    _write_member(tmp_path / "918430.csv", ym)
    assert _member_coverage(_member_forcing(tmp_path / "918430.csv"),
                            daykey_month(ym), ym) == []


def test_member_coverage_tolerates_missing_leap_day(tmp_path) -> None:
    """acidwg 는 2월을 항상 28일로 만든다 — 윤년 2/29 부재는 정상."""
    ym = period_ym(2027, [12, 1, 2])              # 끝월 = 2028-02 (29일)
    csv = tmp_path / "918430.csv"
    rows = []
    for y, m in ym:
        last = 28 if m == 2 else (pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)).day
        for day in range(1, last + 1):
            rows.append({"year": y, "mon": m, "day": day,
                         "prcp": 1.0, "tmax": 30.0, "tmin": 24.0})
    pd.DataFrame(rows).to_csv(csv, index=False)
    assert _member_coverage(_member_forcing(csv), daykey_month(ym), ym) == []


# ── 멤버 월별 기상 집계 (step 3-㉢) ──────────────────────────────────────────

def test_member_monthly_weather_includes_next_year_months(tmp_path) -> None:
    ym = period_ym(2025, [12, 1, 2])
    csv = tmp_path / "918430.csv"
    _write_member(csv, ym)
    w = _member_monthly_weather(csv, ym)
    assert set(w) == {12, 1, 2}
    assert w[1][0] == pytest.approx(31 * 5.0)     # 2026-01 31일 × 5mm
    assert w[2][0] == pytest.approx(28 * 5.0)     # 2026-02 28일 × 5mm


def test_member_monthly_weather_excludes_same_year_january(tmp_path) -> None:
    """2025-01 자료가 섞여 있어도 DJF 예측월(2026-01)만 집계해야 한다."""
    ym = period_ym(2025, [12, 1, 2])
    csv = tmp_path / "918430.csv"
    rows = []
    for y, m, v in [(2025, 1, 99.0), (2025, 12, 5.0), (2026, 1, 5.0), (2026, 2, 5.0)]:
        for d in pd.date_range(pd.Timestamp(y, m, 1),
                               pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0), freq="D"):
            rows.append({"year": y, "mon": m, "day": d.day,
                         "prcp": v, "tmax": 30.0, "tmin": 24.0})
    pd.DataFrame(rows).to_csv(csv, index=False)
    w = _member_monthly_weather(csv, ym)
    assert w[1][0] == pytest.approx(31 * 5.0)     # 99.0 짜리 2025-01 은 제외


# ── time.sim 종료일·종료연도 (step 3-㉠) ─────────────────────────────────────

@pytest.mark.parametrize("fyear,months,day_end,yr_end", [
    (2026, [2, 3, 4],  120, 2026),      # FMA — 한 해 안
    (2025, [10, 11, 12], 365, 2025),    # OND — 한 해 안
    (2025, [11, 12, 1],  31, 2026),     # NDJ — 끝월이 다음 해 1월
    (2025, [12, 1, 2],   59, 2026),     # DJF — 끝월이 다음 해 2월
    (2027, [12, 1, 2],   60, 2028),     # DJF 윤년 — 2028-02-29 = doy 60
])
def test_time_sim_line(fyear, months, day_end, yr_end) -> None:
    from swat_py.drought.dashboard_data import time_sim_line
    toks = time_sim_line(fyear - 3, fyear, months).split()
    assert toks == ["1", str(fyear - 3), str(day_end), str(yr_end), "0"]


def test_time_sim_end_is_after_start_for_every_season() -> None:
    """옛 코드는 NDJ·DJF 에서 종료가 시작보다 앞섰다."""
    from swat_py.drought.dashboard_data import time_sim_line
    for season, months in SEASON_MONTHS.items():
        toks = time_sim_line(2022, 2025, months).split()
        end = pd.Timestamp(int(toks[3]), 1, 1) + pd.Timedelta(days=int(toks[2]) - 1)
        assert end >= period_start(2025, months), season
        assert end == period_end(2025, months), season
