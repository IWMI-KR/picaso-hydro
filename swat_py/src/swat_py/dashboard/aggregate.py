"""1000 멤버 SWAT 출력 → 월평균 + 분위수 집계."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd


def load_ensemble_outputs(
    ensemble_dir: Union[str, Path],
    *,
    outlet_id: int = 1,
    variable_col: str = "flo_out",
    model_type: str = "swat_plus",
    pattern: str = "member_*",
) -> pd.DataFrame:
    """1000 멤버 SWAT 출력을 한 DataFrame 으로 집계.

    Returns
    -------
    DataFrame — date 인덱스, 각 멤버가 컬럼 (member_0001, member_0002, ...)
    """
    ensemble_dir = Path(ensemble_dir)
    if not ensemble_dir.is_dir():
        raise FileNotFoundError(f"앙상블 폴더 없음: {ensemble_dir}")

    member_dirs = sorted(ensemble_dir.glob(pattern))
    if not member_dirs:
        raise FileNotFoundError(f"member_* 폴더 없음: {ensemble_dir}")

    if model_type == "swat_plus":
        from swat_py.output.reader_swat_plus import parse_channel_sd_day as parser
        output_file = "channel_sd_day.txt"
    else:
        from swat_py.output.reader_swat import parse_output_rch as parser
        output_file = "output.rch"

    df_dict: Dict[str, pd.Series] = {}
    for mdir in member_dirs:
        run = mdir / "TxtInOut" if (mdir / "TxtInOut").is_dir() else mdir
        out = run / output_file
        if not out.is_file():
            continue
        df = parser(out)
        # outlet 필터 — gis_id 또는 unit 컬럼
        sub = df[(df.get("gis_id", df.get("unit", -1)) == outlet_id) |
                  (df.get("RCH", -1) == outlet_id)]
        if len(sub) == 0:
            sub = df
        s = pd.Series(sub[variable_col].values,
                       index=pd.to_datetime(sub["date"].values),
                       name=mdir.name)
        df_dict[mdir.name] = s

    if not df_dict:
        raise RuntimeError(
            f"멤버 출력 파일이 하나도 없음. ensemble_dir={ensemble_dir}, "
            f"기대 파일={output_file}"
        )
    return pd.DataFrame(df_dict)


def aggregate_ensemble_monthly(
    ensemble_df: pd.DataFrame,
    *,
    quantiles: Sequence[float] = (0.05, 0.25, 0.50, 0.75, 0.95),
) -> pd.DataFrame:
    """일자료 1000-멤버 → 월평균 분위수.

    Returns
    -------
    DataFrame with columns: month (Period), mean, p5, p25, p50, p75, p95
    """
    # 일자료 → 월평균 (각 멤버별)
    monthly = ensemble_df.resample("MS").mean()   # 월 시작 (matches obs CSV convention)
    out = pd.DataFrame(index=monthly.index)
    out["mean"] = monthly.mean(axis=1)
    for q in quantiles:
        col = f"p{int(q * 100)}"
        out[col] = monthly.quantile(q, axis=1)
    out.index.name = "date"
    return out.reset_index()


def compute_terciles(
    forecast_values: Sequence[float],
    historical_p33: float,
    historical_p67: float,
) -> Dict[str, float]:
    """앙상블 값 → BN/NN/AN tercile 확률 (%).

    Parameters
    ----------
    forecast_values   : 앙상블 멤버 값들 (보통 forecast 기간 평균/합계)
    historical_p33,67 : 역사 baseline 의 33%, 67% 분위수

    Returns
    -------
    dict {below, normal, above} — 합 100
    """
    arr = np.asarray(forecast_values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return {"below": 33.0, "normal": 34.0, "above": 33.0}
    below = float((arr < historical_p33).sum()) / len(arr) * 100.0
    above = float((arr > historical_p67).sum()) / len(arr) * 100.0
    normal = 100.0 - below - above
    return {
        "below":  round(below, 1),
        "normal": round(normal, 1),
        "above":  round(above, 1),
    }


def historical_monthly_mean(
    obs_df: pd.DataFrame,
    value_col: str = "flow_m3s",
    *,
    syear: Optional[int] = None,
    eyear: Optional[int] = None,
) -> pd.DataFrame:
    """역사 관측 (또는 SWAT-ERA5) 일자료 → 월별 평균 (12 행).

    Returns
    -------
    DataFrame with: month (1~12), mean, p33, p67
    """
    df = obs_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    if syear is not None:
        df = df[df["date"].dt.year >= syear]
    if eyear is not None:
        df = df[df["date"].dt.year <= eyear]

    # 월별 평균 — 일자료 → 각 연-월 평균 → 모든 연도의 같은 월 평균
    df_clean = df.copy()
    df_clean[value_col] = df_clean[value_col].replace(-99, np.nan)
    df_clean = df_clean.dropna(subset=[value_col])
    df_clean["month"] = df_clean["date"].dt.month

    grouped = df_clean.groupby("month")[value_col]
    return pd.DataFrame({
        "month": list(range(1, 13)),
        "mean":  [grouped.mean().get(m,  np.nan) for m in range(1, 13)],
        "p33":   [grouped.quantile(0.33).get(m, np.nan) for m in range(1, 13)],
        "p67":   [grouped.quantile(0.67).get(m, np.nan) for m in range(1, 13)],
    })
