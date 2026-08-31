"""master 기상파일 이름 해석 — climatology 실행 전 안전장치 검증.

`stations-acidwg.csv` 의 관측소 ID 와 SWAT+ master 안의 기상파일 이름이 다르면,
SWAT+ 는 없는 파일을 **빈 파일로 만들고 wgn(기상발생기)으로 대체**해 오류 없이
잘못된 결과를 낸다. resolve_master_weather_prefix() 가 이를 사전에 잡아낸다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from swat_py.drought.climatology_run import (
    WEATHER_EXTS,
    _weather_set_ok,
    resolve_master_weather_prefix,
)


def _make_weather(work: Path, prefix: str, *, lon=134.544, lat=7.367,
                  empty: bool = False) -> None:
    """5종 기상파일 생성. empty=True 면 크기 0(= SWAT+ 가 만든 빈 파일 재현)."""
    work.mkdir(parents=True, exist_ok=True)
    for ext in WEATHER_EXTS:
        p = work / f"{prefix}.{ext}"
        if empty:
            p.write_text("", encoding="utf-8")
            continue
        p.write_text(
            f"{prefix}.{ext}: written by test\n"
            "nbyr  tstep  lat       lon        elev\n"
            f"  46     0    {lat:.5f}   {lon:.5f}    53.6\n"
            "1979   1   0.0\n",
            encoding="utf-8",
        )


# ── _weather_set_ok ──────────────────────────────────────────────────────────

def test_weather_set_ok_true_when_all_present(tmp_path) -> None:
    _make_weather(tmp_path, "914080")
    assert _weather_set_ok(tmp_path, "914080") is True


def test_weather_set_ok_false_when_missing(tmp_path) -> None:
    assert _weather_set_ok(tmp_path, "nosuch") is False


def test_weather_set_ok_false_when_empty(tmp_path) -> None:
    """크기 0 파일은 '있음'으로 보면 안 된다 — 이번 팔라우 사고의 핵심."""
    _make_weather(tmp_path, "914080", empty=True)
    assert _weather_set_ok(tmp_path, "914080") is False


def test_weather_set_ok_false_when_one_ext_missing(tmp_path) -> None:
    _make_weather(tmp_path, "914080")
    (tmp_path / "914080.wnd").unlink()
    assert _weather_set_ok(tmp_path, "914080") is False


# ── resolve_master_weather_prefix ────────────────────────────────────────────

def test_resolve_exact_name(tmp_path) -> None:
    _make_weather(tmp_path, "918430")
    assert resolve_master_weather_prefix(tmp_path, "918430") == "918430"


def test_resolve_prefix_match_noaa_to_swat_id(tmp_path) -> None:
    """NOAA 11자리 ID 요청 → master 의 SWAT 6자리 파일로 해석 (팔라우 사례)."""
    _make_weather(tmp_path, "914080")
    assert resolve_master_weather_prefix(tmp_path, "91408040310") == "914080"


def test_resolve_prefers_shortest_partial(tmp_path) -> None:
    _make_weather(tmp_path, "914080")
    _make_weather(tmp_path, "9140804")
    assert resolve_master_weather_prefix(tmp_path, "91408040310") == "914080"


def test_resolve_by_nearest_lonlat(tmp_path) -> None:
    """이름이 전혀 다르면 .pcp 헤더 위경도로 최근접 매칭."""
    _make_weather(tmp_path, "ABC999", lon=134.545, lat=7.368)
    got = resolve_master_weather_prefix(tmp_path, "91408040310",
                                        lon=134.544, lat=7.367)
    assert got == "ABC999"


def test_resolve_lonlat_too_far_raises(tmp_path) -> None:
    _make_weather(tmp_path, "ABC999", lon=127.0, lat=37.5)   # 한국 좌표
    with pytest.raises(FileNotFoundError, match="찾지 못했"):
        resolve_master_weather_prefix(tmp_path, "91408040310",
                                      lon=134.544, lat=7.367)


def test_resolve_empty_files_are_not_candidates(tmp_path) -> None:
    """크기 0 파일만 있으면 후보로 잡지 않고 명확히 실패해야 한다."""
    _make_weather(tmp_path, "914080", empty=True)
    with pytest.raises(FileNotFoundError, match="사용 가능한 관측 기상파일이 없"):
        resolve_master_weather_prefix(tmp_path, "91408040310")


def test_resolve_no_weather_at_all_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="사용 가능한 관측 기상파일이 없"):
        resolve_master_weather_prefix(tmp_path, "918430")


def test_resolve_error_lists_candidates(tmp_path) -> None:
    """실패 메시지에 후보와 조치 안내가 포함돼야 원인 파악이 쉽다."""
    _make_weather(tmp_path, "ABC999", lon=127.0, lat=37.5)
    with pytest.raises(FileNotFoundError) as ei:
        resolve_master_weather_prefix(tmp_path, "918430", lon=134.5, lat=7.3)
    msg = str(ei.value)
    assert "ABC999" in msg
    assert "stations-acidwg.csv" in msg
