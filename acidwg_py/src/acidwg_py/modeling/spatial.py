"""
공간 상관 모델링 — R Base.R의 fit.Gaussian.copula / spatial.modeling 포팅

강수 Gaussian Copula 상관행렬을 월별 × 습윤범주(BN/NN/AN)별로 추정.
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import minimize_scalar
from scipy.stats import multivariate_normal


# ---------------------------------------------------------------------------
# 보조 함수
# ---------------------------------------------------------------------------

def _get_grad_pmvnorm(z1: float, z2: float, rho: float) -> float:
    """bivariate normal의 누적분포 Pr(Z1<=z1, Z2<=z2)를 z2로 편미분한 값.
    R의 get.grad.pmvnorm과 동일.
    """
    value1 = norm.cdf(z1, loc=rho * z2, scale=np.sqrt(max(1 - rho**2, 1e-10)))
    value2 = norm.pdf(z2)
    return value1 * value2


def _pmvnorm2(upper1: float, upper2: float, rho: float) -> float:
    """이변량 정규분포의 CDF Pr(Z1<=upper1, Z2<=upper2), 상관계수=rho."""
    corr = np.array([[1.0, rho], [rho, 1.0]])
    return multivariate_normal.cdf([upper1, upper2], mean=[0, 0], cov=corr)


# ---------------------------------------------------------------------------
# Gaussian Copula 상관 추정 (한 쌍의 관측소)
# ---------------------------------------------------------------------------

def _estim_corr(u_pair: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    """두 관측소 간 Gaussian copula 상관계수 추정 (MLE).

    Parameters
    ----------
    u_pair : shape (n, 2) — 두 관측소의 순위 기반 uniform 변환값
    a      : shape (2,)   — 하한 경계(건조일 비율 + 버퍼)
    b      : shape (2,)   — 상한 경계(0.98)
    """
    def log_likelihood(rho: float) -> float:
        corr_mat = np.array([[1.0, rho], [rho, 1.0]])
        total = 0.0
        for u in u_pair:
            u1, u2 = float(u[0]), float(u[1])
            in1 = a[0] < u1 < b[0]
            in2 = a[1] < u2 < b[1]

            if in1 and in2:
                z = norm.ppf(u)
                sign, logdet = np.linalg.slogdet(corr_mat)
                if sign <= 0:
                    continue
                z_vec = np.linalg.solve(corr_mat, z)
                val = -0.5 * (logdet + z @ z_vec - np.sum(z**2))
                total += val
            elif in1 and u2 <= a[1]:
                z1 = norm.ppf(u1)
                z2 = norm.ppf(a[1])
                gv = _get_grad_pmvnorm(z2, z1, rho)
                if gv > 0:
                    total += np.log(gv) - norm.logpdf(z1)
            elif u1 <= a[0] and in2:
                z1 = norm.ppf(a[0])
                z2 = norm.ppf(u2)
                gv = _get_grad_pmvnorm(z1, z2, rho)
                if gv > 0:
                    total += np.log(gv) - norm.logpdf(z2)
            elif in1 and u2 >= b[1]:
                z1 = norm.ppf(u1)
                z2 = norm.ppf(b[1])
                gv = _get_grad_pmvnorm(z2, z1, rho)
                denom = norm.pdf(z1)
                if denom > 0 and (1 - gv / denom) > 0:
                    total += np.log(1 - gv / denom)
            elif u1 >= b[0] and in2:
                z1 = norm.ppf(b[0])
                z2 = norm.ppf(u2)
                gv = _get_grad_pmvnorm(z1, z2, rho)
                denom = norm.pdf(z2)
                if denom > 0 and (1 - gv / denom) > 0:
                    total += np.log(1 - gv / denom)
            elif u1 >= b[0] and u2 >= b[1]:
                p = 1 - b[0] - b[1] + _pmvnorm2(norm.ppf(b[0]), norm.ppf(b[1]), rho)
                if p > 0:
                    total += np.log(p)
            elif u1 >= b[0] and u2 <= a[1]:
                p = a[1] - _pmvnorm2(norm.ppf(b[0]), norm.ppf(a[1]), rho)
                if p > 0:
                    total += np.log(p)
            elif u1 <= a[0] and u2 >= b[1]:
                p = a[0] - _pmvnorm2(norm.ppf(a[0]), norm.ppf(b[1]), rho)
                if p > 0:
                    total += np.log(p)
            elif u1 <= a[0] and u2 <= a[1]:
                p = _pmvnorm2(norm.ppf(a[0]), norm.ppf(a[1]), rho)
                if p > 0:
                    total += np.log(p)

        return total

    result = minimize_scalar(
        lambda rho: -log_likelihood(rho),
        bounds=(-0.5, 0.99),
        method="bounded",
    )
    return result.x


def fit_gaussian_copula(prcp_value: np.ndarray) -> dict:
    """강수 행렬에 대해 Gaussian copula 상관행렬과 건조일 확률 추정.

    R의 fit.Gaussian.copula와 동일.

    Parameters
    ----------
    prcp_value : shape (n_days, d) — d개 관측소의 강수량

    Returns
    -------
    dict with:
        corr_mat       : ndarray (d, d)
        threshold_prob : ndarray (d,)   — 건조일 비율
    """
    n, d = prcp_value.shape

    # 순위 기반 uniform 변환
    rnk = np.zeros_like(prcp_value, dtype=float)
    for j in range(d):
        # ties.method="max" 대응
        from scipy.stats import rankdata
        rnk[:, j] = rankdata(prcp_value[:, j], method="max")
    U = rnk / n

    # 건조일 비율 (threshold.prob)
    threshold_prob = np.mean(prcp_value == 0, axis=0)
    lower = threshold_prob + 0.05
    upper = np.full(d, 0.98)

    # 상관행렬 초기화
    corr_mat = np.eye(d)

    for i in range(d - 1):
        for j in range(i + 1, d):
            rho = _estim_corr(
                U[:, [i, j]],
                a=np.array([lower[i], lower[j]]),
                b=np.array([upper[i], upper[j]]),
            )
            corr_mat[i, j] = rho
            corr_mat[j, i] = rho

    # 양정치(positive definite) 보정 (R의 singularity problem 처리)
    eigvals = np.linalg.eigvalsh(corr_mat)
    v = eigvals.min()
    if v < 0:
        alpha = (1.0 / (1.0 - v)) * 0.99
        corr_mat = alpha * corr_mat + np.eye(d) * (1.0 - alpha)
    elif v == 0:
        corr_mat = 0.99 * corr_mat + np.eye(d) * 0.01

    return {"corr_mat": corr_mat, "threshold_prob": threshold_prob}


# ---------------------------------------------------------------------------
# 전체 공간 모델링 (월별 × 습윤범주)
# ---------------------------------------------------------------------------

def spatial_modeling(prcp_table: np.ndarray, site_names: list,
                     monthly_wetness: np.ndarray) -> dict:
    """월별 × 습윤범주(BN/NN/AN)별 Gaussian copula 상관행렬 추정.

    R의 spatial.modeling(method="fit.Gaussian.copula")과 동일.

    Parameters
    ----------
    prcp_table      : shape (n_days, 3+d) — [Year, Month, Day, stn1, ...]
    site_names      : list of str, length d
    monthly_wetness : shape (n_days,) — 각 날의 습윤범주 ('BN','NN','AN')

    Returns
    -------
    dict with:
        corr_mats      : dict[month(1-12)][level] → ndarray (d, d)
        threshold_prob : ndarray (12, d, 3)  — [month, station, level_idx]
    """
    levels = ["BN", "NN", "AN"]
    d = len(site_names)
    months = range(1, 13)
    prcp_cols = np.array([3 + j for j in range(d)])

    corr_mats = {m: {s: np.eye(d) for s in levels} for m in months}
    threshold_prob = np.zeros((12, d, 3))

    for m in months:
        month_mask = prcp_table[:, 1] == m
        has_rain = np.any(prcp_table[:, prcp_cols] > 0, axis=1)

        for si, s in enumerate(levels):
            level_mask = (monthly_wetness == s)
            mask = month_mask & has_rain & level_mask
            prcp_vals = prcp_table[mask][:, prcp_cols]

            if prcp_vals.shape[0] < 10:
                # 데이터 부족 시 기본값 유지
                threshold_prob[m - 1, :, si] = np.mean(
                    prcp_table[month_mask][:, prcp_cols] == 0, axis=0
                )
                continue

            try:
                result = fit_gaussian_copula(prcp_vals)
                corr_mats[m][s] = result["corr_mat"]
                threshold_prob[m - 1, :, si] = result["threshold_prob"]
            except Exception:
                threshold_prob[m - 1, :, si] = np.mean(
                    prcp_vals == 0, axis=0
                )

    return {"corr_mats": corr_mats, "threshold_prob": threshold_prob}
