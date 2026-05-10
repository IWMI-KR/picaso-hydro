"""gsod.py — ISO2→FIPS 매핑, 경계 CSV 파싱, 관측소 필터 검증."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from util_py.gsod import (
    ISO2_TO_FIPS,
    _filter_stations,
    _iso2_to_fips,
    _read_boundary,
    write_station_shapefile,
)

# geopandas/shapely 가 없으면 shapefile 테스트 스킵
geopandas = pytest.importorskip("geopandas", reason="geopandas required")


# ── ISO2 → FIPS 매핑 ─────────────────────────────────────────────────────────

def test_iso2_to_fips_known_mappings() -> None:
    assert _iso2_to_fips("CK") == "CW"   # Cook Islands
    assert _iso2_to_fips("KR") == "KS"   # South Korea
    assert _iso2_to_fips("JP") == "JA"   # Japan
    assert _iso2_to_fips("CN") == "CH"   # China


def test_iso2_to_fips_lowercase_input() -> None:
    assert _iso2_to_fips("ck") == "CW"
    assert _iso2_to_fips("kr") == "KS"


def test_iso2_to_fips_unmapped_returns_iso2() -> None:
    """매핑 없는 코드는 ISO2 그대로 (FIPS와 동일한 경우 다수)."""
    assert _iso2_to_fips("FJ") == "FJ"   # Fiji 동일
    assert _iso2_to_fips("XX") == "XX"   # 임의 코드도 그대로
    assert _iso2_to_fips("us") == "US"   # 미국 동일


def test_iso2_to_fips_table_has_pacific_countries() -> None:
    """APCC 사업 관련 태평양 국가 포함 확인."""
    pacific = {"CK", "FJ", "WS", "TO", "VU", "SB", "PG", "FM", "MH", "PW",
               "KI", "TV", "NU", "PF", "NC"}
    assert pacific.issubset(set(ISO2_TO_FIPS.keys()))


# ── boundary CSV 읽기 ────────────────────────────────────────────────────────

def _make_boundary(tmp_path: Path, **overrides) -> Path:
    base = {
        "OBJECTID": 1, "NAME": "Cook Islands",
        "ISO3": "COK", "ISO2": "CK",
        "xmin": -165.86, "ymin": -21.94, "xmax": -157.31, "ymax": -8.94,
    }
    base.update(overrides)
    p = tmp_path / "country_boundary.csv"
    pd.DataFrame([base]).to_csv(p, index=False)
    return p


def test_read_boundary_full(tmp_path) -> None:
    p = _make_boundary(tmp_path)
    info = _read_boundary(str(p))
    assert info["name"] == "Cook Islands"
    assert info["iso2"] == "CK"
    assert info["iso3"] == "COK"
    assert info["bbox"] == (-165.86, -21.94, -157.31, -8.94)


def test_read_boundary_empty_raises(tmp_path) -> None:
    p = tmp_path / "empty.csv"
    pd.DataFrame(columns=["NAME", "ISO2", "xmin", "ymin", "xmax", "ymax"]).to_csv(
        p, index=False)
    with pytest.raises(ValueError, match="비어"):
        _read_boundary(str(p))


def test_read_boundary_missing_columns_raises(tmp_path) -> None:
    p = tmp_path / "bad.csv"
    pd.DataFrame([{"NAME": "X", "ISO2": "XX"}]).to_csv(p, index=False)
    with pytest.raises(ValueError, match="필요한 컬럼"):
        _read_boundary(str(p))


def test_read_boundary_uppercase_iso2(tmp_path) -> None:
    """ISO2가 소문자라도 대문자로 정규화."""
    p = _make_boundary(tmp_path, ISO2="ck")
    info = _read_boundary(str(p))
    assert info["iso2"] == "CK"


# ── 관측소 필터 ──────────────────────────────────────────────────────────────

def _make_isd(*rows) -> pd.DataFrame:
    cols = ["USAF", "WBAN", "STATION NAME", "CTRY", "STATE",
            "LAT", "LON", "ELEV(M)", "BEGIN", "END"]
    return pd.DataFrame(rows, columns=cols)


def test_filter_by_country_only() -> None:
    isd = _make_isd(
        ("066225", "99999", "RAROTONGA", "CW", "",  -21.20, -159.80,  6.7, 19450101, 20251231),
        ("076225", "99999", "PUKAPUKA",  "CW", "",  -10.88, -165.83,  3.0, 19560101, 20251231),
        ("471230", "99999", "SEOUL",     "KS", "",   37.50,  127.00, 30.0, 19500101, 20251231),
    )
    out = _filter_stations(isd, fips="CW", bbox=None)
    assert len(out) == 2
    assert set(out["STATION_ID"]) == {"06622599999", "07622599999"}


def test_filter_with_bbox_excludes_outside() -> None:
    """Cook Islands 영역 안의 두 점 + 영역 밖 한 점."""
    isd = _make_isd(
        ("066225", "99999", "RAROTONGA",       "CW", "", -21.20, -159.80, 6.7, 0, 0),
        ("076225", "99999", "PUKAPUKA",        "CW", "", -10.88, -165.83, 3.0, 0, 0),
        ("099999", "99999", "FAR_FROM_REGION", "CW", "",  10.00,    0.00, 0.0, 0, 0),
    )
    bbox = (-165.86, -21.94, -157.31, -8.94)  # Cook Islands
    out = _filter_stations(isd, fips="CW", bbox=bbox)
    ids = set(out["STATION_ID"])
    assert "06622599999" in ids
    assert "07622599999" in ids
    assert "09999999999" not in ids


def test_filter_no_match_returns_empty() -> None:
    isd = _make_isd(
        ("066225", "99999", "RAROTONGA", "CW", "", -21.20, -159.80, 6.7, 0, 0),
    )
    out = _filter_stations(isd, fips="ZZ", bbox=None)
    assert out.empty


def test_filter_pads_usaf_wban_with_zeros() -> None:
    """USAF 6자리, WBAN 5자리 zfill 검증."""
    isd = _make_isd(
        ("66225", "99999", "RAROTONGA", "CW", "", -21.20, -159.80, 6.7, 0, 0),
    )
    out = _filter_stations(isd, fips="CW", bbox=None)
    assert out.iloc[0]["USAF"] == "066225"
    assert out.iloc[0]["WBAN"] == "99999"
    assert out.iloc[0]["STATION_ID"] == "06622599999"


def test_filter_handles_string_lat_lon() -> None:
    """LAT/LON 이 문자열로 들어와도 처리."""
    isd = _make_isd(
        ("066225", "99999", "RAROTONGA", "CW", "", "-21.20", "-159.80", 6.7, 0, 0),
    )
    out = _filter_stations(isd, fips="CW", bbox=(-180, -25, -150, 0))
    assert len(out) == 1


# ── write_station_shapefile ──────────────────────────────────────────────────

def _sample_stations() -> pd.DataFrame:
    return pd.DataFrame([
        {"USAF": "918430", "WBAN": "99999",
         "STATION_ID": "91843099999", "STATION_NAME": "RAROTONGA INTL",
         "CTRY": "CW", "LAT": -21.20, "LON": -159.81, "ELEV_M": 5.79,
         "BEGIN": 19730101, "END": 20250824,
         "n_records": 18757, "first_date": "1973-01-01", "last_date": "2025-08-24"},
        {"USAF": "918300", "WBAN": "99999",
         "STATION_ID": "91830099999", "STATION_NAME": "AITUTAKI",
         "CTRY": "CW", "LAT": -18.83, "LON": -159.76, "ELEV_M": 4.0,
         "BEGIN": 19730101, "END": 20250824,
         "n_records": 12650, "first_date": "1973-01-01", "last_date": "2025-08-24"},
    ])


def test_write_station_shapefile_creates_file(tmp_path) -> None:
    out = tmp_path / "gsod" / "station-gsod.shp"
    df = _sample_stations()

    saved = write_station_shapefile(df, out)
    assert saved == out
    assert out.is_file()
    # 보조 파일들도 생성됨
    assert (out.with_suffix(".dbf")).is_file()
    assert (out.with_suffix(".prj")).is_file()
    assert (out.with_suffix(".shx")).is_file()


def test_write_station_shapefile_round_trip_geometry(tmp_path) -> None:
    """shapefile 읽기 → Point 좌표가 원본 LAT/LON 과 일치."""
    out = tmp_path / "station-gsod.shp"
    df = _sample_stations()
    write_station_shapefile(df, out)

    gdf = geopandas.read_file(out)
    assert len(gdf) == 2
    assert str(gdf.crs).upper() in {"EPSG:4326", "WGS 84"} or gdf.crs.to_epsg() == 4326

    coords = sorted([(round(p.x, 2), round(p.y, 2)) for p in gdf.geometry])
    assert coords == sorted([(-159.81, -21.20), (-159.76, -18.83)])


def test_write_station_shapefile_renames_long_columns(tmp_path) -> None:
    """STATION_NAME (12자) 등은 DBF 10자 제한 회피용으로 rename 됨."""
    out = tmp_path / "station-gsod.shp"
    write_station_shapefile(_sample_stations(), out)

    gdf = geopandas.read_file(out)
    cols = set(gdf.columns)
    assert "STN_ID"   in cols
    assert "STN_NAME" in cols
    assert "N_REC"    in cols
    assert "F_OBS"    in cols
    assert "L_OBS"    in cols
    # 옛 이름은 사라져야 함
    assert "STATION_ID"   not in cols
    assert "STATION_NAME" not in cols


def test_write_station_shapefile_skips_null_lat_lon(tmp_path) -> None:
    out = tmp_path / "station-gsod.shp"
    df = _sample_stations()
    df.loc[1, "LAT"] = None    # AITUTAKI 의 LAT 결측

    write_station_shapefile(df, out)
    gdf = geopandas.read_file(out)
    assert len(gdf) == 1
    assert gdf.iloc[0]["STN_NAME"] == "RAROTONGA INTL"


def test_write_station_shapefile_empty_returns_none(tmp_path) -> None:
    out = tmp_path / "station-gsod.shp"
    df = _sample_stations()
    df["LAT"] = None     # 모두 결측

    result = write_station_shapefile(df, out)
    assert result is None
    assert not out.exists()


def test_write_station_shapefile_requires_lat_lon(tmp_path) -> None:
    out = tmp_path / "station-gsod.shp"
    df = pd.DataFrame([{"USAF": "x", "WBAN": "y"}])  # LAT/LON 없음
    with pytest.raises(ValueError, match="LAT, LON"):
        write_station_shapefile(df, out)


# ── 한국과 쿡아일랜드의 ISO/FIPS 차이 통합 검증 ──────────────────────────────

def test_korea_fips_differs_from_iso2() -> None:
    """ISO2=KR 인 한국 자료 필터링 시 FIPS=KS 사용해야 함."""
    isd = _make_isd(
        ("471230", "99999", "SEOUL",     "KS", "",  37.50, 127.00, 30.0, 0, 0),
        ("471800", "99999", "BUSAN",     "KS", "",  35.10, 129.10,  3.0, 0, 0),
        ("066225", "99999", "RAROTONGA", "CW", "", -21.20, -159.80, 6.7, 0, 0),
    )
    iso2 = "KR"
    fips = _iso2_to_fips(iso2)   # → "KS"
    out = _filter_stations(isd, fips=fips, bbox=None)
    assert set(out["STATION_ID"]) == {"47123099999", "47180099999"}
