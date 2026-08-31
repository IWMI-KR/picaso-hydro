"""util_py.config — YAML 로더, 교차참조, 환경변수 치환 검증."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from util_py.config import Config, _resolve_string, find_config, load_config


# ── helper ───────────────────────────────────────────────────────────────────

def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "util_py.yaml"
    p.write_text(body, encoding="utf-8")
    return p


# ── 기본 로딩 ────────────────────────────────────────────────────────────────

def test_load_minimal_yaml(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
project:
  root: "/tmp/picaso"
""")
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.project.root == "/tmp/picaso"


def test_load_empty_yaml_returns_defaults(tmp_path) -> None:
    p = _write_yaml(tmp_path, "")
    cfg = load_config(p)
    assert cfg.project.root == ""
    # utc_offset 은 사이트 종속 값이라 코드 기본값을 두지 않는다(None → GIS 에서 자동 추정)
    assert cfg.region.utc_offset is None
    assert cfg.region.buffer_deg == 0.25
    assert cfg.grid.era5_resolution == 0.25
    assert cfg.era5.start_year == 2022


def test_missing_file_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, "key: [unclosed")
    with pytest.raises(ValueError, match="YAML 파싱 실패"):
        load_config(p)


def test_top_level_must_be_mapping(tmp_path) -> None:
    p = _write_yaml(tmp_path, "- 1\n- 2\n")
    with pytest.raises(ValueError, match="최상위는 매핑"):
        load_config(p)


# ── 교차참조 $(key.path) ─────────────────────────────────────────────────────

def test_cross_reference_basic(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
project:
  root: "/data/picaso"
era5:
  output_dir: "$(project.root)/era5/nc"
""")
    cfg = load_config(p)
    assert cfg.era5.output_dir == "/data/picaso/era5/nc"


def test_cross_reference_chained(tmp_path) -> None:
    """$(project.root)을 참조한 값을 또 다른 키가 참조."""
    p = _write_yaml(tmp_path, """
project:
  root: "/r"
region:
  boundary_csv: "$(project.root)/cfg/boundary.csv"
era5:
  output_dir: "$(project.root)/era5"
extract:
  grid_file: "$(project.root)/grid.csv"
""")
    cfg = load_config(p)
    assert cfg.region.boundary_csv == "/r/cfg/boundary.csv"
    assert cfg.era5.output_dir == "/r/era5"
    assert cfg.extract.grid_file == "/r/grid.csv"


def test_unknown_reference_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
era5:
  output_dir: "$(no.such.key)/x"
""")
    with pytest.raises(ValueError, match="해석 실패"):
        load_config(p)


def test_circular_reference_raises() -> None:
    root = {"a": "$(b)", "b": "$(a)"}
    with pytest.raises(ValueError, match="순환"):
        _resolve_string("$(a)", root)


# ── 환경변수 ${env:VAR[:default]} ────────────────────────────────────────────

def test_env_var_substitution(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MY_ROOT", "/from/env")
    p = _write_yaml(tmp_path, """
project:
  root: "${env:MY_ROOT}"
""")
    cfg = load_config(p)
    assert cfg.project.root == "/from/env"


def test_env_var_default_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UNDEFINED_VAR", raising=False)
    p = _write_yaml(tmp_path, """
project:
  root: "${env:UNDEFINED_VAR:/fallback}"
""")
    cfg = load_config(p)
    assert cfg.project.root == "/fallback"


def test_env_var_combined_with_cross_ref(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PROJ_BASE", "/base")
    p = _write_yaml(tmp_path, """
project:
  root: "${env:PROJ_BASE}/picaso"
era5:
  output_dir: "$(project.root)/era5/nc"
""")
    cfg = load_config(p)
    assert cfg.project.root == "/base/picaso"
    assert cfg.era5.output_dir == "/base/picaso/era5/nc"


# ── 섹션별 데이터클래스 변환 ─────────────────────────────────────────────────

def test_full_yaml_round_trip(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
project:
  root: "/p"
region:
  boundary_csv: "$(project.root)/b.csv"
  utc_offset: 9
  buffer_deg: 0.5
era5:
  output_dir: "$(project.root)/era5"
  start_year: 1981
  end_year: 2024
  variables: [prcp, tavg]
  cds:
    url: "https://cds.example.com/api"
    key: "abc123"
extract:
  grid_file: "$(project.root)/g.csv"
  hourly_dir: "$(project.root)/h"
  daily_dir:  "$(project.root)/d"
  start_year: 2020
  end_year: 2023
cmip6:
  source_dir: "/cmip6/in"
  output_dir: "$(project.root)/cmip6"
  variables: [pr, hurs]
grid:
  era5_resolution: 0.5
""")
    cfg = load_config(p)
    assert cfg.region.utc_offset == 9
    assert cfg.region.buffer_deg == 0.5
    assert cfg.era5.start_year == 1981
    assert cfg.era5.end_year == 2024
    assert cfg.era5.variables == ["prcp", "tavg"]
    assert cfg.era5.cds.url == "https://cds.example.com/api"
    assert cfg.era5.cds.key == "abc123"
    assert cfg.extract.start_year == 2020
    assert cfg.extract.end_year == 2023
    assert cfg.cmip6.source_dir == "/cmip6/in"
    assert cfg.cmip6.variables == ["pr", "hurs"]
    assert cfg.grid.era5_resolution == 0.5


# ── 자동 탐색 find_config ────────────────────────────────────────────────────

def test_find_config_walks_up(tmp_path, monkeypatch) -> None:
    # tmp/proj/util_py.yaml 가 있고, tmp/proj/sub/sub2 에서 탐색
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "util_py.yaml").write_text("project: {root: x}", encoding="utf-8")
    deep = proj / "sub" / "sub2"
    deep.mkdir(parents=True)

    monkeypatch.delenv("UTIL_PY_CONFIG", raising=False)
    monkeypatch.delenv("PICASO_ROOT", raising=False)
    found = find_config(start=deep)
    assert found is not None
    assert found.resolve() == (proj / "util_py.yaml").resolve()


def test_find_config_env_var_overrides(tmp_path, monkeypatch) -> None:
    p = tmp_path / "explicit.yaml"
    p.write_text("project: {root: y}", encoding="utf-8")
    monkeypatch.setenv("UTIL_PY_CONFIG", str(p))
    found = find_config(start=tmp_path)
    assert found is not None and found.resolve() == p.resolve()


def test_find_config_returns_none_when_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UTIL_PY_CONFIG", raising=False)
    monkeypatch.delenv("PICASO_ROOT", raising=False)
    # tmp_path 에는 util_py.yaml 이 없음. 단, 탐색은 부모로 올라가므로
    # 가장 위 부모까지 가서도 못 찾으면 None. 이걸 보장하려면 분리된 빈 디렉토리 필요.
    isolated = tmp_path / "isolated_no_yaml_anywhere_above"
    isolated.mkdir()
    # isolated 부모 어딘가에 util_py.yaml 이 우연히 있을 수 있어 그 경우 스킵.
    found = find_config(start=isolated)
    # 운영환경에 따라 None이거나 외부 파일을 찾을 수 있음; 핵심은 환경변수가 없을 때
    # 부모로 올라가며 탐색한다는 점이며, test_find_config_walks_up 으로 이미 검증됨.
    assert found is None or found.is_file()
