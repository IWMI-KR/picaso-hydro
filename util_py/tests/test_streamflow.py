"""streamflow.py — bbox 교차, 서브셋 매핑, USGS 권역 검증."""
from __future__ import annotations

import pytest

from util_py.streamflow import (
    CARAVAN_SUBSETS,
    _bbox_in_usgs_coverage,
    _bbox_intersects,
    caravan_subsets_for_bbox,
)


# ── bbox 교차 ────────────────────────────────────────────────────────────────

def test_bbox_intersects_overlap() -> None:
    assert _bbox_intersects((0, 0, 10, 10), (5, 5, 15, 15))


def test_bbox_intersects_touching() -> None:
    """경계만 닿아도 교차로 간주."""
    assert _bbox_intersects((0, 0, 10, 10), (10, 10, 20, 20))


def test_bbox_intersects_disjoint() -> None:
    assert not _bbox_intersects((0, 0, 5, 5), (10, 10, 15, 15))


# ── CARAVAN 서브셋 매핑 ──────────────────────────────────────────────────────

def test_caravan_subsets_us_central() -> None:
    """미국 중부 (콜로라도) → camels + hysets (둘 다 미국 포함)."""
    bbox = (-106.0, 38.5, -104.5, 40.0)
    subs = {s["name"] for s in caravan_subsets_for_bbox(bbox)}
    assert "camels" in subs
    assert "hysets" in subs


def test_caravan_subsets_australia() -> None:
    bbox = (140.0, -36.0, 145.0, -33.0)   # Sydney 지역
    subs = {s["name"] for s in caravan_subsets_for_bbox(bbox)}
    assert subs == {"camelsaus"}


def test_caravan_subsets_korea_no_match() -> None:
    """한국은 CARAVAN 미수록 (CAMELS-KR 따로 존재하나 통합 미포함)."""
    bbox = (126.0, 33.0, 130.0, 38.0)
    subs = caravan_subsets_for_bbox(bbox)
    assert subs == []


def test_caravan_subsets_cook_islands_no_match() -> None:
    """Cook Islands 같은 소형 도서국은 CARAVAN 어떤 서브셋에도 없음."""
    bbox = (-165.86, -21.94, -157.31, -8.94)
    assert caravan_subsets_for_bbox(bbox) == []


def test_caravan_subsets_brazil() -> None:
    bbox = (-50.0, -15.0, -45.0, -10.0)
    subs = {s["name"] for s in caravan_subsets_for_bbox(bbox)}
    assert subs == {"camelsbr"}


def test_caravan_subsets_metadata_complete() -> None:
    """모든 서브셋이 필수 필드 보유."""
    required = {"name", "bbox", "n_catchments", "country", "size_mb"}
    for s in CARAVAN_SUBSETS:
        assert required <= set(s.keys()), f"{s.get('name')} missing fields"
        assert len(s["bbox"]) == 4
        assert s["n_catchments"] > 0


# ── USGS 권역 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bbox, in_coverage", [
    ((-106, 38, -104, 40),    True),    # 콜로라도
    ((-118, 33, -117, 34),    True),    # LA
    ((-150, 60, -148, 62),    True),    # 알래스카
    ((-158, 21, -157, 22),    True),    # 하와이
    ((-67, 18, -66, 19),      True),    # 푸에르토리코
    ((-165.86, -21.94, -157.31, -8.94), False),   # Cook Islands
    ((126, 33, 130, 38),      False),   # 한국
    ((140, -35, 145, -33),    False),   # 호주
])
def test_usgs_coverage(bbox, in_coverage) -> None:
    assert _bbox_in_usgs_coverage(bbox) is in_coverage
