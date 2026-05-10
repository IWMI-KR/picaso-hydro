"""picaso.py — Lead Time 연도 경계 처리, PICASO 경로 명명규약 검증."""
from __future__ import annotations

from pathlib import Path

import pytest

from acidwg_py.picaso import (
    MONTH_TO_ABB,
    _file_year,
    _picaso_path,
)


# ── MONTH_TO_ABB ─────────────────────────────────────────────────────────────

def test_month_to_abb_has_12_entries() -> None:
    assert len(MONTH_TO_ABB) == 12
    assert all(1 <= k <= 12 for k in MONTH_TO_ABB)


@pytest.mark.parametrize(
    "month, abb",
    [(1, "JAN"), (3, "MAR"), (6, "JUN"), (9, "SEP"), (12, "DEC")],
)
def test_month_to_abb_values(month: int, abb: str) -> None:
    assert MONTH_TO_ABB[month] == abb


def test_month_to_abb_all_uppercase_3letter() -> None:
    for v in MONTH_TO_ABB.values():
        assert len(v) == 3
        assert v == v.upper()


# ── _file_year: 시즌의 다음해로 넘어가는 월 처리 ─────────────────────────────

def test_file_year_within_same_year() -> None:
    """JFM 시즌(첫월 1) — 모든 월이 같은 연도."""
    assert _file_year(1, first_month=1, year=2014) == 2014
    assert _file_year(2, first_month=1, year=2014) == 2014
    assert _file_year(3, first_month=1, year=2014) == 2014


def test_file_year_ndj_crosses_year_boundary() -> None:
    """NDJ 시즌(첫월=11) 2025 발표
       NOV → 2025 (11 < 11 False)
       DEC → 2025 (12 < 11 False)
       JAN → 2026 (1  < 11 True)
    """
    assert _file_year(11, first_month=11, year=2025) == 2025
    assert _file_year(12, first_month=11, year=2025) == 2025
    assert _file_year(1,  first_month=11, year=2025) == 2026


def test_file_year_djf_crosses_year_boundary() -> None:
    """DJF 시즌(첫월=12) 2025
       DEC → 2025
       JAN → 2026
       FEB → 2026
    """
    assert _file_year(12, first_month=12, year=2025) == 2025
    assert _file_year(1,  first_month=12, year=2025) == 2026
    assert _file_year(2,  first_month=12, year=2025) == 2026


# ── _picaso_path: 파일 경로 명명규약 ─────────────────────────────────────────

def test_picaso_path_prec_jan_2014_lt1() -> None:
    base = Path("/picaso")
    p = _picaso_path(base, "prcp", "JAN", 2014, 1)
    assert p == base / "prec" / "JAN" / "2014" / "TP_JAN_2014_LT1.csv"


def test_picaso_path_t2m_uses_tt_prefix() -> None:
    base = Path("/picaso")
    p = _picaso_path(base, "t2m", "MAR", 2020, 3)
    assert p == base / "t2m" / "MAR" / "2020" / "TT_MAR_2020_LT3.csv"


def test_picaso_path_unknown_var_raises() -> None:
    with pytest.raises(KeyError):
        _picaso_path(Path("/x"), "tmax", "JAN", 2014, 1)
