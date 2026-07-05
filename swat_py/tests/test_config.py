"""Tests for YAML config loading — both nested (new) and flat (legacy) formats."""

import textwrap
from pathlib import Path

import pytest

from swat_py.config.env import (
    EnvConfig,
    load_config,
    _resolve_refs,
    _is_nested_format,
    _normalize_nested,
)


# ── $(참조) 해석 ──────────────────────────────────────────────────────────────

def test_resolve_refs_flat_key():
    data = {"PrjDir": "/projects/foo", "DbDir": "$(PrjDir)/db"}
    resolved = _resolve_refs(data)
    assert resolved["DbDir"] == "/projects/foo/db"


def test_resolve_refs_dotpath():
    data = {
        "project": {
            "root": "/projects/foo",
            "database": "$(project.root)/db",
        }
    }
    resolved = _resolve_refs(data)
    assert resolved["project"]["database"] == "/projects/foo/db"


def test_resolve_refs_chain():
    data = {
        "project": {
            "root": "/projects/foo",
            "database": "$(project.root)/db",
        },
        "observed": "$(project.database)/obs",
    }
    resolved = _resolve_refs(data)
    assert resolved["observed"] == "/projects/foo/db/obs"


# ── 형식 감지 ─────────────────────────────────────────────────────────────────

def test_is_nested_format_true():
    assert _is_nested_format({"project": {"root": "/foo"}, "model": {"type": "swat_plus"}})


def test_is_nested_format_false():
    assert not _is_nested_format({"PrjDir": "/foo", "CioNYSKIP": 3})


# ── 신규 중첩 YAML 로드 ───────────────────────────────────────────────────────

def _write_nested_yaml(tmp_path: Path) -> Path:
    prj = str(tmp_path).replace("\\", "/")
    content = textwrap.dedent(f"""
        project:
          root: "{prj}"
          database: "$(project.root)/Database"
          input:
            observed_weather: "$(project.database)/Observed"
            cc_weather: "$(project.database)/ClimateChange"
          output:
            swat_run: "$(project.root)/swat_run/TxtInOut"
            calibration: "$(project.root)/Results/Calibration"
            climate_change: "$(project.root)/Results/CC"
            forecast: "$(project.root)/Results/Forecast"
            database: "$(project.database)/SWAT"

        model:
          type: swat_plus
          executable: SWAT-Plus.exe
          warm_up_years: 3
          output_types: [sd]

        stations:
          metadata_file: stations.csv
          ids: [asos203, asos232]

        observed:
          flow:
            file: obs_flow.csv
          water_quality:
            file: obs_wq.csv

        simulation:
          output_types: [flow, sedc, tnc, tpc]
          calibration:
            start_year: 2017
            end_year: 2018
          validation:
            start_year: 2019
            end_year: 2020
          baseline:
            start_year: 1981
            end_year: 2010

        climate_change:
          enabled: true
          models: [CanESM5, ACCESS-CM2]
          scenarios: [historical, ssp126, ssp585]
          historical_period:
            start_year: 1981
            end_year: 2010
          future_periods:
            - start_year: 2011
              end_year: 2040
              label: near_future
            - start_year: 2071
              end_year: 2100
              label: far_future
    """)
    p = tmp_path / "swat_py.yaml"
    p.write_text(content)
    return p


def test_load_nested_basic(tmp_path):
    p = _write_nested_yaml(tmp_path)
    cfg = load_config(p)
    assert isinstance(cfg, EnvConfig)
    assert cfg.ModelType == "swat_plus"
    assert cfg.CioNYSKIP == 3


def test_load_nested_dirs(tmp_path):
    p = _write_nested_yaml(tmp_path)
    cfg = load_config(p)
    prj = str(tmp_path).replace("\\", "/")
    assert cfg.PrjDir == prj
    assert cfg.DbDir == f"{prj}/Database"
    assert cfg.ObsDayDir == f"{prj}/Database/Observed"
    assert cfg.SwatRunDir == f"{prj}/swat_run/TxtInOut"


def test_load_nested_stations(tmp_path):
    p = _write_nested_yaml(tmp_path)
    cfg = load_config(p)
    assert cfg.StnFile == "stations.csv"
    assert cfg.StnIDs == ["asos203", "asos232"]


def test_load_nested_simulation(tmp_path):
    p = _write_nested_yaml(tmp_path)
    cfg = load_config(p)
    assert cfg.SimOutputTypes == ["flow", "sedc", "tnc", "tpc"]
    assert cfg.CalibrationStartYear == 2017
    assert cfg.CalibrationEndYear == 2018
    assert cfg.ValidationStartYear == 2019
    assert cfg.BaselineStartYear == 1981


def test_load_nested_climate_change(tmp_path):
    p = _write_nested_yaml(tmp_path)
    cfg = load_config(p)
    assert cfg.CChangeOpt == "on"
    assert "CanESM5" in cfg.MdlNms
    assert cfg.Syear_hist == 1981
    assert cfg.Syear_rcp == [2011, 2071]
    assert cfg.Eyear_rcp == [2040, 2100]
    assert len(cfg.FuturePeriods) == 2
    assert cfg.FuturePeriods[0].label == "near_future"


def test_override_nested(tmp_path):
    p = _write_nested_yaml(tmp_path)
    cfg = load_config(p, override={"model": {"warm_up_years": 5}})
    assert cfg.CioNYSKIP == 5


# ── 구 단순 YAML 하위 호환성 ───────────────────────────────────────────────────

def _write_legacy_yaml(tmp_path: Path) -> Path:
    prj = str(tmp_path).replace("\\", "/")
    content = textwrap.dedent(f"""
        PrjDir: "{prj}"
        DbDir: "$(PrjDir)/db"
        ObsDayDir: "$(DbDir)/obs"
        SwatRunDir: "$(PrjDir)/run"
        SwatObsDir: "$(PrjDir)/obs_out"
        SwatCcDir: "$(PrjDir)/cc_out"
        SwatDbDir: "$(PrjDir)/swat_db"
        CioNYSKIP: 2
        StnFile: stations.csv
        StnIDs: [asos203]
        ObsFlowFile: flow.csv
        ObsWqFile: wq.csv
        OutputTypes: [sd]
        CChangeOpt: Off
        MdlNms: [CanESM5]
        ScnNms: [historical]
        Syear_hist: 1981
        Eyear_hist: 2010
        Syear_rcp: [2011]
        Eyear_rcp: [2040]
    """)
    p = tmp_path / "rSWAT.yaml"
    p.write_text(content)
    return p


def test_load_legacy_basic(tmp_path):
    p = _write_legacy_yaml(tmp_path)
    cfg = load_config(p)
    assert isinstance(cfg, EnvConfig)
    assert cfg.CioNYSKIP == 2
    assert cfg.StnIDs == ["asos203"]


def test_load_legacy_refs(tmp_path):
    p = _write_legacy_yaml(tmp_path)
    cfg = load_config(p)
    prj = str(tmp_path).replace("\\", "/")
    assert cfg.DbDir == f"{prj}/db"
    assert cfg.ObsDayDir == f"{prj}/db/obs"


def test_override_legacy(tmp_path):
    p = _write_legacy_yaml(tmp_path)
    cfg = load_config(p, override={"CioNYSKIP": 5})
    assert cfg.CioNYSKIP == 5


# ── 신규 path: 섹션 (swat 전용 경로) ───────────────────────────────────────────

def test_load_path_section(tmp_path):
    """path: 섹션으로 swat 전용 경로 지정 (qswat/swatplus_txtinout/observed/cc_weather)."""
    prj = str(tmp_path).replace("\\", "/")
    content = textwrap.dedent(f"""
        project:
          root: "{prj}"
          database: "{prj}/db"
        path:
          qswat_txtinout:    "$(project.root)/2_qswat/TxtInOut"
          swatplus_txtinout: "$(project.root)/3_swatplus/default"
          observed:          "$(project.database)/obs"
          cc_weather:        "$(project.database)/cmip6"
        stations:
          metadata_file: stations.csv
          ids: [918430]
    """)
    p = tmp_path / "swat_py.yaml"
    p.write_text(content)
    cfg = load_config(p)
    assert cfg.QswatTxtInOut   == f"{prj}/2_qswat/TxtInOut"
    assert cfg.DefaultDir      == f"{prj}/3_swatplus/default"
    assert cfg.ObservedDataDir == f"{prj}/db/obs"
    assert cfg.CcDataDir       == f"{prj}/db/cmip6"


def test_path_section_backward_compat(tmp_path):
    """path: 미사용 시 구 project.input/output 로도 동일 동작(하위호환)."""
    prj = str(tmp_path).replace("\\", "/")
    content = textwrap.dedent(f"""
        project:
          root: "{prj}"
          database: "{prj}/db"
          qswat_txtinout: "$(project.root)/qs"
          input:
            observed:   "$(project.database)/obs"
            cc_weather: "$(project.database)/cc"
          output:
            default: "$(project.root)/3_swatplus/default"
        stations:
          metadata_file: stations.csv
          ids: [1]
    """)
    p = tmp_path / "swat_py.yaml"
    p.write_text(content)
    cfg = load_config(p)
    assert cfg.QswatTxtInOut   == f"{prj}/qs"
    assert cfg.DefaultDir      == f"{prj}/3_swatplus/default"
    assert cfg.ObservedDataDir == f"{prj}/db/obs"
    assert cfg.CcDataDir       == f"{prj}/db/cc"
