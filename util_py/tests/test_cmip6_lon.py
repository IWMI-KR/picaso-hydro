"""cmip6.py의 경도 좌표계 변환 검증."""
from __future__ import annotations

import numpy as np
import pytest

from util_py.cmip6 import _find_lat_idx, _find_lon_idx, _lon_to_0360  # type: ignore[attr-defined]


# ── _lon_to_0360: -180/180 → 0/360 ───────────────────────────────────────

@pytest.mark.parametrize(
    "lon_in, lon_out",
    [
        # 양수는 그대로
        (0.0,    0.0),
        (90.0,   90.0),
        (179.99, 179.99),
        # 음수 → 360 더한 값
        (-1.0,   359.0),
        (-90.0,  270.0),
        (-160.0, 200.0),
        (-179.99, 180.01),
        # 경계
        (180.0,  180.0),
        (-180.0, 180.0),   # ±180은 같은 자오선(antimeridian) — Python % 360 결과 180
        (360.0,    0.0),
    ],
)
def test_lon_to_0360(lon_in: float, lon_out: float) -> None:
    assert _lon_to_0360(lon_in) == pytest.approx(lon_out, abs=1e-9)


# ── _find_lat_idx ────────────────────────────────────────────────────────

def test_find_lat_idx_inclusive_bounds() -> None:
    lat = np.linspace(-90, 90, 19)   # 10° 간격
    idx = _find_lat_idx(lat, ymin=-22.5, ymax=-12.5)
    # -20°만 [−22.5, −12.5] 범위에 들어감
    assert lat[idx].tolist() == [-20.0]


def test_find_lat_idx_multiple() -> None:
    lat = np.array([-25.0, -20.0, -15.0, -10.0, -5.0])
    idx = _find_lat_idx(lat, ymin=-22.0, ymax=-10.0)
    np.testing.assert_array_equal(lat[idx], [-20.0, -15.0, -10.0])


def test_find_lat_idx_raises_when_empty() -> None:
    lat = np.array([0.0, 10.0, 20.0])
    with pytest.raises(ValueError, match="격자점이 없습니다"):
        _find_lat_idx(lat, ymin=-30.0, ymax=-25.0)


# ── _find_lon_idx (0-360 기준) ───────────────────────────────────────────

def test_find_lon_idx_basic() -> None:
    lon = np.arange(0, 360, 1.875)   # CMIP6 144 lat × 192 lon (lon 1.875°)
    # 쿡 아일랜드 ≈ 200°E (경도 -160° → 200°)
    idx = _find_lon_idx(lon, xmin_360=199.0, xmax_360=202.0)
    selected = lon[idx]
    assert all(199.0 <= v <= 202.0 for v in selected)
    assert len(selected) >= 1


def test_find_lon_idx_raises_when_empty() -> None:
    lon = np.array([0.0, 90.0, 180.0, 270.0])
    with pytest.raises(ValueError, match="격자점이 없습니다"):
        _find_lon_idx(lon, xmin_360=10.0, xmax_360=20.0)
