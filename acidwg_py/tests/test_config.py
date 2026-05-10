"""config.py — YAML 로더, 교차참조, 환경변수, season→sim_period 매핑 검증."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from acidwg_py.config import (
    SEASON_MONTHS,
    _expand_seasons,
    _expand_years,
    _resolve_string,
    _season_label,
    find_config,
    load_config,
)


# ── helper ───────────────────────────────────────────────────────────────────

# 모든 테스트가 공통으로 사용 — paths 4 필수 + operational 1 필수
_MIN_YAML = """
paths:
  station_csv: "/p/stations.csv"
  obs_dir:     "/p/obs"
  picaso_dir:  "/p/picaso"
  output_root: "/p/root"

operational:
  year:   2024
  season: "JJA"
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
    p = _write_yaml(tmp_path, _MIN_YAML)
    cfg = load_config(p)
    assert cfg["station_csv"]  == "/p/stations.csv"
    assert cfg["picaso_dir"]   == "/p/picaso"
    assert cfg["output_root"]  == "/p/root"
    assert cfg["sim_period"]   == [6, 7, 8]   # JJA
    assert cfg["forecast_year"] == 2024
    # operational 자동 산출 (Path 비교 — Windows 백슬래시 무관)
    # output_dir 은 year 까지만 — acid_run 이 내부에서 season 폴더 추가하므로
    assert Path(cfg["forecast_csv"]) == Path("/p/picaso/2024_JJA_picaso.csv")
    assert Path(cfg["output_dir"])   == Path("/p/root/operational/2024")
    assert cfg["n_ensemble"]   == 1000
    assert cfg["hindcast"] is None    # 블록 없음 → None


def test_missing_required_path_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
paths:
  station_csv: "/p/x.csv"
  # picaso_dir 누락
  obs_dir:     "/p/obs"
  output_root: "/p/root"
operational: { year: 2024, season: JJA }
""")
    with pytest.raises(ValueError, match="picaso_dir"):
        load_config(p)


def test_missing_operational_section_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
paths:
  station_csv: "/p/x.csv"
  obs_dir:     "/p/obs"
  picaso_dir:  "/p/picaso"
  output_root: "/p/root"
""")
    with pytest.raises(ValueError, match="operational 섹션"):
        load_config(p)


def test_legacy_forecast_key_gives_clear_error(tmp_path) -> None:
    """옛 'forecast:' 키 사용 시 명확한 안내 — operational 으로 바꾸라고 안내."""
    p = _write_yaml(tmp_path, """
paths:
  station_csv: "/p/x.csv"
  obs_dir:     "/p/obs"
  picaso_dir:  "/p/picaso"
  output_root: "/p/root"
forecast: { year: 2024, season: JJA }
""")
    with pytest.raises(ValueError, match="'forecast:' 키.*'operational:'"):
        load_config(p)


def test_missing_file_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


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
  base_dir:    "/data"
  station_csv: "$(paths.base_dir)/stations.csv"
  obs_dir:     "$(paths.base_dir)/obs"
  picaso_dir:  "$(paths.base_dir)/picaso"
  output_root: "$(paths.base_dir)/root"
operational: { year: 2024, season: JJA }
""")
    cfg = load_config(p)
    assert cfg["station_csv"] == "/data/stations.csv"
    assert cfg["picaso_dir"]  == "/data/picaso"


def test_cross_reference_unknown_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
paths:
  station_csv: "$(paths.no_such_key)/x.csv"
  obs_dir:     "/p/obs"
  picaso_dir:  "/p/picaso"
  output_root: "/p/root"
operational: { year: 2024, season: JJA }
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
  base_dir:    "${env:ACID_BASE}"
  station_csv: "$(paths.base_dir)/s.csv"
  obs_dir:     "$(paths.base_dir)/obs"
  picaso_dir:  "$(paths.base_dir)/picaso"
  output_root: "$(paths.base_dir)/root"
operational: { year: 2024, season: JJA }
""")
    cfg = load_config(p)
    assert cfg["station_csv"] == "/from/env/s.csv"


def test_env_var_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UNDEFINED_VAR", raising=False)
    p = _write_yaml(tmp_path, """
paths:
  base_dir:    "${env:UNDEFINED_VAR:/fallback}"
  station_csv: "$(paths.base_dir)/s.csv"
  obs_dir:     "$(paths.base_dir)/obs"
  picaso_dir:  "$(paths.base_dir)/picaso"
  output_root: "$(paths.base_dir)/root"
operational: { year: 2024, season: JJA }
""")
    cfg = load_config(p)
    assert cfg["station_csv"] == "/fallback/s.csv"


# ── operational: season vs months ────────────────────────────────────────────

def test_season_to_sim_period(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_YAML.replace('season: "JJA"', 'season: NDJ'))
    cfg = load_config(p)
    assert cfg["sim_period"] == [11, 12, 1]
    assert cfg["forecast_year"] == 2024
    assert Path(cfg["forecast_csv"]).name == "2024_NDJ_picaso.csv"


def test_months_overrides_season(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
paths:
  station_csv: "/p/stations.csv"
  obs_dir:     "/p/obs"
  picaso_dir:  "/p/picaso"
  output_root: "/p/root"
operational:
  year: 2024
  season: NDJ
  months: [6, 7]
""")
    cfg = load_config(p)
    assert cfg["sim_period"] == [6, 7]


def test_invalid_season_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_YAML.replace('season: "JJA"', 'season: XYZ'))
    with pytest.raises(ValueError, match="지원하지 않는 계절"):
        load_config(p)


def test_invalid_months_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, """
paths:
  station_csv: "/p/stations.csv"
  obs_dir:     "/p/obs"
  picaso_dir:  "/p/picaso"
  output_root: "/p/root"
operational:
  year: 2024
  months: [13, 14]
""")
    with pytest.raises(ValueError, match="범위 오류"):
        load_config(p)


# ── 관측 기간 검증 ───────────────────────────────────────────────────────────

def test_syear_must_be_less_than_eyear(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_YAML + """
observation:
  syear: 2010
  eyear: 1981
""")
    with pytest.raises(ValueError, match="syear"):
        load_config(p)


# ── 앙상블 ───────────────────────────────────────────────────────────────────

def test_n_ensemble_must_be_positive(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_YAML + """
ensemble:
  n_members: 0
""")
    with pytest.raises(ValueError, match="1 이상"):
        load_config(p)


def test_random_seed_null_becomes_none(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_YAML + """
ensemble:
  random_seed: null
""")
    cfg = load_config(p)
    assert cfg["random_seed"] is None


# ── hindcast 블록 ────────────────────────────────────────────────────────────

def test_hindcast_block_range_expansion(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_YAML + """
hindcast:
  years:   [1991, 1995]
  seasons: ["JFM", "JJA"]
""")
    cfg = load_config(p)
    assert cfg["hindcast"]["years"]   == [1991, 1992, 1993, 1994, 1995]
    assert cfg["hindcast"]["seasons"] == ["JFM", "JJA"]
    assert cfg["hindcast"]["observation_eyear_cap"] is True   # 기본값


def test_hindcast_explicit_years_list(tmp_path) -> None:
    """3개 이상 항목이면 명시 리스트로 인식."""
    p = _write_yaml(tmp_path, _MIN_YAML + """
hindcast:
  years:   [1991, 1995, 2010, 2015]
  seasons: "all"
""")
    cfg = load_config(p)
    assert cfg["hindcast"]["years"] == [1991, 1995, 2010, 2015]
    assert len(cfg["hindcast"]["seasons"]) == 12   # 'all' → 12 계절


def test_hindcast_seasons_all(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_YAML + """
hindcast:
  years:   [2000, 2002]
  seasons: "all"
""")
    cfg = load_config(p)
    assert set(cfg["hindcast"]["seasons"]) == set(SEASON_MONTHS.keys())


def test_hindcast_observation_eyear_cap_off(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_YAML + """
hindcast:
  years:   [2000, 2002]
  seasons: ["JFM"]
  observation_eyear_cap: false
""")
    cfg = load_config(p)
    assert cfg["hindcast"]["observation_eyear_cap"] is False


def test_hindcast_invalid_season_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_YAML + """
hindcast:
  years:   [2000, 2002]
  seasons: ["XYZ"]
""")
    with pytest.raises(ValueError, match="지원하지 않는 계절"):
        load_config(p)


def test_hindcast_invalid_years_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, _MIN_YAML + """
hindcast:
  years:   [2000]
  seasons: "all"
""")
    with pytest.raises(ValueError, match="hindcast.years"):
        load_config(p)


def test_no_hindcast_block(tmp_path) -> None:
    """hindcast 블록 없는 yaml 도 정상 로드 — operational 만 사용 가능."""
    p = _write_yaml(tmp_path, _MIN_YAML)
    cfg = load_config(p)
    assert cfg["hindcast"] is None


# ── _expand_years / _expand_seasons / _season_label 단위 ──────────────────────

def test_expand_years_range() -> None:
    assert _expand_years([1991, 1995]) == [1991, 1992, 1993, 1994, 1995]


def test_expand_years_single_pair_ascending_only() -> None:
    """[a, b] 에서 a > b 면 명시 리스트 (2-항목) 로 해석."""
    assert _expand_years([2010, 2005]) == [2010, 2005]


def test_expand_years_explicit_list() -> None:
    assert _expand_years([1991, 1995, 2010]) == [1991, 1995, 2010]


def test_expand_seasons_all() -> None:
    out = _expand_seasons("all")
    assert len(out) == 12 and "JFM" in out and "DJF" in out


def test_expand_seasons_list() -> None:
    assert _expand_seasons(["JFM", "fma"]) == ["JFM", "FMA"]   # 대소문자 무관


def test_season_label_known() -> None:
    assert _season_label([1, 2, 3]) == "JFM"
    assert _season_label([12, 1, 2]) == "DJF"


def test_season_label_unknown() -> None:
    assert _season_label([6, 7]) == "M6_7"


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
    p = tmp_path / "explicit.yaml"
    p.write_text("paths: {x: y}", encoding="utf-8")
    monkeypatch.setenv("ACIDWG_PY_CONFIG", str(p))
    found = find_config(start=tmp_path)
    assert found is not None and found.resolve() == p.resolve()
