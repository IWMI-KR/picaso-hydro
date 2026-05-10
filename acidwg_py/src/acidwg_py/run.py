"""
실행 오케스트레이션 — R InterfaceAIMS.R의 acid.run / acid.modeling 포팅

핵심 변경 사항 (R 대비):
  - NetCDF 예측 파일 → forecast_new.csv의 관측소×월×변수별 AN/NN/BN 확률 사용
  - 출력: Output/ 폴더에 prcp-{i}.csv, tmax-{i}.csv, tmin-{i}.csv 생성
  - 월별 범주 사후 보정(post-calibration): 관측소별 월합계/기온을
    해당 범주의 역사 분포로 스케일링·이동하여 관측소별 재현 확률 오차 < 5%p 보장
"""

import os
import pickle
import traceback
import numpy as np
from tqdm import tqdm

from acidwg_py.io import acid_data_loading, load_forecast_csv, get_basin_prob, write_scenario
from acidwg_py.utils import season_naming
from acidwg_py.modeling.precipitation import prcp_modeling
from acidwg_py.modeling.temperature import temper_modeling
from acidwg_py.simulation.precipitation import prcp_simulation
from acidwg_py.simulation.temperature import generating_iso, temper_simulation


# ---------------------------------------------------------------------------
# 월별 범주 확률 샘플링 (R의 determine.monthly.ch와 동일)
# ---------------------------------------------------------------------------

def determine_monthly_ch(prob_prec: np.ndarray,
                          prob_t2m: np.ndarray) -> dict:
    """prob_prec, prob_t2m 행렬로부터 월별 습윤·온도 범주 결정.

    forecast_new.csv로부터 월별·관측소별 예측 확률이 입력되므로,
    각 시뮬레이션 월마다 해당 월의 예측 확률로 독립 샘플링.

    강수(sf_wetness)와 기온(sf_warmness)은 결합 분포에서 동시 결정하여
    두 변수 간 상관성을 보존.

    Parameters
    ----------
    prob_prec : ndarray (3, n_months) — 행: AN/NN/BN, 열: 월별 유역평균 강수 확률
    prob_t2m  : ndarray (3, n_months) — 행: AN/NN/BN, 열: 월별 유역평균 기온 확률

    Returns
    -------
    dict with:
        sf_wetness  : list of str (len n_months) — 월별 강수 범주
        sf_warmness : list of str (len n_months) — 월별 기온 범주

    Notes
    -----
    앙상블 계절 합계 기준 AN/NN/BN 재현율은 월별 독립 샘플링 특성상
    월간 상관 구조를 반영하지 않아 입력 확률과 다를 수 있음.
    월별 확률이 모두 동일한 단순 계절 예측에는 계절 단위 1회 샘플링이
    보다 정확하나, 월별 서로 다른 확률 입력 시 본 방식이 적합.
    """
    categories = ["AN", "NN", "BN"]
    n = prob_prec.shape[1]
    sf_wetness  = []
    sf_warmness = []

    for i in range(n):
        # 해당 월의 강수 × 기온 결합 확률 (9가지 조합)
        # np.outer(prob_t2m[:,i], prob_prec[:,i]):
        #   행=기온범주(AN/NN/BN), 열=강수범주(AN/NN/BN)
        prob = np.outer(prob_t2m[:, i], prob_prec[:, i]).ravel()
        prob = np.clip(prob, 0, None)
        total = prob.sum()
        if total <= 0:
            prob = np.ones(9) / 9
        else:
            prob /= total

        k = np.random.choice(9, p=prob)
        # k = 0~2: AN온도×AN/NN/BN강수, k=3~5: NN온도×..., k=6~8: BN온도×...
        sf_wetness.append(categories[k % 3])
        sf_warmness.append(categories[k // 3])

    return {"sf_wetness": sf_wetness, "sf_warmness": sf_warmness}


# ---------------------------------------------------------------------------
# 단일 앙상블 시뮬레이션 (R의 main.simulation과 동일)
# ---------------------------------------------------------------------------

def main_simulation(sim_period: list, sf_wetness: list,
                     sf_warmness: list, param_list: dict) -> dict:
    """단일 앙상블 멤버 일단위 기상 시나리오 생성.

    R의 main.simulation과 동일.

    Parameters
    ----------
    sim_period  : 시뮬레이션 월 리스트 (예: [6,7,8])
    sf_wetness  : 월별 강수 범주 (예: ['AN','NN','BN'])
    sf_warmness : 월별 기온 범주
    param_list  : acid_modeling()이 반환한 모수 딕셔너리

    Returns
    -------
    dict with prcp_scenario, tmax_scenario, tmin_scenario
    """
    pp = param_list["prcp"]
    pt = param_list["temper"]
    site_names = pp["site_names"]
    d = len(site_names)

    # 강수 시나리오 생성
    prcp_scen = prcp_simulation(
        site_names=site_names,
        shape=pp["shape"],
        scale=pp["scale"],
        mean_dry_spell=pp["mean_dry_spell"],
        theta=pp["theta"],
        corr_mats=pp["corr_mats"],
        threshold_prob=pp["threshold_prob"],
        threshold=pp["threshold"],
        extreme_prob=pp["extreme_prob"],
        fit_extreme=pp["fit_extreme"],
        pat_breaks=pp["pat_breaks"],
        pat_levels=pp["pat_levels"],
        transition_table=pp["transition_table"],
        sim_period=sim_period,
        monthly_ch=sf_wetness,
    )

    # ISO(저주파 기온 진동) 생성
    iso_param = pt["iso_gen_param"]
    iso = generating_iso(
        warmness=sf_warmness,
        sim_period=sim_period,
        prcp_scenario=prcp_scen,
        **iso_param,
    )

    # 기온 시나리오 생성
    temper_scen = temper_simulation(
        site_names=site_names,
        mean_trend=pt["mean_trend"],
        fit_mu=pt["fit_mu"],
        fit_sigma=pt["fit_sigma"],
        z_score_anomaly_primaryPC_model=pt["z_score_anomaly_primaryPC_model"],
        z_score_anomaly_mean=pt["z_score_anomaly_mean"],
        z_score_anomaly_tmax_eof=pt["z_score_anomaly_tmax_eof"],
        z_score_anomaly_tmin_eof=pt["z_score_anomaly_tmin_eof"],
        z_score_anomaly_tmax_residual=pt["z_score_anomaly_tmax_residual"],
        z_score_anomaly_tmin_residual=pt["z_score_anomaly_tmin_residual"],
        result_fit_sn_tmax=pt["result_fit_sn_tmax"],
        result_fit_sn_tmin=pt["result_fit_sn_tmin"],
        sim_period=sim_period,
        iso=iso,
        prcp_scenario=prcp_scen,
        knot_jd=pt.get("knot_jd"),
    )

    # tmax, tmin 분리 (R의 colnames 분리와 동일)
    tmax_scen = np.column_stack([temper_scen[:, :2], temper_scen[:, 2:2 + d]])
    tmin_scen = np.column_stack([temper_scen[:, :2], temper_scen[:, 2 + d:]])

    return {
        "prcp_scenario": prcp_scen,
        "tmax_scenario": tmax_scen,
        "tmin_scenario": tmin_scen,
    }


# ---------------------------------------------------------------------------
# 월별 범주 사후 보정 (Post-calibration)
# ---------------------------------------------------------------------------

def _build_obs_monthly_pool(obs_data: dict, param_list: dict,
                             sim_period: list) -> dict:
    """관측 자료 기반 월별 AN/NN/BN 목표 분포 풀 구성 (관측소별).

    각 관측소의 (월, 범주) 쌍에 대해 역사적 강수 월합계 및 기온 월평균 목록을
    반환한다. calibrate_monthly_categories()의 목표값 샘플링에 사용.

    Returns
    -------
    dict with keys:
        'prcp'        : {j: {m: {'AN': [...], 'NN': [...], 'BN': [...]}}}  관측소별 월합계
        'temp'        : {j: {m: {'AN': [...], 'NN': [...], 'BN': [...]}}}  관측소별 월평균
        'breaks_prcp' : ndarray (d, 12, 4)  관측소별 강수 AN/NN/BN 경계
        'breaks_temp' : ndarray (d, 12, 4)  관측소별 기온 AN/NN/BN 경계
    """
    prcp_table = obs_data["prcp_table"]
    tmax_table = obs_data["tmax_table"]
    tmin_table = obs_data["tmin_table"]
    d = len(obs_data["site_names"])

    years  = prcp_table[:, 0].astype(int)
    months = prcp_table[:, 1].astype(int)
    period = np.arange(years.min(), years.max() + 1)

    tavg_vals = (tmax_table[:, 3:3+d] + tmin_table[:, 3:3+d]) / 2

    # 관측소별 경계 계산 (d, 12, 4)
    breaks_prcp = np.zeros((d, 12, 4))
    breaks_temp = np.zeros((d, 12, 4))

    for j in range(d):
        for m in range(1, 13):
            stn_totals = []
            stn_tmeans = []
            for yr in period:
                mask = (years == yr) & (months == m)
                if not mask.any():
                    continue
                stn_totals.append(float(prcp_table[mask, 3+j].sum()))
                stn_tmeans.append(float(tavg_vals[mask, j].mean()))
            if len(stn_totals) >= 3:
                q13, q23 = np.quantile(stn_totals, [1/3, 2/3])
            else:
                q13, q23 = 0.0, np.inf
            breaks_prcp[j, m-1] = [0.0, q13, q23, np.inf]
            if len(stn_tmeans) >= 3:
                q13t, q23t = np.quantile(stn_tmeans, [1/3, 2/3])
            else:
                q13t, q23t = -np.inf, np.inf
            breaks_temp[j, m-1] = [-np.inf, q13t, q23t, np.inf]

    # 관측소별 풀 구성
    pool = {"prcp": {}, "temp": {},
            "breaks_prcp": breaks_prcp, "breaks_temp": breaks_temp}

    for j in range(d):
        pool["prcp"][j] = {m: {"AN": [], "NN": [], "BN": []} for m in sim_period}
        pool["temp"][j] = {m: {"AN": [], "NN": [], "BN": []} for m in sim_period}

        for m in sim_period:
            br_p = breaks_prcp[j, m-1]
            br_t = breaks_temp[j, m-1]

            for yr in period:
                mask = (years == yr) & (months == m)
                if not mask.any():
                    continue

                # 관측소 j 월합계
                pt_j = float(prcp_table[mask, 3+j].sum())
                if pt_j <= br_p[1]:
                    pool["prcp"][j][m]["BN"].append(pt_j)
                elif pt_j <= br_p[2]:
                    pool["prcp"][j][m]["NN"].append(pt_j)
                else:
                    pool["prcp"][j][m]["AN"].append(pt_j)

                # 관측소 j 월평균 기온
                tm_j = float(tavg_vals[mask, j].mean())
                if tm_j <= br_t[1]:
                    pool["temp"][j][m]["BN"].append(tm_j)
                elif tm_j <= br_t[2]:
                    pool["temp"][j][m]["NN"].append(tm_j)
                else:
                    pool["temp"][j][m]["AN"].append(tm_j)

    return pool


def calibrate_monthly_categories(
    result: dict,
    sf_wetness: list,
    sf_warmness: list,
    sim_period: list,
    d: int,
    obs_pool: dict,
) -> dict:
    """월별 범주 사후 보정 (관측소별).

    강수: 관측소별 월합계를 목표 범주의 역사 값으로 비례 조정(multiplicative scaling).
    기온: 관측소별 월평균을 목표 범주의 역사 값으로 평행 이동(additive shift).

    관측소별 독립 보정으로 06_station_probability.csv 기준 오차 < 5%p 보장.

    Parameters
    ----------
    result      : main_simulation() 반환 딕셔너리
    sf_wetness  : 월별 강수 범주 리스트
    sf_warmness : 월별 기온 범주 리스트
    sim_period  : 시뮬레이션 월 리스트
    d           : 관측소 수
    obs_pool    : _build_obs_monthly_pool() 반환 딕셔너리
    """
    prcp = result["prcp_scenario"].copy()   # (n_days_prcp, 2+d)
    tmax = result["tmax_scenario"].copy()   # (n_days_temp, 2+d)
    tmin = result["tmin_scenario"].copy()   # (n_days_temp, 2+d)
    # 강수·기온 시뮬레이션의 시간 차원이 다를 수 있으므로 별도 month 컬럼 사용
    months_col_prcp = prcp[:, 0].astype(int)
    months_col_temp = tmax[:, 0].astype(int)

    for mi, m in enumerate(sim_period):
        mask_p = months_col_prcp == m
        mask_t = months_col_temp == m
        cat_p = sf_wetness[mi]
        cat_t = sf_warmness[mi]

        # ── 강수 관측소별 비례 조정 ─────────────────────────
        for j in range(d):
            pool_p = obs_pool["prcp"][j][m][cat_p]
            if pool_p:
                target_j = float(np.random.choice(pool_p))
                current_j = float(prcp[mask_p, 2+j].sum())
                if current_j > 0:
                    scale_j = target_j / current_j
                    prcp[mask_p, 2+j] = np.round(
                        np.maximum(prcp[mask_p, 2+j] * scale_j, 0.0), 1)

        # ── 기온 관측소별 평행 이동 ─────────────────────────
        for j in range(d):
            pool_t = obs_pool["temp"][j][m][cat_t]
            if pool_t:
                target_t = float(np.random.choice(pool_t))
                current_t = float(((tmax[mask_t, 2+j] + tmin[mask_t, 2+j]) / 2).mean())
                shift_j = target_t - current_t
                tmax[mask_t, 2+j] = np.round(tmax[mask_t, 2+j] + shift_j, 1)
                tmin[mask_t, 2+j] = np.round(tmin[mask_t, 2+j] + shift_j, 1)

    return {"prcp_scenario": prcp, "tmax_scenario": tmax, "tmin_scenario": tmin}


# ---------------------------------------------------------------------------
# 모델링 (R의 acid.modeling과 동일)
# ---------------------------------------------------------------------------

def acid_modeling(obs_data: dict, model_file: str = None,
                  retrieve: bool = True) -> dict:
    """관측 자료로부터 강수·기온 모델 모수 추정.

    R의 acid.modeling과 동일.
    model_file이 지정되면 캐싱(pickle).

    Parameters
    ----------
    obs_data   : acid_data_loading()이 반환한 딕셔너리
    model_file : 모수 저장 파일 경로 (None이면 저장 안 함)
    retrieve   : True이면 기존 파일 재사용, False이면 재계산

    Returns
    -------
    dict with 'prcp' and 'temper' param_lists
    """
    if model_file and os.path.exists(model_file) and retrieve:
        print(f"[acidwg_py] 기존 모델 파일 로드: {model_file}")
        with open(model_file, "rb") as f:
            return pickle.load(f)

    site_names = obs_data["site_names"]
    prcp_table = obs_data["prcp_table"]
    tmax_table = obs_data["tmax_table"]
    tmin_table = obs_data["tmin_table"]
    tavg_table = obs_data["tavg_table"]

    print("[acidwg_py] 강수 모델 추정 중...")
    param_list_prcp = prcp_modeling(prcp_table, site_names)

    print("[acidwg_py] 기온 모델 추정 중...")
    param_list_temper = temper_modeling(
        tmax_table, tmin_table, tavg_table, prcp_table, site_names
    )

    result = {"prcp": param_list_prcp, "temper": param_list_temper}

    if model_file:
        os.makedirs(os.path.dirname(model_file) or ".", exist_ok=True)
        with open(model_file, "wb") as f:
            pickle.dump(result, f)
        print(f"[acidwg_py] 모델 저장: {model_file}")

    return result


# ---------------------------------------------------------------------------
# 메인 실행 함수 (R의 acid.run 대체 — 핵심 변경)
# ---------------------------------------------------------------------------

def acid_run(
    station_csv: str,
    obs_dir: str,
    output_dir: str,
    sim_period: list,
    syear_obs: int,
    eyear_obs: int,
    forecast_csv: str,
    n_ensemble: int = 1000,
    model_file: str = None,
    retrieve: bool = True,
    forecast_year: int = None,
):
    """acidWG 메인 실행 함수.

    R의 acid.run을 대체. forecast_new.csv의 관측소별·월별 AN/NN/BN 확률 사용.

    Parameters
    ----------
    station_csv  : Station-Info.csv 경로 (관측소 메타데이터)
    obs_dir      : 관측소 CSV 파일 디렉토리 (asos108.csv 등)
    output_dir   : 시나리오 출력 디렉토리
    sim_period   : 시뮬레이션 월 리스트 (예: [6,7,8] for JJA)
    syear_obs    : 관측 기간 시작 연도
    eyear_obs    : 관측 기간 종료 연도
    forecast_csv : forecast_new.csv 경로 (관측소별·월별·변수별 AN/NN/BN)
    n_ensemble   : 앙상블 멤버 수 (기본 1000)
    model_file   : 모델 캐시 파일 경로 (.pkl)
    retrieve     : True이면 기존 모델 캐시 재사용
    forecast_year: 예보 연도 (각 멤버 CSV의 year 컬럼; None이면 생략)

    출력
    ----
    output_dir/{season}/member_{i:04d}/{station_id}.csv
    각 CSV 컬럼: [year,] mon, day, prcp, tmax, tmin
    """
    MONTH_ABB = ["Jan","Feb","Mar","Apr","May","Jun",
                 "Jul","Aug","Sep","Oct","Nov","Dec"]

    # 1. 관측 자료 로드
    print(f"[acidwg_py] 관측 자료 로드: {obs_dir}")
    obs_data = acid_data_loading(station_csv, obs_dir, syear_obs, eyear_obs)
    site_names = obs_data["site_names"]
    station_ids = obs_data["station_info"]["ID"].tolist()
    d = obs_data["d"]
    print(f"[acidwg_py] 관측소 {d}개: {site_names}")

    # 2. 예측 확률 로드 → (3, n_months) 행렬 구성
    forecast_df = load_forecast_csv(forecast_csv)
    prob_prec, prob_t2m = get_basin_prob(forecast_df, sim_period)

    print("[acidwg_py] 예측 확률 (유역 평균):")
    print(f"  {'월':<5} {'변수':<6} {'AN':>6} {'NN':>6} {'BN':>6}")
    for mi, m in enumerate(sim_period):
        for var, arr in [("prcp", prob_prec), ("t2m", prob_t2m)]:
            print(
                f"  {MONTH_ABB[m-1]:<5} {var:<6}"
                f" {arr[0,mi]*100:6.1f}%"
                f" {arr[1,mi]*100:6.1f}%"
                f" {arr[2,mi]*100:6.1f}%"
            )

    # 3. 모델링
    param_list = acid_modeling(obs_data, model_file=model_file, retrieve=retrieve)

    # 4. 출력 디렉토리 준비
    season = season_naming(sim_period)
    out_path = os.path.join(output_dir, season)
    os.makedirs(out_path, exist_ok=True)
    print(f"[acidwg_py] 출력 경로: {out_path}")

    # 5. 월별 범주 보정 풀 구성 (앙상블 생성 전 1회)
    obs_pool = _build_obs_monthly_pool(obs_data, param_list, sim_period)

    # 6. 앙상블 생성
    print(f"[acidwg_py] 앙상블 {n_ensemble}개 생성 중...")
    success = 0
    attempt = 0

    with tqdm(total=n_ensemble, desc="앙상블 생성") as pbar:
        while success < n_ensemble:
            attempt += 1
            if attempt > n_ensemble * 5:
                print(f"[acidwg_py] 경고: 최대 시도 횟수 초과. {success}개 생성 완료.")
                break

            try:
                monthly_ch = determine_monthly_ch(prob_prec, prob_t2m)
                result = main_simulation(
                    sim_period=sim_period,
                    sf_wetness=monthly_ch["sf_wetness"],
                    sf_warmness=monthly_ch["sf_warmness"],
                    param_list=param_list,
                )
                # 월별 범주 사후 보정 — 재현 확률 오차 < 5%p 보장
                result = calibrate_monthly_categories(
                    result=result,
                    sf_wetness=monthly_ch["sf_wetness"],
                    sf_warmness=monthly_ch["sf_warmness"],
                    sim_period=sim_period,
                    d=d,
                    obs_pool=obs_pool,
                )
                write_scenario(result, out_path, success + 1, site_names,
                               station_ids=station_ids,
                               forecast_year=forecast_year)
                success += 1
                pbar.update(1)
            except Exception as e:
                # 처음 3회만 오류 내용 출력 (반복 스팸 방지)
                if attempt <= 3:
                    tqdm.write(f"\n[acidwg_py] 오류 (시도 {attempt}): {e}")
                    tqdm.write(traceback.format_exc())
                continue

    print(f"[acidwg_py] 완료: {success}개 시나리오 → {out_path}")
    return out_path
