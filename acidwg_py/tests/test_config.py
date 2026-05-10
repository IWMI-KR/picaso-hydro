"""config.py — YAML 로더, 교차참조, 환경변수, season→sim_period 매핑 검증."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from acidwg_py.config import (
    SEASON_MONTHS,
    _resolve_string,
    find_config,
    load_config,
)


# ── helper ───────────────────────────────────────────────────────────────────

_MIN_PATHS = """
paths:
  station_csv:  "/p/stations.csv"
  forecast_csv: "/p/forecast.csv"
  obs_dir:      "/p/obs"
  output_dir:   "/p/out"
"""


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "acidwg_py.yaml"
    p.write_text(body, encoding="utf-8")
    return p


# ── SEASON_MONTHS ────────────────────────────────────────────────────────────

def test_season_months_has_12_entries() -> None:
    assert len(SEASON_MONTHS) == 12
    assert all(len(v) == 3 for v in SEASON_MONTHS.values())


@pytest.mark.parametrize(
    "code, months",
    [
        ("JFM", [1, 2, 3]),
        ("JJA", [6, 7, 8]),
        ("DJF", [12, 1, 2]),
        ("NDJ", [11, 12, 1]),
    ],
)
def test_season_months_values(code: str, months: list) -> None:
    assert SEASON_MONTHS[code] == months


# ── 기본 로딩 ────────────────────────────────────────────────────────────────

def test_load_minimal_yaml(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_PATHS)
    cfg = load_config(p)
    assert cfg["station_csv"] == "/p/stations.csv"
    assert cfg["sim_period"] == [6, 7, 8]   # 기본 JJA
    assert cfg["n_ensemble"] == 1000
    assert cfg["random_seed"] == 1
    assert cfg["overwrite"] is False
    assert cfg["variables"] == ["prcp", "tmax", "tmin"]


def test_missing_required_path_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
paths:
  station_csv:  "/p/x.csv"
  # forecast_csv 누락
  obs_dir:      "/p/obs"
  output_dir:   "/p/out"
""")
    with pytest.raises(ValueError, match="forecast_csv"):
        load_config(p)


def test_missing_file_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yml")


def test_empty_file_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, "")
    with pytest.raises(ValueError, match="비어"):
        load_config(p)


def test_top_level_must_be_mapping(tmp_path) -> None:
    p = _write_yaml(tmp_path, "- 1\n- 2\n")
    with pytest.raises(ValueError, match="매핑"):
        load_config(p)


# ── 교차참조 ─────────────────────────────────────────────────────────────────

def test_cross_reference(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
paths:
  base_dir:     "/data"
  station_csv:  "$(paths.base_dir)/stations.csv"
  forecast_csv: "$(paths.base_dir)/forecast.csv"
  obs_dir:      "$(paths.base_dir)/obs"
  output_dir:   "$(paths.base_dir)/out"
""")
    cfg = load_config(p)
    assert cfg["station_csv"] == "/data/stations.csv"
    assert cfg["forecast_csv"] == "/data/forecast.csv"


def test_cross_reference_unknown_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
paths:
  station_csv:  "$(paths.no_such_key)/x.csv"
  forecast_csv: "/p/f.csv"
  obs_dir:      "/p/obs"
  output_dir:   "/p/out"
""")
    with pytest.raises(ValueError, match="해석 실패"):
        load_config(p)


def test_cross_reference_circular_raises() -> None:
    root = {"a": "$(b)", "b": "$(a)"}
    with pytest.raises(ValueError, match="순환"):
        _resolve_string("$(a)", root)


# ── 환경변수 ─────────────────────────────────────────────────────────────────

def test_env_var(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ACID_BASE", "/from/env")
    p = _write_yaml(tmp_path, """
paths:
  base_dir:     "${env:ACID_BASE}"
  station_csv:  "$(paths.base_dir)/s.csv"
  forecast_csv: "$(paths.base_dir)/f.csv"
  obs_dir:      "$(paths.base_dir)/obs"
  output_dir:   "$(paths.base_dir)/out"
""")
    cfg = load_config(p)
    assert cfg["station_csv"] == "/from/env/s.csv"


def test_env_var_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UNDEFINED_VAR", raising=False)
    p = _write_yaml(tmp_path, """
paths:
  base_dir:     "${env:UNDEFINED_VAR:/fallback}"
  station_csv:  "$(paths.base_dir)/s.csv"
  forecast_csv: "$(paths.base_dir)/f.csv"
  obs_dir:      "$(paths.base_dir)/obs"
  output_dir:   "$(paths.base_dir)/out"
""")
    cfg = load_config(p)
    assert cfg["station_csv"] == "/fallback/s.csv"


# ── season vs months ─────────────────────────────────────────────────────────

def test_season_to_sim_period(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_PATHS + """
forecast:
  year: 2024
  season: NDJ
""")
    cfg = load_config(p)
    assert cfg["sim_period"] == [11, 12, 1]
    assert cfg["forecast_year"] == 2024


def test_months_overrides_season(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_PATHS + """
forecast:
  year: 2024
  season: NDJ
  months: [6, 7]
""")
    cfg = load_config(p)
    assert cfg["sim_period"] == [6, 7]


def test_invalid_season_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_PATHS + """
forecast:
  season: XYZ
""")
    with pytest.raises(ValueError, match="지원하지 않는 계절"):
        load_config(p)


def test_invalid_months_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_PATHS + """
forecast:
  months: [13, 14]
""")
    with pytest.raises(ValueError, match="범위 오류"):
        load_config(p)


# ── 관측 기간 검증 ───────────────────────────────────────────────────────────

def test_syear_must_be_less_than_eyear(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_PATHS + """
observation:
  syear: 2010
  eyear: 1981
""")
    with pytest.raises(ValueError, match="syear"):
        load_config(p)


# ── 앙상블 ───────────────────────────────────────────────────────────────────

def test_n_ensemble_must_be_positive(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_PATHS + """
ensemble:
  n_members: 0
""")
    with pytest.raises(ValueError, match="1 이상"):
        load_config(p)


def test_random_seed_null_becomes_none(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_PATHS + """
ensemble:
  random_seed: null
""")
    cfg = load_config(p)
    assert cfg["random_seed"] is None


# ── find_config ──────────────────────────────────────────────────────────────

def test_find_config_walks_up(tmp_path, monkeypatch) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "acidwg_py.yaml").write_text("paths: {x: y}", encoding="utf-8")
    deep = proj / "sub" / "deeper"
    deep.mkdir(parents=True)

    monkeypatch.delenv("ACIDWG_PY_CONFIG", raising=False)
    monkeypatch.delenv("PICASO_ROOT", raising=False)
    found = find_config(start=deep)
    assert found is not None
    assert found.resolve() == (proj / "acidwg_py.yaml").resolve()


def test_find_config_env_var(tmp_path, monkeypatch) -> None:
    p = tmp_path / "explicit.yml"
    p.write_text("paths: {x: y}", encoding="utf-8")
    monkeypatch.setenv("ACIDWG_PY_CONFIG", str(p))
    found = find_config(start=tmp_path)
    assert found is not None and found.resolve() == p.resolve()
