"""TxtInOut 인자 비교 — default vs calibrated 차이를 CSV 로 추출.

SWAT-Plus / SWAT 2012 의 주요 입력 텍스트 파일 (space-separated, 헤더 라인)
사이에서 셀-by-셀로 다른 값을 찾아 long-format CSV 로 산출합니다.

산출 CSV 컬럼
--------------
file, parameter, row, default, calibrated, delta

- file       : 비교 대상 파일명 (basin.bsn, hydrology.hyd 등)
- parameter  : 헤더 라인의 컬럼 이름
- row        : 데이터 행 인덱스 (0-based, 다중 행 파일 식별용)
- default    : default TxtInOut 의 값
- calibrated : calibrated TxtInOut 의 값
- delta      : (수치인 경우) calibrated - default
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

import pandas as pd


# SWAT-Plus + SWAT 2012 의 주요 보정 대상 입력 파일들 (확장자 기준)
# 너무 큰 파일 (HRU 수만 개 행) 은 첫 N행만 미리보기 하거나 사용자가 명시할 때만.
_DEFAULT_TARGET_FILES = {
    # SWAT-Plus
    "basin.bsn",
    "hydrology.hyd",
    "snow.sno",
    "soils.sol",
    "plants.plt",
    "fertilizer.frt",
    "tillage.til",
    "urban.urb",
    "pesticide.pes",
    # SWAT 2012 (확장자 기준)
    "*.bsn",
    "*.wwq",
    "*.swq",
}


def parse_swat_input_file(path: Union[str, Path]) -> Optional[pd.DataFrame]:
    """SWAT 입력 텍스트 파일 → DataFrame.

    SWAT-Plus 표준 형식 가정:
        line 1: 타이틀/주석
        line 2: 컬럼 이름들 (공백 구분)
        line 3+: 데이터 행 (공백 구분)

    실패 시 None.
    """
    path = Path(path)
    if not path.is_file():
        return None
    try:
        # whitespace separator, 두 번째 줄을 헤더로
        df = pd.read_csv(path, sep=r"\s+", skiprows=1, engine="python")
        return df
    except Exception:
        return None


def _diff_dataframes(
    df_def: pd.DataFrame, df_cal: pd.DataFrame, fname: str
) -> List[dict]:
    """두 동일 구조 DataFrame 의 셀별 차이를 long-format dict 리스트로."""
    rows: List[dict] = []
    common_cols = [c for c in df_def.columns if c in df_cal.columns]
    n_rows = min(len(df_def), len(df_cal))
    for ri in range(n_rows):
        for col in common_cols:
            v_def = df_def[col].iloc[ri]
            v_cal = df_cal[col].iloc[ri]
            # 동일하면 skip
            try:
                if pd.isna(v_def) and pd.isna(v_cal):
                    continue
                if v_def == v_cal:
                    continue
            except Exception:
                continue
            # delta (가능한 경우만)
            delta: object = ""
            try:
                delta = float(v_cal) - float(v_def)
            except (TypeError, ValueError):
                pass
            rows.append({
                "file":       fname,
                "parameter":  col,
                "row":        ri,
                "default":    v_def,
                "calibrated": v_cal,
                "delta":      delta,
            })
    return rows


def compare_txtinout(
    default_dir: Union[str, Path],
    calibrated_dir: Union[str, Path],
    output_csv: Union[str, Path],
    *,
    target_files: Optional[List[str]] = None,
) -> Path:
    """default TxtInOut vs calibrated TxtInOut → parameter_changes.csv 산출.

    Parameters
    ----------
    default_dir    : QSWAT+ 출력 (마스터, READ-ONLY)
    calibrated_dir : 보정 완료 (마스터, READ-ONLY)
    output_csv     : 출력 CSV 경로 (보통 calibration/results/parameter_changes.csv)
    target_files   : 비교할 파일명 리스트. None 이면 default + calibrated 양쪽에서
                     공통 존재하는 표준 보정 파일 (basin.bsn / hydrology.hyd 등) 자동 탐지.

    Returns
    -------
    Path : 산출된 CSV 경로

    출력 형식
    ---------
    file, parameter, row, default, calibrated, delta

    비어 있을 경우 (변경 없음) 헤더만 있는 CSV 가 생성됩니다.
    """
    default_dir = Path(default_dir)
    calibrated_dir = Path(calibrated_dir)
    output_csv = Path(output_csv)

    if not default_dir.is_dir():
        raise FileNotFoundError(f"default_dir 없음: {default_dir}")
    if not calibrated_dir.is_dir():
        raise FileNotFoundError(f"calibrated_dir 없음: {calibrated_dir}")

    if target_files is None:
        # 표준 후보 + 양쪽 폴더에 모두 존재하는 파일만
        candidates: List[str] = []
        for pat in _DEFAULT_TARGET_FILES:
            if "*" in pat:
                for p in default_dir.glob(pat):
                    candidates.append(p.name)
            else:
                if (default_dir / pat).is_file():
                    candidates.append(pat)
        target_files = sorted({
            f for f in candidates
            if (calibrated_dir / f).is_file()
        })

    all_rows: List[dict] = []
    for fname in target_files:
        df_def = parse_swat_input_file(default_dir / fname)
        df_cal = parse_swat_input_file(calibrated_dir / fname)
        if df_def is None or df_cal is None:
            continue
        all_rows.extend(_diff_dataframes(df_def, df_cal, fname))

    out = pd.DataFrame(all_rows,
                       columns=["file", "parameter", "row",
                                "default", "calibrated", "delta"])
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_csv, index=False)
    return output_csv
