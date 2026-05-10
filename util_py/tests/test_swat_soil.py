"""gis_download.download_swat_soil — local copy + lookup CSV 변환 검증."""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from util_py.gis_download import (
    _convert_lookup_txt_to_csv,
    download_swat_soil,
)


# ── lookup TXT → CSV 변환 ────────────────────────────────────────────────────

def _make_lookup_txt(path: Path) -> Path:
    """Soil_global_lookup.txt 와 동일한 형식 (Value,NAME)."""
    rows = "Value,NAME\n0,0\n1,1\n11,11\n6997,WATER\n"
    path.write_text(rows, encoding="utf-8")
    return path


def test_convert_lookup_renames_columns(tmp_path) -> None:
    src = _make_lookup_txt(tmp_path / "Soil_global_lookup.txt")
    dst = tmp_path / "soil_lookup.csv"
    _convert_lookup_txt_to_csv(src, dst)

    df = pd.read_csv(dst)
    assert list(df.columns) == ["val", "SWAT_MUID"]
    assert len(df) == 4


def test_convert_lookup_preserves_values(tmp_path) -> None:
    src = _make_lookup_txt(tmp_path / "lookup.txt")
    dst = tmp_path / "out.csv"
    _convert_lookup_txt_to_csv(src, dst)
    df = pd.read_csv(dst)
    assert (df["val"] == 6997).any()
    assert "WATER" in df["SWAT_MUID"].astype(str).values


# ── download_swat_soil (mock local) ──────────────────────────────────────────

def _make_fake_local_swat(local_dir: Path) -> None:
    """필수 파일만 생성한 합성 SWAT GISDB."""
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "soil_global.tif").write_bytes(b"FAKE_TIF" * 1000)
    (local_dir / "Soil_global_lookup.txt").write_text(
        "Value,NAME\n0,0\n1,1\n2,2\n", encoding="utf-8")
    (local_dir / "SWAT2009-Global-V1.0.mdb").write_bytes(b"FAKE_MDB" * 5000)
    # HWSD 옵션
    (local_dir / "hwsd.bil").write_bytes(b"BIL")
    (local_dir / "hwsd.hdr").write_text("BYTEORDER I\n", encoding="utf-8")
    (local_dir / "download" / "HWSD").mkdir(parents=True, exist_ok=True)
    (local_dir / "download" / "HWSD" / "HWSD.mdb").write_bytes(b"H")
    (local_dir / "download" / "HWSD" / "Readme for HWSD.txt").write_text(
        "x", encoding="utf-8")


def test_download_swat_soil_no_boundary_copies_global_as_canonical(tmp_path) -> None:
    """boundary 없으면 글로벌 raster 를 그대로 canonical 로 복사."""
    local = tmp_path / "swat_gisdb"
    _make_fake_local_swat(local)
    gis_root = tmp_path / "gis"

    saved = download_swat_soil(
        gis_root=gis_root, source="local", local_dir=local,
        boundary_path=None, bbox=None,
    )

    out_dir = gis_root / "soil"
    # canonical: soil.tif + lookup CSV + mdb
    assert (out_dir / "soil.tif").is_file()
    assert (out_dir / "SWAT2009-Global-V1.0.mdb").is_file()
    assert (out_dir / "soil_lookup.csv").is_file()
    # 글로벌 원본은 항상 download/
    assert (out_dir / "download" / "soil_global.tif").is_file()
    assert (out_dir / "download" / "Soil_global_lookup.txt").is_file()
    # HWSD 관련은 절대 다운로드 안 됨
    assert not (out_dir / "download" / "hwsd.bil").exists()
    assert not (out_dir / "download" / "HWSD.mdb").exists()

    df = pd.read_csv(out_dir / "soil_lookup.csv")
    assert list(df.columns) == ["val", "SWAT_MUID"]


def test_download_swat_soil_excludes_hwsd(tmp_path) -> None:
    """HWSD 파일이 local_dir 에 있어도 다운로드되지 않음 (SWAT DB 와 무관)."""
    local = tmp_path / "swat_gisdb"
    _make_fake_local_swat(local)   # HWSD 파일도 만들어짐
    gis_root = tmp_path / "gis"

    download_swat_soil(
        gis_root=gis_root, source="local", local_dir=local,
        boundary_path=None,
    )

    download_dir = gis_root / "soil" / "download"
    # 글로벌 SWAT 자료만 download/
    expected = {"soil_global.tif", "Soil_global_lookup.txt",
                "SWAT2009-Global-V1.0.mdb"}
    actual = {p.name for p in download_dir.iterdir() if p.is_file()}
    # HWSD 관련은 없어야 함
    assert "hwsd.bil"  not in actual
    assert "hwsd.hdr"  not in actual
    assert "HWSD.mdb"  not in actual
    # SWAT 핵심 3개는 있어야
    assert expected.issubset(actual)


def test_download_swat_soil_missing_required_raises(tmp_path) -> None:
    local = tmp_path / "swat_gisdb"
    local.mkdir()
    with pytest.raises(FileNotFoundError, match="필수 파일 없음"):
        download_swat_soil(gis_root=tmp_path / "gis",
                           source="local", local_dir=local)


def test_download_swat_soil_local_dir_missing_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="SWAT 토양 자료 위치"):
        download_swat_soil(gis_root=tmp_path / "gis",
                           source="local", local_dir=tmp_path / "no_such")


def test_download_swat_soil_url_not_implemented(tmp_path) -> None:
    with pytest.raises(NotImplementedError, match="source='url' 미구현"):
        download_swat_soil(gis_root=tmp_path / "gis", source="url")


# ── boundary 클립 + 빈 결과 안 저장 ──────────────────────────────────────────

import numpy as np
import rasterio
from affine import Affine

from util_py.gis_download import _clip_swat_soil_to_boundary


def _make_soil_global(path: Path, *, fill_value: int = 1) -> Path:
    """7.5km 해상도 글로벌 합성 토양 raster (CRS:EPSG:4326)."""
    width, height = 100, 50
    bbox = (-180.0, -90.0, 180.0, 90.0)
    xmin, ymin, xmax, ymax = bbox
    transform = Affine.translation(xmin, ymax) * Affine.scale(
        (xmax - xmin) / width, -(ymax - ymin) / height
    )
    arr = np.full((height, width), fill_value, dtype="uint16")
    with rasterio.open(
        path, "w",
        driver="GTiff", width=width, height=height, count=1,
        dtype="uint16", crs="EPSG:4326", transform=transform, nodata=0,
    ) as dst:
        dst.write(arr, 1)
    return path


def _make_polygon_shp(path: Path, bbox: tuple) -> Path:
    import geopandas as gpd
    from shapely.geometry import box
    gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(*bbox)],
        crs="EPSG:4326",
    ).to_file(path)
    return path


def test_clip_swat_soil_saves_when_valid(tmp_path) -> None:
    """Boundary 안에 유효 픽셀(값 != 0) 있으면 canonical 저장."""
    src = _make_soil_global(tmp_path / "soil_global.tif", fill_value=1)
    poly = _make_polygon_shp(tmp_path / "poly.shp",
                             bbox=(-10.0, -10.0, 10.0, 10.0))
    out = tmp_path / "soil.tif"

    result = _clip_swat_soil_to_boundary(
        src, out, poly, buffer_deg=0.0)

    assert result == out
    assert out.is_file()


def test_clip_swat_soil_returns_none_when_all_nodata(tmp_path) -> None:
    """Boundary 안 모든 픽셀이 nodata(0) 이면 저장 안 함."""
    # 글로벌 raster 가 모두 0 (nodata)
    src = _make_soil_global(tmp_path / "soil_global.tif", fill_value=0)
    poly = _make_polygon_shp(tmp_path / "poly.shp",
                             bbox=(-10.0, -10.0, 10.0, 10.0))
    out = tmp_path / "soil.tif"

    result = _clip_swat_soil_to_boundary(
        src, out, poly, buffer_deg=0.0)

    assert result is None
    assert not out.exists(), "유효 픽셀 0개면 빈 soil.tif 만들지 않음"


def test_clip_swat_soil_partial_valid_saves(tmp_path) -> None:
    """일부 픽셀만 유효해도 저장 (Cook Islands처럼 전부 0이 아닌 한)."""
    width, height = 20, 20
    bbox = (-10.0, -10.0, 10.0, 10.0)
    xmin, ymin, xmax, ymax = bbox
    transform = Affine.translation(xmin, ymax) * Affine.scale(
        (xmax - xmin) / width, -(ymax - ymin) / height
    )
    arr = np.zeros((height, width), dtype="uint16")
    arr[10:12, 10:12] = 5   # 4 픽셀만 유효
    src = tmp_path / "soil_global.tif"
    with rasterio.open(
        src, "w", driver="GTiff",
        width=width, height=height, count=1,
        dtype="uint16", crs="EPSG:4326", transform=transform, nodata=0,
    ) as dst:
        dst.write(arr, 1)

    poly = _make_polygon_shp(tmp_path / "poly.shp", bbox=bbox)
    out = tmp_path / "soil.tif"
    result = _clip_swat_soil_to_boundary(src, out, poly, buffer_deg=0.0)

    assert result == out
    assert out.is_file()


def test_download_swat_soil_with_boundary_no_data(tmp_path) -> None:
    """전체 워크플로우: boundary 안 자료 없으면 soil.tif 저장 안 됨, 나머지는 정상."""
    local = tmp_path / "swat_gisdb"
    _make_fake_local_swat(local)
    # 합성 soil_global.tif 를 모두 nodata 로 덮어쓰기
    _make_soil_global(local / "soil_global.tif", fill_value=0)

    poly = _make_polygon_shp(tmp_path / "poly.shp",
                             bbox=(0.0, 0.0, 1.0, 1.0))

    gis_root = tmp_path / "gis"
    saved = download_swat_soil(
        gis_root=gis_root, source="local", local_dir=local,
        boundary_path=poly, buffer_deg=0.0,
    )

    # canonical soil.tif 는 없어야 함
    assert "soil" not in saved
    assert not (gis_root / "soil" / "soil.tif").is_file()
    # 그러나 mdb + lookup CSV + download/ 는 있어야 함
    assert (gis_root / "soil" / "SWAT2009-Global-V1.0.mdb").is_file()
    assert (gis_root / "soil" / "soil_lookup.csv").is_file()
    assert (gis_root / "soil" / "download" / "soil_global.tif").is_file()
