"""io.load_obs_csv — util_py 표준 daily 포맷 처리 검증."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from acidwg_py.io import acid_data_loading, load_obs_csv


# ── 표준 포맷 fixture ────────────────────────────────────────────────────────

def _write_std_obs(path: Path, *, dates, pcp, tmax, tmin,
                   tavg=None, source: str = "GSOD") -> Path:
    """util_py 표준 daily 포맷 CSV 생성."""
    n = len(dates)
    data = {
        "date":    [d if isinstance(d, str) else d.strftime("%Y-%m-%d") for d in dates],
        "pcp_mm":  pcp,
        "tmax_c":  tmax,
        "tmin_c":  tmin,
        "tavg_c":  tavg if tavg is not None else (np.array(tmax) + np.array(tmin)) / 2,
        "tdew_c":  [np.nan] * n,
        "hmd_pct": [70.0] * n,
        "slr_mjm2":[np.nan] * n,
        "ws10_ms": [3.0] * n,
        "ws2_ms":  [2.2] * n,
        "source":  [source] * n,
    }
    pd.DataFrame(data).to_csv(path, index=False)
    return path


# ── load_obs_csv ────────────────────────────────────────────────────────────

def test_load_obs_csv_parses_standard_format(tmp_path) -> None:
    """date 컬럼 → Year/Month/Day 분해, pcp_mm/tmax_c/tmin_c → prec/tmax/tmin."""
    dates = pd.date_range("2000-01-01", periods=5)
    p = _write_std_obs(tmp_path / "ST001.csv",
                       dates=dates, pcp=[0.0, 1.5, 0.2, 0.0, 5.3],
                       tmax=[28.0, 29.0, 27.5, 28.5, 26.0],
                       tmin=[22.0, 23.0, 21.0, 22.5, 20.0])
    df = load_obs_csv(str(p), syear=2000, eyear=2000)

    assert {"Year", "Month", "Day", "prec", "tmax", "tmin", "tavg"} <= set(df.columns)
    assert len(df) == 5
    assert df["Year"].iloc[0]  == 2000
    assert df["Month"].iloc[0] == 1
    assert df["Day"].iloc[0]   == 1
    assert df["prec"].iloc[1]  == pytest.approx(1.5)
    assert df["tmax"].iloc[2]  == pytest.approx(27.5)
    assert df["tmin"].iloc[3]  == pytest.approx(22.5)


def test_load_obs_csv_year_filter(tmp_path) -> None:
    """syear/eyear 기간 필터링."""
    dates = pd.date_range("1999-12-25", periods=10)   # 1999-12-25 ~ 2000-01-03
    p = _write_std_obs(tmp_path / "ST001.csv", dates=dates,
                       pcp=[0.0]*10, tmax=[28.0]*10, tmin=[22.0]*10)
    df = load_obs_csv(str(p), syear=2000, eyear=2000)
    assert (df["Year"] == 2000).all()
    assert len(df) == 3   # 1/1, 1/2, 1/3


def test_load_obs_csv_missing_date_raises(tmp_path) -> None:
    """date 컬럼 없으면 표준 포맷 위반 — 명확한 에러."""
    p = tmp_path / "bad.csv"
    pd.DataFrame({"Year": [2000], "Mon": [1], "Day": [1],
                  "prec": [0.0], "tmax": [28.0], "tmin": [22.0]}
                 ).to_csv(p, index=False)
    with pytest.raises(ValueError, match="'date' 컬럼 없음"):
        load_obs_csv(str(p), syear=2000, eyear=2000)


def test_load_obs_csv_unparseable_date_raises(tmp_path) -> None:
    """date 가 YYYY-MM-DD 가 아닌 문자열이면 명확한 에러."""
    p = tmp_path / "bad.csv"
    pd.DataFrame({"date": ["20000101", "not-a-date"],
                  "pcp_mm": [0.0, 1.5],
                  "tmax_c": [28.0, 29.0],
                  "tmin_c": [22.0, 23.0]}
                 ).to_csv(p, index=False)
    with pytest.raises(ValueError, match="date 컬럼 파싱 실패"):
        load_obs_csv(str(p), syear=2000, eyear=2000)


def test_load_obs_csv_missing_required_column_raises(tmp_path) -> None:
    """pcp_mm 또는 tmax_c/tmin_c 누락 시 명확한 에러."""
    p = tmp_path / "bad.csv"
    pd.DataFrame({"date": ["2000-01-01"], "pcp_mm": [0.0]}
                 ).to_csv(p, index=False)
    with pytest.raises(ValueError, match="필수 컬럼 누락"):
        load_obs_csv(str(p), syear=2000, eyear=2000)


def test_load_obs_csv_extra_columns_preserved(tmp_path) -> None:
    """tdew_c, hmd_pct, ws10_ms 등 표준 부가 컬럼은 그대로 유지."""
    dates = pd.date_range("2000-01-01", periods=3)
    p = _write_std_obs(tmp_path / "ST001.csv", dates=dates,
                       pcp=[0.0]*3, tmax=[28.0]*3, tmin=[22.0]*3)
    df = load_obs_csv(str(p), syear=2000, eyear=2000)
    assert "hmd_pct" in df.columns
    assert "ws10_ms" in df.columns
    assert "source"  in df.columns


# ── acid_data_loading 통합 ──────────────────────────────────────────────────

def test_acid_data_loading_with_standard_format(tmp_path) -> None:
    """station_csv + 표준 포맷 obs CSV 두 개 → 통합 테이블 정상 생성."""
    # 관측소 메타 (Lon, Lat, ID, Ename 필수)
    station_csv = tmp_path / "stations.csv"
    pd.DataFrame({
        "Lon":   [-159.81, -159.76],
        "Lat":   [-21.20, -18.83],
        "Elev":  [5, 4],
        "ID":    ["ST001", "ST002"],
        "Ename": ["Rarotonga", "Aitutaki"],
        "SYear": [2000, 2000],
    }).to_csv(station_csv, index=False)

    obs_dir = tmp_path / "obs"
    obs_dir.mkdir()
    dates = pd.date_range("2000-01-01", periods=10)
    _write_std_obs(obs_dir / "ST001.csv", dates=dates,
                   pcp=[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
                   tmax=[28.0]*10, tmin=[22.0]*10)
    _write_std_obs(obs_dir / "ST002.csv", dates=dates,
                   pcp=[0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5],
                   tmax=[27.0]*10, tmin=[21.0]*10)

    out = acid_data_loading(str(station_csv), str(obs_dir),
                             syear_obs=2000, eyear_obs=2000)

    assert out["d"] == 2
    assert out["site_names"] == ["Rarotonga", "Aitutaki"]
    assert out["prcp_table"].shape == (10, 5)   # Year/Month/Day + 2 stations
    # 첫 행 1월 1일 확인 (인덱스 0,1,2 = Year, Month, Day)
    assert out["prcp_table"][0, 0] == 2000
    assert out["prcp_table"][0, 1] == 1
    assert out["prcp_table"][0, 2] == 1
    # 관측소 1 첫날 prec
    assert out["prcp_table"][0, 3] == pytest.approx(0.0)
    # 관측소 2 첫날 prec
    assert out["prcp_table"][0, 4] == pytest.approx(0.5)
