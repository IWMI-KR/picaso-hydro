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


# ── drought 수원별(sources) 스키마 + 하위호환 ──────────────────────────────────

def _write_yaml(tmp_path, body):
    p = tmp_path / "swat_py.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_drought_flat_backward_compat(tmp_path):
    """구 flat drought(outlets+thresholds) — sources 없이 그대로 동작(Cook)."""
    p = _write_yaml(tmp_path, """
        project: {root: "/tmp/x"}
        model: {type: swat_plus}
        drought:
          syear: 1982
          eyear: 2023
          thresholds: {method: "fdc_exceedance", values: [70, 90, 95]}
          outlets: {13: "avatiu", 3: "avana"}
    """)
    cfg = load_config(p)
    d = cfg.Drought
    assert d.sources == []                       # sources 없음
    assert d.outlets == {13: "avatiu", 3: "avana"}
    assert d.threshold_method == "fdc_exceedance"
    assert d.threshold_values == [70.0, 90.0, 95.0]
    assert d.threshold_for(13) == ("fdc_exceedance", [70.0, 90.0, 95.0])


def test_drought_sources_per_source(tmp_path):
    """신 sources 스키마 — 수원별 method/values 라우팅(Palau)."""
    p = _write_yaml(tmp_path, """
        project: {root: "/tmp/x"}
        model: {type: swat_plus}
        drought:
          syear: 1982
          eyear: 2023
          sources:
            ngerikiil:
              type: stream
              thresholds: {method: "fdc_exceedance", values: [70, 90, 95]}
              outlets: {1: "ngerikiil"}
            ngerimel:
              type: reservoir
              reservoir: "ngerimel"
              thresholds: {method: "capacity_fraction", values: [100, 85, 65]}
              outlets: {4: "ngerimel"}
    """)
    cfg = load_config(p)
    d = cfg.Drought
    assert len(d.sources) == 2
    assert d.threshold_for(1) == ("fdc_exceedance", [70.0, 90.0, 95.0])
    assert d.threshold_for(4) == ("capacity_fraction", [100.0, 85.0, 65.0])
    # 병합 flat outlets (레거시 소비자 대비)
    assert d.outlets == {1: "ngerikiil", 4: "ngerimel"}
    # 저수지 수원 메타
    s = d.source_for(4)
    assert s.type == "reservoir" and s.reservoir == "ngerimel"
    # 미등록 outlet → flat(첫 수원) fallback
    assert d.threshold_for(999) == ("fdc_exceedance", [70.0, 90.0, 95.0])


def test_drought_reservoir_initial_condition(tmp_path):
    """저수지 예측 초기조건(init_water_level_ft, measured) + 결과명 접미사."""
    p = _write_yaml(tmp_path, """
        project: {root: "/tmp/x"}
        model: {type: swat_plus}
        drought:
          sources:
            ngerikiil:
              type: stream
              thresholds: {method: fdc_exceedance, values: [70, 90, 95]}
              outlets: {1: "ngerikiil"}
            ngerimel:
              type: reservoir
              reservoir: "ngerimel"
              thresholds: {method: capacity_fraction, values: [100, 85, 65]}
              outlets: {4: "ngerimel"}
              initial_condition:
                init_water_level_ft: 44.0
                measured: false
    """)
    d = load_config(p).Drought
    s = d.source_for(4)
    assert s.init_water_level_ft == 44.0 and s.measured is False
    assert s.has_initial_condition() is True
    # 하천 수원은 초기조건 없음
    assert d.source_for(1).has_initial_condition() is False
    # 접미사: 시나리오
    assert d.forecast_suffix() == "__ic44.0ft-scn"


def test_drought_ic_measured_suffix(tmp_path):
    p = _write_yaml(tmp_path, """
        project: {root: "/tmp/x"}
        model: {type: swat_plus}
        drought:
          sources:
            ngerimel:
              type: reservoir
              thresholds: {method: capacity_fraction, values: [100, 85, 65]}
              outlets: {4: "ngerimel"}
              initial_condition: {init_water_level_ft: 40.5, measured: true}
    """)
    assert load_config(p).Drought.forecast_suffix() == "__ic40.5ft-meas"


def test_drought_no_ic_suffix_empty(tmp_path):
    """초기조건 미지정 → 접미사 '' (기존 동작·Cook 하위호환)."""
    p = _write_yaml(tmp_path, """
        project: {root: "/tmp/x"}
        model: {type: swat_plus}
        drought:
          sources:
            ngerimel:
              type: reservoir
              thresholds: {method: capacity_fraction, values: [100, 85, 65]}
              outlets: {4: "ngerimel"}
    """)
    d = load_config(p).Drought
    assert d.forecast_suffix() == ""
    assert d.source_for(4).has_initial_condition() is False


def test_drought_measured_yes_no(tmp_path):
    """measured 를 Yes/No(YAML bool)·문자열로 지정 — 견고 파싱."""
    from swat_py.config.env import _to_bool
    # 헬퍼 견고성
    assert _to_bool("Yes") is True and _to_bool("No") is False
    assert _to_bool("yes") is True and _to_bool("NO") is False
    assert _to_bool(True) is True and _to_bool("true") is True
    # measured: Yes → 실측(-meas)
    p = _write_yaml(tmp_path, """
        project: {root: "/tmp/x"}
        model: {type: swat_plus}
        drought:
          sources:
            ngerimel:
              type: reservoir
              thresholds: {method: capacity_fraction, values: [100, 85, 65]}
              outlets: {4: "ngerimel"}
              initial_condition: {init_water_level_ft: 44.0, measured: Yes}
    """)
    d = load_config(p).Drought
    assert d.source_for(4).measured is True
    assert d.forecast_suffix() == "__ic44.0ft-meas"
    # measured: No → 시나리오(-scn)
    sub = tmp_path / "b"; sub.mkdir(exist_ok=True)
    p2 = _write_yaml(sub, """
        project: {root: "/tmp/x"}
        model: {type: swat_plus}
        drought:
          sources:
            ngerimel:
              type: reservoir
              thresholds: {method: capacity_fraction, values: [100, 85, 65]}
              outlets: {4: "ngerimel"}
              initial_condition: {init_water_level_ft: 44.0, measured: No}
    """)
    d2 = load_config(p2).Drought
    assert d2.source_for(4).measured is False
    assert d2.forecast_suffix() == "__ic44.0ft-scn"
