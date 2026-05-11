"""SWAT 입력 파일의 인자값 변경 — 보정 알고리즘 backend.

핵심 함수
---------
- apply_change(old_value, change_type, value) — 단일 값 변경 계산
- modify_swat_plus_file(path, parameter, value, change_type) — SWAT-Plus 텍스트
- modify_swat2012_file(path, parameter, value, change_type) — SWAT 2012 텍스트
- apply_parameter_set(txtinout_dir, changes, model_type) — 다수 인자 일괄

SWAT-Plus 파일 포맷
-------------------
첫 줄 타이틀, 둘째 줄 공백 구분 컬럼명, 셋째 줄부터 데이터 (공백 구분).
일부 파일 (basin.bsn 등) 은 단일 행, 다른 파일 (hru-data.hru) 은 다수 행.

SWAT 2012 파일 포맷
-------------------
파일별 다양. 일반적으로 각 줄이 ``value | parameter_name | comment`` 형식이지만
.bsn (basin.bsn) 은 한 인자에 한 줄. 라인 기반 정규식 파싱 사용.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union


# ── 값 변경 계산 ────────────────────────────────────────────────────────────

def apply_change(old_value: float, change_type: str, value: float) -> float:
    """change_type 에 따라 old_value 에서 새 값 계산.

    Parameters
    ----------
    old_value   : 기존 값
    change_type : absval | abschg | relchg | pctchg
    value       : 변경 적용값

    Returns
    -------
    new_value
    """
    if change_type == "absval":
        return float(value)
    if change_type == "abschg":
        return float(old_value) + float(value)
    if change_type == "relchg":
        return float(old_value) * (1.0 + float(value))
    if change_type == "pctchg":
        return float(old_value) * (1.0 + float(value) / 100.0)
    raise ValueError(
        f"미지원 change_type: '{change_type}'. "
        "허용: absval | abschg | relchg | pctchg"
    )


# ── SWAT-Plus 파일 수정 ─────────────────────────────────────────────────────

def modify_swat_plus_file(
    path: Union[str, Path],
    parameter: str,
    value: float,
    change_type: str = "absval",
    *,
    rows: Optional[List[int]] = None,
) -> List[Tuple[int, float, float]]:
    """SWAT-Plus 입력 파일에서 컬럼 'parameter' 의 값 변경.

    포맷 가정: 1행 주석/타이틀, 2행 컬럼명 (공백 구분), 3행+ 데이터.

    Parameters
    ----------
    path       : 입력 파일 경로
    parameter  : 컬럼명 (SWAT-Plus 표준 — 소문자)
    value      : 변경 적용값
    change_type: 적용 방식
    rows       : 수정할 데이터 행 인덱스 (0-based). None 이면 전체

    Returns
    -------
    list of (row_idx, old_value, new_value)
    """
    import pandas as pd

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"파일 없음: {path}")

    # 첫 줄 주석 유지, 둘째 줄 헤더로 사용
    with path.open("r", encoding="utf-8") as f:
        title_line = f.readline()
        # pandas 가 처리할 수 있도록 다시 읽기 — skiprows=1, sep=공백
    df = pd.read_csv(path, sep=r"\s+", skiprows=1, engine="python")
    if parameter not in df.columns:
        raise KeyError(
            f"파라미터 '{parameter}' 가 {path.name} 에 없음. "
            f"가능: {list(df.columns)}"
        )

    target_rows = list(range(len(df))) if rows is None else rows
    changes: List[Tuple[int, float, float]] = []
    for ri in target_rows:
        old = float(df.iloc[ri][parameter])
        new = apply_change(old, change_type, value)
        df.at[df.index[ri], parameter] = new
        changes.append((ri, old, new))

    # 동일 포맷 (1행 주석 + 헤더 + 공백 구분 데이터) 으로 다시 쓰기
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(title_line.rstrip("\n") + "\n")
        # 헤더 + 데이터
        f.write(" ".join(df.columns) + "\n")
        for _, row in df.iterrows():
            f.write(" ".join(f"{v}" for v in row.values) + "\n")

    return changes


# ── SWAT 2012 파일 수정 ─────────────────────────────────────────────────────

# SWAT 2012 의 한 줄 형식: "   {value}    | {PARAM_NAME} : description"
# 또는 "value PARAM" 단순형. 정규식으로 PARAM_NAME 일치 라인 찾음.
_SWAT2012_LINE_RE = re.compile(
    r"^(\s*)([-+\d\.Ee]+)(\s*\|\s*)([A-Z_0-9]+)(.*)$"
)


def modify_swat2012_file(
    path: Union[str, Path],
    parameter: str,
    value: float,
    change_type: str = "absval",
) -> List[Tuple[int, float, float]]:
    """SWAT 2012 입력 파일에서 PARAMETER 라인의 값 변경.

    Parameters
    ----------
    path       : 입력 파일 경로 (예: file.bsn, file.gw)
    parameter  : 인자명 (대문자, 예: CN2, ALPHA_BF)
    value      : 변경 적용값
    change_type: 적용 방식

    Returns
    -------
    list of (line_idx, old_value, new_value)
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"파일 없음: {path}")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=False)
    changes: List[Tuple[int, float, float]] = []
    parameter_up = parameter.upper()

    for i, line in enumerate(lines):
        m = _SWAT2012_LINE_RE.match(line)
        if not m:
            continue
        if m.group(4).upper() != parameter_up:
            continue
        old = float(m.group(2))
        new = apply_change(old, change_type, value)
        # 폭 유지 (원본 정렬 보존)
        old_width = len(m.group(2))
        new_str = f"{new:.5f}".rstrip("0").rstrip(".")
        if len(new_str) < old_width:
            new_str = new_str.rjust(old_width)
        lines[i] = f"{m.group(1)}{new_str}{m.group(3)}{m.group(4)}{m.group(5)}"
        changes.append((i, old, new))

    if not changes:
        raise KeyError(f"파라미터 '{parameter}' 가 {path.name} 에 없음")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changes


# ── 일괄 적용 (보정 알고리즘 backend) ───────────────────────────────────────

@dataclass
class ParameterChange:
    """일괄 인자 변경 명세 (yaml.calibration.parameters[] + 적용값)."""
    file:        str           # 파일명 또는 글롭 (예: basin.bsn, *.bsn)
    parameter:   str           # 인자명
    value:       float         # 적용값
    change_type: str = "absval"
    rows:        Optional[List[int]] = None  # SWAT-Plus 일부 행만


def apply_parameter_set(
    txtinout_dir: Union[str, Path],
    changes: List[ParameterChange],
    *,
    model_type: str = "swat_plus",
) -> List[dict]:
    """다수 인자 변경을 한 번에 적용.

    Parameters
    ----------
    txtinout_dir : SWAT 실행 폴더 (TxtInOut)
    changes      : ParameterChange 리스트
    model_type   : swat_plus | swat2012

    Returns
    -------
    list of dict — 각 변경의 결과 요약
        [{file, parameter, change_type, value, n_rows_changed, details}, ...]
    """
    txtinout_dir = Path(txtinout_dir)
    if not txtinout_dir.is_dir():
        raise FileNotFoundError(f"TxtInOut 폴더 없음: {txtinout_dir}")

    log: List[dict] = []
    for ch in changes:
        # 글롭 패턴이면 매칭되는 모든 파일 처리, 명시 파일은 그 파일만
        files = sorted(txtinout_dir.glob(ch.file)) if "*" in ch.file else [
            txtinout_dir / ch.file
        ]
        for fp in files:
            if not fp.is_file():
                continue
            if model_type == "swat_plus":
                results = modify_swat_plus_file(
                    fp, ch.parameter, ch.value, ch.change_type, rows=ch.rows
                )
            else:
                results = modify_swat2012_file(
                    fp, ch.parameter, ch.value, ch.change_type
                )
            log.append({
                "file":            str(fp.relative_to(txtinout_dir)),
                "parameter":       ch.parameter,
                "change_type":     ch.change_type,
                "value":           ch.value,
                "n_rows_changed":  len(results),
                "details":         results,
            })
    return log


def backup_txtinout(txtinout_dir: Union[str, Path],
                     backup_dir: Union[str, Path]) -> Path:
    """TxtInOut 폴더 전체 복사 (변경 전 백업).

    Returns
    -------
    Path : 백업 폴더 경로
    """
    txtinout_dir = Path(txtinout_dir)
    backup_dir = Path(backup_dir)
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    shutil.copytree(txtinout_dir, backup_dir)
    return backup_dir
