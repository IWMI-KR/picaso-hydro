"""gis_download.download_swat_soil — 국가별 (한국/글로벌) 분기 + lookup 변환 검증."""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from util_py.gis_download import (
    _convert_lookup_txt_to_csv,
    _is_korea,
    _swat_soil_sources,
    download_swat_soil,
)


# ── lookup TXT → CSV 변환 ────────────────────────────────────────────────────

def _make_lookup_txt(path: Path) -> Path:
    """Soil_global_lookup.txt 와 동일한 형식 (Value,NAME)."""
    rows = "Value,NAME\n0,0\n1,1\n11,11\n6997,WATER\n"
    path.write_text(rows, encoding="utf-8")
    return path


def _make_lookup_csv_korea(path: Path) -> Path:
    """soil_korea_lookup.csv 와 동일한 형식 (val,SWAT_MUID — 이미 표준)."""
    rows = "val,SWAT_MUID\n1,KOR001\n2,KOR002\n3,KOR003\n"
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


def test_convert_lookup_passes_through_korea_csv(tmp_path) -> None:
    """한국 lookup CSV (이미 val,SWAT_MUID) 는 그대로 통과."""
    src = _make_lookup_csv_korea(tmp_path / "soil_korea_lookup.csv")
    dst = tmp_path / "out.csv"
    _convert_lookup_txt_to_csv(src, dst)
    df = pd.read_csv(dst)
    assert list(df.columns) == ["val", "SWAT_MUID"]
    assert (df["val"] == 2).any()
    assert "KOR002" in df["SWAT_MUID"].astype(str).values


# ── ISO3 → 국가별 URL 셋 분기 ───────────────────────────────────────────────

def test_is_korea_detects_kor_iso3() -> None:
    assert _is_korea("KOR") is True
    assert _is_korea("kor") is True
    assert _is_korea(" Kor ") is True
    assert _is_korea("KR") is False     # ISO2 는 _is_korea 대상이 아님
    assert _is_korea("COK") is False
    assert _is_korea(None) is False
    assert _is_korea("") is False


_BASE = "http://example.invalid/swat_py/"


def test_swat_soil_sources_korea_branch() -> None:
    urls, filenames, label = _swat_soil_sources("KOR", _BASE)
    assert label == "Korea-RDA"
    assert urls["tif"].endswith("soil_korea.tif")
    assert urls["mdb"].endswith("QSWAT-Korea-RDA%20Soil.mdb")
    assert urls["sqlite"].endswith("QSWATPlus-Korea-RDA%20Soil.sqlite")
    assert urls["lookup"].endswith("soil_korea_lookup.csv")
    assert filenames["tif"] == "soil_korea.tif"
    assert filenames["mdb"] == "QSWAT-Korea-RDA Soil.mdb"
    assert filenames["sqlite"] == "QSWATPlus-Korea-RDA Soil.sqlite"
    assert filenames["lookup"] == "soil_korea_lookup.csv"


def test_swat_soil_sources_global_branch() -> None:
    urls, filenames, label = _swat_soil_sources("COK", _BASE)
    assert label == "Global-FAO"
    assert urls["tif"].endswith("soil_global.tif")
    assert urls["mdb"].endswith("QSWAT-Global-FAO%20Soil.mdb")
    assert urls["sqlite"].endswith("QSWATPlus-Global-FAO%20Soil.sqlite")
    assert urls["lookup"].endswith("Soil_global_lookup.txt")
    assert filenames["mdb"] == "QSWAT-Global-FAO Soil.mdb"
    assert filenames["sqlite"] == "QSWATPlus-Global-FAO Soil.sqlite"


def test_swat_soil_sources_defaults_to_global_when_none() -> None:
    urls, _, label = _swat_soil_sources(None, _BASE)
    assert label == "Global-FAO"
    assert urls["tif"].endswith("soil_global.tif")


# ── download_swat_soil (mock local + URL via file:// redirect) ───────────────

def _make_fake_local_swat(local_dir: Path) -> None:
    """sidecar (aux/rrd) 와 HWSD 디스트랙터만 생성한 합성 SWAT GISDB.

    핵심 4종 (tif/mdb/sqlite/lookup) 은 _setup_fake_sources 에서 만들고
    URL 도 그쪽으로 redirect 함.
    """
    local_dir.mkdir(parents=True, exist_ok=True)
    # HWSD 옵션 (절대 다운로드 되면 안 되는 디스트랙터)
    (local_dir / "hwsd.bil").write_bytes(b"BIL")
    (local_dir / "hwsd.hdr").write_text("BYTEORDER I\n", encoding="utf-8")
    (local_dir / "download" / "HWSD").mkdir(parents=True, exist_ok=True)
    (local_dir / "download" / "HWSD" / "HWSD.mdb").write_bytes(b"H")


def _setup_fake_sources(
    fake_root: Path, *,
    is_korea: bool = False,
    tif_bytes: bytes = b"FAKE_TIF" * 1000,
) -> str:
    """핵심 4종 fake 파일을 만들고 그 폴더의 ``file://`` base_url 을 돌려준다.

    URL 은 ``base_url + 파일명`` 으로 조립되므로, 폴더 하나만 준비하면
    실제 다운로드 경로를 그대로 태울 수 있다(별도 monkeypatch 불필요).
    """
    from util_py import gis_download as gd

    fake_root.mkdir(parents=True, exist_ok=True)

    if is_korea:
        filenames = gd._SWAT_SOIL_FILENAMES_KOREA
        lookup_content = "val,SWAT_MUID\n1,KOR001\n2,KOR002\n"
    else:
        filenames = gd._SWAT_SOIL_FILENAMES_GLOBAL
        lookup_content = "Value,NAME\n0,0\n1,1\n2,2\n"

    paths = {k: fake_root / filenames[k] for k in ("tif", "mdb", "sqlite", "lookup")}
    paths["tif"].write_bytes(tif_bytes)
    paths["mdb"].write_bytes(b"FAKE_MDB" * 5000)
    paths["sqlite"].write_bytes(b"FAKE_SQLITE" * 3000)
    paths["lookup"].write_text(lookup_content, encoding="utf-8")

    return fake_root.as_uri() + "/"


def test_download_swat_soil_global_no_boundary(tmp_path) -> None:
    """글로벌 + boundary 없으면 raster 를 그대로 canonical 로 복사 + 4종 모두 저장."""
    base = _setup_fake_sources(tmp_path / "url_src", is_korea=False)
    gis_root = tmp_path / "gis"

    saved = download_swat_soil(
        gis_root=gis_root, base_url=base,
        boundary_path=None, bbox=None, iso3="COK",
    )

    out_dir = gis_root / "soil"
    # canonical
    assert (out_dir / "soil.tif").is_file()
    assert (out_dir / "QSWAT-Global-FAO Soil.mdb").is_file()
    assert (out_dir / "QSWATPlus-Global-FAO Soil.sqlite").is_file()
    assert (out_dir / "soil_lookup.csv").is_file()
    # 원본 4종은 download/
    assert (out_dir / "download" / "soil_global.tif").is_file()
    assert (out_dir / "download" / "QSWAT-Global-FAO Soil.mdb").is_file()
    assert (out_dir / "download" / "QSWATPlus-Global-FAO Soil.sqlite").is_file()
    assert (out_dir / "download" / "Soil_global_lookup.txt").is_file()
    # HWSD 관련은 절대 다운로드 안 됨
    assert not (out_dir / "download" / "hwsd.bil").exists()
    assert not (out_dir / "download" / "HWSD.mdb").exists()

    df = pd.read_csv(out_dir / "soil_lookup.csv")
    assert list(df.columns) == ["val", "SWAT_MUID"]
    # saved dict 키
    assert "mdb" in saved
    assert "sqlite" in saved
    assert "lookup" in saved


def test_download_swat_soil_korea_branch(tmp_path) -> None:
    """ISO3='KOR' 이면 한국 RDA URL 셋 사용 + 한국 파일명 저장."""
    base = _setup_fake_sources(tmp_path / "url_src", is_korea=True)
    gis_root = tmp_path / "gis"

    saved = download_swat_soil(
        gis_root=gis_root, base_url=base,
        boundary_path=None, iso3="KOR",
    )

    out_dir = gis_root / "soil"
    # 한국 파일명으로 download/
    assert (out_dir / "download" / "soil_korea.tif").is_file()
    assert (out_dir / "download" / "QSWAT-Korea-RDA Soil.mdb").is_file()
    assert (out_dir / "download" / "QSWATPlus-Korea-RDA Soil.sqlite").is_file()
    assert (out_dir / "download" / "soil_korea_lookup.csv").is_file()
    # 글로벌 파일명은 다운로드되면 안 됨
    assert not (out_dir / "download" / "soil_global.tif").exists()
    assert not (out_dir / "download" / "QSWAT-Global-FAO Soil.mdb").exists()
    # canonical 도 한국 파일명
    assert (out_dir / "soil.tif").is_file()
    assert (out_dir / "QSWAT-Korea-RDA Soil.mdb").is_file()
    assert (out_dir / "QSWATPlus-Korea-RDA Soil.sqlite").is_file()
    assert (out_dir / "soil_lookup.csv").is_file()


def test_download_swat_soil_excludes_hwsd(tmp_path) -> None:
    """HWSD 파일이 local_dir 에 있어도 다운로드되지 않음 (SWAT DB 와 무관)."""
    base = _setup_fake_sources(tmp_path / "url_src", is_korea=False)
    _make_fake_local_swat(tmp_path / "swat_gisdb")   # 디스트랙터(무시되어야 함)
    gis_root = tmp_path / "gis"

    download_swat_soil(
        gis_root=gis_root, base_url=base,
        boundary_path=None, iso3="COK",
    )

    download_dir = gis_root / "soil" / "download"
    expected = {"soil_global.tif", "Soil_global_lookup.txt",
                "QSWAT-Global-FAO Soil.mdb",
                "QSWATPlus-Global-FAO Soil.sqlite"}
    actual = {p.name for p in download_dir.iterdir() if p.is_file()}
    assert "hwsd.bil"  not in actual
    assert "hwsd.hdr"  not in actual
    assert "HWSD.mdb"  not in actual
    assert expected.issubset(actual)


def test_download_swat_soil_url_failure_raises(tmp_path) -> None:
    """base_url 하위에 파일이 없으면 RuntimeError(URL 다운로드 실패)."""
    empty = tmp_path / "empty_src"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="URL 다운로드 실패"):
        download_swat_soil(gis_root=tmp_path / "gis",
                           base_url=empty.as_uri() + "/", iso3="COK")


def test_download_swat_soil_downloads_core_four(tmp_path) -> None:
    """핵심 4종을 base_url 에서만 받아 동작 (로컬 공유드라이브 불필요)."""
    base = _setup_fake_sources(tmp_path / "url_src", is_korea=False)
    gis_root = tmp_path / "gis"

    download_swat_soil(
        gis_root=gis_root, base_url=base,
        boundary_path=None, iso3=None,
    )

    assert (gis_root / "soil" / "soil.tif").is_file()
    assert (gis_root / "soil" / "QSWAT-Global-FAO Soil.mdb").is_file()
    assert (gis_root / "soil" / "QSWATPlus-Global-FAO Soil.sqlite").is_file()
    assert (gis_root / "soil" / "soil_lookup.csv").is_file()


def test_download_swat_soil_requires_base_url(tmp_path) -> None:
    """base_url 미지정이면 설정을 지정하라는 ValueError."""
    with pytest.raises(ValueError, match="base_url"):
        download_swat_soil(gis_root=tmp_path / "gis", base_url="")


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
    arr[10:12, 10:12] = 5
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
    fake_url_dir = tmp_path / "url_src"
    fake_url_dir.mkdir()
    nodata_tif = fake_url_dir / "soil_global.tif"
    _make_soil_global(nodata_tif, fill_value=0)

    (fake_url_dir / "Soil_global_lookup.txt").write_text(
        "Value,NAME\n0,0\n1,1\n", encoding="utf-8")
    (fake_url_dir / "QSWAT-Global-FAO Soil.mdb").write_bytes(b"FAKE_MDB" * 1000)
    (fake_url_dir / "QSWATPlus-Global-FAO Soil.sqlite").write_bytes(b"FAKE_SQL" * 1000)
    poly = _make_polygon_shp(tmp_path / "poly.shp",
                             bbox=(0.0, 0.0, 1.0, 1.0))

    gis_root = tmp_path / "gis"
    saved = download_swat_soil(
        gis_root=gis_root, base_url=fake_url_dir.as_uri() + "/",
        boundary_path=poly, buffer_deg=0.0, iso3="COK",
    )

    assert "soil" not in saved
    assert not (gis_root / "soil" / "soil.tif").is_file()
    assert (gis_root / "soil" / "QSWAT-Global-FAO Soil.mdb").is_file()
    assert (gis_root / "soil" / "QSWATPlus-Global-FAO Soil.sqlite").is_file()
    assert (gis_root / "soil" / "soil_lookup.csv").is_file()
    assert (gis_root / "soil" / "download" / "soil_global.tif").is_file()
