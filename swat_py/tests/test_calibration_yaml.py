"""env.py — 신규 calibration 블록 (observations / parameters / method) 파싱 검증."""
from __future__ import annotations

import warnings
from pathlib import Path
from textwrap import dedent

import pytest

from swat_py.config.env import load_config


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "swat_py.yaml"
    p.write_text(body, encoding="utf-8")
    return p


_FULL_YAML = dedent("""
project:
  root: "/proj"
model:
  type: "swat_plus"
  executable: "SWAT-Plus.exe"
simulation:
  start_date: "2015-01-01"
  end_date:   "2020-12-31"
  warm_up_years: 3
  time_step: "daily"
calibration:
  period:
    start: "2017-01-01"
    end:   "2018-12-31"
  validation:
    start: "2019-01-01"
    end:   "2020-12-31"
  observations:
    - id: "rarotonga_flow"
      outlet_id: 1
      variable: "flow"
      unit: "m3/s"
      obs_file: "obs_flow.csv"
      obs_column: "inflow_cms"
      time_step: "daily"
      weight: 1.0
      objective: "NSE"
    - id: "rarotonga_tn"
      outlet_id: 1
      variable: "tn"
      unit: "mg/L"
      obs_file: "obs_wq.csv"
      obs_column: "tn_mgl"
      time_step: "monthly"
      weight: 0.3
      objective: "PBIAS"
  parameters:
    - file: "hydrology.hyd"
      key: "cn3_swf"
      range: [0.5, 1.0]
      change_type: "absval"
    - file: "soils.sol"
      key: "sol_awc"
      range: [-0.04, 0.04]
      change_type: "abschg"
  method:
    name: "manual"
    n_iterations: 50
    seed: 42
    parallel:
      enabled: true
      n_workers: 4
  output:
    save_all_runs: false
    save_best_n: 5
    auto_parameter_changes: true
""")


# ── simulation 일자 ─────────────────────────────────────────────────────────

def test_simulation_dates_parsed(tmp_path) -> None:
    cfg = load_config(_write_yaml(tmp_path, _FULL_YAML))
    assert cfg.SimStartDate == "2015-01-01"
    assert cfg.SimEndDate   == "2020-12-31"
    assert cfg.SimTimeStep  == "daily"


# ── calibration.period / validation ─────────────────────────────────────────

def test_calibration_period_dates(tmp_path) -> None:
    cfg = load_config(_write_yaml(tmp_path, _FULL_YAML))
    assert cfg.CalPeriodStart == "2017-01-01"
    assert cfg.CalPeriodEnd   == "2018-12-31"
    assert cfg.ValPeriodStart == "2019-01-01"
    assert cfg.ValPeriodEnd   == "2020-12-31"


# ── observations (flat list) ────────────────────────────────────────────────

def test_observations_list(tmp_path) -> None:
    cfg = load_config(_write_yaml(tmp_path, _FULL_YAML))
    assert len(cfg.Observations) == 2

    o1 = cfg.Observations[0]
    assert o1.id == "rarotonga_flow"
    assert o1.outlet_id == 1
    assert o1.variable == "flow"
    assert o1.unit == "m3/s"
    assert o1.obs_column == "inflow_cms"
    assert o1.time_step == "daily"
    assert o1.weight == pytest.approx(1.0)
    assert o1.objective == "NSE"

    o2 = cfg.Observations[1]
    assert o2.variable == "tn"
    assert o2.unit == "mg/L"
    assert o2.time_step == "monthly"
    assert o2.weight == pytest.approx(0.3)
    assert o2.objective == "PBIAS"


def test_observations_empty_when_no_calibration(tmp_path) -> None:
    """calibration 블록 자체가 없으면 Observations 빈 리스트."""
    minimal = dedent("""
        project: { root: "/p" }
        model:   { type: "swat_plus" }
    """)
    cfg = load_config(_write_yaml(tmp_path, minimal))
    assert cfg.Observations == []
    assert cfg.CalParameters == []


# ── parameters ──────────────────────────────────────────────────────────────

def test_parameters_list(tmp_path) -> None:
    cfg = load_config(_write_yaml(tmp_path, _FULL_YAML))
    assert len(cfg.CalParameters) == 2

    p1 = cfg.CalParameters[0]
    assert p1.file == "hydrology.hyd"
    assert p1.key == "cn3_swf"
    assert p1.range == [0.5, 1.0]
    assert p1.change_type == "absval"

    p2 = cfg.CalParameters[1]
    assert p2.range == [-0.04, 0.04]
    assert p2.change_type == "abschg"


# ── method / output ─────────────────────────────────────────────────────────

def test_method_and_output(tmp_path) -> None:
    cfg = load_config(_write_yaml(tmp_path, _FULL_YAML))
    assert cfg.CalMethod.name == "manual"
    assert cfg.CalMethod.n_iterations == 50
    assert cfg.CalMethod.seed == 42
    assert cfg.CalMethod.parallel.enabled is True
    assert cfg.CalMethod.parallel.n_workers == 4

    assert cfg.CalOutput.save_all_runs is False
    assert cfg.CalOutput.save_best_n == 5
    assert cfg.CalOutput.auto_parameter_changes is True


# ── 호환 — 옛 simulation.calibration.start_year 도 인식 ─────────────────────

def test_legacy_year_fields_still_work(tmp_path) -> None:
    legacy = dedent("""
        project: { root: "/p" }
        model:   { type: "swat_plus" }
        simulation:
          calibration: { start_year: 2017, end_year: 2018 }
          validation:  { start_year: 2019, end_year: 2020 }
    """)
    cfg = load_config(_write_yaml(tmp_path, legacy))
    assert cfg.CalibrationStartYear == 2017
    assert cfg.ValidationEndYear == 2020
