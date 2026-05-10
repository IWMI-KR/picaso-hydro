"""gis_user — naming 규칙, area 발견, 클립 동작 검증."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

rasterio = pytest.importorskip("rasterio")
gpd = pytest.importorskip("geopandas")

from affine import Affine
from shapely.geometry import box

from util_py.gis_user import (
    _parse_area_from_filename,
    clip_to_user_area,
    discover_user_areas,
)


# ── 파일명 → area 추출 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("fname, area", [
    ("boundary-rarotonga.shp", "rarotonga"),
    ("boundary-aitutaki.shp",  "aitutaki"),
    ("boundary-mokoia.shp",    "mokoia"),
    ("boundary-han-river.shp", "han-river"),
    ("boundary-area123.shp",   "area123"),
])
def test_parse_area_from_filename(fname, area) -> None:
    assert _parse_area_from_filename(fname) == area


def test_parse_area_returns_none_for_invalid(tmp_path) -> None:
    assert _parse_area_from_filename("boundary.shp") is None
    assert _parse_area_from_filename("admin.shp")    is None
    assert _parse_area_from_filename("boundary-")    is None


# ── area 자동 발견 ───────────────────────────────────────────────────────────

def test_discover_user_areas(tmp_path) -> None:
    user_dir = tmp_path / "user"
    user_dir.mkdir()

    # 3개의 boundary-*.shp 생성
    for area in ("rarotonga", "aitutaki", "mokoia"):
        gdf = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[box(-160.0, -22.0, -159.0, -21.0)],
            crs="EPSG:4326",
        )
        gdf.to_file(user_dir / f"boundary-{area}.shp")

    # boundary 가 아닌 파일도 추가 — 무시되어야
    gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(0, 0, 1, 1)],
        crs="EPSG:4326",
    ).to_file(user_dir / "other.shp")

    areas = discover_user_areas(user_dir)
    assert {a["area"] for a in areas} == {"rarotonga", "aitutaki", "mokoia"}


def test_discover_returns_empty_for_missing_dir(tmp_path) -> None:
    assert discover_user_areas(tmp_path / "no_such") == []


# ── 통합 클립 ────────────────────────────────────────────────────────────────

def _make_country_setup(gis_root: Path) -> None:
    """국가 raster (DEM, LULC, soil) + lookup + mdb 합성."""
    # DEM (continuous, EPSG:4326, -160 ~ -159 lon, -22 ~ -21 lat)
    width, height = 100, 100
    transform = Affine.translation(-160.0, -21.0) * Affine.scale(0.01, -0.01)
    arr = (np.arange(width * height) % 100).reshape(height, width).astype("float32")
    for sub in ("dem", "landuse", "soil"):
        (gis_root / sub).mkdir(parents=True, exist_ok=True)

    with rasterio.open(
        gis_root / "dem" / "dem.tif", "w",
        driver="GTiff", width=width, height=height, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(arr, 1)

    # LULC (categorical, uint8) + lookup
    lulc = (arr.astype(int) % 5 * 10 + 10).astype("uint8")
    with rasterio.open(
        gis_root / "landuse" / "landuse.tif", "w",
        driver="GTiff", width=width, height=height, count=1,
        dtype="uint8", crs="EPSG:4326", transform=transform, nodata=0,
    ) as dst:
        dst.write(lulc, 1)
    pd.DataFrame({
        "val": [10, 20, 30, 40, 50],
        "description": ["Tree", "Shrub", "Grass", "Crop", "Built"],
        "SWAT_LU_Code": ["FRST", "RNGB", "RNGE", "AGRL", "URBN"],
    }).to_csv(gis_root / "landuse" / "landuse_lookup.csv", index=False)

    # soil + lookup + mdb (mdb는 더미)
    soil = ((arr.astype(int) % 7) + 1).astype("uint16")
    with rasterio.open(
        gis_root / "soil" / "soil.tif", "w",
        driver="GTiff", width=width, height=height, count=1,
        dtype="uint16", crs="EPSG:4326", transform=transform, nodata=0,
    ) as dst:
        dst.write(soil, 1)
    pd.DataFrame({"val": list(range(8)), "SWAT_MUID": [str(i) for i in range(8)]}).to_csv(
        gis_root / "soil" / "soil_lookup.csv", index=False)
    (gis_root / "soil" / "SWAT2009-Global-V1.0.mdb").write_bytes(b"FAKE_MDB")


def test_clip_to_user_area_full_workflow(tmp_path) -> None:
    """user area 클립 + UTM 재투영 + lookup/mdb 복사 통합."""
    gis_root = tmp_path / "gis"
    user_base = gis_root / "user"
    user_base.mkdir(parents=True, exist_ok=True)
    _make_country_setup(gis_root)

    # 사용자 boundary 파일
    gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(-159.7, -21.3, -159.4, -21.0)],
        crs="EPSG:4326",
    ).to_file(user_base / "boundary-rarotonga.shp")

    saved = clip_to_user_area("rarotonga", gis_root, user_base, buffer_deg=0.0)

    area_dir = user_base / "rarotonga"
    # boundary 메타
    assert (area_dir / "boundary" / "boundary-rarotonga.csv").is_file()
    # DEM (clip + UTM)
    assert (area_dir / "dem" / "dem.tif").is_file()
    assert any(p.name.startswith("dem-epsg") for p in (area_dir / "dem").iterdir())
    # LULC (clip + UTM + lookup)
    assert (area_dir / "landuse" / "landuse.tif").is_file()
    assert (area_dir / "landuse" / "landuse_lookup.csv").is_file()
    # SOIL (clip + UTM + lookup + mdb)
    assert (area_dir / "soil" / "soil.tif").is_file()
    assert (area_dir / "soil" / "soil_lookup.csv").is_file()
    assert (area_dir / "soil" / "SWAT2009-Global-V1.0.mdb").is_file()

    # UTM 좌표계 확인
    utm = next(p for p in (area_dir / "dem").iterdir()
               if p.name.startswith("dem-epsg"))
    with rasterio.open(utm) as r:
        assert r.crs.to_epsg() != 4326   # 재투영됨


def test_clip_to_user_area_missing_boundary_raises(tmp_path) -> None:
    gis_root = tmp_path / "gis"
    (gis_root / "user").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="User boundary 없음"):
        clip_to_user_area("notexist", gis_root)


def test_clip_skips_when_country_canonical_missing(tmp_path, capsys) -> None:
    """국가 canonical raster 가 없으면 그 type 만 건너뜀 (실패 X)."""
    gis_root = tmp_path / "gis"
    user_base = gis_root / "user"
    user_base.mkdir(parents=True)
    # DEM 만 있음 (LULC, soil 없음)
    (gis_root / "dem").mkdir()
    width, height = 50, 50
    transform = Affine.translation(-160.0, -21.0) * Affine.scale(0.01, -0.01)
    with rasterio.open(
        gis_root / "dem" / "dem.tif", "w",
        driver="GTiff", width=width, height=height, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(np.ones((height, width), dtype="float32"), 1)

    # 사용자 boundary 는 DEM (-160~-159, -22~-21) 안쪽
    gpd.GeoDataFrame({"id": [1]},
                     geometry=[box(-159.8, -21.8, -159.5, -21.2)],
                     crs="EPSG:4326",
                     ).to_file(user_base / "boundary-area1.shp")

    saved = clip_to_user_area("area1", gis_root, user_base, buffer_deg=0.0)
    out = capsys.readouterr().out
    assert "건너뜀" in out
    # DEM 만 클립되어야 함
    assert "dem" in saved
    assert "landuse" not in saved
    assert "soil" not in saved
