"""Dashboard 자료 생성 — aggregate / json_writers / stitch / build 단위 + 통합."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swat_py.dashboard import (
    aggregate_ensemble_monthly,
    compute_terciles,
    stitch_weather_files,
    write_forecast_json,
    write_timeseries_json,
)
from swat_py.dashboard.aggregate import historical_monthly_mean


# ── 멤버 집계 ─────────────────────────────────────────────────────────────

def _make_ensemble_df(n_days=90, n_members=10, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n_days)
    data = {}
    for i in range(n_members):
        data[f"member_{i+1:04d}"] = 1.0 + 0.5 * rng.random(n_days)
    return pd.DataFrame(data, index=dates)


def test_aggregate_monthly_columns() -> None:
    df = _make_ensemble_df(90, 10)
    monthly = aggregate_ensemble_monthly(df)
    assert {"date", "mean", "p5", "p25", "p50", "p75", "p95"} <= set(monthly.columns)
    assert len(monthly) == 3   # JFM 3개월


def test_aggregate_monotone_quantiles() -> None:
    """p5 ≤ p25 ≤ p50 ≤ p75 ≤ p95."""
    df = _make_ensemble_df(60, 50)
    m = aggregate_ensemble_monthly(df)
    for _, r in m.iterrows():
        assert r["p5"] <= r["p25"] <= r["p50"] <= r["p75"] <= r["p95"]


# ── tercile ─────────────────────────────────────────────────────────────────

def test_tercile_balanced() -> None:
    """uniform 분포 → ~33% 균등."""
    rng = np.random.default_rng(0)
    vals = rng.uniform(0, 1, 1000)
    t = compute_terciles(vals, 0.33, 0.67)
    assert 28 < t["below"]  < 38
    assert 28 < t["normal"] < 38
    assert 28 < t["above"]  < 38
    assert abs(t["below"] + t["normal"] + t["above"] - 100.0) < 0.1


def test_tercile_all_above() -> None:
    """모든 값이 p67 보다 큼 → above 100%."""
    t = compute_terciles([10, 11, 12, 13, 14], 1.0, 5.0)
    assert t["above"] == 100.0
    assert t["below"] == 0.0


# ── historical monthly mean ────────────────────────────────────────────────

def test_historical_monthly_12_rows() -> None:
    dates = pd.date_range("2010-01-01", periods=365 * 3)
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "date":     dates,
        "flow_m3s": 1.0 + 0.5 * np.sin(2 * np.pi * np.arange(len(dates)) / 365)
                    + rng.normal(0, 0.1, len(dates)),
    })
    out = historical_monthly_mean(df, "flow_m3s")
    assert len(out) == 12
    assert out["month"].tolist() == list(range(1, 13))


# ── JSON writers ────────────────────────────────────────────────────────────

def test_write_forecast_json(tmp_path) -> None:
    p = write_forecast_json(
        tmp_path / "forecast.json",
        streamflow_terciles={"below": 30, "normal": 40, "above": 30},
    )
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["streamflow_forecast"][0]["below"] == 30


def test_write_timeseries_json(tmp_path) -> None:
    hist = pd.DataFrame({"month": [1, 2, 3], "mean": [1.0, 1.2, 0.9],
                         "p33": [0.8, 1.0, 0.7], "p67": [1.3, 1.4, 1.1]})
    obs = pd.DataFrame({"date": ["2024-11-01", "2024-12-01"],
                        "value": [1.1, 1.3]})
    fc = pd.DataFrame({
        "date": ["2025-01-01", "2025-02-01", "2025-03-01"],
        "mean": [1.4, 1.5, 1.3], "p5": [0.9, 1.0, 0.8],
        "p25": [1.1, 1.2, 1.0], "p50": [1.4, 1.5, 1.3],
        "p75": [1.7, 1.8, 1.6], "p95": [2.0, 2.1, 1.9],
    })
    p = write_timeseries_json(tmp_path / "timeseries.json",
                                hist_monthly=hist, obs_monthly=obs,
                                forecast_monthly=fc,
                                thresholds={"watch_warning": 1.8,
                                             "warning_crisis": 2.5})
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "data" in data and "thresholds" in data
    # obs 2개 + fc 3개 = 5 month
    assert len(data["data"]) == 5
    # 첫 점 (obs 시작): hist + obs 있고 fc 없음
    assert data["data"][0]["obs"] == 1.1
    assert data["data"][0]["fc"] is None
    # 셋째 점 (forecast 시작): fc + 분위수 있음
    fc_rec = next(r for r in data["data"] if r["fc"] is not None)
    assert "p5" in fc_rec and fc_rec["p25"] is not None


# ── stitch ────────────────────────────────────────────────────────────────

def test_stitch_weather(tmp_path) -> None:
    """ERA5 [2024-10-01 ~ 2024-12-31] + ensemble [2025-01-01 ~ 2025-03-31] 결합."""
    warm = tmp_path / "warm"; warm.mkdir()
    ens  = tmp_path / "ens";  ens.mkdir()
    out  = tmp_path / "out"
    sid  = "918430"

    # ERA5 자료 (90+91+92 = 273 일자)
    era5_dates = pd.date_range("2024-10-01", "2024-12-31")
    pd.DataFrame({
        "date":   era5_dates.strftime("%Y-%m-%d"),
        "pcp_mm": np.full(len(era5_dates), 2.0),
        "tmax_c": np.full(len(era5_dates), 27.0),
        "tmin_c": np.full(len(era5_dates), 22.0),
    }).to_csv(warm / f"{sid}.csv", index=False)

    # acidwg 멤버 자료 (90 일자)
    ens_dates = pd.date_range("2025-01-01", "2025-03-31")
    pd.DataFrame({
        "year": ens_dates.year, "mon": ens_dates.month, "day": ens_dates.day,
        "prcp": np.full(len(ens_dates), 5.0),
        "tmax": np.full(len(ens_dates), 28.0),
        "tmin": np.full(len(ens_dates), 23.0),
    }).to_csv(ens / f"{sid}.csv", index=False)

    p = stitch_weather_files(
        warm, ens, out, sid,
        forecast_start_date="2025-01-01",
        forecast_end_date="2025-03-31",
        warm_up_start_date="2024-10-01",
    )
    df = pd.read_csv(p)
    assert len(df) == 92 + 90    # OND warm-up (oct31+nov30+dec31=92) + JFM forecast 90
    # 2024-12-31 은 ERA5 pcp=2.0, 2025-01-01 은 ensemble pcp=5.0
    df["date"] = pd.to_datetime(df["date"])
    assert df.loc[df["date"] == "2024-12-31", "pcp_mm"].iloc[0] == 2.0
    assert df.loc[df["date"] == "2025-01-01", "pcp_mm"].iloc[0] == 5.0


def test_stitch_missing_warm_up_raises(tmp_path) -> None:
    warm = tmp_path / "warm"; warm.mkdir()
    ens  = tmp_path / "ens";  ens.mkdir()
    pd.DataFrame({"date": ["2025-01-01"], "pcp_mm": [1.0], "tmax_c": [25.0], "tmin_c": [20.0]}).to_csv(warm / "x.csv", index=False)
    pd.DataFrame({"year": [2025], "mon": [1], "day": [1],
                  "prcp": [3.0], "tmax": [26], "tmin": [21]}).to_csv(ens / "x.csv", index=False)

    with pytest.raises(RuntimeError, match="warm-up"):
        stitch_weather_files(warm, ens, tmp_path / "out", "x",
                              forecast_start_date="2025-01-01",
                              forecast_end_date="2025-01-31",
                              warm_up_start_date="2024-01-01")
