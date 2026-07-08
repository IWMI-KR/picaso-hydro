"""계절별 최저강수 연도 + 장기 모의결과 정리(historical_worst).

관측 결측 신뢰성 대체·저수지 관측초기화 물수지 등 SWAT 불필요 순수함수 검증.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from swat_py.drought.historical_worst import (
    SEASONS, MONTHS, _wrap, _days_in_month,
    read_pcp_monthly, seasonal_precip_candidates, select_driest,
    load_monthly_flow, _season_flows, _season_mean,
    load_obs_level_msl, initial_level_msl, reservoir_season_balance,
    reservoir_daily_balance,
)


def test_wrap_and_seasons():
    assert _wrap(2015, 6) == (2015, 6)
    assert _wrap(2015, 13) == (2016, 1)      # NDJ 의 1월
    assert _wrap(2015, 14) == (2016, 2)      # DJF 의 2월
    assert len(SEASONS) == 12
    assert SEASONS["DJF"] == (12, 13, 14)
    assert _days_in_month(2016, 2) == 29     # 윤년


def _write_pcp(path, records):
    lines = ["title", "nbyr tstep lat lon elev", "  1 0 7 134 50"]
    lines += [f"{y}  {j}  {v:.3f}" for y, j, v in records]
    path.write_text("\n".join(lines) + "\n")


def _month_recs(y, mon, val, missing=0):
    import datetime as dt
    out = []
    nd = (dt.date(y + (mon // 12), (mon % 12) + 1, 1) - dt.date(y, mon, 1)).days
    for d in range(nd):
        jd = (dt.date(y, mon, 1) - dt.date(y, 1, 1)).days + 1 + d
        out.append((y, jd, -99.0 if d < missing else val))
    return out


def test_months_periods():
    assert len(MONTHS) == 12
    assert MONTHS["01"] == (1,) and MONTHS["12"] == (12,)   # 단일 달력 월


def test_candidates_monthly_vs_seasonal(tmp_path):
    # 월별(periods=MONTHS)은 단일 월 강수로 후보 산정 — 계절과 다른 최저를 잡을 수 있음.
    recs = []
    for y, jan, feb, mar in [(2001, 9.0, 1.0, 9.0), (2002, 3.0, 3.0, 3.0)]:
        recs += _month_recs(2001 if y == 2001 else 2002, 1, jan)
        recs += _month_recs(2001 if y == 2001 else 2002, 2, feb)
        recs += _month_recs(2001 if y == 2001 else 2002, 3, mar)
    p = tmp_path / "x.pcp"; _write_pcp(p, recs)
    m = read_pcp_monthly(p)
    mon = seasonal_precip_candidates(m, [2001, 2002], periods=MONTHS)
    # 2월: 2001(1mm/day) < 2002(3mm/day) → 최저 2001
    feb = min(mon["02"], key=lambda d: d["precip_mm"])
    assert feb["year"] == 2001
    assert "02" in mon and "01" in mon and len(mon) == 12


def test_read_pcp_monthly_missing(tmp_path):
    p = tmp_path / "x.pcp"
    _write_pcp(p, _month_recs(2020, 1, 5.0, missing=10))     # 1월 31일 중 10일 결측
    m = read_pcp_monthly(p)
    jan = m[(m.year == 2020) & (m.month == 1)].iloc[0]
    assert jan.precip_mm == pytest.approx(21 * 5.0)          # 21 유효일 × 5
    assert jan.valid_days == 21 and jan.total_days == 31


def test_select_driest_substitutes_unreliable(tmp_path):
    # JFM: 2001=저강수지만 1월 대부분 결측(비신뢰) · 2002=정상 저강수 · 2003=정상 고강수
    recs = []
    for mon in (1, 2, 3):
        recs += _month_recs(2001, mon, 1.0, missing=(28 if mon == 1 else 0))
        recs += _month_recs(2002, mon, 3.0)
        recs += _month_recs(2003, mon, 9.0)
    p = tmp_path / "x.pcp"; _write_pcp(p, recs)
    m = read_pcp_monthly(p)
    cands = seasonal_precip_candidates(m, [2001, 2002, 2003])
    log = []
    sel = select_driest(cands, min_frac=0.90, log_lines=log)
    jfm = sel["JFM"]
    assert jfm["driest_year"] == 2002          # 2001 은 결측으로 건너뜀
    assert jfm["substituted"] is True
    assert any("2001" in ln and "건너뜀" in ln for ln in log)
    assert jfm["skipped"][0]["year"] == 2001


def test_obs_level_msl_datum(tmp_path):
    # 관측 23ft, offset -22 → MSL = 23 - (-22) = 45 (만수)
    csv = tmp_path / "res.csv"
    pd.DataFrame({"date": pd.date_range("2020-05-01", periods=3, freq="D"),
                  "wlevel_ft": [23.0, 22.0, 23.0]}).to_csv(csv, index=False)
    ym, clim = load_obs_level_msl(csv, col="wlevel_ft", datum_offset_ft=-22.0)
    assert ym[(2020, 5)] == pytest.approx((45 + 44 + 45) / 3)
    assert clim[5] == pytest.approx((45 + 44 + 45) / 3)


def test_initial_level_priority():
    obs_ym = {(2018, 4): 44.0}
    obs_clim = {4: 40.0, 1: 38.0}
    # (1) 그 연·월 관측 있으면 사용
    assert initial_level_msl(obs_ym, obs_clim, 2018, 4, full_level_ft=45)[0] == 44.0
    assert initial_level_msl(obs_ym, obs_clim, 2018, 4, full_level_ft=45)[1] == "observed"
    # (2) 없으면 월 climatology 평균
    lvl, tag = initial_level_msl(obs_ym, obs_clim, 1998, 4, full_level_ft=45)
    assert lvl == 40.0 and tag == "monthly_mean"
    # (3) 둘 다 없으면 만수
    lvl, tag = initial_level_msl(obs_ym, obs_clim, 1998, 7, full_level_ft=45)
    assert lvl == 45 and tag == "full_default"


@dataclass
class _P:
    full_m3: float
    dead_m3: float
    withdrawal_m3s: float
    curve: object


def test_reservoir_season_balance_drawdown():
    from swat_py.io.reservoir import StageStorageCurve
    curve = StageStorageCurve(elev_ft=np.array([0.0, 100.0]),
                              storage_m3=np.array([0.0, 100000.0]))
    p = _P(full_m3=100000.0, dead_m3=0.0, withdrawal_m3s=0.01, curve=curve)
    # 만수(100ft→100000m³) 시작, 유입 0 · 취수만 → 매월 저하
    flows = [(2016, 1, 0.0), (2016, 2, 0.0), (2016, 3, 0.0)]
    bal = reservoir_season_balance(flows, init_msl=100.0, params=p)
    # Jan: 100000-864*31=73216 → 73.2% ; 이후 계속 감소 → 평균 < 첫달
    assert bal["storage_pct_end"] < bal["storage_pct_mean"] < 100
    assert bal["water_level_ft_end"] < 100         # 수위 하강
    # 유입 충분하면 만수 유지(월류 캡)
    bal2 = reservoir_season_balance([(2016, 1, 10.0)], init_msl=100.0, params=p)
    assert bal2["storage_pct_end"] >= 100          # 잉여 → ≥100%
    assert bal2["water_level_ft_end"] == pytest.approx(100.0)   # 여수로 캡


def test_reservoir_daily_balance_flo_in_drawdown():
    from swat_py.io.reservoir import StageStorageCurve
    curve = StageStorageCurve(elev_ft=np.array([0.0, 100.0]),
                              storage_m3=np.array([0.0, 100000.0]))
    # withdrawal 0.05 m³/s = 4320 m³/일.  reservoir_day flo_in 은 **m³/일 부피**(m³/s 아님).
    p = _P(full_m3=100000.0, dead_m3=0.0, withdrawal_m3s=0.05, curve=curve)
    # 가뭄: flo_in 0 · 취수만 → 만수(100ft)에서 매일 감소, 결국 고갈
    dates = pd.date_range("2018-03-01", "2018-04-30", freq="D")
    rd = pd.DataFrame({"date": dates, "flo_in": 0.0, "precip": 0.0, "evap": 0.0, "seep": 0.0})
    out = reservoir_daily_balance(rd, params=p, init_msl=100.0)
    assert out["storage_pct"].iloc[0] < 100                 # 첫날부터 감소
    assert out["storage_pct"].iloc[-1] == 0.0               # 고갈(관측 2018 강하 재현)
    assert (out["storage_pct"].diff().dropna() <= 0).all()  # 유입0·취수 → 단조 감소
    # 유입(m³/일)이 취수보다 크면 만수 유지
    rd2 = rd.assign(flo_in=10000.0)                         # 10000 m³/일 > 취수 4320
    out2 = reservoir_daily_balance(rd2, params=p, init_msl=50.0)
    assert out2["storage_pct"].iloc[-1] == 100.0            # 만수 캡


def test_load_monthly_flow_and_season(tmp_path):
    csv = tmp_path / "cm.csv"
    dates = pd.date_range("2015-01-01", "2016-03-01", freq="MS")
    pd.DataFrame({"date": dates, "ngerikiil": np.arange(len(dates), dtype=float),
                  "ngerimel": np.arange(len(dates), dtype=float) * 0.5}).to_csv(csv, index=False)
    idx, outlets = load_monthly_flow(csv)
    assert set(outlets) == {"ngerikiil", "ngerimel"}
    fl = _season_flows(idx, "ngerikiil", 2015, (12, 13, 14))     # DJF 2015
    assert [f[2] for f in fl] == [11.0, 12.0, 13.0]              # Dec15,Jan16,Feb16
    assert _season_mean(fl) == pytest.approx(12.0)
