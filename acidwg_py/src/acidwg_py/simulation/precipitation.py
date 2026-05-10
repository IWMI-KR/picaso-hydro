"""
강수 시뮬레이션 — R Base.R의 prcp.simulation 포팅

습윤/건조 기간 기반의 일단위 강수 시나리오 생성.
- Gaussian copula로 관측소 간 공간 상관성 유지
- Gamma 분포로 강수량 생성
- 음이항분포로 건조기간 생성
"""

import numpy as np
from scipy.stats import norm, gamma as gamma_dist, nbinom

from acidwg_py.utils import get_julian_day, distance, MONTH_LENGTH
from acidwg_py.modeling.precipitation import get_pattern_func

LEVELS = ["BN", "NN", "AN"]


def prcp_simulation(
    site_names: list,
    shape: np.ndarray,          # (12, d, 3)
    scale: np.ndarray,          # (12, d, 3)
    mean_dry_spell: np.ndarray, # (12, 3)
    theta: np.ndarray,          # (12,)
    corr_mats: dict,            # dict[month][level] -> (d,d)
    threshold_prob: np.ndarray, # (12, d, 3)
    threshold: np.ndarray,      # (12, d) — extreme threshold (Inf이면 극단값 없음)
    extreme_prob: np.ndarray,   # (12, 3)
    fit_extreme,                # not implemented
    pat_breaks: dict,
    pat_levels: list,
    transition_table: dict,
    sim_period: list,
    monthly_ch: list,           # 길이 n_months: 각 월의 습윤범주
    **kwargs,
) -> np.ndarray:
    """일단위 강수 시나리오 생성.

    R의 prcp.simulation과 동일.

    Returns
    -------
    daily_prcp : ndarray (n_days, 2+d) — [Month, Day, stn1, ...]
    """
    d = len(site_names)

    # sim_period 앞뒤로 1개월 확장 (R과 동일)
    # 단, sim_period가 12개월 전체인 경우 경계월 추가 불필요 (중복 방지)
    if set(sim_period) == set(range(1, 13)):
        sim_period1 = list(sim_period)
        monthly_ch1 = list(monthly_ch)
    else:
        sim_period1 = (
            [(sim_period[0] - 2) % 12 + 1]
            + list(sim_period)
            + [sim_period[-1] % 12 + 1]
        )
        monthly_ch1 = [monthly_ch[0]] + list(monthly_ch) + [monthly_ch[-1]]

    # 달력 구성 (Month, Day)
    rows = []
    for m in sim_period1:
        for day in range(1, MONTH_LENGTH[m - 1] + 1):
            rows.append([m, day])
    daily_prcp = np.zeros((len(rows), 2 + d), dtype=float)
    for i, (m, day) in enumerate(rows):
        daily_prcp[i, 0] = m
        daily_prcp[i, 1] = day

    level_idx = {s: i for i, s in enumerate(LEVELS)}

    def get_s_for_date(cursor):
        m = int(daily_prcp[cursor, 0])
        k = sim_period1.index(m) if m in sim_period1 else 0
        return monthly_ch1[k], m

    def generating_dry_spell(cursor) -> int:
        """건조기간 길이 샘플링 (음이항분포)."""
        s, m = get_s_for_date(cursor)
        si = level_idx[s]
        mu = mean_dry_spell[m - 1, si]
        th = float(theta[m - 1])
        # NegBin: R의 rnbinom(size=theta, mu=mean-1) + 1
        p = th / (th + max(mu - 1, 0.5))
        length = int(nbinom.rvs(n=th, p=p)) + 1
        return max(length, 1)

    def generating_wet_spell(cursor) -> np.ndarray:
        """습윤기간 강수량 행렬 생성.

        Returns
        -------
        rainfall : ndarray (spell_length, d)
        """
        s, m = get_s_for_date(cursor)
        si = level_idx[s]
        corr = corr_mats[m][s]

        def gen_daily_prcp(pattern: str) -> np.ndarray:
            """Pooled Gamma에서 직접 강수량 생성 (수용-거부 없음).

            패턴 인자는 Markov chain에서 전달되지만 강수량 샘플링에는
            사용하지 않는다. 패턴별 Gamma를 쓰면 유역 50/50 분할과
            관측소별 wet-day 분포 사이의 불일치로 ~14% 과소 편의가 발생하기
            때문에 Pooled Gamma(E[Gamma]=표본평균)를 직접 사용한다.
            """
            for _ in range(10):
                # Gaussian copula 샘플링
                try:
                    z = np.random.multivariate_normal(np.zeros(d), corr)
                except Exception:
                    z = np.random.randn(d)
                u = norm.cdf(z)

                rainfall = np.zeros(d)
                for j in range(d):
                    tp = float(threshold_prob[m - 1, j, si])
                    if u[j] > tp:
                        p_gamma = (u[j] - tp) / (1.0 - tp)
                        p_gamma = np.clip(p_gamma, 1e-6, 1 - 1e-6)
                        rainfall[j] = gamma_dist.ppf(
                            p_gamma,
                            a=float(shape[m - 1, j, si]),
                            scale=float(scale[m - 1, j, si]),
                        )

                if np.any(rainfall > 0):
                    return np.round(rainfall, 1)

            return np.round(rainfall, 1)  # 재시도 소진 시 마지막 결과 반환

        # 패턴 시퀀스 생성 (Markov chain)
        tt = transition_table[m][s]
        row_sum = tt[0, 1:].sum()
        if row_sum == 0:
            probs = np.ones(2) / 2
        else:
            probs = tt[0, 1:] / row_sum

        pat_seq = [np.random.choice(pat_levels[1:], p=probs)]

        max_len = 30
        while pat_seq[-1] != pat_levels[0] and len(pat_seq) < max_len:
            curr_idx = pat_levels.index(pat_seq[-1])
            row = tt[curr_idx]
            rs = row.sum()
            if rs == 0:
                pat_seq.append(pat_levels[0])
            else:
                pat_seq.append(np.random.choice(pat_levels, p=row / rs))

        if pat_seq and pat_seq[-1] == pat_levels[0]:
            pat_seq = pat_seq[:-1]

        if not pat_seq:
            pat_seq = [pat_levels[1]]

        spell_rainfall = np.zeros((len(pat_seq), d))
        for i, pat in enumerate(pat_seq):
            spell_rainfall[i] = gen_daily_prcp(pat)

        return spell_rainfall

    # 메인 생성 루프
    state = 0  # 0=건조, 1=습윤
    cursor = 0
    n_total = len(daily_prcp)

    while cursor < n_total:
        if state == 0:
            interval = generating_dry_spell(cursor)
            cursor += interval
            state = 1
        else:
            rainfall_event = generating_wet_spell(cursor)
            dur = len(rainfall_event)
            end = min(cursor + dur, n_total)
            actual_dur = end - cursor
            daily_prcp[cursor:end, 2:] = rainfall_event[:actual_dur]
            cursor += dur
            state = 0

    # sim_period에 해당하는 날만 추출
    mask = np.isin(daily_prcp[:, 0].astype(int), sim_period)
    return daily_prcp[mask]
