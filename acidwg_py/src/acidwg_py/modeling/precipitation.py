"""
강수 모델링 — R Modeling.R의 prcp.modeling / monthly.total.prcp / pattern.modeling 포팅

Gamma 분포 모수 추정, 건조기간 음이항분포 모수, 강수 패턴 마르코프 전이행렬.
"""

import numpy as np
from scipy.stats import gamma as gamma_dist
from scipy.stats import nbinom
from scipy.special import digamma
import warnings

from acidwg_py.modeling.spatial import spatial_modeling


LEVELS = ["BN", "NN", "AN"]
MONTH_LENGTH = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])


def get_pattern_func(prcp_row: np.ndarray, month: int, level: str,
                     breaks: dict, pat_levels: list) -> str:
    """강수 패턴 결정 (0=건조, 1=보통, 2=매우 습윤).
    피클 가능한 모듈 레벨 함수. R의 get.pattern과 동일.
    """
    idx = float(np.mean(prcp_row))
    if idx == 0:
        return pat_levels[0]
    med = breaks[month][level][1]
    if idx <= med:
        return pat_levels[1]
    return pat_levels[2]


# ---------------------------------------------------------------------------
# 월별 총강수량 → 습윤범주 분류
# ---------------------------------------------------------------------------

def monthly_total_prcp(prcp_table: np.ndarray, site_names: list) -> dict:
    """월별 총강수량 계산 및 BN/NN/AN 범주 분류.

    R의 monthly.total.prcp과 동일.

    Parameters
    ----------
    prcp_table : shape (n_days, 3+d) — [Year, Month, Day, stn1, ...]
    site_names : list of str, length d

    Returns
    -------
    dict with:
        period          : ndarray of years
        monthly_wetness : ndarray of str, shape (n_days,)
        breaks          : ndarray (12, 4)  — [0, 1/3-quantile, 2/3-quantile, inf]
    """
    d = len(site_names)
    years = prcp_table[:, 0].astype(int)
    months = prcp_table[:, 1].astype(int)
    period = np.arange(years.min(), years.max() + 1)
    n_years = len(period)

    # 월별 유역 평균 총강수량 (n_years × 12)
    total_prcp = np.zeros((n_years, 12))
    for m in range(1, 13):
        mask_m = months == m
        prcp_m = prcp_table[mask_m][:, 3:3 + d]
        year_m = years[mask_m]
        for yi, yr in enumerate(period):
            mask_yr = year_m == yr
            if mask_yr.any():
                # 유역 평균 (관측소 평균) 합산
                total_prcp[yi, m - 1] = prcp_m[mask_yr].mean(axis=1).sum()

    # 1/3, 2/3 분위수 기반 범주 경계
    #   결측일이 있는 달의 월합계는 NaN 이다. np.quantile 에 그대로 넣으면 경계가 NaN 이
    #   되고, 이후 비교가 모두 False 라 그 달 전 연도가 AN 으로 오분류된다 → 유한값만 사용.
    breaks = np.zeros((12, 4))
    for m in range(12):
        vals = total_prcp[:, m]
        vals = vals[np.isfinite(vals)]
        if len(vals) >= 3:
            q13, q23 = np.quantile(vals, [1 / 3, 2 / 3])
        else:
            q13, q23 = 0.0, np.inf
        breaks[m] = [0.0, q13, q23, np.inf]

    # 각 날짜의 습윤범주 결정
    monthly_wetness = np.empty(len(prcp_table), dtype=object)
    for yi, yr in enumerate(period):
        for m in range(1, 13):
            mask = (years == yr) & (months == m)
            total = total_prcp[yi, m - 1]
            if total <= breaks[m - 1, 1]:
                cat = "BN"
            elif total <= breaks[m - 1, 2]:
                cat = "NN"
            else:
                cat = "AN"
            monthly_wetness[mask] = cat

    return {"period": period, "monthly_wetness": monthly_wetness, "breaks": breaks}


# ---------------------------------------------------------------------------
# Gamma 분포 모수 추정 (MLE)
# ---------------------------------------------------------------------------

def _fit_gamma(data: np.ndarray):
    """Gamma 분포 모수 추정 (shape, scale).
    scipy의 gamma.fit를 사용하고 MLE에서 loc=0으로 고정.
    """
    data = data[data > 0]
    if len(data) < 3:
        return 1.0, 1.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        shape, loc, scale = gamma_dist.fit(data, floc=0)
    return float(shape), float(scale)


# ---------------------------------------------------------------------------
# 건조기간 음이항분포 모수 추정
# ---------------------------------------------------------------------------

def _fit_negbinom_dry_spell(dry_lengths: np.ndarray, labels: np.ndarray):
    """건조기간 길이의 음이항분포 모수를 범주별로 추정.

    R의 glm.nb(y ~ x) 결과와 동일한 목적: 범주별 평균 건조기간 길이.
    단순 추정: 각 범주별 평균값 사용.

    Returns
    -------
    mean_dry_spell : dict[level] → float
    theta          : float (dispersion parameter, 고정값 1 사용)
    """
    mean_dry = {}
    for s in LEVELS:
        mask = labels == s
        if mask.any():
            mean_dry[s] = float(dry_lengths[mask].mean())
        else:
            mean_dry[s] = 3.0  # 기본값
    return mean_dry, 1.0


def _estimate_theta(dry_lengths: np.ndarray) -> float:
    """건조기간 데이터에서 음이항분포 분산 모수(theta) 추정.

    R의 glm.nb()와 동일한 목적을 모멘트 추정법(MOM)으로 근사.
    시뮬레이션 공식: length = NegBin(n=theta, p) + 1
    → (length - 1) ~ NegBin(size=theta, mu=mean-1) 에 MOM 적용.

    E[X]   = mu,  Var[X] = mu + mu²/theta
    → theta = mu² / (var - mu)

    theta가 클수록 분포가 좁아짐(Poisson에 가까워짐).
    theta=1이면 기하분포(분산 최대).

    Parameters
    ----------
    dry_lengths : array of int, 건조기간 길이 (≥ 1)

    Returns
    -------
    theta : float, 클립 범위 [0.5, 50]
    """
    if len(dry_lengths) < 5:
        return 1.0
    y = dry_lengths.astype(float) - 1.0   # NegBin의 지지(support)는 0 이상
    mu_hat = y.mean()
    if mu_hat <= 0:
        return 1.0
    var_hat = y.var(ddof=1)
    if var_hat <= mu_hat:
        # 과소분산(underdispersion) → Poisson 한계 → 큰 theta
        return 50.0
    theta_hat = mu_hat ** 2 / (var_hat - mu_hat)
    # 하한을 1.0(기하분포)으로 설정: theta < 1이면 기하분포보다 분산이 커져
    # 월 강수 합계의 이봉(bimodal) 분포를 유발하므로 허용하지 않음
    return float(np.clip(theta_hat, 1.0, 50.0))


# ---------------------------------------------------------------------------
# 강수 패턴 모델링
# ---------------------------------------------------------------------------

def pattern_modeling(prcp_table: np.ndarray, site_names: list,
                     monthly_wetness: np.ndarray) -> dict:
    """습윤 날 강수 패턴(0=건조, 1=보통 습윤, 2=매우 습윤)의 Markov 전이행렬 추정.

    R의 pattern.modeling과 동일.
    """
    d = len(site_names)
    months = prcp_table[:, 1].astype(int)
    prcp_vals = prcp_table[:, 3:3 + d]
    pat_levels = ["0", "1", "2"]

    # 공간 평균 강수
    index = prcp_vals.mean(axis=1)
    wet_day = np.any(prcp_vals > 0, axis=1)

    # 패턴 경계 (월 × 범주별 중앙값)
    breaks = {}  # breaks[m][s] = (0, median, inf)
    for m in range(1, 13):
        breaks[m] = {}
        for s in LEVELS:
            mask = wet_day & (months == m) & (monthly_wetness == s)
            if mask.any():
                med = float(np.median(index[mask]))
            else:
                med = 1.0
            breaks[m][s] = (0.0, med, np.inf)

    # 전이행렬 구축 (get_pattern_func 사용)
    transition_table = {}
    for m in range(1, 13):
        transition_table[m] = {}
        for s in LEVELS:
            tt = np.zeros((3, 3), dtype=float)  # 행/열: 0,1,2
            mask_m = months == m
            k_indices = np.where(mask_m & (monthly_wetness == s))[0]
            k_indices = k_indices[k_indices > 0]

            for ki in k_indices:
                prev = get_pattern_func(prcp_vals[ki - 1], m, s, breaks, pat_levels)
                curr = get_pattern_func(prcp_vals[ki], m, s, breaks, pat_levels)
                pi = pat_levels.index(prev)
                ci = pat_levels.index(curr)
                tt[pi, ci] += 1

            transition_table[m][s] = tt

    return {
        "breaks": breaks,
        "pat_levels": pat_levels,
        "transition_table": transition_table,
    }


# ---------------------------------------------------------------------------
# 건조·습윤 기간 수집
# ---------------------------------------------------------------------------

def collecting_historical_spells(prcp_table: np.ndarray, site_names: list):
    """역사적 건조/습윤 기간 수집.

    R의 collecting.historical.spell과 동일.
    """
    d = len(site_names)
    prcp_vals = prcp_table[:, 3:3 + d]
    wet_day = np.any(prcp_vals > 0, axis=1)

    dry_spells = []   # (start_idx, end_idx, length, start_month)
    wet_spells = []   # (start_idx, end_idx)

    is_wet = not wet_day[0]
    ds_start = None
    ws_start = None

    for i in range(len(wet_day)):
        if wet_day[i] and not is_wet:
            # 건조 → 습윤 전환
            if ds_start is not None:
                length = i - ds_start
                dry_spells.append({
                    "start_idx": ds_start,
                    "end_idx": i - 1,
                    "length": length,
                    "start_month": int(prcp_table[ds_start, 1]),
                })
            ws_start = i
            is_wet = True
        elif not wet_day[i] and is_wet:
            # 습윤 → 건조 전환
            if ws_start is not None:
                wet_spells.append({"start_idx": ws_start, "end_idx": i - 1})
            ds_start = i
            is_wet = False

    return {"dry_spells": dry_spells, "wet_spells": wet_spells}


# ---------------------------------------------------------------------------
# 강수 모델링 메인
# ---------------------------------------------------------------------------

def prcp_modeling(prcp_table: np.ndarray, site_names: list,
                  spatial_result: dict = None) -> dict:
    """강수 모델 모수 전체 추정.

    R의 prcp.modeling과 동일.

    Returns
    -------
    param_list : dict — 시뮬레이션에 필요한 모든 강수 모수
    """
    d = len(site_names)
    months_col = prcp_table[:, 1].astype(int)
    prcp_vals = prcp_table[:, 3:3 + d]

    # 1. 월별 총강수량 및 습윤범주
    res_mtp = monthly_total_prcp(prcp_table, site_names)
    period = res_mtp["period"]
    monthly_wetness = res_mtp["monthly_wetness"]
    breaks = res_mtp["breaks"]

    # 2. Gamma 분포 모수 (12 × d × 3)
    #    패턴(1/2) 공통 Gamma 추정 — 관측소별 wet-day 주변 분포를 직접 보존.
    #    패턴별로 나누면 유역 평균 기반 50/50 분할이 관측소 wet-day 분포와 맞지 않아
    #    E[시뮬레이션] < E[관측]이 되는 체계적 편의(~14%)가 발생.
    #    Pooled Gamma는 E[Gamma] = 표본평균이므로 관측과 편의 없이 일치.
    shape = np.zeros((12, d, 3))
    scale = np.zeros((12, d, 3))

    for m in range(1, 13):
        for j in range(d):
            for si, s in enumerate(LEVELS):
                mask = (months_col == m) & (prcp_vals[:, j] > 0) & (monthly_wetness == s)
                y = prcp_vals[mask, j]
                sh, sc = _fit_gamma(y)
                shape[m - 1, j, si] = sh
                scale[m - 1, j, si] = sc

    # 3. 건조기간 모수 (12 × 3)
    spells = collecting_historical_spells(prcp_table, site_names)
    dry_spells = spells["dry_spells"]

    mean_dry_spell = np.zeros((12, 3))
    theta = np.ones(12)  # 초기값; 아래에서 데이터 기반 추정으로 교체

    for m in range(1, 13):
        ds_m = [sp for sp in dry_spells if sp["start_month"] == m]
        if not ds_m:
            for si in range(3):
                mean_dry_spell[m - 1, si] = 3.0
            continue

        lengths = np.array([sp["length"] for sp in ds_m])
        start_idx = np.array([sp["start_idx"] for sp in ds_m])
        labels = monthly_wetness[start_idx]

        # R의 glm.nb와 동일하게 월별 theta를 데이터에서 추정
        # (범주 공변수를 포함하나 분산 모수는 월별 1개로 공유)
        theta[m - 1] = _estimate_theta(lengths)

        for si, s in enumerate(LEVELS):
            mask = labels == s
            if mask.any():
                mean_dry_spell[m - 1, si] = float(lengths[mask].mean())
            else:
                mean_dry_spell[m - 1, si] = 3.0

    # 4. 공간 모델링 (Gaussian copula)
    if spatial_result is None:
        spatial_result = spatial_modeling(prcp_table, site_names, monthly_wetness)

    # 5. 패턴 모델링
    pat_result = pattern_modeling(prcp_table, site_names, monthly_wetness)

    # 극단값 모델링 (미구현 — R 원본과 동일하게 더미값)
    threshold = np.full((12, d), np.inf)
    extreme_prob = np.zeros((12, 3))
    fit_extreme = [None] * 12

    return {
        "period": period,
        "site_names": site_names,
        "shape": shape,                  # (12, d, 3)
        "scale": scale,                  # (12, d, 3)
        "mean_dry_spell": mean_dry_spell,  # (12, 3)
        "theta": theta,                  # (12,)
        "corr_mats": spatial_result["corr_mats"],
        "threshold_prob": spatial_result["threshold_prob"],  # (12, d, 3)
        "breaks": breaks,
        "monthly_wetness": monthly_wetness,
        # 패턴 (get_pattern은 모듈 함수 get_pattern_func 사용)
        "pat_breaks": pat_result["breaks"],
        "pat_levels": pat_result["pat_levels"],
        "transition_table": pat_result["transition_table"],
        # 극단값
        "threshold": threshold,
        "extreme_prob": extreme_prob,
        "fit_extreme": fit_extreme,
        "monthly_total_breaks": breaks,
    }
