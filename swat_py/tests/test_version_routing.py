"""env.py — model.type → output 폴더 자동 산출 + mismatch 경고 검증."""
from __future__ import annotations

import warnings
from pathlib import Path
from textwrap import dedent

import pytest

from swat_py.config.env import (
    VALID_MODEL_TYPES,
    _auto_output_root,
    load_config,
)


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "swat_py.yaml"
    p.write_text(body, encoding="utf-8")
    return p


# ── 자동 산출 ────────────────────────────────────────────────────────────────

def test_auto_output_root_swat_plus() -> None:
    assert _auto_output_root("/proj", "swat_plus") == "/proj/3_swatplus"


def test_auto_output_root_swat2012() -> None:
    assert _auto_output_root("/proj", "swat2012") == "/proj/3_swat2012"


def test_auto_output_root_empty_root() -> None:
    assert _auto_output_root("", "swat_plus") == ""


# ── load_config: model.type 별 자동 경로 ────────────────────────────────────

def test_load_config_swat_plus_auto_paths(tmp_path) -> None:
    p = _write_yaml(tmp_path, dedent("""
        project:
          root: "/proj"
        model:
          type: "swat_plus"
        stations:
          metadata_file: "stations.csv"
    """))
    with warnings.catch_warnings():
        warnings.simplefilter("error")        # 경고가 없어야 함
        cfg = load_config(p)
    assert Path(cfg.SwatRunDir)  == Path("/proj/3_swatplus/base_txtinout")
    assert Path(cfg.SwatObsDir)  == Path("/proj/3_swatplus/calibration")
    assert Path(cfg.SwatCcDir)   == Path("/proj/3_swatplus/cchange")
    assert Path(cfg.SwatFcstDir) == Path("/proj/3_swatplus/forecast")


def test_load_config_swat2012_auto_paths(tmp_path) -> None:
    p = _write_yaml(tmp_path, dedent("""
        project:
          root: "/proj"
        model:
          type: "swat2012"
          executable: "SWAT2020.exe"
        stations:
          metadata_file: "stations.csv"
    """))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        cfg = load_config(p)
    assert Path(cfg.SwatRunDir)  == Path("/proj/3_swat2012/base_txtinout")
    assert Path(cfg.SwatObsDir)  == Path("/proj/3_swat2012/calibration")
    assert Path(cfg.SwatCcDir)   == Path("/proj/3_swat2012/cchange")
    assert Path(cfg.SwatFcstDir) == Path("/proj/3_swat2012/forecast")
    assert cfg.Executable == "SWAT2020.exe"


def test_load_config_invalid_model_type_raises(tmp_path) -> None:
    p = _write_yaml(tmp_path, dedent("""
        project: { root: "/proj" }
        model:   { type: "swat3000" }
    """))
    with pytest.raises(ValueError, match="model.type"):
        load_config(p)


# ── 수동 오버라이드 ──────────────────────────────────────────────────────────

def test_user_override_takes_precedence(tmp_path) -> None:
    """yaml 에 output.swat_run 을 명시하면 자동 산출보다 우선."""
    p = _write_yaml(tmp_path, dedent("""
        project:
          root: "/proj"
          output:
            swat_run: "/custom/path/TxtInOut"
        model:
          type: "swat_plus"
    """))
    cfg = load_config(p)
    assert Path(cfg.SwatRunDir) == Path("/custom/path/TxtInOut")


# ── mismatch 경고 ───────────────────────────────────────────────────────────

def test_mismatch_warning_swat_plus_with_swat2012_path(tmp_path) -> None:
    """model.type=swat_plus 인데 경로에 3_swat2012 가 들어있으면 경고."""
    p = _write_yaml(tmp_path, dedent("""
        project:
          root: "/proj"
          output:
            swat_run: "/proj/3_swat2012/base_txtinout"
        model:
          type: "swat_plus"
    """))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        load_config(p)
    assert any("일치하지 않는" in str(w.message) for w in caught)


def test_mismatch_warning_swat2012_with_swatplus_path(tmp_path) -> None:
    """역방향: model.type=swat2012 인데 경로에 3_swatplus."""
    p = _write_yaml(tmp_path, dedent("""
        project:
          root: "/proj"
          output:
            calibration: "/proj/3_swatplus/calibration"
        model:
          type: "swat2012"
        stations:
          metadata_file: "stations.csv"
    """))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        load_config(p)
    assert any("일치하지 않는" in str(w.message) for w in caught)


def test_no_warning_when_paths_match(tmp_path) -> None:
    """경로와 model.type 이 일치하면 경고 없음."""
    p = _write_yaml(tmp_path, dedent("""
        project:
          root: "/proj"
          output:
            swat_run: "/proj/3_swatplus/base_txtinout"
        model:
          type: "swat_plus"
    """))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        load_config(p)
    mismatch = [w for w in caught if "일치하지 않는" in str(w.message)]
    assert not mismatch


# ── 상수 검증 ────────────────────────────────────────────────────────────────

def test_valid_model_types_constant() -> None:
    assert set(VALID_MODEL_TYPES) == {"swat_plus", "swat2012"}
