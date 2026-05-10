"""
입력/출력 함수 — R InterfaceAIMS.R의 acid.dataLoading 포팅 + 입력 방식 수정

핵심 변경 사항 (R 대비):
  - 예측 확률(AN/NN/BN)은 forecast_new.csv에서 별도 관리 (Station-Info.csv에서 분리)
  - 관측소 ID 별 개별 CSV 파일 (util_py 표준 daily 포맷) 에서 일자료 로드
  - 결측·이상값 처리 포함

Station-Info.csv 컬럼:
    Lon, Lat, Elev, ID, Ename, SYear

관측소 CSV — util_py 표준 daily 포맷 (``util-weather-standardize`` 출력):
    date, pcp_mm, tmax_c, tmin_c, tavg_c, tdew_c, hmd_pct, slr_mjm2,
    ws10_ms, ws2_ms, source

내부적으로는 date 를 Year/Month/Day 로 분해하고
pcp_mm/tmax_c/tmin_c/tavg_c → prec/tmax/tmin/tavg 로 rename 하여 사용.
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Station-Info.csv 읽기
# ---------------------------------------------------------------------------

def load_station_info(station_csv: str) -> pd.DataFrame:
    """Station-Info.csv를 읽어 DataFrame 반환.

    반환 컬럼: Lon, Lat, Elev, ID, Ename, SYear
    """
    df = pd.read_csv(station_csv)
    df.columns = df.columns.str.strip()

    required = {"Lon", "Lat", "ID", "Ename"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Station-Info.csv에 필요한 컬럼 없음: {missing}")

    return df


def load_forecast_csv(forecast_csv: str) -> pd.DataFrame:
    """forecast_new.csv를 읽어 DataFrame 반환.

    Tidy long format: 관측소별·월별·변수별 AN/NN/BN 예측 확률.

    컬럼
    ----
    station_id : str  — Station-Info.csv의 ID 컬럼과 일치
    month      : int  — 월 번호 (1~12)
    variable   : str  — 'prcp' (강수) 또는 't2m' (기온)
    AN, NN, BN : int  — 예측 확률 (합계 100)

    Notes
    -----
    - 't2m' 행이 없으면 get_basin_prob()에서 prcp 값을 복사해 사용
    - AN+NN+BN 합이 100이 아닌 행은 ValueError 발생
    """
    df = pd.read_csv(forecast_csv)
    df.columns = df.columns.str.strip()

    required = {"station_id", "month", "variable", "AN", "NN", "BN"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"forecast_new.csv에 필요한 컬럼 없음: {missing}")

    df["month"] = df["month"].astype(int)

    # AN+NN+BN 합 검증
    total = df["AN"] + df["NN"] + df["BN"]
    bad = df[~np.isclose(total, 100, atol=1)]
    if not bad.empty:
        raise ValueError(f"AN+NN+BN 합이 100이 아닌 행:\n{bad}")

    return df


def get_basin_prob(forecast_df: pd.DataFrame, sim_period: list):
    """forecast_new.csv DataFrame으로부터 유역 평균 확률 행렬 생성.

    관측소별 예측 확률을 유역 평균한 뒤 (3, n_months) 행렬로 반환.
    't2m' 변수가 없으면 'prcp' 값을 기온에도 적용.

    Parameters
    ----------
    forecast_df : load_forecast_csv()가 반환한 DataFrame
    sim_period  : 시뮬레이션 월 리스트 (예: [6,7,8])

    Returns
    -------
    prob_prec : ndarray shape (3, n_months)  — 행: AN/NN/BN, 열: 월별
    prob_t2m  : ndarray shape (3, n_months)  — 동일 구조
    """
    n_months = len(sim_period)
    prob_prec = np.zeros((3, n_months))
    prob_t2m  = np.zeros((3, n_months))

    has_t2m = "t2m" in forecast_df["variable"].values

    for mi, m in enumerate(sim_period):
        for var, out_arr in [("prcp", prob_prec), ("t2m", prob_t2m)]:
            sub = forecast_df[
                (forecast_df["month"] == m) & (forecast_df["variable"] == var)
            ]

            if sub.empty:
                # t2m가 없으면 prcp 값을 복사 (fallback)
                if var == "t2m" and not has_t2m:
                    out_arr[:, mi] = prob_prec[:, mi]
                else:
                    out_arr[:, mi] = 1.0 / 3.0  # 데이터 없으면 균등 분포
                continue

            # 관측소별 평균 → 유역 평균
            an = sub["AN"].mean() / 100.0
            nn = sub["NN"].mean() / 100.0
            bn = sub["BN"].mean() / 100.0

            probs = np.array([an, nn, bn])
            probs /= probs.sum()          # 부동소수점 오차 정규화
            out_arr[:, mi] = probs

    # t2m 행이 전혀 없으면 prcp 복사
    if not has_t2m:
        prob_t2m[:] = prob_prec

    return prob_prec, prob_t2m


# ---------------------------------------------------------------------------
# 관측소 CSV 읽기
# ---------------------------------------------------------------------------

def load_obs_csv(filepath: str, syear: int, eyear: int) -> pd.DataFrame:
    """단일 관측소 CSV (util_py 표준 daily 포맷) → 기간 필터링 후 반환.

    입력 포맷 (``util-weather-standardize`` 출력)
    --------------------------------------------
    date, pcp_mm, tmax_c, tmin_c, tavg_c, tdew_c, hmd_pct, slr_mjm2,
    ws10_ms, ws2_ms, source

    Returns
    -------
    DataFrame with columns: Year, Month, Day, prec, tmax, tmin, [tavg, ...]
        date 컬럼을 Year/Month/Day 로 분해, pcp_mm·tmax_c·tmin_c·tavg_c 를
        내부 컬럼명 (prec/tmax/tmin/tavg) 으로 rename. 다른 컬럼은 그대로 유지.
    """
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip()

    if "date" not in df.columns:
        raise ValueError(
            f"util_py 표준 daily 포맷 미준수: 'date' 컬럼 없음.\n"
            f"  파일: {filepath}\n"
            f"  필수 표준 포맷: date,pcp_mm,tmax_c,tmin_c,...\n"
            f"  → util-weather-standardize 출력을 그대로 사용하세요."
        )

    # date 파싱 → Year/Month/Day 분해
    dt = pd.to_datetime(df["date"], errors="coerce")
    if dt.isna().any():
        bad = df.loc[dt.isna(), "date"].head(3).tolist()
        raise ValueError(
            f"date 컬럼 파싱 실패 (예: {bad}). YYYY-MM-DD 형식이어야 합니다.\n"
            f"  파일: {filepath}"
        )
    df["Year"]  = dt.dt.year
    df["Month"] = dt.dt.month
    df["Day"]   = dt.dt.day

    # 표준 포맷 → 내부 컬럼명
    rename_map = {
        "pcp_mm": "prec",
        "tmax_c": "tmax",
        "tmin_c": "tmin",
        "tavg_c": "tavg",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    required = {"prec", "tmax", "tmin"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"필수 컬럼 누락: {sorted(missing)}\n"
            f"  파일: {filepath}\n"
            f"  표준 포맷 (pcp_mm/tmax_c/tmin_c) 이 들어있어야 합니다."
        )

    # 기간 필터
    mask = (df["Year"] >= syear) & (df["Year"] <= eyear)
    df = df[mask].reset_index(drop=True)

    return df


# ---------------------------------------------------------------------------
# 메인 데이터 로딩 함수 (acid.dataLoading 포팅)
# ---------------------------------------------------------------------------

def acid_data_loading(station_csv: str, obs_dir: str,
                      syear_obs: int, eyear_obs: int):
    """관측소 정보 및 일단위 기상 자료 로드.

    R의 acid.dataLoading() 포팅.
    NetCDF 의존성 없이 CSV만 사용.

    Parameters
    ----------
    station_csv : Station-Info.csv 경로
    obs_dir     : 관측소 CSV 파일이 있는 디렉토리
    syear_obs   : 관측 시작 연도
    eyear_obs   : 관측 종료 연도

    Returns
    -------
    dict with keys:
        coord      : ndarray (d, 2)  — [Lon, Lat]
        site_names : list of str
        d          : int
        prcp_table : ndarray (n_days, 3+d)  — [Year, Month, Day, stn1, ...]
        tmax_table : ndarray (n_days, 3+d)
        tmin_table : ndarray (n_days, 3+d)
        tavg_table : ndarray (n_days, 3+d)
        station_info : DataFrame
    """
    station_info = load_station_info(station_csv)
    d = len(station_info)
    site_names = station_info["Ename"].tolist()
    coord = station_info[["Lon", "Lat"]].values.astype(float)

    # 각 관측소 CSV 로드
    obs_list = []
    for _, row in station_info.iterrows():
        fpath = os.path.join(obs_dir, f"{row['ID']}.csv")
        if not os.path.exists(fpath):
            raise FileNotFoundError(f"관측소 파일 없음: {fpath}")
        df = load_obs_csv(fpath, syear_obs, eyear_obs)
        obs_list.append(df)

    # 기준 날짜 프레임 (첫 번째 관측소 기준)
    base = obs_list[0][["Year", "Month", "Day"]].values.astype(int)
    n_days = len(base)

    # 각 변수 테이블 초기화 (Year, Month, Day + d개 관측소)
    prcp_arr = np.zeros((n_days, 3 + d), dtype=float)
    tmax_arr = np.zeros((n_days, 3 + d), dtype=float)
    tmin_arr = np.zeros((n_days, 3 + d), dtype=float)
    tavg_arr = np.zeros((n_days, 3 + d), dtype=float)

    prcp_arr[:, :3] = base
    tmax_arr[:, :3] = base
    tmin_arr[:, :3] = base
    tavg_arr[:, :3] = base

    for j, df in enumerate(obs_list):
        # 날짜 정렬 보장
        obs_base = df[["Year", "Month", "Day"]].values.astype(int)
        assert np.array_equal(obs_base, base), (
            f"관측소 {site_names[j]}의 날짜가 기준과 다릅니다."
        )
        prcp_arr[:, 3 + j] = df["prec"].values
        tmax_arr[:, 3 + j] = df["tmax"].values
        tmin_arr[:, 3 + j] = df["tmin"].values

        if "tavg" in df.columns:
            tavg_arr[:, 3 + j] = df["tavg"].values
        else:
            tavg_arr[:, 3 + j] = (df["tmax"].values + df["tmin"].values) / 2.0

    # R과 동일: tavg_table = (tmax + tmin) / 2
    tavg_computed = np.zeros_like(tmax_arr)
    tavg_computed[:, :3] = base
    tavg_computed[:, 3:] = (tmax_arr[:, 3:] + tmin_arr[:, 3:]) / 2.0

    # 결측값 처리 -------------------------------------------------------
    # 강수: 음수 → 0
    prcp_arr[:, 3:] = np.where(prcp_arr[:, 3:] < 0, 0.0, prcp_arr[:, 3:])

    # 기온: -99는 결측 표시 → 선형 보간
    for col in range(3, 3 + d):
        for arr in (tmax_arr, tmin_arr, tavg_computed):
            arr[:, col] = _interpolate_missing(arr[:, col], missing_val=-99.0)

    col_names = ["Year", "Month", "Day"] + site_names

    return {
        "coord": coord,
        "site_names": site_names,
        "d": d,
        "prcp_table": prcp_arr,
        "tmax_table": tmax_arr,
        "tmin_table": tmin_arr,
        "tavg_table": tavg_computed,
        "col_names": col_names,
        "station_info": station_info,
    }


def _interpolate_missing(series: np.ndarray, missing_val: float = -99.0,
                         threshold: float = -50.0) -> np.ndarray:
    """극단값(threshold 이하)을 선형 보간으로 대체.

    R의 내부 f() 함수와 동일한 로직.
    """
    result = series.copy()
    missing_idx = np.where(result <= threshold)[0]

    if len(missing_idx) == 0:
        return result

    for i in missing_idx:
        # 앞쪽 유효값 탐색
        a = i - 1
        while a >= 0 and a in missing_idx:
            a -= 1
        # 뒤쪽 유효값 탐색
        b = i + 1
        while b < len(result) and b in missing_idx:
            b += 1

        if a < 0 and b >= len(result):
            result[i] = missing_val
        elif a < 0:
            result[i] = result[b]
        elif b >= len(result):
            result[i] = result[a]
        else:
            result[i] = ((b - i) / (b - a)) * result[a] + ((i - a) / (b - a)) * result[b]

    return result


# ---------------------------------------------------------------------------
# 출력 함수
# ---------------------------------------------------------------------------

def write_scenario(result: dict, output_dir: str, ensemble_idx: int,
                   site_names: list, station_ids: list = None,
                   forecast_year: int = None):
    """시뮬레이션 결과를 member 폴더 구조로 저장.

    Parameters
    ----------
    result        : main_simulation() 반환 딕셔너리
    output_dir    : 출력 루트 폴더 (member 폴더가 이 아래에 생성됨)
    ensemble_idx  : 앙상블 번호 (1-based)
    site_names    : 관측소 영문 이름 목록 (시나리오 배열 컬럼 순서)
    station_ids   : 관측소 ID 목록 (파일명에 사용; None이면 site_names 사용)
    forecast_year : 예보 연도 (CSV에 year 컬럼 추가; None이면 생략)

    출력 구조
    ---------
    output_dir/
        member_0001/
            {station_id}.csv  (columns: [year,] mon, day, prcp, tmax, tmin)
        member_0002/
            ...

    각 CSV는 pyswat의 ``_load_station_data``가 직접 읽을 수 있는 형식입니다.
    wspd, rhum, rsds 컬럼이 없으면 pyswat이 SWAT-Plus 기상발생기(-99)로 대체합니다.
    """
    ids = station_ids if station_ids is not None else site_names

    member_dir = Path(output_dir) / f"member_{ensemble_idx:04d}"
    member_dir.mkdir(parents=True, exist_ok=True)

    prcp = result["prcp_scenario"]  # (n_days, 2+d): Month, Day, stn1...
    tmax = result["tmax_scenario"]  # (n_days, 2+d): Month, Day, stn1...
    tmin = result["tmin_scenario"]  # (n_days, 2+d): Month, Day, stn1...

    for j, stn_id in enumerate(ids):
        data: dict = {}
        if forecast_year is not None:
            data["year"] = int(forecast_year)
        data["mon"]  = prcp[:, 0].astype(int)
        data["day"]  = prcp[:, 1].astype(int)
        data["prcp"] = np.round(prcp[:, 2 + j], 1)
        data["tmax"] = np.round(tmax[:, 2 + j], 1)
        data["tmin"] = np.round(tmin[:, 2 + j], 1)

        pd.DataFrame(data).to_csv(
            member_dir / f"{stn_id}.csv", index=False, float_format="%.1f"
        )
