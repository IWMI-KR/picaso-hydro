"""예측 계절(3개월)의 (연도, 월) 산술 — 해를 넘기는 NDJ·DJF 포함.

계절 라벨의 연도는 **시작월 기준**이다: ``2025_NDJ`` = 2025-11 ~ 2026-01.

월 번호만으로는 해를 넘는 구간을 나타낼 수 없다 — ``[11, 12, 1]`` 의 1월이
어느 해인지 알 수 없다. 이 모듈이 그것을 (연도, 월) 쌍으로 풀어 주고,
날짜 경계와 SWAT+ 기상파일 조회키를 만든다.

이 모듈을 거치지 않고 ``pd.Timestamp(fyear, months[-1], 1)`` 처럼 계산하면
NDJ·DJF 에서 **끝이 시작보다 앞서는** 구간이 만들어지고, 그 구간으로 거른
행은 하나도 없어 멤버 기상이 주입되지 않는다(전 멤버 동일값).

관례
----
- 월 번호는 그대로 **dict/DataFrame 의 키**로 쓴다. 3개월 계절은 월이 겹치지
  않으므로 해를 넘어도 키 충돌이 없다. 바뀌는 것은 **날짜 산술**뿐이다.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

import pandas as pd

#: 12개 rolling 3개월 계절 — 라벨 연도는 **시작월**의 연도.
SEASON_MONTHS: Dict[str, List[int]] = {
    "JFM": [1, 2, 3], "FMA": [2, 3, 4], "MAM": [3, 4, 5], "AMJ": [4, 5, 6],
    "MJJ": [5, 6, 7], "JJA": [6, 7, 8], "JAS": [7, 8, 9], "ASO": [8, 9, 10],
    "SON": [9, 10, 11], "OND": [10, 11, 12], "NDJ": [11, 12, 1], "DJF": [12, 1, 2],
}

#: 대시보드 series 의 관측(observed) 기본 길이 — 예측 시작 **직전** n개월.
#: APCC 요청 기준: "observed 는 전년도 달까지 포함해 예측 직전 달들을 채워 주세요.
#: 예: JFM 은 전년 7~12월" (= 6개월).
DEFAULT_OBSERVED_MONTHS = 6

#: 대시보드 series 의 예측 **뒤쪽** 여유 개월 — 예측 끝월 다음 n개월.
#: APCC 요청 기준 창 길이: 직전 6 + 예측 3 + 이후 3 = **연속 12개월**.
DEFAULT_TRAILING_MONTHS = 3

#: (연도, 월)
YM = Tuple[int, int]


def season_months(season: str) -> List[int]:
    """계절 이름 → 월 번호 3개. 모르는 이름이면 사용 가능 목록과 함께 알린다."""
    try:
        return list(SEASON_MONTHS[season])
    except KeyError:
        raise KeyError(f"알 수 없는 계절: {season!r} — "
                       f"사용 가능: {list(SEASON_MONTHS)}") from None


def period_ym(fyear: int, months: Sequence[int]) -> List[YM]:
    """(연도, 월) 쌍 목록. **월 번호가 작아지는 지점에서 해가 바뀐다.**

    >>> period_ym(2025, [11, 12, 1])
    [(2025, 11), (2025, 12), (2026, 1)]
    >>> period_ym(2025, [12, 1, 2])
    [(2025, 12), (2026, 1), (2026, 2)]
    >>> period_ym(2026, [2, 3, 4])
    [(2026, 2), (2026, 3), (2026, 4)]
    """
    out: List[YM] = []
    year, prev = int(fyear), None
    for m in months:
        m = int(m)
        if prev is not None and m < prev:
            year += 1
        out.append((year, m))
        prev = m
    return out


def assert_period_sane(fyear: int, months: Sequence[int]) -> List[YM]:
    """예측 구간이 성립하는지 확인하고 (연, 월) 목록을 돌려준다 — 아니면 중단.

    요청(최기섭 2026-10-02): "기간이 뒤집히거나 예측월 결과가 비면 0 이 아닌
    종료 코드로 실패하게 해 주세요. 지금은 exit 0 으로 끝나서 틀린 결과를
    감지할 수 없습니다."

    확인하는 것: 빈 목록 / 1~12 범위 밖 / 중복된 달 / 한 달씩 이어지지 않음 /
    끝이 시작보다 앞섬. ``period_ym`` 을 거친 구간은 뒤집힐 수 없지만, 그 계산을
    건너뛴 코드나 잘못된 계절 정의가 끼어들 수 있으므로 **쓰기 직전에** 확인한다.

    >>> assert_period_sane(2025, [11, 12, 1])
    [(2025, 11), (2025, 12), (2026, 1)]
    >>> assert_period_sane(2025, [11, 1, 12])      # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ValueError: 예측 구간이 연속한 달이 아니다: ...
    """
    ms = [int(m) for m in months]
    if not ms:
        raise ValueError(f"예측 구간이 비어 있다: fyear={fyear}, months={months!r}")
    bad = [m for m in ms if not 1 <= m <= 12]
    if bad:
        raise ValueError(f"월 번호가 1~12 밖이다: {bad} (fyear={fyear})")
    if len(set(ms)) != len(ms):
        raise ValueError(f"예측 구간에 같은 달이 두 번 있다: {ms} (fyear={fyear})")
    yms = period_ym(fyear, ms)
    idx = [y * 12 + m for y, m in yms]
    if any(b - a != 1 for a, b in zip(idx, idx[1:])):
        raise ValueError(f"예측 구간이 연속한 달이 아니다: fyear={fyear}, "
                         f"months={ms} → {ym_labels(yms)}")
    if period_end(fyear, ms) <= pd.Timestamp(yms[0][0], yms[0][1], 1):
        raise ValueError(f"예측 구간이 뒤집혔다: fyear={fyear}, months={ms} → "
                         f"{ym_labels(yms)[0]} ~ {ym_labels(yms)[-1]}")
    return yms


def period_start(fyear: int, months: Sequence[int]) -> pd.Timestamp:
    """예측 **시작월 1일**."""
    y, m = period_ym(fyear, months)[0]
    return pd.Timestamp(y, m, 1)


def period_end(fyear: int, months: Sequence[int]) -> pd.Timestamp:
    """예측 **끝월 말일**. NDJ 2025 → 2026-01-31 (윤년 자동 반영).

    >>> period_end(2025, [12, 1, 2]).date().isoformat()
    '2026-02-28'
    """
    y, m = period_ym(fyear, months)[-1]
    return pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)


def period_end_year(fyear: int, months: Sequence[int]) -> int:
    """예측이 **끝나는 해** — ``time.sim`` 의 모의 종료 연도."""
    return period_ym(fyear, months)[-1][0]


def preceding_ym(fyear: int, months: Sequence[int],
                 n: int = DEFAULT_OBSERVED_MONTHS) -> List[YM]:
    """예측 시작 **직전** n개월의 (연도, 월) — 전년도로 자연히 넘어간다.

    >>> preceding_ym(2026, [1, 2, 3], n=6)        # JFM → 전년 7~12월
    [(2025, 7), (2025, 8), (2025, 9), (2025, 10), (2025, 11), (2025, 12)]
    """
    first = period_start(fyear, months)
    out: List[YM] = []
    for k in range(int(n), 0, -1):
        d = first - pd.DateOffset(months=k)
        out.append((int(d.year), int(d.month)))
    return out


def following_ym(fyear: int, months: Sequence[int],
                 n: int = DEFAULT_TRAILING_MONTHS) -> List[YM]:
    """예측 **끝월 다음** n개월의 (연도, 월) — 해를 자연히 넘어간다.

    >>> following_ym(2025, [11, 12, 1], n=3)      # NDJ → 2026-01 다음 3개월
    [(2026, 2), (2026, 3), (2026, 4)]
    """
    y, m = period_ym(fyear, months)[-1]
    base = pd.Timestamp(y, m, 1)
    return [((base + pd.DateOffset(months=k)).year,
             (base + pd.DateOffset(months=k)).month) for k in range(1, int(n) + 1)]


def series_ym(fyear: int, months: Sequence[int], *,
              before: int = DEFAULT_OBSERVED_MONTHS,
              after: int = DEFAULT_TRAILING_MONTHS) -> List[YM]:
    """대시보드 series 의 **연속 12개월 창** = 직전 before + 예측 3 + 이후 after.

    달력 1~12월 고정을 대신한다. 예측 계절이 창 안에 들어오므로 NDJ·DJF 도
    한 줄로 이어진다(요청: 최기섭 2026-10-02).

    >>> ym_labels(series_ym(2025, [11, 12, 1]))[:6]      # 예측 직전 6개월
    ['2025-05', '2025-06', '2025-07', '2025-08', '2025-09', '2025-10']
    >>> ym_labels(series_ym(2025, [11, 12, 1]))[6:]      # 예측 3개월 + 이후 3개월
    ['2025-11', '2025-12', '2026-01', '2026-02', '2026-03', '2026-04']
    >>> ym_labels(series_ym(2026, [2, 3, 4]))[:2]
    ['2025-08', '2025-09']

    창은 12개월을 넘을 수 없다 — 월 번호를 dict 키로 쓰는 관례가 깨진다
    (같은 월이 두 번 나오면 평년·관측·예측 매핑이 서로를 덮어쓴다).
    """
    total = int(before) + len(months) + int(after)
    if total > 12:
        raise ValueError(
            f"series 창이 12개월을 넘는다(before={before} + {len(months)} + "
            f"after={after} = {total}) — 월 번호가 중복돼 매핑이 깨진다")
    return (preceding_ym(fyear, months, before)
            + period_ym(fyear, months)
            + following_ym(fyear, months, after))


def ym_label(ym: YM) -> str:
    """(2026, 1) → ``"2026-01"``."""
    return f"{ym[0]:04d}-{ym[1]:02d}"


def ym_labels(yms: Iterable[YM]) -> List[str]:
    return [ym_label(x) for x in yms]


def in_ym(dates, yms: Iterable[YM]) -> pd.Series:
    """datetime Series → 주어진 (연, 월) 집합에 드는 행 마스크.

    ``df["date"].dt.year == fyear`` 처럼 단일 연도로 거르면 해를 넘는 달이
    빠지므로, 추출 조건은 모두 이 함수를 쓴다.
    """
    s = pd.to_datetime(pd.Series(dates).reset_index(drop=True))
    want = {y * 100 + m for y, m in yms}
    return (s.dt.year * 100 + s.dt.month).isin(want)


def daykey_month(yms: Iterable[YM]) -> Dict[Tuple[int, int], int]:
    """``{(연, 연중일): 월}`` — SWAT+ 기상파일의 ``년 연중일`` 행과 바로 맞춘다.

    ``.pcp``/``.tmp`` 는 날짜를 (year, julian day) 로 적는다. 연중일 범위
    비교(``jday0 <= jd <= jday1``)는 해를 넘으면 뒤집히므로, 구간을 미리
    **조회표**로 펼쳐 멤버십으로 판정한다(윤년도 자동).
    """
    out: Dict[Tuple[int, int], int] = {}
    for y, m in yms:
        first = pd.Timestamp(y, m, 1)
        for d in pd.date_range(first, first + pd.offsets.MonthEnd(0), freq="D"):
            out[(int(d.year), int(d.dayofyear))] = int(m)
    return out
