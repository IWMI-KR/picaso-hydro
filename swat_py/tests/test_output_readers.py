"""Tests for output file parsers."""

import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swat_py.output.reader_swat import parse_output_rch, extract_rch_outtype
from swat_py.output.reader_swat_plus import parse_channel_sd_day, extract_cha_outtype


# ── SWAT 2012 output.rch ─────────────────────────────────────────────────────

def _make_rch_file(tmp_path: Path, outlet: int = 5) -> Path:
    """Create a minimal output.rch with two rows for the target outlet."""
    header = "\n" * 9  # 9 skip lines
    # Columns: Type RCH GIS MON AREAkm2 FLOW_IN FLOW_OUT EVAPcms ...
    row = f"  RCH  {outlet}  {outlet}  1  100.0  5.0  4.5  0.1  0.0  0.5  0.4  10.0"
    row += "  0.1  0.08  0.05  0.04  0.02  0.01  0.005  0.004  0.001  0.001"
    row += "  0.0  0.0  0.0  0.0  0.0  0.0  0.0  0.0\n"
    content = header + row * 3  # 3 daily rows
    p = tmp_path / "output.rch"
    p.write_text(content)
    return p


def test_parse_output_rch_returns_df(tmp_path):
    p = _make_rch_file(tmp_path, outlet=5)
    df = parse_output_rch(p, outlet=5, sdate="2020-01-01")
    assert df is not None
    assert "date" in df.columns
    assert len(df) == 3


def test_parse_output_rch_wrong_outlet(tmp_path):
    p = _make_rch_file(tmp_path, outlet=5)
    df = parse_output_rch(p, outlet=99, sdate="2020-01-01")
    assert df is None


def test_extract_rch_flow(tmp_path):
    p = _make_rch_file(tmp_path, outlet=5)
    raw = parse_output_rch(p, outlet=5, sdate="2020-01-01")
    typed = extract_rch_outtype(raw, "flow")
    assert "flow_cms" in typed.columns
    assert not typed["flow_cms"].isna().all()


# ── SWAT-Plus channel_sd_day.txt ─────────────────────────────────────────────

def _make_channel_sd_file(tmp_path: Path, outlet: int = 23) -> Path:
    """Create a minimal channel_sd_day.txt."""
    header_lines = (
        "SWAT-Plus channel output\n"
        "units: various\n"
        "jday  mon  day  yr  unit  type  gis_id  flo_out  sed_out  orgn_out  "
        "no3_out  nh3_out  no2_out  sedp_out  solp_out\n"
    )
    row = (
        f"  1  1  1  2020  1  cha  {outlet}  "
        f"5.0  0.3  0.01  0.005  0.001  0.0005  0.002  0.001\n"
    )
    content = header_lines + row * 5
    p = tmp_path / "channel_sd_day.txt"
    p.write_text(content)
    return p


def test_parse_channel_sd_day(tmp_path):
    p = _make_channel_sd_file(tmp_path, outlet=23)
    df = parse_channel_sd_day(p, outlet=23, sdate="2020-01-01")
    assert df is not None
    assert len(df) == 5


def test_extract_cha_flow(tmp_path):
    p = _make_channel_sd_file(tmp_path, outlet=23)
    raw = parse_channel_sd_day(p, outlet=23, sdate="2020-01-01")
    typed = extract_cha_outtype(raw, "flow")
    assert "flow_cms" in typed.columns


def test_extract_cha_sedc(tmp_path):
    p = _make_channel_sd_file(tmp_path, outlet=23)
    raw = parse_channel_sd_day(p, outlet=23, sdate="2020-01-01")
    typed = extract_cha_outtype(raw, "sedc")
    assert "Sed_mgl" in typed.columns
