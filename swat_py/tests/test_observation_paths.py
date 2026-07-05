"""env.py — observation obs_file / obs_column / outlet_name 자동 산출 검증."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from swat_py.config.env import load_config
from swat_py.units import default_column_name


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "swat_py.yaml"
    p.write_text(body, encoding="utf-8")
    return p


# ── default_column_name ─────────────────────────────────────────────────────

def test_column_name_flow_m3s() -> None:
    assert default_column_name("flow", "m3/s") == "flow_m3s"


def test_column_name_flow_mm() -> None:
    assert default_column_name("flow", "mm/day") == "flow_mm"


def test_column_name_tn_mgl() -> None:
    assert default_column_name("tn", "mg/L") == "tn_mgl"


def test_column_name_tp_kgd() -> None:
    assert default_column_name("tp", "kg/day") == "tp_kgd"


def test_column_name_ss_td() -> None:
    assert default_column_name("ss", "t/day") == "ss_td"


def test_column_name_invalid_raises() -> None:
    with pytest.raises(ValueError, match="허용"):
        default_column_name("flow", "kg/day")


# ── 자동 산출 통합 ──────────────────────────────────────────────────────────

_BASE = dedent("""
project:
  root: "/proj"
  database: "/proj/data"
  input:
    observed: "/proj/data/obs"
model:
  type: "swat_plus"
""")


def test_obs_file_auto_generated(tmp_path) -> None:
    """obs_file 생략 시 자동 산출 — obs_root/variable/step/outlet_name.csv."""
    p = _write_yaml(tmp_path, _BASE + dedent("""
        calibration:
          observations:
            - id: "raro_flow"
              outlet_id: 1
              variable: "flow"
              unit: "m3/s"
              time_step: "daily"
    """))
    cfg = load_config(p)
    obs = cfg.Observations[0]
    assert obs.outlet_name == "outlet_1"
    assert obs.obs_column == "flow_m3s"
    assert Path(obs.obs_file) == Path("/proj/data/obs/flow/daily/outlet_1.csv")


def test_obs_file_user_override_wins(tmp_path) -> None:
    """yaml 에 obs_file 명시하면 자동 산출보다 우선."""
    p = _write_yaml(tmp_path, _BASE + dedent("""
        calibration:
          observations:
            - id: "raro_flow"
              outlet_id: 1
              variable: "flow"
              unit: "m3/s"
              time_step: "daily"
              obs_file: "/custom/path/flow.csv"
              obs_column: "custom_col"
    """))
    cfg = load_config(p)
    obs = cfg.Observations[0]
    assert Path(obs.obs_file) == Path("/custom/path/flow.csv")
    assert obs.obs_column == "custom_col"


def test_obs_file_monthly_wq(tmp_path) -> None:
    """수질 + monthly 자동 산출."""
    p = _write_yaml(tmp_path, _BASE + dedent("""
        calibration:
          observations:
            - id: "raro_tn"
              outlet_id: 1
              variable: "tn"
              unit: "mg/L"
              time_step: "monthly"
    """))
    cfg = load_config(p)
    obs = cfg.Observations[0]
    assert obs.obs_column == "tn_mgl"
    assert Path(obs.obs_file) == Path("/proj/data/obs/tn/monthly/outlet_1.csv")


def test_observed_root_auto_from_database(tmp_path) -> None:
    """yaml 에 project.input.observed 미명시 시 $(project.database)/obs 자동."""
    p = _write_yaml(tmp_path, dedent("""
        project:
          root: "/proj"
          database: "/proj/data"
        model:
          type: "swat_plus"
        calibration:
          observations:
            - id: "a_flow"
              outlet_id: 1
              variable: "flow"
              unit: "m3/s"
              time_step: "daily"
    """))
    cfg = load_config(p)
    assert Path(cfg.ObservedDataDir) == Path("/proj/data/obs")
    obs = cfg.Observations[0]
    assert Path(obs.obs_file) == Path("/proj/data/obs/flow/daily/outlet_1.csv")


def test_outlet_name_default_from_id(tmp_path) -> None:
    """outlet_name 미명시 시 'outlet_{id}' 로 자동 산출."""
    p = _write_yaml(tmp_path, dedent("""
        project: { root: "/proj", database: "/proj/data" }
        model:   { type: "swat_plus" }
        calibration:
          observations:
            - id: "unknown"
              outlet_id: 99
              variable: "flow"
              unit: "m3/s"
              time_step: "daily"
    """))
    cfg = load_config(p)
    obs = cfg.Observations[0]
    assert obs.outlet_name == "outlet_99"
    assert "outlet_99" in obs.obs_file


def test_outlet_name_explicit_in_observation(tmp_path) -> None:
    """observation 자체에 outlet_name 명시하면 그게 우선."""
    p = _write_yaml(tmp_path, _BASE + dedent("""
        calibration:
          observations:
            - id: "raro_flow"
              outlet_id: 1
              outlet_name: "MyCustomName"
              variable: "flow"
              unit: "m3/s"
              time_step: "daily"
    """))
    cfg = load_config(p)
    obs = cfg.Observations[0]
    assert obs.outlet_name == "MyCustomName"
    assert "MyCustomName.csv" in obs.obs_file
