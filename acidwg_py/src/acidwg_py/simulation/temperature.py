"""
기온 시뮬레이션 — R Base.R의 generating.iso / temper.simulation 포팅

1. generating_iso  : 기온 저주파 진동(ISO) 생성 — sf.warmness 범주 기반
2. temper_simulation: 일단위 기온 시나리오 생성 — AR(p) + EOF + 왜도정규분포
"""

import numpy as np
from scipy.stats import skewnorm, norm

from acidwg_py.utils import get_julian_day, distance, MONTH_LENGTH

LEVELS = ["BN", "NN", "AN"]


# ---------------------------------------------------------------------------
# 1. ISO (저주파 기온 진동) 생성
# ---------------------------------------------------------------------------

def generating_iso(
    warmness: list,
    sim_period: list,
    iso_tmax_mean: np.ndarray,   # (365, d)
    iso_tmin_mean: np.ndarray,   # (365, d)
    iso_tmax_dev: np.ndarray,    # (n_years, 365, d)
    iso_tmin_dev: np.ndarray,    # (n_years, 365, d)
    breaks: np.ndarray,          # (12, 4)
    length_period: int,
    levels: list,
    prcp_scenario: np.ndarray,   # (n_days, 2+d)
    fit_mu,
    mean_trend,
    **kwargs,
) -> dict:
    """기온 저주파 진동 생성.

    R의 generating.iso (version 2)와 동일.
    sf.warmness에 따라 과거 년도에서 적합한 ISO 편차를 샘플링.

    Returns
    -------
    iso : dict {'TMAX': (365,d), 'TMIN': (365,d)}
    """
    d = iso_tmax_mean.shape[1]
    n_years = iso_tmax_dev.shape[0]

    # sim_period가 연말을 포함하는 경우(예: DJF)
    if len(sim_period) > 1 and sim_period[0] > sim_period[-1]:
        # 연도 경계를 교차하는 경우: 앞해 + 뒷해 합치기
        n = n_years - 1
        iso_dev_t = np.zeros((n, 365, d))
        iso_dev_n = np.zeros((n, 365, d))
        cal_month = []
        cum = 0
        for m in range(1, 13):
            for _ in range(MONTH_LENGTH[m - 1]):
                cal_month.append(m)

        i_flag = np.array([m < sim_period[0] for m in cal_month])
        for j in range(d):
            iso_dev_t[:, :, j] = np.concatenate(
                [iso_tmax_dev[1:, i_flag, j], iso_tmax_dev[:n, ~i_flag, j]], axis=1
            )
            iso_dev_n[:, :, j] = np.concatenate(
                [iso_tmin_dev[1:, i_flag, j], iso_tmin_dev[:n, ~i_flag, j]], axis=1
            )
    else:
        n = n_years
        iso_dev_t = iso_tmax_dev
        iso_dev_n = iso_tmin_dev

    # warmness 기반으로 적합한 연도 선택
    # breaks[month-1] = [−∞, q1/3, q2/3, +∞]  (LOESS 대비 °C 이상편차 기반)
    level_idx = {"BN": 0, "NN": 1, "AN": 2}
    m0 = sim_period[0]          # 첫 번째 시뮬레이션 월 (1-based)
    w = warmness[0] if warmness else "NN"
    wi = level_idx.get(w, 1)
    br = breaks[m0 - 1]         # [−∞, q1/3, q2/3, +∞]

    # raw_basin_anom: 연도별 월평균 기온 이상편차 (°C), shape (n_years, 12)
    raw_basin_anom = kwargs.get("raw_basin_anom", None)

    if raw_basin_anom is not None:
        yr_vals = raw_basin_anom[:, m0 - 1]  # 첫 번째 시뮬레이션 월의 연도별 이상편차
        if wi == 0:    # BN — 평균 이하 연도
            valid = np.where(yr_vals <= br[1])[0]
        elif wi == 2:  # AN — 평균 이상 연도
            valid = np.where(yr_vals > br[2])[0]
        else:          # NN — 중간 연도
            valid = np.where((yr_vals > br[1]) & (yr_vals <= br[2]))[0]

        if len(valid) == 0:
            valid = np.arange(n)  # fallback: 전체 연도에서 선택
        sampled_year = int(np.random.choice(valid))
    else:
        sampled_year = np.random.randint(0, n)

    iso_tmax_sim = iso_tmax_mean + iso_dev_t[sampled_year]  # (365, d), °C
    iso_tmin_sim = iso_tmin_mean + iso_dev_n[sampled_year]

    return {
        "TMAX": iso_tmax_sim,
        "TMIN": iso_tmin_sim,
    }


# ---------------------------------------------------------------------------
# 2. 기온 시뮬레이션
# ---------------------------------------------------------------------------

def temper_simulation(
    site_names: list,
    mean_trend: dict,
    fit_mu: dict,
    fit_sigma: dict,
    z_score_anomaly_primaryPC_model: dict,
    z_score_anomaly_mean: np.ndarray,      # (12, 2d)
    z_score_anomaly_tmax_eof: dict,         # {month: (d, 2)}
    z_score_anomaly_tmin_eof: dict,
    z_score_anomaly_tmax_residual: dict,
    z_score_anomaly_tmin_residual: dict,
    result_fit_sn_tmax: dict,
    result_fit_sn_tmin: dict,
    sim_period: list,
    iso: dict,
    prcp_scenario: np.ndarray,
    knot_jd: np.ndarray = None,
    **kwargs,
) -> np.ndarray:
    """일단위 기온 시나리오 생성.

    R의 temper.simulation과 동일.

    Returns
    -------
    temper : ndarray (n_days, 2+2d) — [Month, Day, TMAX_stn1,..., TMIN_stn1,...]
    """
    d = len(site_names)
    n = sum(MONTH_LENGTH[m - 1] for m in sim_period)

    name_tmax = [f"TMAX_{sn}" for sn in site_names]
    name_tmin = [f"TMIN_{sn}" for sn in site_names]

    # 출력 행렬 구성
    temper = np.zeros((n, 2 + 2 * d), dtype=float)
    idx = 0
    for m in sim_period:
        for day in range(1, MONTH_LENGTH[m - 1] + 1):
            temper[idx, 0] = m
            temper[idx, 1] = day
            idx += 1

    # burn-in AR
    s0 = sim_period[0]
    pc_model_s0 = z_score_anomaly_primaryPC_model[s0]
    p_order = pc_model_s0["order"]
    ar_coef = pc_model_s0["ar_coef"]
    error_cov = pc_model_s0["error_cov"]
    length_burnin = 100

    # EOF 차원에서 PC 개수 자동 추출 (n_comp = min(2, d))
    # 기존엔 n_pc=4 (d>=2 가정) 하드코딩 → d=1 사이트에서 차원 mismatch 였음
    n_comp = z_score_anomaly_tmax_eof[s0].shape[1]
    n_pc   = 2 * n_comp                 # tmax PC + tmin PC

    P = np.zeros((length_burnin + n, n_pc))
    for i in range(p_order, length_burnin):
        pred = np.concatenate([P[i - h] for h in range(1, p_order + 1)])
        try:
            error = np.random.multivariate_normal(np.zeros(n_pc), error_cov)
        except Exception:
            error = np.random.randn(n_pc)
        P[i] = ar_coef @ pred + error

    def gen_error(s: int) -> np.ndarray:
        resids = z_score_anomaly_primaryPC_model[s]["resid"]
        if not resids:
            return np.random.randn(n_pc)
        ri = np.random.randint(len(resids))
        rr = resids[ri]
        if len(rr) == 0:
            return np.random.randn(n_pc)
        ti = np.random.randint(len(rr))
        return rr[ti]

    def inversion(z_score_anom: np.ndarray, s: int) -> np.ndarray:
        """z-score → 실제 이상편차 변환 (왜도정규분포 역변환)."""
        u = norm.cdf(z_score_anom)
        anom = np.zeros(2 * d)
        for j in range(d):
            p_t = result_fit_sn_tmax[s][j]
            p_n = result_fit_sn_tmin[s][j]
            ui_t = float(np.clip(u[j], 1e-6, 1 - 1e-6))
            ui_n = float(np.clip(u[d + j], 1e-6, 1 - 1e-6))
            anom[j] = float(skewnorm.ppf(ui_t,
                                         a=p_t["alpha"],
                                         loc=p_t["xi"],
                                         scale=p_t["omega"]))
            anom[d + j] = float(skewnorm.ppf(ui_n,
                                              a=p_n["alpha"],
                                              loc=p_n["xi"],
                                              scale=p_n["omega"]))
        return anom

    # 달력 월 배열 (1~365 반복)
    cal_month = []
    for m in range(1, 13):
        for _ in range(MONTH_LENGTH[m - 1]):
            cal_month.append(m)

    iso_tmax = iso["TMAX"]  # (365, d)
    iso_tmin = iso["TMIN"]

    for i in range(n):
        si = i + length_burnin
        m = int(temper[i, 0])
        day = int(temper[i, 1])
        jd = get_julian_day(m, day)

        # 월 선택 (±15일 이내 달력 월 중 랜덤)
        nearby = [cal_month[jd2 - 1]
                  for jd2 in range(1, 366)
                  if distance(jd2, jd) <= 15]
        if not nearby:
            nearby = [m]
        s = int(np.random.choice(nearby))

        pc_model = z_score_anomaly_primaryPC_model[s]
        p_ord = pc_model["order"]
        ar_c = pc_model["ar_coef"]
        err_cov = pc_model["error_cov"]

        # 평균 기온 및 표준편차 예측
        trend_mu = _predict_mean_daily(
            jd, fit_mu, site_names, iso_tmax, iso_tmin, mean_trend, knot_jd
        )
        trend_sigma = _predict_sigma_daily(
            i, jd, fit_sigma, site_names, prcp_scenario, knot_jd
        )

        pred_vec = np.concatenate([P[si - h] for h in range(1, p_ord + 1)])
        mv_P = ar_c @ pred_vec

        max_try = 10
        for r in range(max_try):
            pc = mv_P + gen_error(s)

            z1 = np.zeros(2 * d)
            eof_t = z_score_anomaly_tmax_eof[s]  # (d, n_comp)
            eof_n = z_score_anomaly_tmin_eof[s]
            z1[:d] = eof_t @ pc[:n_comp]
            z1[d:] = eof_n @ pc[n_comp:2 * n_comp]

            resid_t = z_score_anomaly_tmax_residual[s]
            resid_n = z_score_anomaly_tmin_residual[s]
            z2 = np.zeros(2 * d)
            if resid_t is not None and len(resid_t) > 0:
                ai = np.random.randint(len(resid_t))
                z2[:d] = resid_t[ai]
            if resid_n is not None and len(resid_n) > 0:
                ai = np.random.randint(len(resid_n))
                z2[d:] = resid_n[ai]

            z_anom = z1 + z2 + np.concatenate([
                z_score_anomaly_mean[s - 1, :d],
                z_score_anomaly_mean[s - 1, d:],
            ])

            anom = inversion(z_anom, s)

            tmax_sim = trend_mu[:d] + trend_sigma[:d] * anom[:d]
            tmin_sim = trend_mu[d:] + trend_sigma[d:] * anom[d:]

            # 제약: TMAX > TMIN
            prev_tmax = temper[max(i - 1, 0), 2:2 + d] if i > 0 else tmax_sim
            if np.all(tmax_sim > tmin_sim) and np.all(prev_tmax > tmin_sim):
                P[si] = pc
                break

            if r == max_try - 1:
                tmin_sim = np.minimum(tmax_sim - 0.1, prev_tmax - 0.1)
                P[si] = pc

        temper[i, 2:2 + d] = np.round(tmax_sim, 1)
        temper[i, 2 + d:] = np.round(tmin_sim, 1)

    return temper


def _predict_mean_daily(jd: int, fit_mu: dict, site_names: list,
                        iso_tmax: np.ndarray, iso_tmin: np.ndarray,
                        mean_trend: dict, knot_jd) -> np.ndarray:
    """일별 평균 기온 예측 (TMAX d개 + TMIN d개 벡터 반환)."""
    d = len(site_names)
    result = np.zeros(2 * d)

    for vi, var in enumerate(["TMAX", "TMIN"]):
        iso = iso_tmax if var == "TMAX" else iso_tmin
        trend = mean_trend[var]
        for j, sn in enumerate(site_names):
            trend_val = float(trend[jd - 1, j])
            # iso_daily: LOESS 대비 샘플 연도의 실제 기온 이상편차 (°C)
            # iso_val을 0으로 고정하여 특정 연도(최초 연도) 편향을 제거.
            # 연도 간 변동은 iso_daily가 완전히 담당.
            iso_daily = float(iso[jd - 1, j])
            result[vi * d + j] = trend_val + iso_daily

    return result


def _predict_sigma_daily(i: int, jd: int, fit_sigma: dict,
                         site_names: list, prcp_scenario: np.ndarray,
                         knot_jd) -> np.ndarray:
    """일별 기온 표준편차 예측 (TMAX d개 + TMIN d개 벡터 반환)."""
    d = len(site_names)
    result = np.ones(2 * d)

    for vi, var in enumerate(["TMAX", "TMIN"]):
        for j, sn in enumerate(site_names):
            if knot_jd is not None:
                dists = [distance(jd, kj) for kj in knot_jd]
                l_idx = int(np.argmin(dists))
                log_s = fit_sigma[var][sn][l_idx]["log_sigma"]
                result[vi * d + j] = max(np.exp(log_s), 0.1)
            else:
                result[vi * d + j] = 1.0

    return result
