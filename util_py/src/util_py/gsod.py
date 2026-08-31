"""NOAA GSOD (Global Summary of the Day) 일자료 다운로드 모듈.

워크플로우
----------
1. boundary_csv 에서 ISO2 국가 코드 + bbox 추출
2. NOAA isd-history.csv 다운로드 → FIPS 매핑 후 해당 국가 + bbox 내 관측소 필터
3. 각 관측소의 연도별 GSOD .csv 를 NOAA 에서 **직접 다운로드**
   (전세계 {year}.tar.gz 아카이브는 쓰지 않는다 — 관측소 1개당 필요한 연도만 받는다)
4. 관측소별로 모든 연도 통합 → ``obs_dir/{STATION_ID}.csv``
5. 처리 완료 관측소 메타를 ``station-gsod.csv`` 로 저장

식별자 규약
-----------
- ``NOAA_ID``     : ``{USAF}{WBAN}`` (11자) — NOAA 측 URL 의 파일명
- ``STATION_ID``  : 로컬 파일명 (보통 6자 USAF, 일부 케이스만 11자)
    * 기본       : USAF (6자)  — 본 사업 대상 도서국·동남아 거의 모두 해당
    * fallback   : USAF=``999999`` 또는 같은 USAF 가 중복되는 경우 NOAA_ID (11자)
NOAA 원본 파일 fetch 는 항상 NOAA_ID 사용, 로컬 저장만 STATION_ID 사용.

증분 갱신
---------
NOAA 는 진행 중인 연도의 관측소 CSV 를 계속 덧붙여 갱신한다. 따라서 재실행 시
**이미 받은 연도는 건너뛰고, 마지막으로 받은 연도와 그 이후만 다시 받아** 병합한다.
(마지막 연도는 그 사이 행이 늘어났을 수 있으므로 항상 다시 받는다.)
연도 범위는 isd-history 의 관측소별 BEGIN/END 로 좁혀 불필요한 404 요청을 줄인다.

데이터 소스
-----------
isd-history.csv
    https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv
    컬럼: USAF, WBAN, STATION NAME, CTRY (FIPS 10-4), STATE, ICAO, LAT, LON,
          ELEV(M), BEGIN, END

GSOD 일자료 (CSV, 2020년 이후 표준)
    URL : https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/{year}/{USAF}{WBAN}.csv
          (관측소·연도 단위 파일. 진행 중인 연도는 계속 갱신됨)
    주요 컬럼: STATION, DATE, LATITUDE, LONGITUDE, ELEVATION, NAME,
              TEMP, DEWP, SLP, STP, VISIB, WDSP, MXSPD, GUST, MAX, MIN,
              PRCP, SNDP, FRSHTT (모두 9999.9 등 결측 sentinel 사용)

ISO2 ↔ FIPS 차이
----------------
isd-history.csv 의 CTRY 필드는 FIPS 10-4 코드를 사용해 ISO 3166 alpha-2 와
다른 국가가 다수 존재. :data:`ISO2_TO_FIPS` 에 주요 매핑 내장.
"""

from __future__ import annotations

import io
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

# DBF (shapefile 속성) 컬럼명 10자 제한 회피 매핑
_SHP_RENAME = {
    "STATION_ID":   "STN_ID",
    "STATION_NAME": "STN_NAME",
    "n_records":    "N_REC",
    "first_date":   "F_OBS",
    "last_date":    "L_OBS",
}


# ── ISO2 → FIPS 10-4 매핑 (NOAA isd-history.csv CTRY 필드용) ─────────────────
# 주요 mismatch 만 등록. 매핑 미등록 시 ISO2 그대로 사용 (ISO2 == FIPS 인 경우).
ISO2_TO_FIPS: Dict[str, str] = {
    "CK": "CW",   # Cook Islands
    "KR": "KS",   # Korea, Republic of (South)
    "KP": "KN",   # Korea, DPR (North)
    "JP": "JA",   # Japan
    "CN": "CH",   # China
    "VN": "VM",   # Vietnam
    "PH": "RP",   # Philippines
    "MY": "MY",   # Malaysia (동일)
    "ID": "ID",   # Indonesia (동일)
    "AU": "AS",   # Australia
    "NZ": "NZ",   # New Zealand (동일)
    "FJ": "FJ",   # Fiji (동일)
    "WS": "WS",   # Samoa (동일)
    "TO": "TN",   # Tonga
    "VU": "NH",   # Vanuatu
    "SB": "BP",   # Solomon Islands
    "PG": "PP",   # Papua New Guinea
    "FM": "FM",   # Micronesia (동일)
    "MH": "RM",   # Marshall Islands
    "PW": "PS",   # Palau
    "KI": "KR",   # Kiribati  (주의: ISO2 KI ≠ ISO2 KR)
    "TV": "TV",   # Tuvalu (동일)
    "NU": "NE",   # Niue
    "TK": "TL",   # Tokelau
    "PF": "FP",   # French Polynesia
    "NC": "NC",   # New Caledonia (동일)
    "GU": "GQ",   # Guam
    "AS": "AQ",   # American Samoa
}


def _iso2_to_fips(iso2: str) -> str:
    """ISO2 코드를 FIPS 10-4 코드로 변환. 매핑이 없으면 ISO2 그대로 반환."""
    return ISO2_TO_FIPS.get(iso2.upper(), iso2.upper())


# ── 1. 경계 CSV 읽기 ─────────────────────────────────────────────────────────

def _read_boundary(boundary_csv: str) -> Dict[str, object]:
    """country_boundary.csv 첫 행에서 국가명·코드·bbox 추출.

    필수 컬럼: NAME, ISO2, ISO3 (선택), xmin, ymin, xmax, ymax
    """
    df = pd.read_csv(boundary_csv)
    if df.empty:
        raise ValueError(f"경계 CSV 가 비어 있음: {boundary_csv}")
    row = df.iloc[0]
    required = {"NAME", "ISO2", "xmin", "ymin", "xmax", "ymax"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"경계 CSV 에 필요한 컬럼 없음: {missing}")
    return {
        "name": str(row["NAME"]),
        "iso2": str(row["ISO2"]).strip().upper(),
        "iso3": str(row.get("ISO3", "")).strip().upper(),
        "bbox": (
            float(row["xmin"]), float(row["ymin"]),
            float(row["xmax"]), float(row["ymax"]),
        ),
    }


# ── 2. isd-history.csv ───────────────────────────────────────────────────────

def _fetch_isd_history(url: str, cache_path: Path,
                       max_age_days: int = 30) -> pd.DataFrame:
    """NOAA isd-history.csv 를 가져옴. 30일 이내 캐시 사용."""
    cache_path = Path(cache_path)
    if cache_path.is_file():
        age_days = (time.time() - cache_path.stat().st_mtime) / 86400
        if age_days < max_age_days:
            return pd.read_csv(cache_path)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  [GET] {url}")
    df = pd.read_csv(url)
    df.to_csv(cache_path, index=False)
    return df


def _make_station_id(usaf: str, wban: str) -> str:
    """로컬 파일명 ID 결정.

    - 기본       : USAF (6자) — 본 사업 대상 도서국·동남아 일반 케이스
    - fallback   : USAF=``999999`` (sentinel) 이면 USAF+WBAN (11자)
    중복 USAF 검출은 _filter_stations 에서 처리 (해당 행만 NOAA_ID 로 swap).
    """
    if usaf == "999999":
        return f"{usaf}{wban}"
    return usaf


def _filter_stations(
    isd: pd.DataFrame,
    fips: str,
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> pd.DataFrame:
    """국가 코드(FIPS) + bbox 로 관측소 필터.

    Returns
    -------
    DataFrame with columns: USAF, WBAN, NOAA_ID, STATION_ID, STATION_NAME,
        CTRY, LAT, LON, ELEV_M, BEGIN, END

    - NOAA_ID    : USAF+WBAN (11자, NOAA archive/URL 측 식별자)
    - STATION_ID : 로컬 파일명 (보통 USAF 6자, sentinel/중복 시 NOAA_ID)
    """
    df = isd.copy()
    df.columns = [c.strip().upper().replace(" ", "_") for c in df.columns]
    # ELEV(M) → ELEV_M  (이미 위 변환에서 처리됨; 일부 dump는 'ELEV(M)' 그대로일 수도)
    df = df.rename(columns={"ELEV(M)": "ELEV_M"})

    df["CTRY"] = df["CTRY"].astype(str).str.strip().str.upper()
    df["LAT"]  = pd.to_numeric(df["LAT"], errors="coerce")
    df["LON"]  = pd.to_numeric(df["LON"], errors="coerce")

    mask = df["CTRY"] == fips.upper()
    if bbox is not None:
        xmin, ymin, xmax, ymax = bbox
        mask &= df["LON"].between(xmin, xmax) & df["LAT"].between(ymin, ymax)

    out = df.loc[mask].copy()
    if out.empty:
        return out

    out["USAF"]    = out["USAF"].astype(str).str.zfill(6)
    out["WBAN"]    = out["WBAN"].astype(str).str.zfill(5)
    out["NOAA_ID"] = out["USAF"] + out["WBAN"]
    out["STATION_ID"] = [
        _make_station_id(u, w) for u, w in zip(out["USAF"], out["WBAN"])
    ]

    # USAF 중복 검사 — 같은 USAF + 다른 WBAN 행이 있으면 그 행들만 NOAA_ID 로 fallback
    dup_mask = out["STATION_ID"].duplicated(keep=False)
    out.loc[dup_mask, "STATION_ID"] = out.loc[dup_mask, "NOAA_ID"]

    keep = [c for c in
            ["USAF", "WBAN", "NOAA_ID", "STATION_ID", "STATION_NAME", "CTRY",
             "STATE", "ICAO", "LAT", "LON", "ELEV_M", "BEGIN", "END"]
            if c in out.columns]
    return out[keep].reset_index(drop=True)


# ── 3. 단일 관측소-연도 데이터 가져오기 ──────────────────────────────────────

def _year_of(value) -> Optional[int]:
    """isd-history 의 BEGIN/END(YYYYMMDD) 에서 연도만 뽑는다. 실패 시 None."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return v // 10000 if v > 9999 else (v if 1900 <= v <= 2200 else None)


def _existing_years(out_path: Path) -> Tuple[Optional[pd.DataFrame], set]:
    """기존 통합 CSV 를 읽어 (DataFrame, 이미 보유한 연도 집합) 을 돌려준다."""
    if not out_path.is_file():
        return None, set()
    try:
        df = pd.read_csv(out_path)
    except Exception as e:
        print(f"    [WARN] 기존 파일 읽기 실패({out_path.name}): {e} → 전체 재수집")
        return None, set()
    if "DATE" not in df.columns or df.empty:
        return None, set()
    years = set(pd.to_datetime(df["DATE"], errors="coerce").dt.year.dropna().astype(int))
    return df, years


def _years_to_fetch(requested: List[int], have: set,
                    begin_year: Optional[int], end_year_meta: Optional[int]) -> List[int]:
    """실제로 내려받을 연도 목록.

    - isd-history 의 BEGIN/END 로 관측소가 보고한 기간 밖은 제외(불필요한 404 방지)
    - 기존 파일이 있으면 **가장 최근 보유 연도부터 앞으로만** 받는다.
      과거의 빈 연도는 GSOD 에 자료가 없어서 비어 있는 것이라 다시 물어도 404 이고,
      과거 자료는 새로 추가되지 않으므로 매달 재요청할 이유가 없다.
      (과거까지 전부 다시 받으려면 overwrite=True)
    - 가장 최근 보유 연도는 항상 다시 받는다 — 진행 중이던 연도라면 행이 늘어났을 수 있음.
    """
    lo = max(requested[0], begin_year) if begin_year else requested[0]
    hi = min(requested[-1], end_year_meta) if end_year_meta else requested[-1]
    window = [y for y in requested if lo <= y <= hi]
    if not have:
        return window
    newest_have = max(have)
    return [y for y in window if y >= newest_have]


def _download_station_year(
    base_url: str, station_id: str, year: int, timeout: int = 60
) -> Optional[pd.DataFrame]:
    """URL에서 단일 관측소·연도 CSV 다운로드. 404는 None 반환."""
    url = f"{base_url}/{year}/{station_id}.csv"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        return pd.read_csv(io.BytesIO(data))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"    [WARN] HTTP {e.code} {url}")
        return None
    except (urllib.error.URLError, OSError) as e:
        print(f"    [WARN] {url}: {e}")
        return None


# ── 4. 관측소 위치 shapefile 작성 ────────────────────────────────────────────

def write_station_shapefile(
    stations: pd.DataFrame,
    output_shp: Union[str, Path],
    epsg: int = 4326,
) -> Optional[Path]:
    """station 메타 DataFrame → 위치 shapefile (Point geometry).

    LAT/LON 결측 행은 제외. DBF 10자 컬럼명 제한 자동 회피 (rename).

    Parameters
    ----------
    stations   : LAT, LON 컬럼이 있는 DataFrame (download_gsod_country 의 반환)
    output_shp : 출력 .shp 경로 (예: gis/gsod/station-gsod.shp)
    epsg       : 좌표계 (기본 4326 = WGS84)

    Returns
    -------
    Path | None : 저장 경로 (저장할 자료 없으면 None)
    """
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except ImportError as e:
        raise ImportError(
            "geopandas, shapely 가 필요합니다 (pip install geopandas)"
        ) from e

    if "LAT" not in stations.columns or "LON" not in stations.columns:
        raise ValueError("stations DataFrame 에 LAT, LON 컬럼이 필요합니다.")

    df = stations[stations["LAT"].notna() & stations["LON"].notna()].copy()
    if df.empty:
        return None

    df = df.rename(columns={k: v for k, v in _SHP_RENAME.items() if k in df.columns})

    gdf = gpd.GeoDataFrame(
        df,
        geometry=[Point(float(lon), float(lat))
                  for lon, lat in zip(df["LON"], df["LAT"])],
        crs=f"EPSG:{epsg}",
    )

    output_shp = Path(output_shp)
    output_shp.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(output_shp)
    return output_shp


# ── 5. 메인 함수 ─────────────────────────────────────────────────────────────

def download_gsod_country(
    boundary_csv: str,
    obs_dir: str,
    station_csv: str,
    station_shp: Optional[str] = None,
    start_year: int = 1929,
    end_year: Optional[int] = None,
    country_code: Optional[str] = None,
    use_bbox_filter: bool = True,
    isd_history_url: str = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv",
    gsod_access_url: str = "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access",
    overwrite: bool = False,
) -> pd.DataFrame:
    """NOAA GSOD에서 한 국가의 일자료를 받아 관측소별 통합 CSV로 저장.

    Parameters
    ----------
    boundary_csv     : 경계 CSV (NAME/ISO2/xmin/ymin/xmax/ymax 컬럼)
    obs_dir          : 관측소별 통합 일자료 출력 폴더
    station_csv      : 처리된 관측소 메타 출력 경로 (예: station-gsod.csv)
    station_shp      : 관측소 위치 shapefile 경로 (None 이면 생성 안 함)
                       권장: $(gis.root)/gsod/station-gsod.shp
    start_year       : 시작 연도 (기본 1929 = GSOD 최초 연도)
    end_year         : 종료 연도 (None → 현재 연도)
    country_code     : ISO2 또는 FIPS 코드 직접 지정 (None → boundary_csv 의 ISO2)
    use_bbox_filter  : True 면 국가 코드 + bbox 교집합으로 제한
    overwrite        : True 면 기존 통합 CSV 를 무시하고 전 연도를 다시 받는다.
                       False(기본)면 **증분** — 없는 연도와 마지막 보유 연도만 받아 병합.

    Returns
    -------
    DataFrame : station-gsod.csv 와 동일한 내용 (처리 성공 관측소만)
    """
    info = _read_boundary(boundary_csv)
    iso2 = (country_code or info["iso2"]).upper()
    fips = _iso2_to_fips(iso2)
    bbox = info["bbox"] if use_bbox_filter else None

    if end_year is None:
        end_year = date.today().year
    years = list(range(start_year, end_year + 1))

    obs_dir   = Path(obs_dir)
    station_p = Path(station_csv)
    obs_dir.mkdir(parents=True, exist_ok=True)
    station_p.parent.mkdir(parents=True, exist_ok=True)
    isd_cache = obs_dir.parent / ".cache" / "isd-history.csv"
    print("=" * 64)
    print("  NOAA GSOD 일자료 다운로드")
    print("=" * 64)
    print(f"  국가         : {info['name']}  (ISO2={iso2}, FIPS={fips})")
    print(f"  bbox         : lon [{bbox[0]:.3f}, {bbox[2]:.3f}], "
          f"lat [{bbox[1]:.3f}, {bbox[3]:.3f}]" if bbox else "  bbox: 사용 안함")
    print(f"  연도 범위    : {years[0]} ~ {years[-1]}  ({len(years)}개)")
    mode = "전체 재수집" if overwrite else "증분"
    print(f"  수집 방식    : NOAA 관측소별 직접 다운로드 ({mode})")
    print(f"  obs_dir      : {obs_dir}")
    print(f"  station_csv  : {station_p}")
    print("=" * 64)

    # 관측소 필터
    isd = _fetch_isd_history(isd_history_url, isd_cache)
    stations = _filter_stations(isd, fips, bbox)
    print(f"\n  필터 결과 관측소: {len(stations)}개")
    if stations.empty:
        print("  → 일치하는 관측소가 없어 종료합니다.")
        empty = stations.copy()
        empty.to_csv(station_p, index=False)
        return empty
    for _, st in stations.iterrows():
        print(f"    {st['STATION_ID']:<11s}  {st['STATION_NAME']:<32} "
              f"({st['LAT']:+.3f}, {st['LON']:+.3f})")

    # 관측소별 통합
    print()
    done_rows: List[dict] = []
    for _, st in stations.iterrows():
        sid     = st["STATION_ID"]   # 로컬 파일명 (보통 USAF 6자)
        noaa_id = st["NOAA_ID"]      # NOAA fetch 식별자 (USAF+WBAN 11자)
        out = obs_dir / f"{sid}.csv"

        # ── 증분 판단 ────────────────────────────────────────────────────
        prev, have = (None, set()) if overwrite else _existing_years(out)
        prev_last = (str(prev["DATE"].iloc[-1])
                     if prev is not None and not prev.empty else None)
        begin_y = _year_of(st.get("BEGIN"))
        end_y   = _year_of(st.get("END"))
        targets = _years_to_fetch(years, have, begin_y, end_y)

        if not targets:
            print(f"  [SKIP] {sid} {st['STATION_NAME']} — "
                  f"새로 받을 연도 없음 (~{prev_last})")
            row = st.to_dict()
            row["n_records"] = len(prev) if prev is not None else 0
            if prev_last:
                row["first_date"] = str(prev["DATE"].iloc[0])
                row["last_date"]  = prev_last
            done_rows.append(row)
            continue

        yearly: List[pd.DataFrame] = []
        for year in targets:
            df = _download_station_year(gsod_access_url, noaa_id, year)
            if df is not None and not df.empty:
                yearly.append(df)

        frames = ([prev] if prev is not None else []) + yearly
        if not frames:
            print(f"  [NONE] {sid} {st['STATION_NAME']} — 자료 없음")
            continue

        combined = pd.concat(frames, ignore_index=True)
        if "DATE" in combined.columns:
            # 새로 받은 행이 뒤에 오므로 keep="last" 로 최신본을 남긴다
            combined = (combined.drop_duplicates(subset="DATE", keep="last")
                                .sort_values("DATE").reset_index(drop=True))
        combined.to_csv(out, index=False)

        row = st.to_dict()
        row["n_records"] = len(combined)
        if "DATE" in combined.columns and not combined.empty:
            row["first_date"] = str(combined["DATE"].iloc[0])
            row["last_date"]  = str(combined["DATE"].iloc[-1])
        done_rows.append(row)

        added = len(combined) - (len(prev) if prev is not None else 0)
        mode  = "전체" if prev is None else f"증분 +{added:,}행"
        span  = f"{targets[0]}~{targets[-1]}" if targets else "-"
        print(f"  [OK]   {sid} {st['STATION_NAME']}  "
              f"{len(combined):,} 행  ({mode}, 요청 연도 {span})")

    # station-gsod.csv 저장
    out_meta = pd.DataFrame(done_rows)
    out_meta.to_csv(station_p, index=False)

    # 관측소 위치 shapefile (선택)
    shp_saved: Optional[Path] = None
    if station_shp and not out_meta.empty:
        try:
            shp_saved = write_station_shapefile(out_meta, station_shp)
        except Exception as exc:
            print(f"  [WARN] shapefile 생성 실패: {exc}")

    print()
    print("=" * 64)
    print(f"  완료: {len(out_meta)}개 관측소 처리, 통합 CSV → {obs_dir}")
    print(f"  관측소 CSV   → {station_p}")
    if shp_saved:
        print(f"  관측소 SHP   → {shp_saved}")
    print("=" * 64)
    return out_meta
