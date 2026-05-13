"""util_py.weather_std 표준 CSV → SWAT-Plus 가중치 입력 파일 변환.

표준 CSV 컬럼
-------------
date, pcp_mm, tmax_c, tmin_c, tavg_c, tdew_c, hmd_pct, slr_mjm2,
ws10_ms, ws2_ms, source

SWAT-Plus 가중치 파일 형식 (per station, per variable)
-----------------------------------------------------
헤더 3행 — SWAT+ 표준 / SWAT+ Editor import 파서 (`add_weather_files_type`)
도 동일하게 line idx 3 부터 데이터로 해석한다.

    {filename}                                # 1행 (코멘트)
    nbyr  tstep  lat  lon  elev               # 2행 (라벨)
    {nbyr}  {tstep}  {lat:.5f}  {lon:.5f}  {elev:.1f}   # 3행 (값)
데이터
    {year}  {jday}  {value(s)}                # tmp 는 두 값, 나머지는 한 값

생성 파일
---------
{station}.pcp   precipitation (mm)
{station}.tmp   max + min temperature (°C, 2 columns)
{station}.hmd   relative humidity (fraction 0–1)   ★ % → fraction 변환
{station}.slr   solar radiation (MJ/m²/day)
{station}.wnd   wind speed at 2 m (m/s)            ★ ws2_ms 사용

플러스 1개 인덱스
    weather-sta.cli   SWAT-Plus 가중치 station 목록 (이름·메타·5개 파일명)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd


# ── 변수별 메타 ─────────────────────────────────────────────────────────────

# (파일 확장자, 표준 컬럼 또는 컬럼들, 단위 라벨, 변환 함수)
_VAR_SPEC: Dict[str, Dict] = {
    "pcp": {
        "ext":     "pcp",
        "cols":    ["pcp_mm"],
        "header":  "pcp_mm",
        "convert": None,
    },
    "tmp": {
        "ext":     "tmp",
        "cols":    ["tmax_c", "tmin_c"],
        "header":  "tmax_c   tmin_c",
        "convert": None,
    },
    "hmd": {
        "ext":     "hmd",
        "cols":    ["hmd_pct"],
        "header":  "hmd_frac",      # SWAT-Plus 0–1 fraction
        "convert": lambda s: s / 100.0,
    },
    "slr": {
        "ext":     "slr",
        "cols":    ["slr_mjm2"],
        "header":  "slr_mjm2",
        "convert": None,
    },
    "wnd": {
        "ext":     "wnd",
        "cols":    ["ws2_ms"],      # ★ SWAT 는 2 m 풍속 사용
        "header":  "wnd_ms_2m",
        "convert": None,
    },
}


@dataclass
class StationMeta:
    """가중치 station 메타정보."""
    id:   str
    lat:  float
    lon:  float
    elev: float = 0.0


# ── std CSV 로드 ─────────────────────────────────────────────────────────────

def load_std_daily(csv_path: Union[str, Path]) -> pd.DataFrame:
    """표준 일자료 CSV 로드 (date 파싱 + 정렬 + jday 부여)."""
    df = pd.read_csv(csv_path, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["year"] = df["date"].dt.year
    df["jday"] = df["date"].dt.dayofyear
    return df


# ── 단일 변수 파일 작성 ─────────────────────────────────────────────────────

def _write_variable_file(
    df: pd.DataFrame,
    var_key: str,
    output_path: Path,
    station: StationMeta,
    fill_missing: float = -99.0,
) -> Path:
    """std DataFrame 의 한 변수를 SWAT-Plus 형식으로 저장."""
    spec = _VAR_SPEC[var_key]
    cols = spec["cols"]
    convert = spec["convert"]

    # 컬럼 존재 확인
    missing_cols = [c for c in cols if c not in df.columns]
    if missing_cols:
        raise ValueError(f"std DataFrame 에 필요한 컬럼 없음: {missing_cols}")

    nbyr = int(df["year"].nunique())

    # 데이터 추출 + 결측치 채움
    sub = df[["year", "jday"] + cols].copy()
    for c in cols:
        if convert is not None:
            sub[c] = convert(sub[c])
        sub[c] = sub[c].fillna(fill_missing)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        # 헤더 3행 (SWAT+ 표준 — Editor import 파서가 line idx 3 부터 데이터로 읽음)
        f.write(f"{output_path.name}: {spec['header']} - written by swat_py\n")
        f.write(f"nbyr  tstep  lat       lon        elev\n")
        f.write(f"{nbyr:4d}  {0:4d}  "
                f"{station.lat:9.5f}  {station.lon:10.5f}  {station.elev:6.1f}\n")

        # 데이터
        if len(cols) == 1:
            for _, r in sub.iterrows():
                f.write(f"{int(r['year']):4d}  {int(r['jday']):3d}  "
                        f"{r[cols[0]]:8.3f}\n")
        else:  # tmp: 2개 값
            for _, r in sub.iterrows():
                f.write(f"{int(r['year']):4d}  {int(r['jday']):3d}  "
                        f"{r[cols[0]]:7.2f}  {r[cols[1]]:7.2f}\n")

    return output_path


# ── 한 station 의 모든 변수 작성 ─────────────────────────────────────────────

def write_swat_plus_station(
    std_csv: Union[str, Path],
    output_dir: Union[str, Path],
    station: StationMeta,
    variables: Optional[List[str]] = None,
    *,
    skip_if_all_missing: bool = True,
) -> Dict[str, Path]:
    """std CSV → SWAT-Plus 가중치 5종 파일 (station 1개).

    Parameters
    ----------
    std_csv             : 표준 일자료 CSV
    output_dir          : 출력 폴더 (가중치 파일들이 모두 여기 저장)
    station             : station 메타 (id/lat/lon/elev)
    variables           : 작성할 변수 목록 (기본: pcp/tmp/hmd/slr/wnd 모두)
    skip_if_all_missing : True 면 컬럼 전체가 NaN 일 때 그 변수 파일은 안 만듦

    Returns
    -------
    dict : {variable: 저장된 파일 경로}
    """
    variables = variables or list(_VAR_SPEC.keys())
    output_dir = Path(output_dir)

    df = load_std_daily(std_csv)
    written: Dict[str, Path] = {}

    for var in variables:
        if var not in _VAR_SPEC:
            print(f"  [WARN] 알 수 없는 변수: {var}")
            continue
        cols = _VAR_SPEC[var]["cols"]
        # 결측 검사
        valid_count = df[cols].notna().any(axis=1).sum()
        if skip_if_all_missing and valid_count == 0:
            print(f"  [SKIP] {station.id}.{var}  (모든 값 결측)")
            continue

        out = output_dir / f"{station.id}.{var}"
        _write_variable_file(df, var, out, station)
        written[var] = out

    return written


# ── 다중 station + 인덱스 파일 ──────────────────────────────────────────────

def write_weather_sta_cli(
    stations: List[Tuple[StationMeta, Dict[str, Path]]],
    output_path: Union[str, Path],
) -> Path:
    """SWAT-Plus weather-sta.cli 인덱스 파일 작성.

    포맷
    ----
    weather-sta.cli
    name           wgn       pcp                tmp                hmd                slr                wnd
    {id}           sim       {pcp_filename}     {tmp_filename}     ...
    ...
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        f.write("weather-sta.cli\n")
        f.write(f"{'name':<14s} {'wgn':<10s} "
                f"{'pcp':<22s} {'tmp':<22s} {'hmd':<22s} {'slr':<22s} {'wnd':<22s}\n")
        for station, files in stations:
            row = [f"{station.id:<14s}", f"{'sim':<10s}"]
            for v in ("pcp", "tmp", "hmd", "slr", "wnd"):
                fname = files[v].name if v in files else "null"
                row.append(f"{fname:<22s}")
            f.write(" ".join(row) + "\n")

    return output_path


def write_swat_plus_weather_batch(
    std_csvs: List[Tuple[Union[str, Path], StationMeta]],
    output_dir: Union[str, Path],
    variables: Optional[List[str]] = None,
    *,
    write_sta_cli: bool = True,
) -> Dict[str, Dict[str, Path]]:
    """여러 station 의 std CSV → SWAT-Plus 가중치 파일 + 인덱스.

    Parameters
    ----------
    std_csvs        : [(csv_path, StationMeta), ...]
    output_dir      : 출력 폴더
    variables       : 작성할 변수 목록
    write_sta_cli   : True 면 weather-sta.cli 인덱스도 작성

    Returns
    -------
    dict : {station_id: {variable: file_path}}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: Dict[str, Dict[str, Path]] = {}
    sta_entries: List[Tuple[StationMeta, Dict[str, Path]]] = []

    print(f"  [SWAT-Plus weather] {len(std_csvs)}개 station → {output_dir}")
    for csv_path, station in std_csvs:
        try:
            files = write_swat_plus_station(csv_path, output_dir, station,
                                             variables=variables)
            if files:
                results[station.id] = files
                sta_entries.append((station, files))
                print(f"    [OK] {station.id:<16s} ({len(files)}개 변수)")
            else:
                print(f"    [SKIP] {station.id:<16s} (자료 없음)")
        except Exception as e:
            print(f"    [FAIL] {station.id:<16s}: {e}")

    if write_sta_cli and sta_entries:
        idx = write_weather_sta_cli(sta_entries, output_dir / "weather-sta.cli")
        print(f"  [INDEX] {idx.name}  ({len(sta_entries)}개 station)")

    return results


# ── QSWAT+ / SWAT+ Editor weather import 폴더 ──────────────────────────────

def write_qswatplus_cli_index(
    filenames: List[str],
    output_path: Union[str, Path],
    var: str,
    *,
    written_by: str = "swat_py.io.weather_std_adapter",
) -> Path:
    """QSWAT+ / SWAT+ Editor 의 per-variable weather import index 파일 작성.

    SWAT+ Editor ``actions/import_weather.py::add_weather_files_type`` 가
    읽는 형식 — 첫 2 줄은 헤더로 건너뛰고, line 3+ 의 각 줄을 station 파일명
    으로 해석한다 (``if i > 1: station_name = line.strip('\\n')``).

    출력 포맷::
        {var}.cli: written by {written_by} on {date}
        filename
        sta1.{var}
        sta2.{var}

    Parameters
    ----------
    filenames    : station 데이터 파일명 목록 (예: ["918430.pcp", "461303.pcp"])
    output_path  : 출력 .cli 경로 (예: .../pcp.cli)
    var          : 변수 약어 (pcp/tmp/hmd/slr/wnd/pet) — 첫 줄 메타 표기용
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: List[str] = [f"{var}.cli: written by {written_by} on {now}",
                        "filename"] + list(filenames)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def write_qswatplus_weather_input(
    std_csvs: List[Tuple[Union[str, Path], StationMeta]],
    output_dir: Union[str, Path],
    variables: Optional[List[str]] = None,
    *,
    write_sta_cli: bool = True,
) -> Dict[str, Dict[str, Path]]:
    """QSWAT+ / SWAT+ Editor 의 weather import 폴더 일괄 생성.

    출력 구조 ::
        output_dir/
            {sta}.pcp, {sta}.tmp, {sta}.hmd, {sta}.slr, {sta}.wnd  (station × 변수)
            pcp.cli, tmp.cli, hmd.cli, slr.cli, wnd.cli            (변수별 index)
            weather-sta.cli                                         (선택)

    QSWAT+ 가 "Use SWAT+ weather data" → 폴더 지정 시 즉시 import 가능한
    파일 셋이다. 각 station 데이터 파일은 line 2 (값 행) 에 ``nbyr tstep
    lat lon elev`` 가 들어가야 하며, Editor 는 그 lat/lon 으로 station
    좌표를 인식한다 (`write_swat_plus_weather_batch` 가 이미 보장).

    Parameters
    ----------
    std_csvs       : [(표준 일자료 CSV 경로, StationMeta), ...]
    output_dir     : QSWAT+ import 폴더
    variables      : 작성할 변수 목록 (기본: pcp/tmp/hmd/slr/wnd)
    write_sta_cli  : True 면 SWAT+ 모형 runtime 용 weather-sta.cli 도 작성
    """
    output_dir = Path(output_dir)
    results = write_swat_plus_weather_batch(
        std_csvs, output_dir, variables=variables, write_sta_cli=write_sta_cli,
    )

    by_var: Dict[str, List[str]] = {}
    for _sta_id, files in results.items():
        for var, p in files.items():
            by_var.setdefault(var, []).append(p.name)

    for var, fnames in by_var.items():
        write_qswatplus_cli_index(sorted(fnames), output_dir / f"{var}.cli", var)
        print(f"  [INDEX] {var}.cli  ({len(fnames)}개 파일)")

    return results


# ── 편의: era5 grid_points + std → SWAT-Plus ───────────────────────────────

def from_era5(
    grid_points_csv: Union[str, Path],
    std_dir: Union[str, Path],
    output_dir: Union[str, Path],
    variables: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Path]]:
    """ERA5 grid_points-era5.csv + grid_daily_std/{ID}.csv → SWAT-Plus 입력.

    Parameters
    ----------
    grid_points_csv : Lon, Lat, Elev, ID, Ename, Syear 컬럼 CSV
    std_dir         : std 일자료 폴더 (각 ID 별 .csv)
    output_dir      : SWAT-Plus 가중치 출력 폴더
    """
    grid = pd.read_csv(grid_points_csv)
    std_dir = Path(std_dir)

    pairs: List[Tuple[Path, StationMeta]] = []
    for _, r in grid.iterrows():
        sid = str(r["ID"])
        csv = std_dir / f"{sid}.csv"
        if not csv.is_file():
            print(f"  [MISS] std 파일 없음: {csv.name}")
            continue
        elev = float(r.get("Elev", 0.0))
        pairs.append((csv, StationMeta(id=sid, lat=float(r["Lat"]),
                                        lon=float(r["Lon"]),
                                        elev=elev if elev >= 0 else 0.0)))

    return write_swat_plus_weather_batch(pairs, output_dir, variables=variables)


def from_gsod(
    station_csv: Union[str, Path],
    std_dir: Union[str, Path],
    output_dir: Union[str, Path],
    variables: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Path]]:
    """GSOD station-gsod.csv + daily_std/{STATION_ID}.csv → SWAT-Plus 입력."""
    sta = pd.read_csv(station_csv)
    std_dir = Path(std_dir)

    pairs: List[Tuple[Path, StationMeta]] = []
    for _, r in sta.iterrows():
        sid = str(r["STATION_ID"])
        csv = std_dir / f"{sid}.csv"
        if not csv.is_file():
            print(f"  [MISS] std 파일 없음: {csv.name}")
            continue
        elev = float(r.get("ELEV_M", 0.0)) if pd.notna(r.get("ELEV_M")) else 0.0
        pairs.append((csv, StationMeta(id=sid, lat=float(r["LAT"]),
                                        lon=float(r["LON"]),
                                        elev=max(0.0, elev))))

    return write_swat_plus_weather_batch(pairs, output_dir, variables=variables)
