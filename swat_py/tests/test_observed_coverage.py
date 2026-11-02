"""observed 가 비는 이유를 화면이 말할 수 있게 한다 (업체 지적 §5).

    "다만 아래 기간에는 observed 가 비게 됩니다. 2024_DJF 시험 실행에서도
     12칸이 모두 비어 있었습니다. … 운영 중인 최근 시즌에도 observed 를 채울
     계획이 있으신지 알려 주세요."

방침(D-1) — **비워 두되 이유를 함께 내보낸다.**
평년 기간을 해마다 늘려 채우는 길은 쿡 기상자료(918430) 결손 때문에 지금은 막혀 있고,
팔라우 실측 수위는 2023-08 에서 끊긴다(PPUC 추가 확보는 별도 요청).

문제는 "비어 있다"가 아니라 **빈칸의 뜻을 알 수 없다**는 것이었다 —
자료가 없어서인지 계산이 실패해서인지 화면에서 구분되지 않았다.
"""
from __future__ import annotations

import pandas as pd
import pytest

from swat_py.drought.dashboard_data import (
    _coverage_from_dates,
    _observed_note,
    observed_coverage_stream,
)
from swat_py.drought.season import period_ym

# ── 관측 가능 범위 산출 ──────────────────────────────────────────────────────

def test_범위는_실제_값이_있는_구간이다():
    d = pd.to_datetime(["2018-01-05", "2019-07-01", "2023-08-04"])
    assert _coverage_from_dates(d) == {"start": "2018-01", "end": "2023-08"}


def test_빈_계열은_None():
    assert _coverage_from_dates(pd.to_datetime([])) is None
    assert _coverage_from_dates([None, pd.NaT]) is None


def test_하천_범위는_결측을_빼고_센다():
    daily = pd.DataFrame({
        "date": pd.to_datetime(["2023-01-01", "2023-02-01", "2024-01-01"]),
        "ngerikiil": [1.0, 2.0, None],          # 2024 는 값이 없다
    })
    assert observed_coverage_stream(daily, "ngerikiil") == {"start": "2023-01",
                                                            "end": "2023-02"}


def test_없는_수원은_None():
    daily = pd.DataFrame({"date": pd.to_datetime(["2023-01-01"]), "a": [1.0]})
    assert observed_coverage_stream(daily, "없는수원") is None


# ── ★ 빈칸의 이유를 설명한다 ────────────────────────────────────────────────

def test_업체가_본_2024_DJF_상황을_설명한다():
    """12칸이 모두 비었던 그 경우 — 왜 비는지 문장으로 나와야 한다."""
    ym = period_ym(2024, [12, 1, 2])            # 창은 12개월로 넓혀 쓰지만 핵심은 동일
    cov = {"start": "2018-01", "end": "2023-08"}
    note = _observed_note(cov, ym, "measured_gauge")
    assert note is not None
    assert "2023-08" in note, "언제까지 자료가 있는지 밝혀야 한다"
    assert "계산 실패가 아니다" in note, "빈칸의 뜻을 구분해 줘야 한다"
    assert "2024-12" in note, "비는 달을 짚어 줘야 한다"


def test_평년_기간이_끝난_뒤_하천도_설명된다():
    ym = period_ym(2024, [1, 2, 3])
    note = _observed_note({"start": "1985-01", "end": "2023-12"}, ym, "sim_obs_weather")
    assert note is not None
    assert "관측기상으로 구동한 모의값" in note, "observed 의 정체를 밝혀야 한다"
    assert "2023-12" in note


def test_자료가_아예_없으면_그렇게_말한다():
    note = _observed_note(None, period_ym(2026, [4, 5, 6]), "measured_gauge")
    assert note is not None and "자료가 없다" in note


def test_전부_덮이면_안내하지_않는다():
    """과거 기간(hindcast)은 observed 가 다 차므로 군더더기 문구가 없어야 한다."""
    ym = period_ym(2020, [4, 5, 6])
    assert _observed_note({"start": "2018-01", "end": "2023-08"}, ym,
                          "measured_gauge") is None


def test_일부만_비면_그_달만_짚는다():
    ym = period_ym(2023, [7, 8, 9])             # 자료는 2023-08 까지
    note = _observed_note({"start": "2018-01", "end": "2023-08"}, ym, "measured_gauge")
    assert note is not None
    assert "2023-09" in note
    assert "2023-07" not in note and "2023-08" not in note.split("은(는)")[0][-20:]


def test_해를_넘기는_창도_올바로_짚는다():
    """NDJ — 1월은 다음 해다. 연-월로 비교해야 한다."""
    ym = period_ym(2023, [11, 12, 1])           # 2023-11, 2023-12, 2024-01
    note = _observed_note({"start": "2018-01", "end": "2023-12"}, ym, "measured_gauge")
    assert note is not None
    assert "2024-01" in note, "다음 해 1월이 빠진 것을 짚어야 한다"
    assert "2023-11" not in note


# ── dashboard.json 에 실리는지 (회귀 방지) ──────────────────────────────────

@pytest.mark.parametrize("field", ["observed_coverage", "observed_note"])
def test_dashboard_json_에_실린다(field):
    import inspect

    from swat_py.drought import dashboard_data

    src = inspect.getsource(dashboard_data)
    assert src.count(f'"{field}"') >= 2, (
        f"{field} 가 하천·저수지 양쪽 dashboard.json 에 들어가야 한다")


def test_콘솔에도_사유를_남긴다():
    import inspect

    from swat_py.drought import dashboard_data

    src = inspect.getsource(dashboard_data)
    assert src.count("· observed:") >= 2, (
        "실행 로그에서도 빈칸의 이유가 보여야 한다")
