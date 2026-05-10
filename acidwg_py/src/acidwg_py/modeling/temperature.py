"""
기온 모델링 — R Modeling.R의 temper.modeling / Base.R의 detrending 포팅

단계:
  1. detrending  : LOESS로 연주기 평균 추세 제거, 회귀로 강수 효과 제거
  2. EOF 분해    : z-score 이상편차의 주성분 분석
  3. pooled AR(p): 다변량 AR(2) 모수 추정 (Yule-Walker)
  4. 왜도 정규분포 적합 (scipy.stats.skewnorm)
"""

import numpy as np
from scipy.stats import skewnorm
from scipy.optimize import minimize
from scipy.linalg import pinv
from sklearn.decomposition import PCA
from statsmodels.nonparametric.smoothers_lowess import lowess

from acidwg_py.utils import get_julian_day, distance, difference, MONTH_LENGTH

MONTH_ABB = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def _build_julian_days(table):
    """테이블의 Month, Day 컬럼으로 Julian day 배열 생성."""
    months = table[:, 1].astype(int)
    days = table[:, 2].astype(int)
    return np.array([get_julian_day(m, d) for m, d in zip(months, days)], dtype=int)


# ---------------------------------------------------------------------------
# 1. Detrending
# ---------------------------------------------------------------------------

def detrending(tmax_table: np.ndarray, tmin_table: np.ndarray,
               prcp_table: np.ndarray, site_names: list,
               span: float = 0.1) -> dict:
    """기온의 연주기 평균 추세 및 강수 효과 제거.

    R의 detrending()과 동일한 목적.
    단순화: LOESS로 연중 평균 추세를 제거한 후,
    강수 효과는 월별 선형 회귀로 추정.

    Returns
    -------
    dict with:
        mean_trend   : {'TMAX': (365, d), 'TMIN': (365, d)}
        fit_mu       : 일평균 예측 모수 구조
        fit_sigma    : 일표준편차 예측 모수 구조
        anomaly      : ndarray (n, 3+2d)  — 정규화된 이상편차
        mu           : {'TMAX': table, 'TMIN': table}
        sigma        : {'TMAX': table, 'TMIN': table}
    """
    d = len(site_names)
    n = len(tmax_table)
    years = tmax_table[:, 0].astype(int)
    months = tmax_table[:, 1].astype(int)
    days_col = tmax_table[:, 2].astype(int)
    jd_arr = _build_julian_days(tmax_table)
    period = np.arange(years.min(), years.max() + 1)
    tmax_vals = tmax_table[:, 3:3 + d]
    tmin_vals = tmin_table[:, 3:3 + d]
    prcp_vals = prcp_table[:, 3:3 + d]

    # 연주기 평균 추세 (LOESS, R의 loess(span=0.1)과 동일)
    mean_trend_tmax = np.zeros((365, d))
    mean_trend_tmin = np.zeros((365, d))
    mean_adj_tmax = np.zeros((n, d))
    mean_adj_tmin = np.zeros((n, d))

    for j in range(d):
        # 양 끝 연장 처리 (R과 동일: 10~12월 → 앞, 1~3월 → 뒤 추가)
        mask_oct_dec = np.isin(months, [10, 11, 12])
        mask_jan_mar = np.isin(months, [1, 2, 3])

        x_ext = np.concatenate([
            jd_arr[mask_oct_dec] - 365,
            jd_arr,
            jd_arr[mask_jan_mar] + 365,
        ])
        y_tmax = np.concatenate([
            tmax_vals[mask_oct_dec, j],
            tmax_vals[:, j],
            tmax_vals[mask_jan_mar, j],
        ])
        y_tmin = np.concatenate([
            tmin_vals[mask_oct_dec, j],
            tmin_vals[:, j],
            tmin_vals[mask_jan_mar, j],
        ])

        # LOESS 적합
        jd_query = np.arange(1, 366)
        frac = span
        smooth_tmax = lowess(y_tmax, x_ext, frac=frac, return_sorted=True)
        smooth_tmin = lowess(y_tmin, x_ext, frac=frac, return_sorted=True)

        # 쿼리 포인트에서 보간
        mean_trend_tmax[:, j] = np.interp(jd_query, smooth_tmax[:, 0], smooth_tmax[:, 1])
        mean_trend_tmin[:, j] = np.interp(jd_query, smooth_tmin[:, 0], smooth_tmin[:, 1])

        # 이상편차 계산
        mean_adj_tmax[:, j] = tmax_vals[:, j] - mean_trend_tmax[jd_arr - 1, j]
        mean_adj_tmin[:, j] = tmin_vals[:, j] - mean_trend_tmin[jd_arr - 1, j]

    mean_trend = {"TMAX": mean_trend_tmax, "TMIN": mean_trend_tmin}

    # knot Julian days (R과 동일: 1~365를 37등분)
    knot_jd = np.round(np.linspace(1, 365, 37)).astype(int)

    # 강수 효과 모수 추정 (fit_mu, fit_sigma)
    # 단순화: knot별로 ±15일 데이터를 사용한 선형회귀
    fit_mu = _fit_mean_model(
        mean_adj_tmax, mean_adj_tmin, prcp_vals,
        jd_arr, years, period, site_names, knot_jd,
    )

    # 예측 평균 계산
    mu_tmax, mu_tmin = _predict_mean(
        fit_mu, prcp_vals, jd_arr, years, period,
        site_names, mean_trend, knot_jd,
    )

    # 편차
    dev_tmax = tmax_vals - mu_tmax
    dev_tmin = tmin_vals - mu_tmin

    # fit_sigma: 편차 제곱에 대한 knot별 GLM
    fit_sigma = _fit_sigma_model(
        dev_tmax, dev_tmin, prcp_vals,
        jd_arr, site_names, knot_jd,
    )

    # 예측 표준편차
    sigma_tmax, sigma_tmin = _predict_sigma(
        fit_sigma, prcp_vals, jd_arr, site_names, knot_jd,
    )

    # 이상편차 정규화
    anomaly_tmax = np.where(sigma_tmax > 0, dev_tmax / sigma_tmax, 0.0)
    anomaly_tmin = np.where(sigma_tmin > 0, dev_tmin / sigma_tmin, 0.0)

    # anomaly 행렬 구성 (n × (3 + 2d))
    anomaly = np.zeros((n, 3 + 2 * d))
    anomaly[:, :3] = tmax_table[:, :3]
    for j, sn in enumerate(site_names):
        anomaly[:, 3 + j] = anomaly_tmax[:, j]
        anomaly[:, 3 + d + j] = anomaly_tmin[:, j]

    mu = {
        "TMAX": np.column_stack([tmax_table[:, :3], mu_tmax]),
        "TMIN": np.column_stack([tmax_table[:, :3], mu_tmin]),
    }
    sigma = {
        "TMAX": np.column_stack([tmax_table[:, :3], sigma_tmax]),
        "TMIN": np.column_stack([tmax_table[:, :3], sigma_tmin]),
    }

    return {
        "mean_trend": mean_trend,
        "fit_mu": fit_mu,
        "fit_sigma": fit_sigma,
        "anomaly": anomaly,
        "mu": mu,
        "sigma": sigma,
        "knot_jd": knot_jd,
    }


def _fit_mean_model(mean_adj_tmax, mean_adj_tmin, prcp_vals,
                    jd_arr, years, period, site_names, knot_jd):
    """knot별 평균 회귀 모수 추정 (단순화 버전).
    각 knot에서 ±15일 이내 데이터로 선형 회귀 적합.
    반환값은 R의 fit.mu 구조와 유사한 중첩 dict.
    """
    d = len(site_names)
    n = len(jd_arr)

    fit_mu = {"TMAX": {}, "TMIN": {}}
    for var, adj in [("TMAX", mean_adj_tmax), ("TMIN", mean_adj_tmin)]:
        fit_mu[var] = {}
        for j, sn in enumerate(site_names):
            fit_mu[var][sn] = {}
            for ki, jd0 in enumerate(knot_jd):
                # ±15일 이내 데이터
                dists = np.array([distance(jd, jd0) for jd in jd_arr])
                k = np.where(dists <= 15)[0]
                if len(k) < 5:
                    fit_mu[var][sn][ki] = {
                        "iso_coef": np.zeros((len(period), 3)),
                        "prcp_coef": np.zeros(2),
                        "knot_jd": jd0,
                    }
                    continue

                time_vals = np.array([difference(jd_arr[i], jd0) for i in k])
                response = adj[k, j]

                # 강수 가중합 (단순 공간 평균)
                prcp_mean = prcp_vals[k].mean(axis=1)
                prcp_lag0 = prcp_mean
                prcp_lag1 = prcp_vals[np.clip(k - 1, 0, n - 1)].mean(axis=1)

                # 연도별 절편 + 시간 2차 + 강수 효과
                yr_k = years[k]
                n_k = len(k)

                # 연도 더미 (이분)
                X = np.column_stack([
                    time_vals,
                    time_vals**2,
                    prcp_lag0**0.5,
                    prcp_lag1**0.5,
                ])
                # 연도별 절편은 전체 평균 사용 (단순화)
                yr_intercept = {}
                for yr in period:
                    mask_yr = yr_k == yr
                    if mask_yr.any():
                        yr_intercept[yr] = float(response[mask_yr].mean())
                    else:
                        yr_intercept[yr] = 0.0

                # iso_coef: (n_years, 3) → [intercept, time_coef, time2_coef]
                iso_coef = np.zeros((len(period), 3))
                for yi, yr in enumerate(period):
                    iso_coef[yi, 0] = yr_intercept.get(yr, 0.0)

                # 강수 효과 계수 (간단히 OLS)
                if X.shape[0] > X.shape[1]:
                    try:
                        from numpy.linalg import lstsq
                        coef, _, _, _ = lstsq(X, response - np.array(
                            [yr_intercept.get(yr, 0.0) for yr in yr_k]), rcond=None)
                        prcp_coef = coef[2:4]
                    except Exception:
                        prcp_coef = np.zeros(2)
                else:
                    prcp_coef = np.zeros(2)

                fit_mu[var][sn][ki] = {
                    "iso_coef": iso_coef,
                    "prcp_coef": prcp_coef,
                    "knot_jd": jd0,
                }

    return fit_mu


def _predict_mean(fit_mu, prcp_vals, jd_arr, years, period,
                  site_names, mean_trend, knot_jd):
    """fit_mu를 이용해 일별 평균 기온 예측."""
    d = len(site_names)
    n = len(jd_arr)
    mu_tmax = np.zeros((n, d))
    mu_tmin = np.zeros((n, d))

    for var, mu_arr in [("TMAX", mu_tmax), ("TMIN", mu_tmin)]:
        for j, sn in enumerate(site_names):
            for i in range(n):
                jd = int(jd_arr[i])
                yr = int(years[i])
                # 가장 가까운 knot 찾기
                dists = [distance(jd, kj) for kj in knot_jd]
                l_idx = int(np.argmin(dists))
                knot = knot_jd[l_idx]

                fm = fit_mu[var][sn][l_idx]
                yi = np.searchsorted(period, yr)
                if yi >= len(period):
                    yi = len(period) - 1

                iso_val = float(fm["iso_coef"][yi, 0])
                mean_t = mean_trend[var][jd - 1, j]
                mu_arr[i, j] = mean_t + iso_val

    return mu_tmax, mu_tmin


def _fit_sigma_model(dev_tmax, dev_tmin, prcp_vals, jd_arr, site_names, knot_jd):
    """편차 제곱에 대한 knot별 분산 모델 추정."""
    d = len(site_names)
    n = len(jd_arr)

    fit_sigma = {"TMAX": {}, "TMIN": {}}
    for var, dev in [("TMAX", dev_tmax), ("TMIN", dev_tmin)]:
        fit_sigma[var] = {}
        for j, sn in enumerate(site_names):
            fit_sigma[var][sn] = {}
            for ki, jd0 in enumerate(knot_jd):
                dists = np.array([distance(jd, jd0) for jd in jd_arr])
                k = np.where(dists <= 15)[0]

                if len(k) < 5:
                    fit_sigma[var][sn][ki] = {"log_sigma": 0.0, "knot_jd": jd0}
                    continue

                sq_dev = dev[k, j]**2
                pos_mask = sq_dev > 1e-5
                if pos_mask.sum() < 3:
                    fit_sigma[var][sn][ki] = {
                        "log_sigma": float(np.log(np.mean(sq_dev) + 1e-10) / 2),
                        "knot_jd": jd0,
                    }
                    continue

                log_sq = np.log(sq_dev[pos_mask] + 1e-10)
                fit_sigma[var][sn][ki] = {
                    "log_sigma": float(log_sq.mean() / 2),
                    "knot_jd": jd0,
                }

    return fit_sigma


def _predict_sigma(fit_sigma, prcp_vals, jd_arr, site_names, knot_jd):
    """fit_sigma를 이용해 일별 표준편차 예측."""
    d = len(site_names)
    n = len(jd_arr)
    sigma_tmax = np.zeros((n, d))
    sigma_tmin = np.zeros((n, d))

    for var, sig_arr in [("TMAX", sigma_tmax), ("TMIN", sigma_tmin)]:
        for j, sn in enumerate(site_names):
            for i in range(n):
                jd = int(jd_arr[i])
                dists = [distance(jd, kj) for kj in knot_jd]
                l_idx = int(np.argmin(dists))
                log_s = fit_sigma[var][sn][l_idx]["log_sigma"]
                sig_arr[i, j] = np.exp(log_s)
                if sig_arr[i, j] < 0.1:
                    sig_arr[i, j] = 0.1

    return sigma_tmax, sigma_tmin


# ---------------------------------------------------------------------------
# 2. Pooled Yule-Walker AR(p) 추정
# ---------------------------------------------------------------------------

def pooled_yule_walker(series_list: list, p: int = 2) -> dict:
    """다변량 AR(p) 계수행렬 및 오차 공분산 추정.

    R의 pooled.YuleWalker.estimation(no.intercept=TRUE)과 동일.

    Parameters
    ----------
    series_list : list of ndarray, each shape (T_i, dim_X)
                  연도별 시계열 데이터
    p           : AR 차수

    Returns
    -------
    dict with ar_coef, error_cov, order, resid
    """
    m = len(series_list)
    dim_X = series_list[0].shape[1]

    # 공분산 행렬 G(h) 계산
    G = {}
    Z0 = np.zeros((dim_X, dim_X))
    for xi in series_list:
        n_i = len(xi)
        Z0 += (xi.T @ xi) / n_i
    G[0] = Z0 / m

    for h in range(1, p + 1):
        Zh = np.zeros((dim_X, dim_X))
        for xi in series_list:
            n_i = len(xi)
            Zh += (xi[h:].T @ xi[:-h]) / n_i
        G[h] = Zh / m

    for h in range(-p + 1, 0):
        G[h] = G[-h].T

    # Yule-Walker 행렬 구성
    V = np.hstack([G[h] for h in range(1, p + 1)])  # (dim_X, dim_X*p)

    rows = []
    for i in range(1, p + 1):
        cols = []
        for j in range(1, p + 1):
            cols.append(G[j - i])
        rows.append(np.hstack(cols))
    M = np.vstack(rows)  # (dim_X*p, dim_X*p)

    ar_coef = V @ pinv(M)  # (dim_X, dim_X*p)

    # 잔차 및 오차 공분산
    resid_list = []
    error_cov = np.zeros((dim_X, dim_X))
    for xi in series_list:
        n_i = len(xi)
        resid = np.zeros_like(xi)
        for t in range(p, n_i):
            pred_vec = np.concatenate([xi[t - h] for h in range(1, p + 1)])
            resid[t] = xi[t] - ar_coef @ pred_vec
        resid = resid[p:]
        if len(resid) > 1:
            error_cov += np.cov(resid.T, bias=False)
        resid_list.append(resid)

    error_cov /= m

    return {
        "ar_coef": ar_coef,
        "error_cov": error_cov,
        "order": p,
        "resid": resid_list,
        "center": np.zeros((m, dim_X)),
    }


# ---------------------------------------------------------------------------
# 3. 기온 모델링 메인
# ---------------------------------------------------------------------------

def temper_modeling(tmax_table: np.ndarray, tmin_table: np.ndarray,
                    tavg_table: np.ndarray, prcp_table: np.ndarray,
                    site_names: list, result_detrending: dict = None) -> dict:
    """기온 모델 전체 모수 추정.

    R의 temper.modeling과 동일.
    """
    d = len(site_names)
    months = tmax_table[:, 1].astype(int)
    years = tmax_table[:, 0].astype(int)
    period = np.arange(years.min(), years.max() + 1)
    n = len(tmax_table)

    if result_detrending is None:
        result_detrending = detrending(
            tmax_table, tmin_table, prcp_table, site_names
        )

    knot_jd = result_detrending["knot_jd"]

    # --- ISO 저주파 진동 파라미터 ---
    # ISO는 LOESS 평균 대비 연도별 실제 기온 이상편차(°C)로 저장.
    # z-score 단위로 저장하면 trend_val(°C)과 단위가 불일치하므로 원시 편차 사용.
    anomaly = result_detrending["anomaly"]
    anomaly_tmax = anomaly[:, 3:3 + d]      # z-score (EOF/AR 모델용)
    anomaly_tmin = anomaly[:, 3 + d:3 + 2 * d]

    jd_arr = _build_julian_days(tmax_table)
    tmax_vals_iso = tmax_table[:, 3:3 + d]
    tmin_vals_iso = tmin_table[:, 3:3 + d]
    mean_trend_t = result_detrending["mean_trend"]["TMAX"]  # (365, d)
    mean_trend_n = result_detrending["mean_trend"]["TMIN"]  # (365, d)

    # LOESS 대비 원시 편차 (°C)
    raw_tmax_anom = tmax_vals_iso - mean_trend_t[jd_arr - 1]  # (n, d)
    raw_tmin_anom = tmin_vals_iso - mean_trend_n[jd_arr - 1]  # (n, d)

    iso_tmax = np.zeros((len(period), 365, d))
    iso_tmin = np.zeros((len(period), 365, d))

    for jd in range(1, 366):
        mask_jd = jd_arr == jd
        for yi, yr in enumerate(period):
            mask_yr = years == yr
            mask = mask_jd & mask_yr
            if mask.any():
                iso_tmax[yi, jd - 1] = raw_tmax_anom[mask].mean(axis=0)  # °C
                iso_tmin[yi, jd - 1] = raw_tmin_anom[mask].mean(axis=0)  # °C

    iso_tmax_mean = iso_tmax.mean(axis=0)  # (365, d) — 다년 평균 ≈ 0
    iso_tmin_mean = iso_tmin.mean(axis=0)

    iso_tmax_dev = iso_tmax - iso_tmax_mean[np.newaxis]  # (n_years, 365, d)
    iso_tmin_dev = iso_tmin - iso_tmin_mean[np.newaxis]

    # BN/NN/AN 범주 경계: LOESS 대비 연도별 월평균 이상편차(°C) 기반
    # 장기 추세를 제거하고 연도 간 변동(ISO)만으로 범주 결정
    raw_basin_anom = np.zeros((len(period), 12))  # (n_years, 12), °C
    for m in range(1, 13):
        mask_m = months == m
        for yi, yr in enumerate(period):
            mask = mask_m & (years == yr)
            if mask.any():
                raw_basin_anom[yi, m - 1] = (
                    raw_tmax_anom[mask].mean() + raw_tmin_anom[mask].mean()
                ) / 2.0

    breaks_iso = np.column_stack([
        np.full(12, -np.inf),
        np.quantile(raw_basin_anom, 1 / 3, axis=0),
        np.quantile(raw_basin_anom, 2 / 3, axis=0),
        np.full(12, np.inf),
    ])  # (12, 4)

    iso_gen_param = {
        "iso_tmax_mean": iso_tmax_mean,
        "iso_tmin_mean": iso_tmin_mean,
        "iso_tmax_dev": iso_tmax_dev,
        "iso_tmin_dev": iso_tmin_dev,
        "breaks": breaks_iso,
        "length_period": len(period),
        "levels": ["BN", "NN", "AN"],
        "fit_mu": result_detrending["fit_mu"],
        "mean_trend": result_detrending["mean_trend"],
        "raw_basin_anom": raw_basin_anom,  # warmness 기반 연도 선택용 (°C)
    }

    # --- z-score 이상편차 계산 ---
    z_score_tmax = np.zeros_like(anomaly_tmax)
    z_score_tmin = np.zeros_like(anomaly_tmin)

    for m in range(1, 13):
        k = months == m
        for j in range(d):
            vals_t = anomaly_tmax[k, j]
            vals_n = anomaly_tmin[k, j]
            from scipy.stats import rankdata
            nt, nn = k.sum(), k.sum()
            z_score_tmax[k, j] = norm_scores(vals_t)
            z_score_tmin[k, j] = norm_scores(vals_n)

    # --- 왜도 정규분포 적합 ---
    result_fit_sn_tmax = {}
    result_fit_sn_tmin = {}
    for m in range(1, 13):
        k = months == m
        result_fit_sn_tmax[m] = []
        result_fit_sn_tmin[m] = []
        for j in range(d):
            result_fit_sn_tmax[m].append(_fit_skewnorm(anomaly_tmax[k, j]))
            result_fit_sn_tmin[m].append(_fit_skewnorm(anomaly_tmin[k, j]))

    # --- EOF 분해 (월별) ---
    z_mean = np.zeros((12, 2 * d))
    eof_tmax = {}
    eof_tmin = {}
    residual_tmax = {}
    residual_tmin = {}

    for m in range(1, 13):
        k = months == m
        z_mean[m - 1, :d] = z_score_tmax[k].mean(axis=0)
        z_mean[m - 1, d:] = z_score_tmin[k].mean(axis=0)

        zt = z_score_tmax[k] - z_mean[m - 1, :d]
        zn = z_score_tmin[k] - z_mean[m - 1, d:]

        n_comp = min(2, d)
        pca_t = PCA(n_components=d).fit(zt)
        pca_n = PCA(n_components=d).fit(zn)

        eof_tmax[m] = pca_t.components_[:2].T   # (d, 2)
        eof_tmin[m] = pca_n.components_[:2].T

        # 잔차 (PC 3 이후)
        scores_t = zt @ pca_t.components_.T
        scores_n = zn @ pca_n.components_.T
        residual_tmax[m] = scores_t[:, 2:] @ pca_t.components_[2:]
        residual_tmin[m] = scores_n[:, 2:] @ pca_n.components_[2:]

    # EOF 방향 일관성 (월 간 부호 정렬, R과 동일)
    for m in range(2, 13):
        for i in range(2):
            if np.dot(eof_tmax[m - 1][:, i], eof_tmax[m][:, i]) < 0:
                eof_tmax[m][:, i] *= -1
            if np.dot(eof_tmin[m - 1][:, i], eof_tmin[m][:, i]) < 0:
                eof_tmin[m][:, i] *= -1

    # --- 다변량 AR(2) 추정 (월별) ---
    pc_model = {}
    for m in range(1, 13):
        k = months == m
        z_t_centered = (z_score_tmax[k] - z_mean[m - 1, :d]) @ eof_tmax[m]
        z_n_centered = (z_score_tmin[k] - z_mean[m - 1, d:]) @ eof_tmin[m]
        X = np.column_stack([z_t_centered, z_n_centered])

        yr_k = years[k]
        series_list = [X[yr_k == yr] for yr in period if (yr_k == yr).any()]
        pc_model[m] = pooled_yule_walker(series_list, p=2)

    return {
        "site_names": site_names,
        "mean_trend": result_detrending["mean_trend"],
        "fit_mu": result_detrending["fit_mu"],
        "fit_sigma": result_detrending["fit_sigma"],
        "knot_jd": knot_jd,
        "z_score_anomaly_primaryPC_model": pc_model,
        "z_score_anomaly_mean": z_mean,
        "z_score_anomaly_tmax_eof": eof_tmax,
        "z_score_anomaly_tmin_eof": eof_tmin,
        "z_score_anomaly_tmax_residual": residual_tmax,
        "z_score_anomaly_tmin_residual": residual_tmin,
        "result_fit_sn_tmax": result_fit_sn_tmax,
        "result_fit_sn_tmin": result_fit_sn_tmin,
        "iso_gen_param": iso_gen_param,
    }


def norm_scores(x: np.ndarray) -> np.ndarray:
    """배열 x의 순위 기반 정규 점수 변환 (R의 qnorm(rank/n+1) 대응)."""
    from scipy.stats import rankdata, norm
    n = len(x)
    rnk = rankdata(x, method="max")
    return norm.ppf(rnk / (n + 1))


def _fit_skewnorm(data: np.ndarray) -> dict:
    """왜도 정규분포 적합 (R의 fitdistr(..., dsn) 대응).
    scipy.stats.skewnorm 사용.
    """
    if len(data) < 5:
        return {"xi": 0.0, "omega": 1.0, "alpha": 0.0}
    try:
        alpha, loc, scale = skewnorm.fit(data)
        return {"xi": float(loc), "omega": float(scale), "alpha": float(alpha)}
    except Exception:
        return {"xi": float(data.mean()), "omega": float(data.std() + 1e-6), "alpha": 0.0}


# scipy.stats.norm 임포트 (norm_scores에서 사용)
from scipy.stats import norm
