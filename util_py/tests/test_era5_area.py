"""ERA5 영역 계산 — 격자 스냅 + compute_area 동작 검증."""
from __future__ import annotations

import math

import pytest

from util_py.era5 import ERA5_GRID_RES, compute_area
from util_py.era5 import _snap  # type: ignore[attr-defined]


# ── _snap: 0.25° 격자 스냅 ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value, direction, expected",
    [
        # 정확히 격자 위 → 그대로
        (10.00, "up",   10.00),
        (10.00, "down", 10.00),
        # 격자 사이 값 → 방향대로 스냅
        (10.10, "up",   10.25),
        (10.10, "down", 10.00),
        (10.40, "up",   10.50),
        (10.40, "down", 10.25),
        # 음수
        (-21.65, "up",   -21.50),
        (-21.65, "down", -21.75),
        # 0 근처
        (0.10,  "up",    0.25),
        (-0.10, "down", -0.25),
    ],
)
def test_snap_matches_grid(value: float, direction: str, expected: float) -> None:
    assert _snap(value, direction) == pytest.approx(expected)


def test_snap_uses_default_grid_res() -> None:
    assert ERA5_GRID_RES == 0.25
    assert _snap(0.13, "up") == pytest.approx(0.25)


def test_snap_custom_grid_res() -> None:
    # 1.0° 격자 스냅
    assert _snap(10.7, "up",   res=1.0) == pytest.approx(11.0)
    assert _snap(10.7, "down", res=1.0) == pytest.approx(10.0)


# ── compute_area: 경계 CSV → [N,W,S,E] ───────────────────────────────────

def _make_boundary_csv(tmp_path, xmin, ymin, xmax, ymax):
    p = tmp_path / "country_boundary.csv"
    p.write_text(
        "OBJECTID,NAME,xmin,ymin,xmax,ymax\n"
        f"1,TEST,{xmin},{ymin},{xmax},{ymax}\n",
        encoding="utf-8",
    )
    return p


def test_compute_area_returns_NWSE_order(tmp_path) -> None:
    """Returns [North, West, South, East] (CDS API convention)."""
    p = _make_boundary_csv(tmp_path, xmin=-160.0, ymin=-22.0, xmax=-159.0, ymax=-21.0)
    n, w, s, e = compute_area(str(p))
    assert n > s
    assert e > w


def test_compute_area_applies_buffer_and_snap(tmp_path) -> None:
    """기본 0.25° 버퍼 + 격자 스냅."""
    p = _make_boundary_csv(tmp_path, xmin=-159.85, ymin=-21.30, xmax=-159.70, ymax=-21.18)
    n, w, s, e = compute_area(str(p))
    # 모든 값이 0.25° 격자 위에 있어야 함
    for v in (n, w, s, e):
        # value / 0.25 가 정수에 매우 가까워야 함
        assert math.isclose(v * 4, round(v * 4), abs_tol=1e-9), f"{v} 가 0.25° 격자에 없음"


def test_compute_area_buffer_expands_outward(tmp_path) -> None:
    """버퍼가 영역을 외측으로 확장한다 (N up, S down, W down, E up)."""
    p = _make_boundary_csv(tmp_path, xmin=-160.0, ymin=-22.0, xmax=-159.0, ymax=-21.0)
    n, w, s, e = compute_area(str(p), buffer=0.25)
    assert n >= -21.0
    assert s <= -22.0
    assert w <= -160.0
    assert e >= -159.0


def test_compute_area_zero_buffer_keeps_grid_aligned_values(tmp_path) -> None:
    """버퍼 0이고 입력이 이미 격자 위라면 그대로."""
    p = _make_boundary_csv(tmp_path, xmin=-160.0, ymin=-22.0, xmax=-159.0, ymax=-21.0)
    n, w, s, e = compute_area(str(p), buffer=0.0)
    assert (n, w, s, e) == (-21.0, -160.0, -22.0, -159.0)
