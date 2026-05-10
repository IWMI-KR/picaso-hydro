"""
PICASO 힌드캐스트 예보 확률 → acidwg_py 입력 파일(forecast_csv) 변환 모듈

PICASO 원본 자료 구조
----------------------
  {picaso_dir}/prec/{MON}/{YEAR}/TP_{MON}_{YEAR}_LT{lt}.csv  — 강수 확률
  {picaso_dir}/t2m/{MON}/{YEAR}/TT_{MON}_{YEAR}_LT{lt}.csv   — 기온 확률

  컬럼: stnid, an, nn, bn, Fcst, Category, fcst_min, ...
  (an+nn+bn = 100)

출력 형식 (acidwg_py forecast_csv)
---------------------------------
  컬럼: station_id, month, variable, AN, NN, BN
  파일명: {year}_{season}_picaso.csv
  예) 2014_JFM_picaso.csv

Lead Time 규칙
--------------
  3개월 예보 시즌의 각 월에 LT(Lead Time) 1, 2, 3을 순서대로 할당합니다.
  예) JFM 2014 예보 (12월 발표 기준):
      JAN → prec/JAN/2014/TP_JAN_2014_LT1.csv  (LT=1)
      FEB → prec/FEB/2014/TP_FEB_2014_LT2.csv  (LT=2)
      MAR → prec/MAR/2014/TP_MAR_2014_LT3.csv  (LT=3)

  연도 경계를 넘는 시즌 처리 (예: NDJ 2025):
      NOV → prec/NOV/2025/TP_NOV_2025_LT1.csv  (YYYY=2025)
      DEC → prec/DEC/2025/TP_DEC_2025_LT2.csv  (YYYY=2025)
      JAN → prec/JAN/2026/TP_JAN_2026_LT3.csv  (YYYY+1, 1 < 11)

관측소 필터
-----------
  1_acidwg/config/stations.csv의 ID 컬럼(WMO stnid)에 해당하는
  관측소만 출력에 포함합니다.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from acidwg_py.config import SEASON_MONTHS

# 월 번호 → 3글자 대문자 약어
MONTH_TO_ABB: dict[int, str] = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR",
    5: "MAY", 6: "JUN", 7: "JUL", 8: "AUG",
    9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}

# 변수 유형 → 폴더명 / 파일 접두사
_VAR_META = {
    "prcp": ("prec", "TP"),
    "t2m":  ("t2m",  "TT"),
}


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _picaso_path(picaso_dir: Path, var: str, month_str: str,
                 file_year: int, lt: int) -> Path:
    """PICASO 원본 CSV 파일 경로를 반환합니다."""
    folder, prefix = _VAR_META[var]
    return (picaso_dir / folder / month_str / str(file_year)
            / f"{prefix}_{month_str}_{file_year}_LT{lt}.csv")


def _read_picaso(fpath: Path, target_ids: list[str]) -> pd.DataFrame:
    """PICASO CSV를 읽어 대상 관측소의 stnid, an, nn, bn 반환합니다."""
    df = pd.read_csv(fpath)
    df.columns = df.columns.str.strip().str.lower()
    df["stnid"] = df["stnid"].astype(str)
    return df.loc[df["stnid"].isin(target_ids), ["stnid", "an", "nn", "bn"]].copy()


def _file_year(month: int, first_month: int, year: int) -> int:
    """시즌 첫 월보다 작은 월(다음 해로 넘어가는 월)의 실제 파일 연도 계산."""
    return year + 1 if month < first_month else year


# ── 공개 API ──────────────────────────────────────────────────────────────────

def build_picaso_forecast_csv(
    picaso_dir: str,
    stations_csv: str,
    output_dir: str,
    season: str,
    year: int,
) -> Optional[str]:
    """단일 season/year에 대한 acidwg_py 입력 CSV를 생성합니다.

    Parameters
    ----------
    picaso_dir   : PICASO 원본 자료 루트 디렉토리
                   (예: PICASO-Hydro/0_database/picaso)
    stations_csv : 대상 관측소 목록 CSV
                   (ID 컬럼에 WMO stnid 값 포함)
    output_dir   : 출력 디렉토리 (예: PICASO-Hydro/1_acidwg/picaso)
    season       : APCC 3개월 계절 코드 (예: "JFM", "DJF", "NDJ")
    year         : 예보 연도 — 시즌 첫 번째 월의 연도
                   예) JFM 2014 → year=2014,  NDJ 2025 → year=2025

    Returns
    -------
    str
        생성된 파일 경로. 필요한 원본 파일이 없거나 해당 관측소 자료가
        없으면 ``None``을 반환합니다.
    """
    season = season.upper()
    if season not in SEASON_MONTHS:
        raise ValueError(
            f"지원하지 않는 계절 코드: '{season}'\n"
            f"  사용 가능: {list(SEASON_MONTHS.keys())}"
        )

    months = SEASON_MONTHS[season]
    first_month = months[0]
    picaso_dir = Path(picaso_dir)

    # 관측소 ID 로드 (WMO stnid → str 형식으로 정규화)
    stn_df = pd.read_csv(stations_csv)
    stn_df.columns = stn_df.columns.str.strip()
    target_ids = stn_df["ID"].astype(str).tolist()

    rows: list[dict] = []

    for lt, month in enumerate(months, start=1):
        fy = _file_year(month, first_month, year)
        month_str = MONTH_TO_ABB[month]

        for var in ("prcp", "t2m"):
            fpath = _picaso_path(picaso_dir, var, month_str, fy, lt)
            if not fpath.exists():
                return None   # 원본 파일 미존재 → 해당 season/year 건너뜀

            sub = _read_picaso(fpath, target_ids)
            if sub.empty:
                continue

            for _, row in sub.iterrows():
                rows.append({
                    "station_id": row["stnid"],
                    "month":      month,
                    "variable":   var,
                    "AN":         int(round(float(row["an"]))),
                    "NN":         int(round(float(row["nn"]))),
                    "BN":         int(round(float(row["bn"]))),
                })

    if not rows:
        return None

    out_df = pd.DataFrame(rows, columns=["station_id", "month", "variable",
                                          "AN", "NN", "BN"])
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(output_dir) / f"{year}_{season}_picaso.csv"
    out_df.to_csv(out_path, index=False)
    return str(out_path)


def build_all_picaso_forecasts(
    picaso_dir: str,
    stations_csv: str,
    output_dir: str,
    seasons: Optional[List[str]] = None,
    years: Optional[List[int]] = None,
) -> Tuple[List[str], List[str]]:
    """모든 season/year 조합에 대해 일괄 변환합니다.

    Parameters
    ----------
    picaso_dir   : PICASO 원본 자료 루트 디렉토리
    stations_csv : 대상 관측소 목록 CSV
    output_dir   : 출력 디렉토리
    seasons      : 변환할 계절 목록 (None → SEASON_MONTHS 전체 12개)
    years        : 변환할 연도 목록 (None → 각 시즌 첫 월 디렉토리로 자동 감지)

    Returns
    -------
    (created, skipped)
        created : 생성된 파일 경로 목록
        skipped : 원본 파일 미존재로 건너뛴 "{year}_{season}" 목록
    """
    if seasons is None:
        seasons = list(SEASON_MONTHS.keys())

    created: List[str] = []
    skipped: List[str] = []

    for season in seasons:
        season = season.upper()
        months = SEASON_MONTHS[season]
        first_month_str = MONTH_TO_ABB[months[0]]

        # 연도 목록: 지정되지 않으면 첫 번째 월 디렉토리에서 자동 감지
        if years is None:
            first_month_dir = Path(picaso_dir) / "prec" / first_month_str
            if not first_month_dir.exists():
                continue
            candidate_years = sorted(
                int(d.name) for d in first_month_dir.iterdir() if d.is_dir()
            )
        else:
            candidate_years = sorted(years)

        for year in candidate_years:
            out_path = build_picaso_forecast_csv(
                picaso_dir, stations_csv, output_dir, season, year
            )
            if out_path:
                created.append(out_path)
            else:
                skipped.append(f"{year}_{season}")

    return created, skipped
