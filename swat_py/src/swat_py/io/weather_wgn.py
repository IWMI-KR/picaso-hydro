"""SWAT-Plus weather-wgn.cli 작성 - 일자료에서 WGEN 매개변수 산출 + 직렬화.

목적
----
QSWAT+ 가 생성한 default/weather-wgn.cli 의 통계값은 외부 격자점 (CFSR 등) 기반
이라 사용자 유역의 실제 기후를 정확히 반영하지 못할 수 있다. 본 모듈은 사용자가
보유한 util_py 표준 daily CSV (date, pcp_mm, tmax_c, tmin_c, [slr_mjm2, tdew_c,
ws10_ms/ws2_ms]) 에서 직접 WGEN 14 매개변수를 산출하여 weather-wgn.cli 를 재생성한다.

WGEN 14 매개변수 (월별, SWAT-Plus 표준)
---------------------------------------
1.  tmp_max_ave : 일최고기온 월평균 (°C)
2.  tmp_min_ave : 일최저기온 월평균 (°C)
3.  tmp_max_sd  : 일최고기온 월표준편차 (°C)
4.  tmp_min_sd  : 일최저기온 월표준편차 (°C)
5.  pcp_ave     : 월총강수량 평균 (mm/month - 연별 합의 평균)
6.  pcp_sd      : 강수일 일강수량 표준편차 (mm/day)
7.  pcp_skew    : 강수일 일강수량 왜도
8.  wet_dry     : P(wet|prev dry) - 1차 Markov 전이
9.  wet_wet     : P(wet|prev wet)
10. pcp_days    : 월별 평균 강수일수
11. pcp_hhr     : 월별 30분 최대 강수 (mm) - 일자료 산출 불가 → 0
12. slr_ave     : 월평균 일사 (MJ/m²/day)
13. dew_ave     : 월평균 이슬점 (°C)
14. wnd_ave     : 월평균 풍속 (m/s)

Wet day 기준: 일강수 ≥ 0.1 mm (SWAT 표준)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Union

import numpy as np
import pandas as pd


_WET_THRESHOLD_MM = 0.1

_WGN_COLUMNS: List[str] = [
    "tmp_max_ave", "tmp_min_ave",
    "tmp_max_sd",  "tmp_min_sd",
    "pcp_ave",     "pcp_sd",     "pcp_skew",
    "wet_dry",     "wet_wet",
    "pcp_days",    "pcp_hhr",
    "slr_ave",     "dew_ave",    "wnd_ave",
]

_DAILY_COL_ALIASES = {
    # util_py 표준
    "pcp_mm":   "pcp",
    "tmax_c":   "tmax",
    "tmin_c":   "tmin",
    "slr_mjm2": "slr",
    "tdew_c":   "dew",
    "ws10_ms":  "wnd",
    "ws2_ms":   "wnd",
    # legacy
    "prcp":     "pcp",
    "dewpt":    "dew",
    "wind":     "wnd",
    "solar":    "slr",
}


@dataclass
class WgnStation:
    """한 station 의 WGEN 매개변수 세트."""
    name:   str
    lat:    float
    lon:    float
    elev:   float
    years:  int             # 통계 산출에 사용된 자료 길이 (years)
    params: pd.DataFrame    # 12 row × _WGN_COLUMNS


def compute_wgn_params(
    daily: pd.DataFrame,
    *,
    syear: Optional[int] = None,
    eyear: Optional[int] = None,
    wet_threshold_mm: float = _WET_THRESHOLD_MM,
) -> pd.DataFrame:
    """일자료 → 12 month × 14 WGEN 매개변수 DataFrame.

    Required columns: date, {pcp_mm|prcp}, {tmax_c|tmax}, {tmin_c|tmin}
    Optional: slr_mjm2|solar, tdew_c|dewpt, ws10_ms|ws2_ms|wind
    """
    df = _normalize_daily(daily)
    if syear is not None:
        df = df[df["date"].dt.year >= syear]
    if eyear is not None:
        df = df[df["date"].dt.year <= eyear]
    if df.empty:
        raise ValueError(f"필터링 후 자료가 비어 있음 (syear={syear}, eyear={eyear})")

    df = df.sort_values("date").reset_index(drop=True)
    df["month"]    = df["date"].dt.month
    df["year"]     = df["date"].dt.year
    df["wet"]      = (df["pcp"].fillna(0) >= wet_threshold_mm).astype(int)
    df["prev_wet"] = df["wet"].shift(1)

    rows = []
    for m in range(1, 13):
        sub = df[df["month"] == m]
        if len(sub) == 0:
            rows.append({"month": m, **{c: 0.0 for c in _WGN_COLUMNS}})
            continue

        tmx = sub["tmax"].dropna()
        tmn = sub["tmin"].dropna()
        wet_pcp = sub.loc[sub["wet"] == 1, "pcp"].dropna()

        year_total = sub.groupby("year")["pcp"].sum(min_count=1)
        pcp_ave = float(year_total.mean()) if len(year_total) else 0.0
        year_wet_days = sub.groupby("year")["wet"].sum()
        pcp_days = float(year_wet_days.mean()) if len(year_wet_days) else 0.0

        # Markov 전이 — prev_wet 가 정의된 day 만
        lag = sub.dropna(subset=["prev_wet"])
        n_prev_dry = int((lag["prev_wet"] == 0).sum())
        n_prev_wet = int((lag["prev_wet"] == 1).sum())
        n_wd = int(((lag["wet"] == 1) & (lag["prev_wet"] == 0)).sum())
        n_ww = int(((lag["wet"] == 1) & (lag["prev_wet"] == 1)).sum())
        wet_dry = n_wd / n_prev_dry if n_prev_dry > 0 else 0.0
        wet_wet = n_ww / n_prev_wet if n_prev_wet > 0 else 0.0

        rows.append({
            "month":       m,
            "tmp_max_ave": float(tmx.mean())                 if len(tmx) else 0.0,
            "tmp_min_ave": float(tmn.mean())                 if len(tmn) else 0.0,
            "tmp_max_sd":  float(tmx.std(ddof=1))            if len(tmx) > 1 else 0.0,
            "tmp_min_sd":  float(tmn.std(ddof=1))            if len(tmn) > 1 else 0.0,
            "pcp_ave":     pcp_ave,
            "pcp_sd":      float(wet_pcp.std(ddof=1))        if len(wet_pcp) > 1 else 0.0,
            "pcp_skew":    float(wet_pcp.skew())             if len(wet_pcp) > 2 else 0.0,
            "wet_dry":     wet_dry,
            "wet_wet":     wet_wet,
            "pcp_days":    pcp_days,
            "pcp_hhr":     0.0,
            "slr_ave":     float(sub["slr"].dropna().mean()) if "slr" in sub and sub["slr"].notna().any() else 0.0,
            "dew_ave":     float(sub["dew"].dropna().mean()) if "dew" in sub and sub["dew"].notna().any() else 0.0,
            "wnd_ave":     float(sub["wnd"].dropna().mean()) if "wnd" in sub and sub["wnd"].notna().any() else 0.0,
        })

    return pd.DataFrame(rows)


def _normalize_daily(daily: pd.DataFrame) -> pd.DataFrame:
    df = daily.copy()
    if "date" not in df.columns:
        raise KeyError("daily DataFrame 에 'date' 컬럼 필요")
    df["date"] = pd.to_datetime(df["date"])

    rename = {}
    for orig, std in _DAILY_COL_ALIASES.items():
        if orig in df.columns and std not in rename.values():
            rename[orig] = std
    df = df.rename(columns=rename)

    required = ["pcp", "tmax", "tmin"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"필수 컬럼 누락: {missing}. 입력 컬럼: {list(daily.columns)}")

    for c in ("pcp", "tmax", "tmin", "slr", "dew", "wnd"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
            df[c] = df[c].replace([-99, -99.0, -999, -999.0], np.nan)
    return df


def build_wgn_station(
    daily_csv: Union[str, Path],
    *,
    station_name: str,
    lat: float,
    lon: float,
    elev: float,
    syear: Optional[int] = None,
    eyear: Optional[int] = None,
) -> WgnStation:
    """단일 표준 daily CSV → WgnStation."""
    df = pd.read_csv(daily_csv)
    params = compute_wgn_params(df, syear=syear, eyear=eyear)

    df["date"] = pd.to_datetime(df["date"])
    eff_s = syear if syear else int(df["date"].dt.year.min())
    eff_e = eyear if eyear else int(df["date"].dt.year.max())
    years = eff_e - eff_s + 1

    return WgnStation(name=station_name, lat=lat, lon=lon, elev=elev,
                      years=years, params=params)


def write_weather_wgn(
    stations: Sequence[WgnStation],
    output_path: Union[str, Path],
    *,
    written_by: str = "swat_py.io.weather_wgn",
) -> Path:
    """WgnStation 목록 → SWAT-Plus weather-wgn.cli 작성.

    형식 (per station)
        line 1 : NAME(30) LAT(10.5f) LON(10.5f) ELEV(10.5f) YEARS(6d)
        line 2 : 14개 컬럼 헤더 (각 12자, 2 공백 구분)
        line 3-14 : 1~12월 통계 (각 12.5f, 2 공백 구분)
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: List[str] = [f"weather-wgn.cli: written by {written_by} on {now}"]
    header_str = " " + "  ".join(f"{c:>12s}" for c in _WGN_COLUMNS) + "  "

    for st in stations:
        lines.append(
            f"{st.name:<30s} {st.lat:>10.5f}    {st.lon:>10.5f}"
            f"    {st.elev:>10.5f}    {st.years:>6d}  "
        )
        lines.append(header_str)
        for _, r in st.params.iterrows():
            vals = "  ".join(f"{float(r[c]):>12.5f}" for c in _WGN_COLUMNS)
            lines.append(" " + vals + "  ")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def write_wgn_import_csv(
    stations: Sequence[WgnStation],
    output_path: Union[str, Path],
) -> Path:
    """SWAT+ Editor 1-file wgn import CSV 작성.

    SWAT+ Editor ``actions/import_weather.py::add_wgn_stations_sf`` 가
    기대하는 단일 파일 wgn import 포맷이다 (one_file 모드).

    컬럼 순서 (5 + 14×12 = 173):
        name, lat, lon, elev, rain_yrs,
        <14 vars>_1, <14 vars>_2, ..., <14 vars>_12

    각 월의 14 변수는 ``_WGN_COLUMNS`` 순서:
        tmp_max_ave, tmp_min_ave, tmp_max_sd, tmp_min_sd,
        pcp_ave, pcp_sd, pcp_skew, wet_dry, wet_wet, pcp_days,
        pcp_hhr, slr_ave, dew_ave, wnd_ave

    Editor 파서는 ``val[0]=name, val[1]=lat, ...`` 위치 기반이라
    ID 컬럼이 있으면 lat 자리에 name 문자열이 들어가
    ``weather_sta_name`` 에서 ``str >= int`` TypeError 가 발생한다.
    이 함수는 ID 컬럼 없이 순서를 맞춰 출력한다.

    참고: Editor 는 csv.Sniffer 로 헤더 유무를 자동 판별한다 — 본 함수는
    헤더 행을 포함시킨다.

    station name 의 공백은 Editor 가 ``utils.remove_space`` 로 제거하므로
    호출 측에서 미리 strip 하여 일관된 이름을 보장한다.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    header: List[str] = ["name", "lat", "lon", "elev", "rain_yrs"]
    for m in range(1, 13):
        header.extend(f"{c}_{m}" for c in _WGN_COLUMNS)

    rows = []
    for st in stations:
        params = st.params.set_index("month") if "month" in st.params.columns else st.params
        row: List[Union[str, float, int]] = [
            "".join(st.name.split()),   # whitespace 제거 — Editor 동작과 일치
            float(st.lat),
            float(st.lon),
            float(st.elev),
            int(st.years),
        ]
        for m in range(1, 13):
            r = params.loc[m] if m in params.index else None
            for c in _WGN_COLUMNS:
                v = float(r[c]) if r is not None and pd.notna(r[c]) else 0.0
                row.append(v)
        rows.append(row)

    df = pd.DataFrame(rows, columns=header)
    df.to_csv(output_path, index=False)
    return output_path


def read_weather_wgn(path: Union[str, Path]) -> List[WgnStation]:
    """기존 weather-wgn.cli → WgnStation 목록 (round-trip / 검증용)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    idx = 1   # 첫 줄은 메타
    stations: List[WgnStation] = []
    while idx < len(lines):
        parts = lines[idx].split()
        if len(parts) < 5:
            idx += 1
            continue
        name = parts[0]
        try:
            lat, lon, elev = float(parts[1]), float(parts[2]), float(parts[3])
            years = int(parts[4])
        except ValueError:
            idx += 1
            continue

        rows = []
        for m in range(1, 13):
            row_idx = idx + 1 + m
            if row_idx >= len(lines):
                break
            vals = lines[row_idx].split()
            if len(vals) < len(_WGN_COLUMNS):
                break
            d = {"month": m}
            for j, c in enumerate(_WGN_COLUMNS):
                d[c] = float(vals[j])
            rows.append(d)
        if len(rows) == 12:
            stations.append(WgnStation(name=name, lat=lat, lon=lon, elev=elev,
                                       years=years, params=pd.DataFrame(rows)))
        idx = idx + 1 + 1 + 12  # station header + col header + 12 rows
    return stations
