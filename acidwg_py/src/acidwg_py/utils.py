"""
Utility functions — R Utility.R 포팅

month_length, get_julian_day, jd_to_md, distance, difference, season_naming
"""

import numpy as np

# 월별 일수 (윤년 미고려, R의 month.length와 동일)
MONTH_LENGTH = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], dtype=int)
MONTH_ABB = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# 누적 월 길이 (index 0 = 0, index 1 = 31, ..., index 12 = 365)
_CUMLEN = np.concatenate([[0], np.cumsum(MONTH_LENGTH)])


def get_julian_day(month: int, day: int) -> int:
    """월/일 → Julian day (1~365).
    R의 get.JulianDay와 동일. 윤년 2/29는 3/1과 같은 값(60)을 반환.
    """
    return int(_CUMLEN[month - 1]) + day


def jd_to_md(jd: int):
    """Julian day → (month, day) 튜플.

    side='left' 를 사용해 jd가 정확히 누적합 경계와 같을 때(예: jd=31)
    해당 월의 마지막 날로 매핑. jd=32는 다음 달 1일로 정확히 매핑됨.
    """
    month = int(np.searchsorted(_CUMLEN, jd, side="left"))
    if month < 1:
        month = 1
    if month > 12:
        month = 12
    day = jd - int(_CUMLEN[month - 1])
    return month, day


def distance(jd1: int, jd2: int) -> int:
    """두 Julian day 사이의 원형 거리 (0~182)."""
    dist = abs(jd1 - jd2)
    return int(min(dist, 365 - dist))


def difference(jd: int, pivot_jd: int) -> int:
    """Julian day jd와 pivot_jd의 부호 있는 원형 차이.
    R의 difference(jd, pivot.jd)와 동일.
    """
    dist = abs(jd - pivot_jd)
    a = [dist, 365 - dist]
    if a[0] <= a[1]:
        return jd - pivot_jd
    return int(a[1] * np.sign(pivot_jd - jd))


def season_naming(sim_period) -> str:
    """시뮬레이션 월 리스트 → 계절 이름 문자열.
    3개월 이상: 각 월 첫 글자 (예: JJA), 미만: 하이픈 구분 (예: Jun-Jul).
    """
    sim_period = list(sim_period)
    if len(sim_period) >= 3:
        return "".join(MONTH_ABB[m - 1][0] for m in sim_period)
    return "-".join(MONTH_ABB[m - 1] for m in sim_period)


def make_calendar(sim_period):
    """sim_period(월 리스트) → (MONTH, DAY) 행 배열. shape (n_days, 2)."""
    rows = []
    for m in sim_period:
        for d in range(1, MONTH_LENGTH[m - 1] + 1):
            rows.append((m, d))
    return np.array(rows, dtype=int)


def build_daily_jd(sim_period):
    """sim_period의 각 일에 대한 Julian day 배열."""
    cal = make_calendar(sim_period)
    return np.array([get_julian_day(r[0], r[1]) for r in cal], dtype=int)


def nearest_month_by_jd(jd: int, sim_period, window: int = 15):
    """Julian day에서 ±window 일 이내의 sim_period 월 목록을 반환."""
    months = []
    for m in sim_period:
        for d in range(1, MONTH_LENGTH[m - 1] + 1):
            if distance(get_julian_day(m, d), jd) <= window:
                months.append(m)
                break
    return months if months else list(sim_period)
