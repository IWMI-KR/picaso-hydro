"""SWAT-Plus output file parsers.

Mirrors output_swat_plus.R :: Swat.Cha.Summary.Plus() and
Swat.Wb.Summary.Plus().
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from swat_py.output.aggregator import aggregate_output, add_date_parts

_M_TO_FT = 3.280839895013123


# ── channel_sd_day.txt parser ──────────────────────────────────────────────────

def _detect_colnames(path: Path) -> list[str]:
    """Scan file lines for the header row containing 'gis_id'."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "gis_id" in line.lower():
                parts = line.strip().split()
                return parts
    raise ValueError(f"Column header with 'gis_id' not found in {path}")


def parse_channel_sd_day(
    path: Path,
    outlet: int,
    sdate: str,
    skip: int = 3,
) -> Optional[pd.DataFrame]:
    """Parse channel_sd_day.txt and return daily data for *outlet*.

    Parameters
    ----------
    path:    Full path to ``channel_sd_day-{SimType}.txt``.
    outlet:  Channel GIS id (value in the ``gis_id`` column). QSWAT+ 채널 번호.
    sdate:   Simulation start date string ``"YYYY-01-01"`` (before warm-up skip).
    skip:    Header rows to skip (default 3).

    Returns
    -------
    DataFrame with columns: date, flo_out, sed_out, orgn_out, no3_out,
    nh3_out, no2_out, sedp_out, solp_out, ... (all raw channel output columns).
    Returns ``None`` if file cannot be read or outlet has no data.
    """
    path = Path(path)
    if not path.exists():
        return None

    colnames = _detect_colnames(path)

    try:
        df = pd.read_csv(
            path,
            sep=r"\s+",
            skiprows=skip,
            header=None,
            na_values=["-99", "-99.0"],
        )
    except Exception:
        return None

    if df.empty:
        return None

    # Filter on the gis_id column, located dynamically from the header row.
    # (열 순서: jday mon day yr unit gis_id name ... — gis_id 는 보통 index 5,
    #  단 하드코딩하지 않고 헤더에서 위치를 찾아 SWAT+ 버전 차이에 견고하게 대응.)
    try:
        gis_idx = [c.lower() for c in colnames].index("gis_id")
    except ValueError:
        return None
    if gis_idx >= df.shape[1]:
        return None
    df = df[df.iloc[:, gis_idx] == outlet].copy()
    if df.empty:
        return None

    n_cols = min(len(colnames), df.shape[1])
    df = df.iloc[:, :n_cols].copy()
    df.columns = colnames[:n_cols]

    # Assign dates.
    #  1순위: 파일의 실제 yr/mon/day 컬럼으로 구성 → warm-up(nyskip) 자동 반영,
    #         출력 시작일이 sim 시작과 달라도(예: nyskip>0) 정확.
    #  fallback: 해당 컬럼이 없으면 기존처럼 sdate 부터 일 순차 부여.
    n_rows = len(df)
    lc = {c.lower(): c for c in df.columns}
    if {"yr", "mon", "day"} <= set(lc):
        df["date"] = pd.to_datetime({
            "year":  df[lc["yr"]].astype(float).astype(int),
            "month": df[lc["mon"]].astype(float).astype(int),
            "day":   df[lc["day"]].astype(float).astype(int),
        })
    else:
        df["date"] = pd.date_range(start=pd.Timestamp(sdate),
                                   periods=n_rows, freq="D")
    df = df.reset_index(drop=True)

    return df


# ── outtype extraction ─────────────────────────────────────────────────────────

def extract_cha_outtype(df: pd.DataFrame, outtype: str) -> pd.DataFrame:
    """Extract and compute derived columns for a given output type.

    Parameters
    ----------
    df:       Raw channel DataFrame from :func:`parse_channel_sd_day`.
    outtype:  One of ``"flow"``, ``"sedc"``, ``"tnc"``, ``"tpc"``.

    Returns
    -------
    DataFrame with ``date`` plus outtype-specific columns.
    """
    result = pd.DataFrame({"date": df["date"]})

    if outtype == "flow":
        result["flow_cms"] = df["flo_out"]

    elif outtype == "sedc":
        result["Sed_mgl"] = (
            (df["sed_out"] * 1e6) / (df["flo_out"] * 86400)
        )

    elif outtype == "tnc":
        flow_s = df["flo_out"] * 86400
        result["OrgN_mgl"] = df["orgn_out"] * 1e3 / flow_s
        result["NO3_mgl"]  = df["no3_out"]  * 1e3 / flow_s
        result["NH4_mgl"]  = df["nh3_out"]  * 1e3 / flow_s
        result["NO2_mgl"]  = df["no2_out"]  * 1e3 / flow_s
        result["TN_mgl"]   = (
            result["OrgN_mgl"] + result["NO3_mgl"]
            + result["NH4_mgl"] + result["NO2_mgl"]
        )

    elif outtype == "tpc":
        flow_s = df["flo_out"] * 86400
        result["OrgP_mgl"] = df["sedp_out"] * 1e3 / flow_s
        result["MinP_mgl"] = df["solp_out"] * 1e3 / flow_s
        result["TP_mgl"]   = result["OrgP_mgl"] + result["MinP_mgl"]

    else:
        raise ValueError(f"Unknown outtype '{outtype}'. Use flow/sedc/tnc/tpc.")

    return result


# ── reservoir_day.txt parser ────────────────────────────────────────────────────
#
#  QSWAT+ 댐(저수지)은 SWAT+ 'reservoir' 객체로 모형화되며, 채널이 아니라
#  reservoir_day.txt 에 일자료가 출력된다 (channel_sd_day.txt 에는 없음).
#
#  파일 구조 (SWAT+ rev.61):
#    L0 : 제목        L1 : 컬럼명(gis_id 포함)   L2 : 단위행     L3+ : 데이터
#  주요 컬럼/단위: unit(저수지 번호) gis_id(=QSWAT+ 저수지 gis_id) name area(ha)
#                 precip(m^3) evap(m^3) seep(m^3) flo_stor(m^3) ... flo_out(m^3/s)
#
#  댐 수위(stage) 보정: SWAT+ 는 stage 를 직접 출력하지 않으므로 저장량(flo_stor)
#  과 수면적(area)에서 수위를 추정한다.  reservoir_storage_to_stage() 참조.

def parse_reservoir_day(
    path: Path,
    outlet: int,
    sdate: str,
    skip: int = 3,
    filter_col: str = "gis_id",
) -> Optional[pd.DataFrame]:
    """Parse reservoir_day.txt and return daily data for one reservoir.

    channel 파서(:func:`parse_channel_sd_day`)와 동일한 방식이나, 저수지 출력
    파일을 읽고 ``gis_id``(기본) 또는 ``unit`` 컬럼으로 대상 저수지를 고른다.

    Parameters
    ----------
    path:        ``reservoir_day.txt`` (또는 rename 된 ``reservoir_day-{Sim}.txt``).
    outlet:      대상 저수지 식별자. ``filter_col`` 컬럼의 값과 일치.
                 QSWAT+ 저수지 gis_id (reservoir_con.gis_id, 예: res4 → 4).
    sdate:       시뮬레이션 시작일 ``"YYYY-01-01"`` (yr/mon/day 컬럼 없을 때 fallback).
    skip:        건너뛸 헤더 행 수 (기본 3: 제목·컬럼명·단위).
    filter_col:  대상 선택 컬럼 (``"gis_id"`` 기본, 또는 ``"unit"``).

    Returns
    -------
    DataFrame(date + flo_stor, area, flo_out, precip, evap, seep, ...) 또는
    파일이 없거나 대상 저수지 자료가 없으면 ``None``.
    """
    path = Path(path)
    if not path.exists():
        return None

    colnames = _detect_colnames(path)

    try:
        df = pd.read_csv(
            path,
            sep=r"\s+",
            skiprows=skip,
            header=None,
            na_values=["-99", "-99.0"],
        )
    except Exception:
        return None
    if df.empty:
        return None

    try:
        fcol = [c.lower() for c in colnames].index(filter_col.lower())
    except ValueError:
        return None
    if fcol >= df.shape[1]:
        return None
    df = df[df.iloc[:, fcol] == outlet].copy()
    if df.empty:
        return None

    n_cols = min(len(colnames), df.shape[1])
    df = df.iloc[:, :n_cols].copy()
    df.columns = colnames[:n_cols]

    lc = {c.lower(): c for c in df.columns}
    if {"yr", "mon", "day"} <= set(lc):
        df["date"] = pd.to_datetime({
            "year":  df[lc["yr"]].astype(float).astype(int),
            "month": df[lc["mon"]].astype(float).astype(int),
            "day":   df[lc["day"]].astype(float).astype(int),
        })
    else:
        df["date"] = pd.date_range(start=pd.Timestamp(sdate),
                                   periods=len(df), freq="D")
    return df.reset_index(drop=True)


def reservoir_storage_to_stage(
    storage_m3: "pd.Series | float",
    area_ha: "pd.Series | float",
    *,
    shape_factor: float = 1.0,
    datum_m: float = 0.0,
) -> "pd.Series | float":
    """저수지 저장량 → 수위(stage) 추정.

    SWAT+ 는 저수지 stage 를 직접 출력하지 않는다. 본 함수는 **저수지 출력 자체**
    (저장량 ``flo_stor`` m³, 수면적 ``area`` ha)만으로 수위를 추정하므로 단위가
    모호한 hydrology.res 매개변수에 의존하지 않는다.

    방법
    ----
    수위-저장 관계를 단순 기하로 근사::

        stage(m) = datum_m + shape_factor · V / A

        V = 저장량(m³),  A = 수면적(m²) = area_ha × 10⁴

    - ``shape_factor = 1.0`` : 각주형(prismatic, 수직벽) → V/A = **평균 수심**.
    - ``shape_factor = 2.0`` : 쐐기형(선형 면적-수심, A ∝ h) → 표면 수심.
    실제 저수지는 두 값 사이. ``datum_m`` 은 관측 수위계 기준면(staff-gauge
    datum) 보정용 오프셋으로, 보정 시 관측과 맞추는 자유 매개변수로 둔다.

    주의(검증 필요)
    --------------
    - 관측 자료가 절대 수위(ft, 기준면 포함)라면 ``datum_m``/``shape_factor``
      를 관측에 맞춰 보정하거나, 편차(anomaly)/정규화 공간에서 목적함수를 평가할 것.
    - ``area`` 가 0(빈 저수지)이면 결과는 NaN(0 division 회피).
    """
    A_m2 = (area_ha if not isinstance(area_ha, (int, float)) else float(area_ha))
    A_m2 = A_m2 * 1.0e4  # ha → m²
    if isinstance(storage_m3, (int, float)) and isinstance(A_m2, float):
        if A_m2 <= 0:
            return float("nan")
        return datum_m + shape_factor * float(storage_m3) / A_m2
    # Series 경로: 0 division → NaN
    A_series = A_m2 if hasattr(A_m2, "where") else pd.Series(A_m2)
    safe_A = A_series.where(A_series > 0)
    return datum_m + shape_factor * storage_m3 / safe_A


def read_hydrology_res(path: Path, name: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """hydrology.res 를 읽어 저수지별 stage-storage 매개변수를 반환.

    Returns ``{res_name: {area_ps, vol_ps, area_es, vol_es, k, evap_co,
    shp_co1, shp_co2}}``.  ``name`` 지정 시 해당 저수지만.

    참고: SWAT+ hydrology.res 의 area/vol 단위는 버전·설정에 따라 다를 수 있어
    (ha vs km², ha·m vs Mm³) 절대 수위 환산에 직접 쓰기보다 형상 비교용으로 남긴다.
    수위 추정은 단위가 명확한 reservoir_day.txt 기반
    :func:`reservoir_storage_to_stage` 를 권장.
    """
    path = Path(path)
    cols = ["area_ps", "vol_ps", "area_es", "vol_es", "k",
            "evap_co", "shp_co1", "shp_co2"]
    out: Dict[str, Dict[str, float]] = {}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for ln in lines[2:]:            # L0 제목, L1 헤더
        parts = ln.split()
        if len(parts) < 4:
            continue
        rname = parts[0]
        nums = parts[3:]            # name yr_op mon_op <8 vals>
        vals = {}
        for i, c in enumerate(cols):
            try:
                vals[c] = float(nums[i])
            except (ValueError, IndexError):
                vals[c] = float("nan")
        out[rname] = vals
    if name is not None:
        return {name: out[name]} if name in out else {}
    return out


def extract_res_outtype(
    df: pd.DataFrame,
    outtype: str,
    *,
    curve: "object | None" = None,
    datum_offset_ft: float = 0.0,
    interp: str = "pchip",
    storage_override: "object | None" = None,
    shape_factor: float = 1.0,
    datum_m: float = 0.0,
) -> pd.DataFrame:
    """저수지 raw DataFrame → 보정용 파생 컬럼.

    Parameters
    ----------
    df:       :func:`parse_reservoir_day` 결과.
    outtype:  ``"wlevel"`` | ``"resstor"`` | ``"resflow"``.
    curve:    :class:`swat_py.io.reservoir.StageStorageCurve` (선택).
              지정 시 **실측 수위-내용적 곡선**으로 저류량(flo_stor)→수위 환산
              (권장). ``datum_offset_ft`` 를 더해 관측 datum 과 정합.
    datum_offset_ft:  곡선 수위(ft) 에 더할 오프셋 (관측 staff-gauge datum 보정).
    interp:   곡선 보간 방식 ``"pchip"`` | ``"linear"``.
    storage_override:  취수 반영 등으로 재계산한 저류량(m³) Series(선택). 지정 시
                       ``flo_stor`` 대신 이 값으로 수위(wlevel) 환산
                       (:func:`swat_py.io.reservoir.simulate_managed_storage`).
    shape_factor, datum_m:  **곡선 미지정 시** fallback 근사
                            (:func:`reservoir_storage_to_stage`, stage=datum_m+shape·V/A).

    Returns
    -------
    DataFrame(date + outtype별 컬럼).
      - wlevel  : wlevel_ft (+ 곡선 사용 시 wlevel_m)
      - resstor : stor_m3, stor_1e4m3
      - resflow : flow_cms   (방류량)

    단위 주의: 채널(channel_sd_day)의 ``flo_out`` 은 m³/s 이지만, **저수지
    (reservoir_day)의 ``flo_in``/``flo_out`` 은 일 부피(m³/day)** 이다(질량수지로
    확인됨). ``resflow`` 는 m³/day → m³/s (÷86400) 로 환산해 채널과 단위를 맞춘다.
    """
    result = pd.DataFrame({"date": df["date"]})
    lc = {c.lower(): c for c in df.columns}

    if outtype == "wlevel":
        stor = storage_override if storage_override is not None else df[lc["flo_stor"]]
        if curve is not None:
            # 실측 수위-내용적 곡선: 저류량(m³) → 수위(ft) + datum 보정
            import numpy as _np
            wl_ft = curve.storage_to_stage(_np.asarray(stor, dtype=float), interp=interp)
            wl_ft = wl_ft + datum_offset_ft
            result["wlevel_ft"] = wl_ft
            result["wlevel_m"] = wl_ft / _M_TO_FT
        else:
            # fallback: 저류량+수면적 기하 근사 (V/A)
            area = df[lc["area"]]
            wl_m = reservoir_storage_to_stage(
                stor, area, shape_factor=shape_factor, datum_m=datum_m,
            )
            result["wlevel_m"] = wl_m
            result["wlevel_ft"] = wl_m * _M_TO_FT

    elif outtype == "resstor":
        result["stor_m3"] = df[lc["flo_stor"]]
        result["stor_1e4m3"] = df[lc["flo_stor"]] / 1.0e4

    elif outtype == "resflow":
        # 저수지 flo_out 은 m³/day → m³/s 로 환산 (채널 flow_cms 와 정합)
        result["flow_cms"] = df[lc["flo_out"]] / 86400.0

    else:
        raise ValueError(
            f"Unknown reservoir outtype '{outtype}'. Use wlevel/resstor/resflow."
        )

    return result


# ── basin water-balance parser ─────────────────────────────────────────────────

def parse_basin_wb_day(
    path: Path,
    sdate: str,
    ws_area_km2: Optional[float] = None,
    skip: int = 9,
) -> Optional[pd.DataFrame]:
    """Parse basin_wb_day.txt.

    Returns a raw DataFrame; further extraction mirrors
    Swat.Wb.Summary.Plus().
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, sep=r"\s+", skiprows=skip, header=None)
    except Exception:
        return None

    if df.empty:
        return None

    n_rows = len(df)
    start = pd.Timestamp(sdate)
    df["date"] = pd.date_range(start=start, periods=n_rows, freq="D")
    return df
