"""weather_validation — haversine, 매칭, 통계, 산점도 검증."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from util_py.weather_validation import (
    compute_stats,
    find_nearest_pairs,
    haversine_km,
    plot_scatter_one_to_one,
    scatter_compare_era5_obs,
)


# ── haversine ────────────────────────────────────────────────────────────────

def test_haversine_zero() -> None:
    assert haversine_km(0, 0, 0, 0) == pytest.approx(0.0)


def test_haversine_known_pair() -> None:
    """Seoul ~ Tokyo ≈ 1160 km."""
    d = haversine_km(37.5665, 126.9780, 35.6762, 139.6503)
    assert 1100 < d < 1200


def test_haversine_array() -> None:
    """배열 입력도 동작."""
    lats = np.array([37.5, 35.7])
    lons = np.array([127.0, 139.7])
    d = haversine_km(0, 0, lats, lons)
    assert d.shape == (2,)
    assert (d > 0).all()


# ── 매칭 ─────────────────────────────────────────────────────────────────────

def test_find_nearest_pairs_no_radius() -> None:
    """radius_km=None 면 nearest 1개씩."""
    era5 = pd.DataFrame({
        "ID":  ["E001", "E002"],
        "Lat": [-21.20, -10.0],
        "Lon": [-159.81, -158.0],
    })
    obs = pd.DataFrame({
        "STATION_ID": ["S1", "S2"],
        "LAT": [-21.21, -10.5],
        "LON": [-159.80, -158.1],
    })
    pairs = find_nearest_pairs(era5, obs, radius_km=None)
    assert len(pairs) == 2
    assert pairs.iloc[0]["obs_id"] == "S1"
    assert pairs.iloc[1]["obs_id"] == "S2"


def test_find_nearest_pairs_within_radius_picks_all() -> None:
    """반경 내 station 이 2개 이상이면 모두 채택."""
    era5 = pd.DataFrame({"ID": ["E001"], "Lat": [-21.20], "Lon": [-159.81]})
    obs = pd.DataFrame({
        "STATION_ID": ["S1", "S2", "S3"],
        "LAT": [-21.21, -21.22, -10.0],     # S1, S2 가까움 / S3 멀리
        "LON": [-159.80, -159.83, -158.0],
    })
    pairs = find_nearest_pairs(era5, obs, radius_km=10.0)
    # E001 → S1, S2 두 개 (S3 는 멀어서 제외)
    assert len(pairs) == 2
    assert set(pairs["obs_id"]) == {"S1", "S2"}
    assert pairs["within_radius"].all()
    # 거리 오름차순
    assert pairs.iloc[0]["distance_km"] <= pairs.iloc[1]["distance_km"]


def test_find_nearest_pairs_fallback_to_nearest() -> None:
    """반경 내 station 0 → fallback 으로 nearest 1개."""
    era5 = pd.DataFrame({"ID": ["E001"], "Lat": [-21.20], "Lon": [-159.81]})
    obs = pd.DataFrame({
        "STATION_ID": ["S1"],
        "LAT": [-15.0], "LON": [-150.0],   # 약 1000 km 멀리
    })
    pairs = find_nearest_pairs(era5, obs, radius_km=10.0)
    assert len(pairs) == 1
    assert pairs.iloc[0]["obs_id"] == "S1"
    assert not pairs.iloc[0]["within_radius"]
    assert pairs.iloc[0]["distance_km"] > 100


# ── 통계 ─────────────────────────────────────────────────────────────────────

def test_compute_stats_perfect_match() -> None:
    """y == x 인 경우 R²=1, RMSE=0, bias=0."""
    x = pd.Series(np.arange(10, dtype=float))
    y = pd.Series(np.arange(10, dtype=float))
    s = compute_stats(x, y)
    assert s["r2"]   == pytest.approx(1.0)
    assert s["rmse"] == pytest.approx(0.0)
    assert s["mae"]  == pytest.approx(0.0)
    assert s["bias"] == pytest.approx(0.0)
    assert s["slope"]     == pytest.approx(1.0)
    assert s["intercept"] == pytest.approx(0.0)
    assert s["n"] == 10


def test_compute_stats_constant_offset() -> None:
    """y = x + 2 → R²=1, RMSE=2, bias=+2."""
    x = pd.Series(np.arange(10, dtype=float))
    y = x + 2.0
    s = compute_stats(x, y)
    assert s["r2"]   == pytest.approx(1.0)
    assert s["rmse"] == pytest.approx(2.0, abs=0.01)
    assert s["bias"] == pytest.approx(2.0, abs=0.01)


def test_compute_stats_drops_nan() -> None:
    """NaN 행은 통계에서 제외."""
    x = pd.Series([1.0, 2.0, np.nan, 4.0])
    y = pd.Series([1.0, np.nan, 3.0, 4.0])
    s = compute_stats(x, y)
    assert s["n"] == 2   # (1,1), (4,4) 만 유효


def test_compute_stats_too_few_returns_nan() -> None:
    """N<2 면 통계 NaN."""
    s = compute_stats(pd.Series([1.0]), pd.Series([1.0]))
    assert s["n"] == 1
    assert pd.isna(s["r2"])


# ── 산점도 ───────────────────────────────────────────────────────────────────

def test_plot_scatter_creates_png(tmp_path) -> None:
    np.random.seed(0)
    x = pd.Series(np.random.normal(20, 5, 100))
    y = x + np.random.normal(0, 1, 100)
    out = tmp_path / "scatter.png"
    plot_scatter_one_to_one(x, y, "ERA5 (mm)", "Obs (mm)", out, title="test")
    assert out.is_file()
    assert out.stat().st_size > 5000   # PNG 가 의미있게 생성


def test_plot_scatter_handles_empty(tmp_path) -> None:
    """모두 NaN 이어도 에러 없이 저장."""
    x = pd.Series([np.nan, np.nan])
    y = pd.Series([np.nan, np.nan])
    out = tmp_path / "empty.png"
    plot_scatter_one_to_one(x, y, "x", "y", out)
    assert out.is_file()


# ── 통합 워크플로우 ─────────────────────────────────────────────────────────

def _make_std(path: Path, dates, **vars) -> Path:
    df = pd.DataFrame({"date": dates, **vars})
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def test_scatter_compare_era5_obs_full_workflow(tmp_path) -> None:
    """E2E: 메타 + std → pairs/stats/plots 모두 생성."""
    # ERA5 격자점 메타
    era5_pts = tmp_path / "era5_pts.csv"
    pd.DataFrame({
        "ID": ["ERA001"], "Lat": [-21.20], "Lon": [-159.81],
    }).to_csv(era5_pts, index=False)

    # Obs station 메타
    obs_pts = tmp_path / "obs_pts.csv"
    pd.DataFrame({
        "STATION_ID": ["91843099999"],
        "LAT": [-21.20], "LON": [-159.80],
    }).to_csv(obs_pts, index=False)

    # std daily 합성
    np.random.seed(0)
    dates = pd.date_range("2020-01-01", periods=30)
    era_dir = tmp_path / "era5_std"
    obs_dir = tmp_path / "obs_std"
    pcp = np.random.exponential(2.0, 30)
    tmax = 28.0 + np.random.normal(0, 2, 30)
    _make_std(era_dir / "ERA001.csv", dates,
              pcp_mm=pcp, tmax_c=tmax, tmin_c=tmax - 5,
              tavg_c=tmax - 2, tdew_c=tmax - 7, hmd_pct=70.0,
              ws10_ms=4.0, source="ERA5")
    # GSOD 자료에 약간의 noise + 일부 NaN
    obs_pcp = pcp + np.random.normal(0, 0.3, 30)
    obs_pcp[5] = np.nan
    obs_tmax = tmax + np.random.normal(0, 0.5, 30)
    _make_std(obs_dir / "91843099999.csv", dates,
              pcp_mm=obs_pcp, tmax_c=obs_tmax, tmin_c=obs_tmax - 5,
              tavg_c=obs_tmax - 2, tdew_c=obs_tmax - 7, hmd_pct=72.0,
              ws10_ms=3.5, source="GSOD")

    out = tmp_path / "out"
    result = scatter_compare_era5_obs(
        era5_grid_points_csv=era5_pts,
        era5_std_dir=era_dir,
        obs_station_csv=obs_pts,
        obs_std_dir=obs_dir,
        output_dir=out,
        variables=["pcp_mm", "tmax_c"],
        obs_source="GSOD",
    )

    assert (out / "nearest_pairs.csv").is_file()
    assert (out / "statistics.csv").is_file()
    assert (out / "plots" / "pcp_mm" / "ERA001__91843099999.png").is_file()
    assert (out / "plots" / "tmax_c" / "ERA001__91843099999.png").is_file()
    # combined plot (pair 별 다변수 통합)
    assert (out / "plots" / "combined" / "ERA001__91843099999.png").is_file()

    stats = pd.read_csv(out / "statistics.csv")
    assert len(stats) == 2  # 2 변수 × 1 pair
    pcp_row = stats[stats["variable"] == "pcp_mm"].iloc[0]
    assert pcp_row["n"] == 29   # 1 NaN 제외


def test_combined_plot_skip_when_disabled(tmp_path) -> None:
    """write_combined=False → combined PNG 안 만듦."""
    era5_pts = tmp_path / "era5_pts.csv"
    pd.DataFrame({"ID": ["ERA001"], "Lat": [0.0], "Lon": [0.0]}).to_csv(era5_pts, index=False)
    obs_pts = tmp_path / "obs_pts.csv"
    pd.DataFrame({"STATION_ID": ["S1"], "LAT": [0.0], "LON": [0.0]}).to_csv(obs_pts, index=False)

    dates = pd.date_range("2020-01-01", periods=10)
    (tmp_path / "era5_std").mkdir()
    (tmp_path / "obs_std").mkdir()
    pd.DataFrame({"date": dates, "tmax_c": np.arange(10.0)}).to_csv(
        tmp_path / "era5_std" / "ERA001.csv", index=False)
    pd.DataFrame({"date": dates, "tmax_c": np.arange(10.0) + 1}).to_csv(
        tmp_path / "obs_std" / "S1.csv", index=False)

    out = tmp_path / "out"
    scatter_compare_era5_obs(
        era5_grid_points_csv=era5_pts, era5_std_dir=tmp_path / "era5_std",
        obs_station_csv=obs_pts, obs_std_dir=tmp_path / "obs_std",
        output_dir=out, variables=["tmax_c"], obs_source="GSOD",
        write_combined=False, write_per_variable=True,
    )
    assert (out / "plots" / "tmax_c" / "ERA001__S1.png").is_file()
    assert not (out / "plots" / "combined").exists()
