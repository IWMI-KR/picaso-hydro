"""cli/acidwg.py — _resolve_op_seasons 동작 검증."""
from __future__ import annotations

import pytest

from acidwg_py.cli.acidwg import _resolve_op_seasons


def test_no_seasons_returns_default() -> None:
    """args.seasons 미지정 → yaml 의 단일 season 반환."""
    assert _resolve_op_seasons(None, "JFM") == ["JFM"]
    assert _resolve_op_seasons([], "MAM") == ["MAM"]


def test_seasons_all_expands_to_12() -> None:
    """--seasons all → 12 계절 전체."""
    out = _resolve_op_seasons(["all"], "JFM")
    assert len(out) == 12
    assert "JFM" in out and "DJF" in out and "NDJ" in out


def test_seasons_all_case_insensitive() -> None:
    """ALL, All, all 모두 인식."""
    assert len(_resolve_op_seasons(["ALL"], "JFM")) == 12
    assert len(_resolve_op_seasons(["All"], "JFM")) == 12


def test_seasons_explicit_list() -> None:
    """명시 리스트 — 대소문자 무관, 정규화."""
    assert _resolve_op_seasons(["JFM", "fma", "Mam"], "JJA") == ["JFM", "FMA", "MAM"]


def test_seasons_invalid_raises() -> None:
    """잘못된 코드 → SystemExit."""
    with pytest.raises(SystemExit, match="지원하지 않는 계절"):
        _resolve_op_seasons(["XYZ"], "JFM")


def test_seasons_single_explicit() -> None:
    """한 시즌만 명시 → 그 한 시즌."""
    assert _resolve_op_seasons(["JFM"], "JJA") == ["JFM"]
