"""Tests for SWAT-Plus and SWAT 2012 weather input writers."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swat_py.io.station import StationInfo
from swat_py.io.weather_swat_plus import write_all_weather_plus, write_cli_index
from swat_py.io.weather_swat import write_pcp, write_all_weather


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_station_csv(tmp_path: Path) -> Path:
    """Write a 2-station CSV and return the path."""
    content = "ID,Lat,Lon,Elev\nstn_A,37.5,127.0,50\nstn_B,37.6,127.1,80\n"
    p = tmp_path / "stations.csv"
    p.write_text(content)
    return p


def _make_weather_csvs(tmp_path: Path) -> None:
    """Write minimal 12-column daily weather CSV for two stations."""
    dates = pd.date_range("2020-01-01", "2020-01-10")
    for stn_id in ["stn_A", "stn_B"]:
        rows = []
        for d in dates:
            rows.append([d.year, d.month, d.day,
                         2.0, 15.0, 5.0, 3.0, 0.7, 12.0,
                         8.0, 0.3, 10.0])
        df = pd.DataFrame(rows, columns=[
            "year", "mon", "day", "prcp", "tmax", "tmin",
            "wspd", "rhum", "rsds", "sshine", "cloud", "tavg",
        ])
        df.to_csv(tmp_path / f"{stn_id}.csv", index=False)


# ── SWAT-Plus tests ───────────────────────────────────────────────────────────

def test_write_cli_index(tmp_path):
    write_cli_index("pcp", ["stn_A", "stn_B"], tmp_path)
    p = tmp_path / "pcp.cli"
    assert p.exists()
    lines = p.read_text().splitlines()
    assert "filename" in lines[1]
    assert "stn_A.pcp" in lines[2]
    assert "stn_B.pcp" in lines[3]


def test_write_all_weather_plus_creates_files(tmp_path):
    _make_weather_csvs(tmp_path)
    stations = [
        StationInfo("stn_A", 37.5, 127.0, 50),
        StationInfo("stn_B", 37.6, 127.1, 80),
    ]
    out_dir = tmp_path / "swat_run"
    write_all_weather_plus(stations, wthr_dir=tmp_path, out_dir=out_dir)

    # CLI files
    for cli in ("pcp.cli", "tmp.cli", "wnd.cli", "hmd.cli", "slr.cli"):
        assert (out_dir / cli).exists(), f"{cli} not created"

    # Per-station files
    for stn_id in ["stn_A", "stn_B"]:
        for ext in ("pcp", "tmp", "wnd", "hmd", "slr"):
            assert (out_dir / f"{stn_id}.{ext}").exists(), f"{stn_id}.{ext} not created"


def test_tmp_file_format(tmp_path):
    _make_weather_csvs(tmp_path)
    stations = [StationInfo("stn_A", 37.5, 127.0, 50)]
    out_dir = tmp_path / "run"
    write_all_weather_plus(stations, wthr_dir=tmp_path, out_dir=out_dir)
    lines = (out_dir / "stn_A.tmp").read_text().splitlines()
    # Line 0: title; Line 1: header; Line 2: metadata; Line 3+: data
    assert "nbyr" in lines[1]
    # Data row: year  julian  tmax  tmin
    parts = lines[3].split()
    assert len(parts) == 4, f"Expected 4 columns in tmp data row, got: {lines[3]}"


# ── SWAT 2012 tests ───────────────────────────────────────────────────────────

def test_write_pcp_creates_file(tmp_path):
    _make_weather_csvs(tmp_path)
    stations = [
        StationInfo("stn_A", 37.5, 127.0, 50),
        StationInfo("stn_B", 37.6, 127.1, 80),
    ]
    p = write_pcp(stations, wthr_dir=tmp_path, out_dir=tmp_path)
    assert p.exists()
    lines = p.read_text().splitlines()
    # Header + 3 metadata lines + 10 data rows
    assert len(lines) >= 14
    # Data row format: %4d%03d%05.1f%05.1f
    assert len(lines[4]) >= 7
