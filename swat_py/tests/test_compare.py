"""compare.parameters — default vs calibrated TxtInOut 비교 검증."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pandas as pd
import pytest

from swat_py.compare import compare_txtinout, parse_swat_input_file


def _write_swat_file(path: Path, header: list, rows: list) -> Path:
    """SWAT-Plus 형식 (line1: 주석, line2: 컬럼명, line3+: 데이터) 작성."""
    lines = ["# title comment"]
    lines.append(" ".join(header))
    for r in rows:
        lines.append(" ".join(str(v) for v in r))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ── parse_swat_input_file ────────────────────────────────────────────────────

def test_parse_swat_file_basic(tmp_path) -> None:
    p = _write_swat_file(tmp_path / "basin.bsn",
                         ["surlag", "cn3_swf"],
                         [[4.0, 0.85]])
    df = parse_swat_input_file(p)
    assert df is not None
    assert "surlag" in df.columns
    assert df["surlag"].iloc[0] == 4.0


def test_parse_missing_file_returns_none(tmp_path) -> None:
    assert parse_swat_input_file(tmp_path / "missing.bsn") is None


# ── compare_txtinout ────────────────────────────────────────────────────────

def test_compare_detects_changed_values(tmp_path) -> None:
    """default 와 calibrated 에서 값이 다른 셀만 산출."""
    d = tmp_path / "default"; d.mkdir()
    c = tmp_path / "calibrated"; c.mkdir()

    _write_swat_file(d / "basin.bsn", ["surlag", "cn3_swf"], [[4.0, 0.85]])
    _write_swat_file(c / "basin.bsn", ["surlag", "cn3_swf"], [[2.5, 0.85]])

    out = compare_txtinout(d, c, tmp_path / "changes.csv")
    df = pd.read_csv(out)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["file"] == "basin.bsn"
    assert row["parameter"] == "surlag"
    assert row["default"] == 4.0
    assert row["calibrated"] == 2.5
    assert row["delta"] == pytest.approx(-1.5)


def test_compare_empty_when_no_changes(tmp_path) -> None:
    """동일한 두 파일 → 결과 비어 있음 (헤더만)."""
    d = tmp_path / "default"; d.mkdir()
    c = tmp_path / "calibrated"; c.mkdir()
    _write_swat_file(d / "basin.bsn", ["surlag"], [[4.0]])
    _write_swat_file(c / "basin.bsn", ["surlag"], [[4.0]])

    out = compare_txtinout(d, c, tmp_path / "changes.csv")
    df = pd.read_csv(out)
    assert len(df) == 0
    assert list(df.columns) == ["file", "parameter", "row",
                                 "default", "calibrated", "delta"]


def test_compare_multiple_files_and_rows(tmp_path) -> None:
    """여러 파일 × 여러 행 변경 모두 추출."""
    d = tmp_path / "default"; d.mkdir()
    c = tmp_path / "calibrated"; c.mkdir()

    _write_swat_file(d / "basin.bsn", ["surlag"], [[4.0]])
    _write_swat_file(c / "basin.bsn", ["surlag"], [[2.0]])

    _write_swat_file(d / "hydrology.hyd",
                     ["cn3_swf", "esco"],
                     [[0.85, 0.95], [0.85, 0.95]])
    _write_swat_file(c / "hydrology.hyd",
                     ["cn3_swf", "esco"],
                     [[0.70, 0.95], [0.75, 0.90]])

    out = compare_txtinout(d, c, tmp_path / "changes.csv")
    df = pd.read_csv(out)
    # basin.bsn 1 행 + hydrology.hyd 3 행 = 4
    assert len(df) == 4
    assert set(df["file"].unique()) == {"basin.bsn", "hydrology.hyd"}
    # row 0 의 cn3_swf, row 1 의 cn3_swf, row 1 의 esco
    hyd = df[df["file"] == "hydrology.hyd"]
    assert {(r["row"], r["parameter"]) for _, r in hyd.iterrows()} == {
        (0, "cn3_swf"), (1, "cn3_swf"), (1, "esco")
    }


def test_compare_target_files_explicit(tmp_path) -> None:
    """target_files 명시 시 해당 파일만 비교."""
    d = tmp_path / "default"; d.mkdir()
    c = tmp_path / "calibrated"; c.mkdir()
    _write_swat_file(d / "basin.bsn",   ["x"], [[1.0]])
    _write_swat_file(c / "basin.bsn",   ["x"], [[2.0]])
    _write_swat_file(d / "other.txt",   ["y"], [[1.0]])
    _write_swat_file(c / "other.txt",   ["y"], [[3.0]])

    # other.txt 만 명시 — basin.bsn 변경은 무시됨
    out = compare_txtinout(d, c, tmp_path / "changes.csv",
                            target_files=["other.txt"])
    df = pd.read_csv(out)
    assert len(df) == 1
    assert df["file"].iloc[0] == "other.txt"


def test_compare_missing_dir_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        compare_txtinout(tmp_path / "no_default",
                          tmp_path / "no_calibrated",
                          tmp_path / "out.csv")
