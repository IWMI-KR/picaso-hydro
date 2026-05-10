"""gis_download.py — tile 좌표 산출, region 매핑, boundary 파싱 검증.

실제 네트워크 호출은 하지 않음 (mock 또는 helper 함수만).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from util_py.gis_download import (
    _lat_to_tile_str,
    _lon_to_tile_str,
    _read_bbox_iso,
    bbox_to_dem_tiles,
    bbox_to_hydrosheds_region,
    bbox_to_worldcover_tiles,
)


# ── tile 문자열 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lat, expected", [
    (0,    "N00"),
    (37,   "N37"),
    (-21,  "S21"),
    (-22,  "S22"),
    (-9,   "S09"),
    (90,   "N90"),
    (-90,  "S90"),
])
def test_lat_to_tile_str(lat: int, expected: str) -> None:
    assert _lat_to_tile_str(lat) == expected


@pytest.mark.parametrize("lon, expected", [
    (0,     "E000"),
    (127,   "E127"),
    (-159,  "W159"),
    (-160,  "W160"),
    (-9,    "W009"),
    (180,   "E180"),
    (-180,  "W180"),
])
def test_lon_to_tile_str(lon: int, expected: str) -> None:
    assert _lon_to_tile_str(lon) == expected


# ── DEM tile 산출 ────────────────────────────────────────────────────────────

def test_bbox_to_dem_tiles_cook_islands() -> None:
    """Cook Islands bbox → 1°×1° tile 좌표 목록."""
    bbox = (-165.86, -21.94, -157.31, -8.94)
    tiles = bbox_to_dem_tiles(bbox)
    # lon: floor(-165.86)=-166 ~ ceil(-157.31)=-157 → 9개 (-166..-158)
    # lat: floor(-21.94)=-22  ~ ceil(-8.94)=-8     → 14개 (-22..-9)
    assert len(tiles) == 9 * 14
    assert (-22, -160) in tiles  # Rarotonga 포함 tile (S22 W160)
    assert (-22, -166) in tiles  # SW 코너
    assert (-9, -158)  in tiles  # NE 코너


def test_bbox_to_dem_tiles_single_point_box() -> None:
    """1x1 도 영역."""
    tiles = bbox_to_dem_tiles((10.0, 20.0, 11.0, 21.0))
    assert tiles == [(20, 10)]


# ── ESA WorldCover tile (3°×3°) ──────────────────────────────────────────────

def test_worldcover_tiles_cook_islands() -> None:
    """Cook Islands 3°×3° tile."""
    bbox = (-165.86, -21.94, -157.31, -8.94)
    tiles = bbox_to_worldcover_tiles(bbox)
    # lon: floor(-165.86/3)*3 = -168, ceil(-157.31/3)*3 = -156 → -168, -165, -162, -159 (4개)
    # lat: floor(-21.94/3)*3 = -24,  ceil(-8.94/3)*3  = -6   → -24, -21, -18, -15, -12, -9 (6개)
    assert len(tiles) == 4 * 6
    assert "S24W168" in tiles
    assert "S09W159" in tiles
    # 모든 tile 코드는 7자 (S/N + 2자리 + W/E + 3자리)
    assert all(len(t) == 7 for t in tiles)


def test_worldcover_tile_alignment() -> None:
    """3°단위 정렬 확인."""
    bbox = (3.5, 6.5, 5.5, 7.5)
    tiles = bbox_to_worldcover_tiles(bbox)
    # lon 3 → tile 3 (E003), lat 6 → tile 6 (N06)
    assert "N06E003" in tiles


# ── HydroSHEDS region 매핑 ───────────────────────────────────────────────────

@pytest.mark.parametrize("center_lon, center_lat, expected_region", [
    # 명확한 대륙
    (140, -25,  "au"),       # 호주 중부
    (10,  50,   "eu"),       # 유럽
    (15,  0,    "af"),       # 아프리카 적도
    (100, 30,   "as"),       # 아시아
    (-100, 40,  "na"),       # 미국 중부
    (-60, -20,  "sa"),       # 남미
    # Pacific 동부 (안티메리디안 가로질러 au 에 속함)
    (-161, -15, "au"),       # Cook Islands
    (-149, -17, "au"),       # French Polynesia (Tahiti)
    (-172,  -13, "au"),      # Samoa
])
def test_hydrosheds_region_clear(center_lon: float, center_lat: float,
                                  expected_region: str) -> None:
    bbox = (center_lon - 0.5, center_lat - 0.5,
            center_lon + 0.5, center_lat + 0.5)
    assert bbox_to_hydrosheds_region(bbox) == expected_region


def test_hydrosheds_region_returns_valid_code() -> None:
    """경계 영역에서도 항상 유효한 region 반환."""
    valid = {"af", "ar", "as", "au", "eu", "gr", "na", "sa", "si"}
    # 태평양 중부 등 어디도 정확히 안 들어가는 경우
    assert bbox_to_hydrosheds_region((-160, -20, -158, -18)) in valid


# ── boundary CSV 파싱 ────────────────────────────────────────────────────────

def test_read_bbox_iso(tmp_path) -> None:
    p = tmp_path / "boundary.csv"
    pd.DataFrame([{
        "OBJECTID": 58, "NAME": "Cook Islands",
        "ISO3": "COK", "ISO2": "CK",
        "xmin": -165.86, "ymin": -21.94, "xmax": -157.31, "ymax": -8.94,
    }]).to_csv(p, index=False)

    bbox, iso2, iso3, name = _read_bbox_iso(str(p))
    assert bbox == (-165.86, -21.94, -157.31, -8.94)
    assert iso2 == "CK"
    assert iso3 == "COK"
    assert name == "Cook Islands"


def test_read_bbox_iso_uppercase(tmp_path) -> None:
    """ISO 코드는 대문자로 정규화."""
    p = tmp_path / "b.csv"
    pd.DataFrame([{
        "NAME": "X", "ISO3": "cok", "ISO2": "ck",
        "xmin": 0, "ymin": 0, "xmax": 1, "ymax": 1,
    }]).to_csv(p, index=False)
    _, iso2, iso3, _ = _read_bbox_iso(str(p))
    assert iso2 == "CK"
    assert iso3 == "COK"


def test_read_bbox_empty_raises(tmp_path) -> None:
    p = tmp_path / "empty.csv"
    pd.DataFrame(columns=["NAME","ISO2","ISO3","xmin","ymin","xmax","ymax"]).to_csv(p, index=False)
    with pytest.raises(ValueError, match="빈 boundary"):
        _read_bbox_iso(str(p))


# ── ESA WorldCover lookup table ──────────────────────────────────────────────

from util_py.gis_download import (  # noqa: E402
    WORLDCOVER_LOOKUP,
    write_worldcover_lookup,
)


def test_worldcover_lookup_has_all_classes() -> None:
    """ESA WorldCover v200 11개 클래스 모두 포함."""
    vals = {row["val"] for row in WORLDCOVER_LOOKUP}
    expected = {10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}
    assert vals == expected


def test_worldcover_lookup_swat_codes() -> None:
    """주요 SWAT-Plus land use 코드 매핑."""
    by_val = {row["val"]: row for row in WORLDCOVER_LOOKUP}
    assert by_val[10]["SWAT_LU_Code"]  == "FRST"   # Tree → Forest
    assert by_val[40]["SWAT_LU_Code"]  == "AGRL"   # Crop → Agricultural
    assert by_val[50]["SWAT_LU_Code"]  == "URBN"   # Built-up → Urban
    assert by_val[80]["SWAT_LU_Code"]  == "WATR"   # Water
    assert by_val[95]["SWAT_LU_Code"]  == "WETF"   # Mangroves → Wetland forested


def test_worldcover_lookup_required_columns() -> None:
    required = {"val", "description", "SWAT_LU_Code"}
    for row in WORLDCOVER_LOOKUP:
        assert required <= set(row.keys())


# ── _clip_vector_to_bbox: 0 features → 저장 안 함 ──────────────────────────

def test_clip_vector_returns_none_when_empty(tmp_path) -> None:
    """클리핑 결과가 0 feature 이면 빈 .shp 를 만들지 않음."""
    import geopandas as gpd
    from shapely.geometry import Point

    from util_py.gis_download import _clip_vector_to_bbox

    # 호주 부근 점 1개 (Cook Islands bbox 와 겹치지 않음)
    src = tmp_path / "src.shp"
    gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[Point(140.0, -25.0)],
        crs="EPSG:4326",
    )
    gdf.to_file(src)

    dst = tmp_path / "out.shp"
    cook_bbox = (-165.86, -21.94, -157.31, -8.94)
    result = _clip_vector_to_bbox(src, dst, cook_bbox)

    assert result is None, "0 feature 이면 None 반환"
    assert not dst.exists(), "빈 .shp 파일이 만들어지면 안 됨"


def test_clip_vector_saves_when_overlaps(tmp_path) -> None:
    """교차하는 feature 가 있으면 정상 저장."""
    import geopandas as gpd
    from shapely.geometry import Point

    from util_py.gis_download import _clip_vector_to_bbox

    src = tmp_path / "src.shp"
    gdf = gpd.GeoDataFrame(
        {"id": [1, 2]},
        geometry=[Point(-159.8, -21.2),  # Rarotonga 안
                  Point(140.0, -25.0)],   # 호주 (밖)
        crs="EPSG:4326",
    )
    gdf.to_file(src)

    dst = tmp_path / "out.shp"
    cook_bbox = (-165.86, -21.94, -157.31, -8.94)
    result = _clip_vector_to_bbox(src, dst, cook_bbox)

    assert result == dst
    assert dst.exists()
    out = gpd.read_file(dst)
    assert len(out) == 1   # Rarotonga 만


def test_write_worldcover_lookup_csv(tmp_path) -> None:
    out = tmp_path / "landuse_lookup.csv"
    saved = write_worldcover_lookup(out)
    assert saved == out
    assert out.is_file()

    df = pd.read_csv(out)
    assert list(df.columns) == ["val", "description", "SWAT_LU_Code"]
    assert len(df) == 11
    assert (df["val"] == 10).any()
    assert (df.loc[df["val"] == 80, "description"].iloc[0] == "Permanent water bodies")
