"""gis.py — UTM EPSG 자동 산출, canonical/reprojected 경로 규약 검증."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from util_py.gis import (
    auto_utm_epsg,
    clip_raster,
    gis_canonical_path,
    gis_reprojected_path,
    prepare_raster_for_swat,
    reproject_raster,
)

# rasterio 없으면 raster 테스트 스킵
rasterio = pytest.importorskip("rasterio", reason="rasterio required for raster tests")


# ── auto_utm_epsg ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "lon, lat, expected_epsg, label",
    [
        # 남반구
        (-159.8, -21.2, 32704, "Rarotonga, Cook Islands"),
        (-161.5, -15.0, 32704, "Cook Islands center"),
        (151.0,  -33.9, 32756, "Sydney"),
        (178.4,  -18.1, 32760, "Suva, Fiji"),
        # 북반구
        (127.0,   37.5, 32652, "Seoul"),
        (139.7,   35.7, 32654, "Tokyo"),
        (-74.0,   40.7, 32618, "New York"),
        (2.35,    48.86, 32631, "Paris"),
        # 적도
        (0.0,     0.0,  32631, "적도 그리니치 — 북반구로 처리 (lat>=0)"),
    ],
)
def test_auto_utm_epsg_known_points(lon, lat, expected_epsg, label) -> None:
    assert auto_utm_epsg(lon=lon, lat=lat) == expected_epsg, label


def test_auto_utm_epsg_from_bbox_uses_center() -> None:
    """Cook Islands bbox 중심으로 zone 산출."""
    bbox = (-165.86, -21.94, -157.31, -8.94)
    # center ≈ (-161.585, -15.44) → zone 4 남반구 → 32704
    assert auto_utm_epsg(bbox=bbox) == 32704


def test_auto_utm_epsg_from_boundary_csv(tmp_path) -> None:
    p = tmp_path / "boundary.csv"
    pd.DataFrame([{
        "OBJECTID": 1, "NAME": "Cook Islands", "ISO3": "COK", "ISO2": "CK",
        "xmin": -165.86, "ymin": -21.94, "xmax": -157.31, "ymax": -8.94,
    }]).to_csv(p, index=False)
    assert auto_utm_epsg(boundary_csv=str(p)) == 32704


def test_auto_utm_epsg_no_input_raises() -> None:
    with pytest.raises(ValueError):
        auto_utm_epsg()


def test_auto_utm_epsg_lon_only_raises() -> None:
    """lat 없이 lon만 주면 에러."""
    with pytest.raises(ValueError):
        auto_utm_epsg(lon=127.0)


def test_auto_utm_epsg_zone_boundary() -> None:
    """경도 -180 / 180 (날짜변경선) 처리."""
    # zone 1 = -180 ~ -174
    assert auto_utm_epsg(lon=-179.0, lat=0.0) == 32601
    # zone 60 = 174 ~ 180
    assert auto_utm_epsg(lon=179.0, lat=0.0) == 32660


def test_auto_utm_epsg_negative_zero_lat_north() -> None:
    """lat == 0 은 북반구로 분류."""
    assert auto_utm_epsg(lon=0.0, lat=0.0) >= 32600


# ── gis_canonical_path ───────────────────────────────────────────────────────

def test_canonical_with_explicit_ext(tmp_path) -> None:
    p = gis_canonical_path(tmp_path, "boundary", ext="shp")
    assert p == tmp_path / "boundary" / "boundary.shp"


def test_canonical_strips_dot_in_ext(tmp_path) -> None:
    p = gis_canonical_path(tmp_path, "dem", ext=".tif")
    assert p.name == "dem.tif"


def test_canonical_auto_detects_existing(tmp_path) -> None:
    """폴더에 boundary.shp 가 있으면 자동 발견."""
    folder = tmp_path / "boundary"
    folder.mkdir()
    (folder / "boundary.shp").write_text("")
    (folder / "boundary.dbf").write_text("")  # supporting file

    p = gis_canonical_path(tmp_path, "boundary")
    # shp 가 dbf 보다 우선 (다만 둘 다 stem == "boundary" 라 둘 다 매칭됨)
    # 그래서 _EXT_PRIORITY 에 따라 .shp 가 먼저
    assert p.suffix == ".shp"


def test_canonical_excludes_epsg_suffix(tmp_path) -> None:
    """boundary-epsg32704.shp 는 canonical 이 아니므로 제외."""
    folder = tmp_path / "boundary"
    folder.mkdir()
    (folder / "boundary.shp").write_text("")
    (folder / "boundary-epsg32704.shp").write_text("")

    p = gis_canonical_path(tmp_path, "boundary")
    assert p.name == "boundary.shp"


def test_canonical_no_file_raises(tmp_path) -> None:
    folder = tmp_path / "dem"
    folder.mkdir()
    (folder / "dem-epsg32704.tif").write_text("")  # 사본만 있고 canonical 없음
    with pytest.raises(FileNotFoundError, match="canonical 파일 없음"):
        gis_canonical_path(tmp_path, "dem")


def test_canonical_no_folder_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="디렉토리 없음"):
        gis_canonical_path(tmp_path, "nonexistent_type")


def test_canonical_priority_shp_over_csv(tmp_path) -> None:
    """같은 stem의 .shp 와 .csv 가 공존하면 .shp 우선."""
    folder = tmp_path / "boundary"
    folder.mkdir()
    (folder / "boundary.csv").write_text("")
    (folder / "boundary.shp").write_text("")
    p = gis_canonical_path(tmp_path, "boundary")
    assert p.suffix == ".shp"


# ── gis_reprojected_path ─────────────────────────────────────────────────────

def test_reprojected_with_explicit_ext(tmp_path) -> None:
    p = gis_reprojected_path(tmp_path, "dem", epsg=32704, ext="tif")
    assert p == tmp_path / "dem" / "dem-epsg32704.tif"


def test_reprojected_infers_ext_from_canonical(tmp_path) -> None:
    folder = tmp_path / "boundary"
    folder.mkdir()
    (folder / "boundary.shp").write_text("")
    p = gis_reprojected_path(tmp_path, "boundary", epsg=32704)
    assert p.name == "boundary-epsg32704.shp"


def test_reprojected_path_does_not_require_existing_file(tmp_path) -> None:
    """ext 가 명시되면 canonical 파일 없어도 경로 계산 가능."""
    p = gis_reprojected_path(tmp_path, "future_data", epsg=4326, ext="gpkg")
    assert p.parent.name == "future_data"
    assert p.name == "future_data-epsg4326.gpkg"


# ── name 파라미터 (descriptive 파일명) ─────────────────────────────────────

def test_canonical_with_custom_name(tmp_path) -> None:
    """era5 폴더 안의 grid_points-era5.shp 처럼 stem 이 data_type 과 다른 경우."""
    p = gis_canonical_path(tmp_path, "era5", ext="shp", name="grid_points-era5")
    assert p == tmp_path / "era5" / "grid_points-era5.shp"


def test_canonical_auto_detect_with_name(tmp_path) -> None:
    """ext=None + name 지정 → 폴더에서 grid_points-era5.* 검색."""
    folder = tmp_path / "era5"
    folder.mkdir()
    (folder / "grid_points-era5.shp").write_text("")
    (folder / "grid_points-era5.dbf").write_text("")
    p = gis_canonical_path(tmp_path, "era5", name="grid_points-era5")
    assert p.name == "grid_points-era5.shp"


def test_reprojected_with_custom_name(tmp_path) -> None:
    p = gis_reprojected_path(tmp_path, "era5", epsg=32704,
                             ext="shp", name="grid_points-era5")
    assert p.name == "grid_points-era5-epsg32704.shp"


# ── 통합: Cook Islands 자동 SWAT EPSG ───────────────────────────────────────

# ── 합성 raster 픽스처 ─────────────────────────────────────────────────────

import numpy as np
from affine import Affine


def _make_test_raster(path: Path, *, width: int = 100, height: int = 100,
                      bbox=(-160.0, -22.0, -158.0, -20.0), dtype="float32",
                      fill_value=10.0, crs_epsg: int = 4326) -> Path:
    """테스트용 합성 GeoTIFF."""
    xmin, ymin, xmax, ymax = bbox
    transform = Affine.translation(xmin, ymax) * Affine.scale(
        (xmax - xmin) / width, -(ymax - ymin) / height
    )
    arr = np.full((height, width), fill_value, dtype=dtype)
    # 그라디언트로 채우기 (테스트 가독성)
    for i in range(height):
        for j in range(width):
            arr[i, j] = float(i + j)
    with rasterio.open(
        path, "w",
        driver="GTiff", height=height, width=width, count=1,
        dtype=dtype, crs=f"EPSG:{crs_epsg}", transform=transform,
    ) as dst:
        dst.write(arr, 1)
    return path


def _make_test_polygon(path: Path, bbox=(-159.5, -21.5, -158.5, -20.5),
                       crs_epsg: int = 4326) -> Path:
    """테스트용 폴리곤 shapefile."""
    import geopandas as gpd
    from shapely.geometry import box
    gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(*bbox)],
        crs=f"EPSG:{crs_epsg}",
    )
    gdf.to_file(path)
    return path


# ── clip_raster ──────────────────────────────────────────────────────────────

def test_clip_raster_with_bbox(tmp_path) -> None:
    src = _make_test_raster(tmp_path / "src.tif")
    dst = tmp_path / "clip.tif"
    clip_raster(src, dst, bbox=(-159.5, -21.5, -158.5, -20.5))
    assert dst.is_file()
    with rasterio.open(dst) as r:
        assert r.width < 100
        assert r.height < 100


def test_clip_raster_bbox_with_buffer(tmp_path) -> None:
    """버퍼가 클립 영역을 외측으로 확장."""
    src = _make_test_raster(tmp_path / "src.tif")
    no_buf = tmp_path / "no_buf.tif"
    with_buf = tmp_path / "with_buf.tif"

    clip_raster(src, no_buf, bbox=(-159.5, -21.5, -158.5, -20.5), buffer_deg=0.0)
    clip_raster(src, with_buf, bbox=(-159.5, -21.5, -158.5, -20.5), buffer_deg=0.1)

    with rasterio.open(no_buf) as a, rasterio.open(with_buf) as b:
        assert b.width  > a.width
        assert b.height > a.height


def test_clip_raster_with_polygon(tmp_path) -> None:
    src = _make_test_raster(tmp_path / "src.tif")
    poly = _make_test_polygon(tmp_path / "poly.shp")
    dst = tmp_path / "clip.tif"
    clip_raster(src, dst, boundary_path=poly)
    assert dst.is_file()
    with rasterio.open(dst) as r:
        assert r.crs.to_epsg() == 4326
        assert r.width < 100  # 클립되었음


def test_clip_raster_polygon_with_buffer_expands(tmp_path) -> None:
    src = _make_test_raster(tmp_path / "src.tif")
    poly = _make_test_polygon(tmp_path / "poly.shp")
    no_buf  = tmp_path / "no_buf.tif"
    with_buf = tmp_path / "with_buf.tif"

    clip_raster(src, no_buf, boundary_path=poly, buffer_deg=0.0)
    clip_raster(src, with_buf, boundary_path=poly, buffer_deg=0.2)

    with rasterio.open(no_buf) as a, rasterio.open(with_buf) as b:
        assert b.width >= a.width
        assert b.height >= a.height


def test_clip_raster_requires_bbox_or_boundary(tmp_path) -> None:
    src = _make_test_raster(tmp_path / "src.tif")
    with pytest.raises(ValueError, match="bbox 또는 boundary"):
        clip_raster(src, tmp_path / "x.tif")


# ── reproject_raster ─────────────────────────────────────────────────────────

def test_reproject_raster_to_utm(tmp_path) -> None:
    src = _make_test_raster(tmp_path / "src.tif",
                            bbox=(-160.0, -22.0, -159.0, -21.0))
    dst = tmp_path / "utm.tif"
    reproject_raster(src, dst, target_epsg=32704, resampling="bilinear")

    with rasterio.open(dst) as r:
        assert r.crs.to_epsg() == 32704
        # UTM 좌표는 미터 단위, 큰 값
        assert abs(r.bounds.left)   > 100_000
        assert abs(r.bounds.right)  > 100_000


def test_reproject_raster_invalid_resampling_raises(tmp_path) -> None:
    src = _make_test_raster(tmp_path / "src.tif")
    with pytest.raises(ValueError, match="resampling"):
        reproject_raster(src, tmp_path / "x.tif", 32704, resampling="invalid")


# ── prepare_raster_for_swat ──────────────────────────────────────────────────

def test_prepare_raster_for_swat_clip_only(tmp_path) -> None:
    src = _make_test_raster(tmp_path / "src.tif")
    poly = _make_test_polygon(tmp_path / "poly.shp")
    out = prepare_raster_for_swat(src, boundary_path=poly,
                                   buffer_deg=0.05, target_epsg=None)
    assert out.name == "src-clip.tif"
    with rasterio.open(out) as r:
        assert r.crs.to_epsg() == 4326   # 재투영 안함


def test_prepare_raster_for_swat_clip_and_reproject(tmp_path) -> None:
    src = _make_test_raster(tmp_path / "dem.tif",
                            bbox=(-160.0, -22.0, -159.0, -21.0))
    poly = _make_test_polygon(tmp_path / "poly.shp",
                              bbox=(-159.8, -21.8, -159.2, -21.2))
    out = prepare_raster_for_swat(src, boundary_path=poly,
                                   buffer_deg=0.05, target_epsg=32704,
                                   resampling="bilinear")
    assert out.name == "dem-epsg32704.tif"
    with rasterio.open(out) as r:
        assert r.crs.to_epsg() == 32704


def test_prepare_raster_keep_intermediate(tmp_path) -> None:
    """keep_intermediate=True 면 -clip.tif 도 보존."""
    src = _make_test_raster(tmp_path / "lulc.tif")
    poly = _make_test_polygon(tmp_path / "poly.shp")
    out = prepare_raster_for_swat(src, boundary_path=poly,
                                   target_epsg=32704,
                                   resampling="nearest",
                                   keep_intermediate=True)
    assert out.is_file()
    intermediate = tmp_path / "lulc-clip.tif"
    assert intermediate.is_file()


def test_prepare_raster_nearest_for_categorical(tmp_path) -> None:
    """범주형(LULC)은 nearest 로 정수 픽셀값 보존."""
    src = _make_test_raster(tmp_path / "cat.tif", dtype="uint8", fill_value=10)
    # 일정 패턴 (0, 10, 20, 30 등)
    with rasterio.open(src) as s:
        arr = s.read(1)
    arr_pattern = ((arr.astype(int) % 4) * 10).astype("uint8")
    with rasterio.open(src, "r+") as s:
        s.write(arr_pattern, 1)

    poly = _make_test_polygon(tmp_path / "poly.shp")
    out = prepare_raster_for_swat(src, boundary_path=poly,
                                   target_epsg=32704, resampling="nearest")
    with rasterio.open(out) as r:
        unique_vals = set(np.unique(r.read(1)).tolist())
    # nearest 보간이라 원본 4개 값(0,10,20,30) 만 나타나야 함
    assert unique_vals.issubset({0, 10, 20, 30})


def test_cook_islands_swat_epsg_workflow(tmp_path) -> None:
    """boundary CSV → auto UTM → canonical+reprojected 경로 일관성 검증."""
    bnd = tmp_path / "boundary.csv"
    pd.DataFrame([{
        "OBJECTID": 58, "NAME": "Cook Islands",
        "ISO3": "COK", "ISO2": "CK",
        "xmin": -165.86, "ymin": -21.94, "xmax": -157.31, "ymax": -8.94,
    }]).to_csv(bnd, index=False)

    swat_epsg = auto_utm_epsg(boundary_csv=str(bnd))
    assert swat_epsg == 32704

    canonical = gis_canonical_path(tmp_path / "gis", "boundary", ext="shp")
    utm = gis_reprojected_path(tmp_path / "gis", "boundary", epsg=swat_epsg, ext="shp")

    assert canonical.parent == utm.parent
    assert canonical.name == "boundary.shp"
    assert utm.name == "boundary-epsg32704.shp"
