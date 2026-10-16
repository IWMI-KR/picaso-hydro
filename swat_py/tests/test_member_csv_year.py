"""앙상블 멤버 CSV 의 연도 표기 (P2-C, 회귀 방지).

요청(최기섭 2026-10-02): "앙상블 멤버 CSV 의 `year` 열이 **다음 해 달(1·2월)에
올바르게 붙는지** 확인 부탁드립니다."

"멤버 CSV" 라는 이름의 파일이 둘이고 증상이 달랐다.
  · `1_acidwg/forecast/{기간}/member_XXXX/{관측소}.csv` — year 열은 있는데 **값이 틀림**
    (전 행이 계절 시작 연도) → P1-A 의 `acidwg_py.io._row_years` 로 해결, 그쪽에서 시험한다.
  · `3_swatplus/forecast/{기간}/{수원}.csv` — year 열이 **아예 없음**        ← 여기
  · `4_drought_risk/forecast/{기간}/{수원}/ensemble_members.csv` — 열 이름이 월 번호뿐 ← 여기
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.drought.dashboard_data import member_detail_rows, members_wide
from swat_py.drought.season import period_ym, ym_labels

# 2025_DJF — 12월은 2025, 1·2월은 2026
DJF = period_ym(2025, [12, 1, 2])
MON_YEAR = {m: y for y, m in DJF}
MON_YM = {m: lbl for (_, m), lbl in zip(DJF, ym_labels(DJF))}


def _mem(index=("member_0001", "member_0002")):
    return pd.DataFrame([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
                        index=list(index), columns=[12, 1, 2])


# ── 3_swatplus/{수원}.csv — long format 의 year 열 ───────────────────────────

def test_detail_rows_have_correct_year_across_new_year() -> None:
    rows, cols = member_detail_rows(_mem(), MON_YEAR)
    assert cols[:3] == ["member", "year", "month"]      # year 가 month 앞
    got = {(r["year"], r["month"]) for r in rows}
    assert got == {(2025, 12), (2026, 1), (2026, 2)}    # 1·2월은 다음 해


def test_detail_rows_keep_values_aligned() -> None:
    rows, _ = member_detail_rows(_mem(), MON_YEAR)
    v = {(r["member"], r["year"], r["month"]): r["flo_m3s"] for r in rows}
    assert v[("member_0001", 2026, 1)] == 2.0
    assert v[("member_0002", 2025, 12)] == 4.0
    assert len(rows) == 6                               # 멤버 2 × 월 3


def test_detail_rows_pick_up_weather() -> None:
    w = {"precip_mm": pd.DataFrame([[10.0, 20.0, 30.0]], index=["member_0001"],
                                   columns=[12, 1, 2])}
    rows, _ = member_detail_rows(_mem(["member_0001", "member_0002"]), MON_YEAR,
                                 weather=w)
    by = {(r["member"], r["month"]): r for r in rows}
    assert by[("member_0001", 1)]["precip_mm"] == 20.0
    assert np.isnan(by[("member_0002", 1)]["precip_mm"])   # 없는 멤버는 NaN
    assert np.isnan(by[("member_0001", 1)]["tmax_c"])      # 없는 변수도 NaN


def test_detail_rows_reservoir_columns() -> None:
    wl = pd.DataFrame([[23.0, 22.0, 21.0]], index=["member_0001"], columns=[12, 1, 2])
    rows, cols = member_detail_rows(_mem(["member_0001", "member_0002"]), MON_YEAR,
                                    wlevel=wl)
    assert cols[-2:] == ["water_level_ft", "storage_pct"]
    assert "flo_m3s" not in cols
    by = {(r["member"], r["month"]): r for r in rows}
    assert by[("member_0001", 2)]["water_level_ft"] == 21.0
    assert by[("member_0001", 2)]["storage_pct"] == 3.0


@pytest.mark.parametrize("fyear,months,want", [
    (2026, [2, 3, 4],    {(2026, 2), (2026, 3), (2026, 4)}),       # 한 해 안
    (2025, [11, 12, 1],  {(2025, 11), (2025, 12), (2026, 1)}),     # NDJ
    (2025, [12, 1, 2],   {(2025, 12), (2026, 1), (2026, 2)}),      # DJF
])
def test_detail_rows_year_follows_season(fyear, months, want) -> None:
    yms = period_ym(fyear, months)
    mem = pd.DataFrame([[1.0, 2.0, 3.0]], index=["m"], columns=months)
    rows, _ = member_detail_rows(mem, {m: y for y, m in yms})
    assert {(r["year"], r["month"]) for r in rows} == want


# ── 4_drought_risk/.../ensemble_members.csv — 열 이름을 연-월로 ──────────────

def test_members_wide_header_is_ym() -> None:
    out = members_wide(_mem(), MON_YM)
    assert list(out.columns) == ["2025-12", "2026-01", "2026-02"]
    assert out.index.name == "member"


def test_members_wide_csv_round_trip() -> None:
    csv = members_wide(_mem(), MON_YM).to_csv()
    assert csv.splitlines()[0] == "member,2025-12,2026-01,2026-02"


def test_members_wide_does_not_mutate_input() -> None:
    mem = _mem()
    members_wide(mem, MON_YM)
    assert list(mem.columns) == [12, 1, 2]              # 원본은 그대로(월 번호 키)


def test_members_wide_keeps_unknown_month_as_is() -> None:
    """예측월이 아닌 열이 섞여 들어와도 조용히 지우지 않는다."""
    mem = pd.DataFrame([[1.0, 2.0]], index=["m"], columns=[12, 7])
    assert list(members_wide(mem, MON_YM).columns) == ["2025-12", "7"]
