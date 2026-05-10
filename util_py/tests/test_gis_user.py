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
    _clip_reproject_rasterize_vector,
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


def test_clip_reproject_rasterize_vector_basic(tmp_path) -> None:
    """polygon shapefile → UTM shp + val rasterize."""
    # 입력 vector: 4 features 와 val 값 다양
    polys = [
        box(-160.0, -22.0, -159.5, -21.5),  # val=10
        box(-159.5, -22.0, -159.0, -21.5),  # val=20
        box(-160.0, -21.5, -159.5, -21.0),  # val=30
        box(-159.5, -21.5, -159.0, -21.0),  # val=40
    ]
    vshp = tmp_path / "soil-swat.shp"
    gpd.GeoDataFrame({"val": [10, 20, 30, 40]},
                     geometry=polys, crs="EPSG:4326").to_file(vshp)

    # boundary: 좌하단 4분면만 포함
    bshp = tmp_path / "boundary.shp"
    gpd.GeoDataFrame({"id": [1]},
                     geometry=[box(-160.0, -22.0, -159.5, -21.5)],
                     crs="EPSG:4326").to_file(bshp)

    out_shp = tmp_path / "out" / "soil-swat-utm.shp"
    out_tif = tmp_path / "out" / "soil-swat-utm.tif"
    _clip_reproject_rasterize_vector(
        vshp, bshp, out_shp, out_tif,
        target_epsg=32705,    # Cook UTM
        val_column="val", pixel_size_m=100.0, buffer_deg=0.0,
    )

    assert out_shp.is_file()
    assert out_tif.is_file()

    # shp: UTM CRS, val=10만 남음
    g_out = gpd.read_file(out_shp)
    assert g_out.crs.to_epsg() == 32705
    assert set(g_out["val"].unique()) == {10}

    # tif: UTM, val=10 픽셀 존재
    with rasterio.open(out_tif) as r:
        assert r.crs.to_epsg() == 32705
        arr = r.read(1)
    assert (arr == 10).any()
    assert (arr == 0).any()  # nodata 영역


def test_clip_reproject_rasterize_vector_missing_val_raises(tmp_path) -> None:
    """val 컬럼 없으면 ValueError."""
    vshp = tmp_path / "no_val.shp"
    gpd.GeoDataFrame({"id": [1]},
                     geometry=[box(-160.0, -22.0, -159.0, -21.0)],
                     crs="EPSG:4326").to_file(vshp)
    bshp = tmp_path / "b.shp"
    gpd.GeoDataFrame({"id": [1]},
                     geometry=[box(-160.0, -22.0, -159.0, -21.0)],
                     crs="EPSG:4326").to_file(bshp)
    with pytest.raises(ValueError, match="'val' 컬럼 없음"):
        _clip_reproject_rasterize_vector(
            vshp, bshp, tmp_path / "o.shp", tmp_path / "o.tif",
            target_epsg=32705, val_column="val", pixel_size_m=30.0,
        )


def test_clip_to_user_area_uses_vector_fallback_when_soil_tif_missing(tmp_path) -> None:
    """soil.tif 없고 soil-swat.shp 있으면 vector→UTM shp + tif 생성 + lookup/mdb 복사."""
    gis_root = tmp_path / "gis"
    user_base = gis_root / "user"
    user_base.mkdir(parents=True)
    (gis_root / "soil").mkdir()

    # soil-swat.shp (val 컬럼)
    polys = [box(-160.0, -22.0, -159.5, -21.5),
             box(-159.5, -22.0, -159.0, -21.5)]
    gpd.GeoDataFrame({"val": [165, 570]}, geometry=polys, crs="EPSG:4326"
                     ).to_file(gis_root / "soil" / "soil-swat.shp")
    # lookup + mdb (FAO Soil 명으로 — 후보 인식 검증)
    pd.DataFrame({"val": [165, 570], "SWAT_MUID": ["A", "B"]}).to_csv(
        gis_root / "soil" / "soil_lookup.csv", index=False)
    (gis_root / "soil" / "SWAT2009-Global-FAO Soil.mdb").write_bytes(b"FAKE")

    # boundary
    gpd.GeoDataFrame({"id": [1]},
                     geometry=[box(-160.0, -22.0, -159.0, -21.0)],
                     crs="EPSG:4326",
                     ).to_file(user_base / "boundary-area1.shp")

    saved = clip_to_user_area("area1", gis_root, user_base,
                               raster_types=["soil"], buffer_deg=0.0)

    soil_dir = user_base / "area1" / "soil"
    # raster fallback 결과
    vshp = next(soil_dir.glob("soil-swat-epsg*.shp"))
    vtif = next(soil_dir.glob("soil-swat-epsg*.tif"))
    assert vshp.is_file()
    assert vtif.is_file()
    # lookup + mdb 복사 (raster 부재에도 실행)
    assert (soil_dir / "soil_lookup.csv").is_file()
    assert (soil_dir / "SWAT2009-Global-FAO Soil.mdb").is_file()
    assert "soil_vector_shp" in saved
    assert "soil_vector_tif" in saved
    assert "soil_lookup" in saved
    assert "soil_mdb" in saved


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
