"""예측기간 기상행 확보 — 앙상블 스프레드 0 사고 방지 검증.

관측 기록 밖(운영 예보)을 예측하면 base 기상파일에 그 기간 행이 없어
_overwrite_forecast_rows 가 멤버 forcing 을 주입할 대상을 찾지 못한다.
그 경우 SWAT+ 는 전 멤버에 동일한 wgn 날씨를 써서 **오류 없이 스프레드 0** 결과를 낸다.
extend_weather_to() 가 자리표시자 행을 미리 만들고,
_assert_forecast_weather_rows() 가 그래도 없으면 중단한다.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from swat_py.drought.dashboard_data import (
    WEATHER_MISSING,
    _assert_forecast_weather_rows,
    extend_weather_to,
)


def _write_pcp(path: Path, first_year: int, last_year: int, nbyr: int | None = None) -> None:
    """연 단위 완전한 .pcp 생성 (year doy value)."""
    rows = []
    for d in pd.date_range(f"{first_year}-01-01", f"{last_year}-12-31", freq="D"):
        rows.append(f"  {d.year:4d} {d.dayofyear:5d} {1.5:9.3f}")
    n = nbyr if nbyr is not None else (last_year - first_year + 1)
    path.write_text(
        f"{path.name}: test\n"
        "nbyr  tstep  lat       lon        elev\n"
        f"  {n}     0   -21.20270  -159.80560     6.0\n" + "\n".join(rows) + "\n",
        encoding="utf-8")


def _write_tmp(path: Path, first_year: int, last_year: int) -> None:
    rows = [f"  {d.year:4d} {d.dayofyear:5d} {28.0:9.3f} {22.0:9.3f}"
            for d in pd.date_range(f"{first_year}-01-01", f"{last_year}-12-31", freq="D")]
    path.write_text(
        f"{path.name}: test\n"
        "nbyr  tstep  lat       lon        elev\n"
        f"  {last_year - first_year + 1}     0   -21.20270  -159.80560     6.0\n"
        + "\n".join(rows) + "\n", encoding="utf-8")


def _rows(path: Path):
    return [ln.split() for ln in
            path.read_text(encoding="utf-8").splitlines()[3:] if ln.split()]


# ── extend_weather_to ────────────────────────────────────────────────────────

def test_extends_pcp_to_forecast_end(tmp_path) -> None:
    p = tmp_path / "918430.pcp"
    _write_pcp(p, 2022, 2024)
    end = pd.Timestamp("2026-04-30")
    added = extend_weather_to(tmp_path, end)
    assert added[p.name] == len(pd.date_range("2025-01-01", end, freq="D"))
    last = _rows(p)[-1]
    assert int(last[0]) == 2026 and int(last[1]) == end.dayofyear


def test_extended_rows_use_missing_sentinel(tmp_path) -> None:
    """연장 구간은 -99 → SWAT+ 가 wgn 으로 보완(허구값을 만들지 않음)."""
    p = tmp_path / "918430.pcp"
    _write_pcp(p, 2023, 2024)
    extend_weather_to(tmp_path, pd.Timestamp("2026-04-30"))
    assert float(_rows(p)[-1][2]) == WEATHER_MISSING


def test_updates_nbyr_header(tmp_path) -> None:
    """nbyr 가 실제 연수와 어긋나면 SWAT+ 가 끝까지 진행하지 못한다(쿡 정지 사례)."""
    p = tmp_path / "918430.pcp"
    _write_pcp(p, 2022, 2024)
    extend_weather_to(tmp_path, pd.Timestamp("2026-04-30"))
    nbyr = int(p.read_text(encoding="utf-8").splitlines()[2].split()[0])
    assert nbyr == 2026 - 2022 + 1


def test_extends_tmp_with_two_values(tmp_path) -> None:
    p = tmp_path / "918430.tmp"
    _write_tmp(p, 2023, 2024)
    extend_weather_to(tmp_path, pd.Timestamp("2026-04-30"))
    last = _rows(p)[-1]
    assert len(last) == 4
    assert float(last[2]) == WEATHER_MISSING and float(last[3]) == WEATHER_MISSING


def test_skips_files_already_long_enough(tmp_path) -> None:
    p = tmp_path / "918430.pcp"
    _write_pcp(p, 2023, 2026)
    before = p.read_text(encoding="utf-8")
    added = extend_weather_to(tmp_path, pd.Timestamp("2026-04-30"))
    assert p.name not in added
    assert p.read_text(encoding="utf-8") == before        # 손대지 않음


def test_extends_all_station_files(tmp_path) -> None:
    """관측소가 여럿이면 전부 연장해야 한다(일부만 되면 그 유역만 wgn)."""
    for sid in ("918430", "427608", "461303"):
        _write_pcp(tmp_path / f"{sid}.pcp", 2023, 2024)
    added = extend_weather_to(tmp_path, pd.Timestamp("2026-04-30"))
    assert set(added) == {"918430.pcp", "427608.pcp", "461303.pcp"}


# ── _assert_forecast_weather_rows ────────────────────────────────────────────

def test_assert_passes_after_extend(tmp_path) -> None:
    _write_pcp(tmp_path / "918430.pcp", 2023, 2024)
    extend_weather_to(tmp_path, pd.Timestamp("2026-04-30"))
    _assert_forecast_weather_rows(tmp_path, 2026, 32, 120)     # 예외 없음


def test_assert_raises_when_forecast_year_absent(tmp_path) -> None:
    """연장하지 않으면 중단 — 이번 사고를 실행 전에 잡아낸다."""
    _write_pcp(tmp_path / "918430.pcp", 2023, 2024)
    with pytest.raises(SystemExit, match="예측기간"):
        _assert_forecast_weather_rows(tmp_path, 2026, 32, 120)


def test_assert_reports_only_offending_files(tmp_path) -> None:
    _write_pcp(tmp_path / "ok.pcp", 2023, 2026)
    _write_pcp(tmp_path / "bad.pcp", 2023, 2024)
    with pytest.raises(SystemExit) as ei:
        _assert_forecast_weather_rows(tmp_path, 2026, 32, 120)
    assert "bad.pcp" in str(ei.value) and "ok.pcp" not in str(ei.value)


def test_partial_year_coverage_still_flagged(tmp_path) -> None:
    """쿡 427608 처럼 2026 자료가 34일뿐이면 예측 창(doy 32~120) 밖일 수 있다."""
    p = tmp_path / "partial.pcp"
    _write_pcp(p, 2023, 2025)
    lines = p.read_text(encoding="utf-8").splitlines()
    for doy in range(1, 32):                       # 2026 doy 1~31 만 존재
        lines.append(f"  {2026:4d} {doy:5d} {1.0:9.3f}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="partial.pcp"):
        _assert_forecast_weather_rows(tmp_path, 2026, 32, 120)
