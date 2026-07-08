"""계절별(rolling 3개월) 최저강수 연도 + 장기 모의결과 정리 (대시보드 보조 분석).

`historical mean`(장기 climatology SWAT+ 모의)을 구동한 **관측 강수**(장기 관측소 .pcp)로
12개 rolling 3개월 계절(JFM·FMA·…·NDJ·DJF)의 연도별 강수총량을 구해 각 계절에서 **가장
건조했던 연도**를 찾고, 같은 장기모의에서 그 연도 계절의 결과를 수원별로 정리한다:

  · ngerikiil(하천)  : 채널 유량(m³/s) + fdc 가뭄단계
  · ngerimel(저수지) : 채널 유량(m³/s), 그리고 물수지 저수량%(만수대비)·저수위(ft)·단계

**신뢰성(결측) 처리** — 어떤 계절의 raw 최저강수 연도가 결측이 많아(월 유효일 < ``min_frac``)
신뢰할 수 없으면, 그 연도를 **로그에 기록**하고 순위상 다음(차선) 신뢰가능 연도를 채택해
모델링한다(예: 팔라우 2006/2007 관측 공백이 허위 '최저'로 뽑히는 것 방지).

**저수지 초기수위** — 예측시점 초기 저수위는 (1) 그 시점 **관측 수위**가 있으면 사용,
(2) 없으면 **해당 월의 관측 평균 수위**(climatology)로 대체한다. 관측 datum(staff-gauge)은
registry ``obs_datum_offset_ft`` 로 곡선(MSL)에 정합한다.

출력: ``{PrjDir}/3_swatplus/forecast/historical_worst/``
  - ``driest_year_by_season.csv``       계절 × (채택 최저강수년·강수량·신뢰성·차선대체 여부)
  - ``modeling_results_by_season.csv``  계절 × 채택연도의 관측강수 + 수원별 모의결과
  - ``reliability_log.txt``             결측으로 건너뛴 raw 최저 후보 기록

설정은 모두 yaml(``config/swat_py.yaml`` + 공통 ``picaso-hydro.yaml``)에서 읽으며,
**인자 없이** 실행된다: ``python -m swat_py.drought.historical_worst``
프로그램: from swat_py.drought.historical_worst import build_historical_worst
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# 12개 rolling 3개월 계절 — 첫 달의 연도로 라벨(2016_AMJ 예보 관례와 동일).
# month > 12 는 다음 해(month-12): 연도 경계를 넘는 계절(NDJ·DJF).
SEASONS: Dict[str, Tuple[int, int, int]] = {
    "JFM": (1, 2, 3), "FMA": (2, 3, 4), "MAM": (3, 4, 5), "AMJ": (4, 5, 6),
    "MJJ": (5, 6, 7), "JJA": (6, 7, 8), "JAS": (7, 8, 9), "ASO": (8, 9, 10),
    "SON": (9, 10, 11), "OND": (10, 11, 12), "NDJ": (11, 12, 13), "DJF": (12, 13, 14),
}

_MISSING = -90.0            # SWAT+ .pcp 결측 표식(-99) 판정 임계(그 미만=결측)
_SEC_PER_DAY = 86400.0

# 달력 월(1~12월) — 계절(rolling 3개월) 대신 월별 분석용 period 정의.
MONTHS: Dict[str, Tuple[int, ...]] = {f"{m:02d}": (m,) for m in range(1, 13)}


def _wrap(year: int, month: int) -> Tuple[int, int]:
    """month>12 → (year+1, month-12)."""
    return (year, month) if month <= 12 else (year + 1, month - 12)


def _days_in_month(year: int, month: int) -> int:
    return int(pd.Timestamp(year, month, 1).days_in_month)


# ── 관측 강수(.pcp) → 월 강수·유효일 ────────────────────────────────────────────

def find_climatology_pcp(cfg) -> Path:
    """장기모의(historical mean)를 구동한 관측 강수 .pcp 경로.

    CalibratedDir 의 .pcp 중 stations-acidwg 첫 관측소 id 와 일치하는 것,
    없으면 데이터가 가장 많은(장기 단일 관측소) .pcp 를 선택한다.
    """
    cal = Path(cfg.CalibratedDir)
    pcps = sorted(cal.glob("*.pcp"))
    if not pcps:
        raise FileNotFoundError(f"{cal} 에 .pcp 없음")
    try:
        from swat_py.io.station import load_station_csv
        stns = load_station_csv(Path(cfg.ObsDayDir) / "stations-acidwg.csv", [])
        sid = str(stns[0].id)
        for p in pcps:
            if p.stem == sid:
                return p
    except Exception:
        pass
    return max(pcps, key=lambda p: sum(1 for _ in p.open(encoding="utf-8", errors="replace")))


def read_pcp_monthly(pcp_path: Path) -> pd.DataFrame:
    """SWAT+ .pcp(yr jday pcp) → 월별 [year, month, precip_mm, valid_days, total_days].

    결측(-99)은 강수합에서 제외하고 valid_days 에서 제외한다.
    """
    lines = Path(pcp_path).read_text(encoding="utf-8", errors="replace").splitlines()
    recs = []
    for ln in lines[3:]:                       # 헤더 3줄(title, nbyr…, 첫 데이터 앞)
        t = ln.split()
        if len(t) < 3:
            continue
        try:
            yr, jd, v = int(float(t[0])), int(float(t[1])), float(t[2])
        except ValueError:
            continue
        recs.append((yr, jd, v))
    df = pd.DataFrame(recs, columns=["yr", "jday", "pcp"])
    df["date"] = pd.to_datetime(df["yr"].astype(str) + "-" + df["jday"].astype(str),
                                format="%Y-%j")
    df["month"] = df["date"].dt.month
    df["ok"] = df["pcp"] > _MISSING
    g = df.groupby(["yr", "month"])
    out = pd.DataFrame({
        "precip_mm": g.apply(lambda s: s.loc[s["ok"], "pcp"].sum(), include_groups=False),
        "valid_days": g["ok"].sum(),
        "total_days": g["pcp"].count(),
    }).reset_index().rename(columns={"yr": "year"})
    return out


def seasonal_precip_candidates(pcp_monthly: pd.DataFrame, years: List[int],
                               periods: Dict[str, Tuple[int, ...]] = SEASONS
                               ) -> Dict[str, List[dict]]:
    """월강수 → period별 후보목록(강수 오름차순).

    각 후보: {year, precip_mm, min_valid_frac}. period 의 전 월에 데이터가 있는 연도만 후보.
    min_valid_frac = period 내 월 유효일 비율의 최솟값(신뢰성 판정용).
    periods: 계절(SEASONS, 3개월) 또는 월(MONTHS, 1개월).
    """
    idx = {(int(r.year), int(r.month)):
           (r.precip_mm, (r.valid_days / r.total_days) if r.total_days else 0.0)
           for r in pcp_monthly.itertuples()}
    out: Dict[str, List[dict]] = {}
    for s, months in periods.items():
        cands = []
        for y in years:
            keys = [_wrap(y, m) for m in months]
            if any(k not in idx for k in keys):
                continue
            precip = sum(idx[k][0] for k in keys)
            mvf = min(idx[k][1] for k in keys)
            cands.append({"year": y, "precip_mm": float(precip), "min_valid_frac": float(mvf)})
        cands.sort(key=lambda d: d["precip_mm"])
        out[s] = cands
    return out


def select_driest(candidates: Dict[str, List[dict]], *, min_frac: float,
                  log_lines: List[str]) -> Dict[str, dict]:
    """계절별 최저강수 연도 선택 — 신뢰불가(결측 과다)는 로그 후 차선으로 대체.

    Returns {season: {driest_year, precip_mm, median_mm, n_candidates,
                      substituted(bool), skipped:[{year,precip,min_valid_frac}]}}.
    """
    sel: Dict[str, dict] = {}
    for s, cands in candidates.items():
        med = float(np.median([c["precip_mm"] for c in cands])) if cands else float("nan")
        skipped = []
        chosen = None
        for c in cands:
            if c["min_valid_frac"] >= min_frac:
                chosen = c
                break
            skipped.append(c)
            log_lines.append(
                f"[{s}] raw 최저후보 {c['year']} ({c['precip_mm']:.1f}mm) "
                f"= 결측 과다(월 유효일 {c['min_valid_frac']:.0%} < {min_frac:.0%}) → 건너뜀")
        if chosen is None and cands:                       # 신뢰가능 없음 → raw 최저 사용(경고)
            chosen = cands[0]
            log_lines.append(f"[{s}] 신뢰가능 연도 없음 → raw 최저 {chosen['year']} 사용(주의)")
        if chosen is None:
            sel[s] = {"driest_year": None, "precip_mm": float("nan"), "median_mm": med,
                      "n_candidates": 0, "substituted": False, "skipped": skipped}
            continue
        if skipped:
            log_lines.append(
                f"[{s}] → 차선 채택 {chosen['year']} ({chosen['precip_mm']:.1f}mm, "
                f"유효일 {chosen['min_valid_frac']:.0%})")
        sel[s] = {"driest_year": int(chosen["year"]),
                  "precip_mm": round(chosen["precip_mm"], 1), "median_mm": round(med, 1),
                  "n_candidates": len(cands), "substituted": bool(skipped),
                  "skipped": skipped}
    return sel


# ── 장기 climatology 월유량 (모의 유입) ─────────────────────────────────────────

def load_monthly_flow(csv_path: Path) -> Tuple[Dict[Tuple[int, int], Dict[str, float]], List[str]]:
    """channel_monthly_{tag}.csv(wide: date + 채널) → {(year,month): {outlet: flo}}."""
    df = pd.read_csv(csv_path, parse_dates=["date"])
    outlets = [c for c in df.columns if c != "date"]
    idx = {(r.date.year, r.date.month): {o: getattr(r, o) for o in outlets}
           for r in df.itertuples()}
    return idx, outlets


def _season_flows(mon_idx: Dict[Tuple[int, int], Dict[str, float]], outlet: str,
                  y: int, months: Tuple[int, int, int]) -> List[Tuple[int, int, float]]:
    """계절 각 월의 (year, month, flow_m3s) 리스트 (결측 월은 NaN)."""
    out = []
    for m in months:
        yy, mm = _wrap(y, m)
        out.append((yy, mm, mon_idx.get((yy, mm), {}).get(outlet, np.nan)))
    return out


def _season_mean(flows: List[Tuple[int, int, float]]) -> float:
    vals = [f for _, _, f in flows if not (f is None or np.isnan(f))]
    return float(np.mean(vals)) if vals else np.nan


# ── 관측 저수위 → 초기 저수위(MSL) ──────────────────────────────────────────────

def load_obs_level_msl(obs_csv: Path, *, col: str, datum_offset_ft: float
                       ) -> Tuple[Dict[Tuple[int, int], float], Dict[int, float]]:
    """관측 수위 CSV → (연·월 평균 MSL, 월별 climatology 평균 MSL).

    MSL = 관측값 − datum_offset_ft (곡선 datum 정합; reader 는 곡선+offset=관측이므로 역변환).
    """
    df = pd.read_csv(obs_csv, parse_dates=["date"])
    df = df[["date", col]].dropna()
    df["msl"] = pd.to_numeric(df[col], errors="coerce") - float(datum_offset_ft)
    df = df.dropna(subset=["msl"])
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    ym = {(int(r.year), int(r.month)): float(r.msl)
          for r in df.groupby(["year", "month"])["msl"].mean().reset_index().itertuples()}
    clim = {int(r.month): float(r.msl)
            for r in df.groupby("month")["msl"].mean().reset_index().itertuples()}
    return ym, clim


def initial_level_msl(obs_ym: Dict[Tuple[int, int], float], obs_clim: Dict[int, float],
                      year: int, month0: int, *, full_level_ft: float
                      ) -> Tuple[float, str]:
    """예측시점(계절 첫 달) 초기 저수위(MSL) + 출처 태그.

    (1) 그 (year,month) 관측 있으면 사용  → 'observed'
    (2) 없으면 그 월의 climatology 평균     → 'monthly_mean'
    (3) 둘 다 없으면 만수(full)             → 'full_default'
    """
    if (year, month0) in obs_ym:
        return obs_ym[(year, month0)], "observed"
    if month0 in obs_clim:
        return obs_clim[month0], "monthly_mean"
    return float(full_level_ft), "full_default"


# ── 저수지 계절 물수지 (관측 초기화 · 채널유입 구동) ─────────────────────────────

def reservoir_season_balance(flows: List[Tuple[int, int, float]], *, init_msl: float,
                             params, ) -> dict:
    """계절 3개월 물수지 → 평균 저수량%·평균 저수위(MSL) + 월말값.

    flows: [(year, month, inflow_m3s)] (모의 채널유입, 결측 월은 NaN→0 유입).
    init_msl: 계절 첫 달 초기 저수위(MSL). params.curve 로 저류량 환산.
    수지: supply = min(S,full) + inflow_vol − withdrawal_vol ; %=max(supply,dead)/full.
    (저수지 수면 강수/증발/누수는 자료 없어 생략 — 유입·취수가 지배항.)
    """
    curve = params.curve
    full, dead = params.full_m3, params.dead_m3
    S = float(curve.stage_to_storage(init_msl)) if curve is not None else float("nan")
    pcts, levels = [], []
    for yy, mm, inflow in flows:
        days = _days_in_month(yy, mm)
        inflow_vol = (0.0 if inflow is None or np.isnan(inflow) else inflow) * _SEC_PER_DAY * days
        wdr_vol = params.withdrawal_m3s * _SEC_PER_DAY * days
        supply = min(S, full) + inflow_vol - wdr_vol
        pct = max(supply, dead) / full * 100.0 if full > 0 else np.nan
        S = max(min(supply, full), dead)
        lvl = float(curve.storage_to_stage(S)) if curve is not None else np.nan
        pcts.append(pct)
        levels.append(lvl)
    return {"storage_pct_mean": float(np.mean(pcts)) if pcts else np.nan,
            "storage_pct_end": pcts[-1] if pcts else np.nan,
            "water_level_ft_mean": float(np.mean(levels)) if levels else np.nan,
            "water_level_ft_end": levels[-1] if levels else np.nan}


# ── 저수지 일 물수지 (SWAT 저수지 실제 유입 flo_in 구동) ───────────────────────────
#  ⚠ reservoir_season_balance 는 채널유량을 유입으로 쓰는데, Ngerimel 처럼 저수지 용량이
#    채널 월유량보다 훨씬 작으면(예: 용량 0.1MCM ≪ 채널 0.87MCM/월) 매월 즉시 만수 재충전되어
#    실제 강하를 재현하지 못한다. 관측기간(reservoir_day 존재)에는 아래처럼 SWAT 저수지 객체의
#    실제 유입 flo_in(가뭄시 ~0) + 취수 물수지를 써야 관측 강하가 재현된다.

def reservoir_daily_balance(daily_res: pd.DataFrame, *, params, init_msl: float,
                            use_losses: bool = True) -> pd.DataFrame:
    """저수지 일자료(reservoir_day: flo_in·precip·evap·seep) → 일 물수지 저수량%/수위.

    init_msl 초기수위에서 시작해 매일:
        S = clip(S + flo_in (+precip−evap−seep) − 취수, dead, full).
    Returns [date, storage_pct, storage_m3, water_level_ft].
    """
    curve = params.curve
    full, dead = params.full_m3, params.dead_m3
    df = daily_res.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    lc = {c.lower(): c for c in df.columns}

    def col(n):
        return (pd.to_numeric(df[lc[n]], errors="coerce").fillna(0.0)
                if n in lc else pd.Series(0.0, index=df.index))

    net = col("flo_in")
    if use_losses:
        net = net + col("precip") - col("evap") - col("seep")
    wdr = params.withdrawal_m3s * _SEC_PER_DAY
    S = float(curve.stage_to_storage(init_msl)) if curve is not None else float(init_msl)
    out = []
    for d, nv in zip(df["date"], net.to_numpy()):
        S = min(max(S + float(nv) - wdr, dead), full)
        pct = S / full * 100.0 if full > 0 else np.nan
        lvl = float(curve.storage_to_stage(S)) if curve is not None else np.nan
        out.append((d, pct, S, lvl))
    return pd.DataFrame(out, columns=["date", "storage_pct", "storage_m3", "water_level_ft"])


def reservoir_hindcast(cfg) -> Dict[str, str]:
    """관측기간 저수지 재모델링(실제 유입 flo_in + 취수 + 관측 초기수위) vs 관측 저수량%.

    CalibratedDir/reservoir_day.txt(관측기간 SWAT 저수지 일유입)를 써서 관측 첫 수위로
    초기화한 일 물수지를 돌리고, 관측 저수량%와 비교(PBIAS/RMSE/R)한다. 채널유량 기반
    (reservoir_season_balance)이 재현 못 하는 실제 강하를 검증하는 산출물.

    산출: historical_worst/reservoir_hindcast_daily.csv (+ 콘솔 스킬).
    """
    prj = Path(cfg.PrjDir)
    out_dir = prj / "3_swatplus" / "forecast" / "historical_worst"
    out_dir.mkdir(parents=True, exist_ok=True)
    rs = _reservoir_source(cfg)
    if rs is None:
        raise RuntimeError("drought.sources 에 곡선 있는 reservoir 수원이 없음")
    _, params, rcfg = rs
    from swat_py.output.reader_swat_plus import parse_reservoir_day
    rd_path = Path(cfg.CalibratedDir) / "reservoir_day.txt"
    sdate = f"{int(getattr(cfg.Drought, 'syear', None) or 2015)}-01-01"
    rd = parse_reservoir_day(rd_path, outlet=params.gis_id, sdate=sdate)
    if rd is None or rd.empty:
        raise SystemExit(f"reservoir_day.txt 없음/빈 결과: {rd_path}")
    rd["date"] = pd.to_datetime(rd["date"])

    obs_csv, obs_col = _find_reservoir_obs(cfg, params)
    off = getattr(rcfg, "obs_datum_offset_ft", 0.0)
    obs_ym = obs_clim = None
    obs_daily = None
    if obs_csv and Path(obs_csv).is_file():
        raw = pd.read_csv(obs_csv, parse_dates=["date"])
        raw = raw[pd.to_numeric(raw[obs_col], errors="coerce").notna()].copy()
        raw["msl"] = pd.to_numeric(raw[obs_col], errors="coerce") - float(off)
        raw = raw[raw["msl"] > (params.curve.elev_ft[0] if params.curve is not None else -1e9)]
        obs_daily = raw[["date", "msl"]].sort_values("date")
        full = params.full_m3
        obs_daily["obs_pct"] = np.clip(
            params.curve.stage_to_storage(obs_daily["msl"].to_numpy()) / full * 100.0, 0, None)
    # 초기수위 = 관측 첫 수위(없으면 만수)
    if obs_daily is not None and len(obs_daily):
        init_msl = float(obs_daily.iloc[0]["msl"])
        rd = rd[rd["date"] >= obs_daily.iloc[0]["date"]]
    else:
        init_msl = _full_level(params, rcfg)

    mod = reservoir_daily_balance(rd, params=params, init_msl=init_msl)
    skill = {}
    if obs_daily is not None:
        mrg = mod.merge(obs_daily[["date", "obs_pct"]], on="date", how="inner")
        if len(mrg) > 2:
            err = mrg["storage_pct"] - mrg["obs_pct"]
            skill = {"n": int(len(mrg)), "pbias": float(err.mean()),
                     "rmse": float((err ** 2).mean() ** 0.5),
                     "r": float(np.corrcoef(mrg["storage_pct"], mrg["obs_pct"])[0, 1])}
            mod = mod.merge(obs_daily[["date", "obs_pct"]], on="date", how="left")
    csv = out_dir / "reservoir_hindcast_daily.csv"
    mod.to_csv(csv, index=False, encoding="utf-8-sig")
    print(f"[저수지 hindcast] 초기수위 {init_msl:.1f}ft(MSL) · flo_in+취수 일 물수지 "
          f"{mod['date'].min().date()}~{mod['date'].max().date()}")
    print(f"  모델 최저 저수량% = {mod['storage_pct'].min():.1f}%")
    if skill:
        print(f"  vs 관측: n={skill['n']} PBIAS={skill['pbias']:+.1f}% "
              f"RMSE={skill['rmse']:.1f}% R={skill['r']:.2f}")
    print(f"  저장: {csv}")
    return {"daily": str(csv), **{f"skill_{k}": str(v) for k, v in skill.items()}}


def run_reservoir_daily(cfg, *, workdir=None, timeout: int = 7200,
                        save_path=None) -> pd.DataFrame:
    """장기(syear–eyear) SWAT+ 를 저수지 **일자료** 출력으로 실행 → reservoir_day 일 DataFrame.

    climatology_run 과 동일한 기상 재배정·기간 확장을 쓰되, print.prt 는 채널을 월단위로
    낮추고 **reservoir 를 일단위**로 유지, 출력창(yrc_start/yrc_end)을 syear+warmup~eyear 로
    맞춰 **전 기간(예 1985–2023) 저수지 일유입 flo_in** 을 생산한다.
    반환: [date, flo_in, precip, evap, seep, flo_stor, ...] (저수지 수원 gis_id).
    """
    import shutil
    import subprocess
    import sys
    import tempfile
    from swat_py.drought.climatology_run import setup_acidwg_weather
    from swat_py.output.reader_swat_plus import parse_reservoir_day
    from swat_py.runner.file_manager import resolve_swat_exe

    rs = _reservoir_source(cfg)
    if rs is None:
        raise RuntimeError("drought.sources 에 곡선 있는 reservoir 수원이 없음")
    _, params, _ = rs
    master = Path(cfg.CalibratedDir)
    work = (Path(workdir) if workdir
            else Path(tempfile.gettempdir()) / "picaso_res_long" / "TxtInOut")
    warmup = int(cfg.CioNYSKIP)
    dc = cfg.Drought
    syear = dc.syear or 1982
    eyear = dc.eyear or 2023
    out_first = pd.Timestamp(f"{syear + warmup}-01-01")

    if work.parent.exists():
        shutil.rmtree(work.parent, ignore_errors=True)
    print(f"[1/4] calibrated master 복사 → {work}")
    shutil.copytree(master, work)
    stn = setup_acidwg_weather(cfg, work)
    print(f"[2/4] 기상 재배정 → {stn} 단일 관측소, time.sim {syear}–{eyear}")

    ts = work / "time.sim"
    tl = ts.read_text().splitlines()
    tl[2] = f"       1      {syear}       366      {eyear}         0"
    ts.write_text("\n".join(tl) + "\n")

    # print.prt: nyskip·출력창(yrc) 을 전 기간으로 · channel_sd 월 · reservoir 일.
    pp = work / "print.prt"
    pl = pp.read_text().splitlines()
    if len(pl) >= 3 and pl[2].split():
        tk = pl[2].split()
        # nyskip day_start yrc_start day_end yrc_end interval
        tk[0] = str(warmup)
        if len(tk) >= 5:
            tk[2] = str(syear)          # yrc_start = sim 시작(웜업 nyskip 로 제외)
            tk[4] = str(eyear)          # yrc_end
        pl[2] = "  ".join(tk)
    for i, ln in enumerate(pl):
        t = ln.split()
        if not t:
            continue
        if t[0] == "channel_sd":
            pl[i] = f"{t[0]:<28} n             y             n             n"
        elif t[0] == "reservoir":
            pl[i] = f"{t[0]:<28} y             n             n             n"
    pp.write_text("\n".join(pl) + "\n")

    exe_src = resolve_swat_exe(cfg.Executable, master,
                               fetch_dirs=[cfg.CalibratedDir, cfg.DefaultDir])
    exe = work / exe_src.name
    if not exe.is_file():
        shutil.copyfile(exe_src, exe)
        try:
            exe.chmod(0o755)
        except OSError:
            pass
    print("[3/4] SWAT+ 실행 … (장기, 수 분)")
    log = work / "swat_run.log"
    with log.open("w", encoding="utf-8", errors="replace") as fh:
        r = subprocess.run([str(exe)], cwd=str(work), stdout=fh,
                           stderr=subprocess.STDOUT, timeout=timeout)
    if r.returncode != 0:
        sys.stderr.write(log.read_text(encoding="utf-8", errors="replace")[-1500:])
        raise SystemExit(f"SWAT 실행 실패 rc={r.returncode} (log: {log})")

    raw = parse_reservoir_day(work / "reservoir_day.txt", outlet=params.gis_id,
                              sdate=f"{syear}-01-01")
    if raw is None or raw.empty:
        raise SystemExit("reservoir_day.txt 파싱 실패/빈 결과")
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw[raw["date"] >= out_first].reset_index(drop=True)
    print(f"[4/4] reservoir_day gis_id={params.gis_id} n={len(raw)} "
          f"{raw['date'].min().date()}~{raw['date'].max().date()}")
    if save_path:
        cols = [c for c in ("date", "flo_in", "precip", "evap", "seep", "flo_stor",
                            "flo_out") if c in raw.columns]
        raw[cols].to_csv(save_path, index=False, encoding="utf-8-sig")
        print(f"      저장: {save_path}")
    return raw


def _reservoir_stage(pct: float, q1: float, q2: float, q3: float) -> str:
    """저수지 단계 — 만수(cap) **이상**은 Normal(월류). capacity_fraction 임계.

    classify_stage4 는 >q1 만 Normal(하천용)이나, flo_in 물수지는 저수량%가 만수에서
    정확히 q1(=100)에 캡되므로 만수 유지 월이 Watch 로 오분류된다. 저수지는 만수 이상=Normal.
    """
    from swat_py.drought.stages import classify_stage4
    if not (pct == pct):
        return "NA"
    if pct >= q1:
        return "Normal"
    return classify_stage4(pct, q1, q2, q3)


def _reservoir_source(cfg):
    """cfg.Drought.sources 첫 저수지 → (source, ReservoirForecastParams, reservoir_cfg) 또는 None."""
    dc = cfg.Drought
    for s in (getattr(dc, "sources", None) or []):
        if getattr(s, "type", None) != "reservoir":
            continue
        rcfg = (getattr(cfg, "Reservoirs", {}) or {}).get(s.reservoir)
        if not (rcfg and rcfg.stage_storage_file):
            continue
        from swat_py.drought.reservoir_forecast import build_reservoir_forecast_params
        from swat_py.io.reservoir import load_stage_storage
        curve = load_stage_storage(rcfg.stage_storage_file, name=s.reservoir)
        return s, build_reservoir_forecast_params(s, rcfg, curve), rcfg
    return None


# ── 오케스트레이션 (무변수 CLI) ─────────────────────────────────────────────────

def build_historical_worst(cfg, *, min_frac: float = 0.90,
                           by_month: bool = False) -> Dict[str, str]:
    """period(계절 또는 월)별 최저강수 연도 + 모의결과 표를 historical_worst/ 에 저장.

    by_month=False → 12개 계절(rolling 3개월) · True → 12개 달력 월(1~12월). 반환: 경로 dict.
    """
    from swat_py.drought.climatology import climatology_tag
    from swat_py.drought.fdc import stage_thresholds
    from swat_py.drought.stages import classify_stage4

    periods = MONTHS if by_month else SEASONS
    pcol = "month" if by_month else "season"
    suffix = "by_month" if by_month else "by_season"
    kind = "월" if by_month else "계절"

    prj = Path(cfg.PrjDir)
    out_dir = prj / "3_swatplus" / "forecast" / "historical_worst"
    out_dir.mkdir(parents=True, exist_ok=True)
    dc = cfg.Drought
    warmup = int(cfg.CioNYSKIP)
    syear = dc.syear or 1982
    eyear = dc.eyear or 2023
    years = list(range(syear + warmup, eyear + 1))          # historical mean 출력기간
    log_lines: List[str] = [
        f"# historical_worst 신뢰성 로그 [{kind}별]  (기간 {years[0]}–{years[-1]}, "
        f"월 유효일 임계 {min_frac:.0%})", ""]

    # 1) 관측 강수 → period별 최저강수(신뢰가능) 연도
    pcp = find_climatology_pcp(cfg)
    print(f"[강수] 관측 .pcp = {pcp.name}  ({kind}별, 유효일 ≥{min_frac:.0%} 신뢰성 필터)")
    log_lines.append(f"관측 강수 소스: {pcp.name}")
    pmon = read_pcp_monthly(pcp)
    cands = seasonal_precip_candidates(pmon, years, periods=periods)
    sel = select_driest(cands, min_frac=min_frac, log_lines=log_lines)

    rank_rows = []
    for s in periods:
        d = sel[s]
        rank_rows.append({
            pcol: s, "driest_year": d["driest_year"], "precip_mm": d["precip_mm"],
            "median_mm": d["median_mm"],
            "substituted_from_unreliable": d["substituted"],
            "skipped_years": ";".join(f"{c['year']}({c['precip_mm']:.0f}mm,"
                                      f"{c['min_valid_frac']:.0%})" for c in d["skipped"]),
            "n_candidates": d["n_candidates"]})
    rank = pd.DataFrame(rank_rows)
    rank_csv = out_dir / f"driest_year_{suffix}.csv"
    rank.to_csv(rank_csv, index=False, encoding="utf-8-sig")

    # 2) 장기 climatology 월유량 (모의 유입) + 임계
    tag = climatology_tag(cfg)
    flow_csv = prj / "4_drought_risk" / "climatology" / f"channel_monthly_{tag}.csv"
    mon_idx, outlets = load_monthly_flow(flow_csv)
    thr = {}                                   # {outlet: (q1,q2,q3,type)}
    for s_ in (getattr(dc, "sources", None) or []):
        for gid, nm in (s_.outlets or {}).items():
            if nm not in outlets:
                continue
            method, values = dc.threshold_for(gid)
            series = [mon_idx[k][nm] for k in mon_idx
                      if nm in mon_idx[k] and not np.isnan(mon_idx[k][nm])]
            st = stage_thresholds(series if method != "capacity_fraction" else [],
                                  method, values)
            thr[nm] = (st["normal_watch"], st["watch_warning"], st["warning_crisis"], s_.type)

    # 3) 저수지 초기수위(관측/월평균) + 물수지
    rs = _reservoir_source(cfg)
    obs_ym = obs_clim = None
    res_name = res_params = res_rcfg = None
    full_lvl = float("nan")
    if rs is not None:
        _, res_params, res_rcfg = rs
        res_name = res_params.name
        full_lvl = _full_level(res_params, res_rcfg)
        obs_csv, obs_col = _find_reservoir_obs(cfg, res_params)
        if obs_csv and Path(obs_csv).is_file():
            obs_ym, obs_clim = load_obs_level_msl(
                Path(obs_csv), col=obs_col,
                datum_offset_ft=getattr(res_rcfg, "obs_datum_offset_ft", 0.0))
            log_lines.append("")
            log_lines.append(f"저수지 관측수위: {Path(obs_csv).name} col={obs_col} "
                             f"datum_offset={getattr(res_rcfg, 'obs_datum_offset_ft', 0.0)} "
                             f"→ 연·월 {len(obs_ym)}개, 월 climatology {len(obs_clim)}개")
        else:
            log_lines.append("저수지 관측수위 파일 없음 → 초기수위 만수/설정값 사용")

    # 3b) 개선된 저수지 유입 — 장기 flo_in(reservoir_day) 연속 물수지 → 월 저수량%.
    #     reservoir_day_1985_2023.csv 있으면 채널유량 대신 이 값을 쓴다(용량 대비 채널유량이
    #     과대해 만수 고정되던 문제 해결). 없으면 채널유량 근사(reservoir_season_balance)로 폴백.
    res_month_idx = None
    if rs is not None:
        flo_in_csv = out_dir / f"reservoir_day_{years[0]}_{years[-1]}.csv"
        if flo_in_csv.is_file():
            rd = pd.read_csv(flo_in_csv, parse_dates=["date"])
            daily = reservoir_daily_balance(rd, params=res_params, init_msl=full_lvl)
            daily["year"] = daily["date"].dt.year
            daily["month"] = daily["date"].dt.month
            g = daily.groupby(["year", "month"])
            res_month_idx = {(int(y), int(m)): {
                "pct": float(sub["storage_pct"].mean()),
                "pct_min": float(sub["storage_pct"].min()),
                "level": float(sub["water_level_ft"].mean())}
                for (y, m), sub in g}
            log_lines.append(f"저수지 유입: flo_in 연속 물수지 ({flo_in_csv.name}, "
                             f"초기 만수 {full_lvl:.0f}ft, 취수 {res_params.withdrawal_m3s} m³/s)")
            print(f"[저수지] flo_in 연속 물수지 사용 ({flo_in_csv.name})")
        else:
            log_lines.append(f"[주의] {flo_in_csv.name} 없음 → 채널유량 근사(만수 편향) 폴백. "
                             f"개선하려면: python -m swat_py.drought.historical_worst --gen-reservoir-daily")
            print(f"[저수지] flo_in 파일 없음 → 채널유량 근사 폴백")

    # 4) 결과 표
    rows = []
    for s, months in periods.items():
        d = sel[s]
        y = d["driest_year"]
        rec = {pcol: s, "driest_year": y, "precip_mm": d["precip_mm"],
               "substituted": d["substituted"]}
        if y is None:
            rows.append(rec)
            continue
        for nm in outlets:
            fl = _season_flows(mon_idx, nm, y, months)
            fmean = _season_mean(fl)
            rec[f"{nm}_flow_m3s"] = round(fmean, 4) if not np.isnan(fmean) else np.nan
            if nm in thr and thr[nm][3] == "stream":
                q1, q2, q3, _ = thr[nm]
                rec[f"{nm}_stage"] = classify_stage4(fmean, q1, q2, q3)
        # 저수지 저수량% — 개선(flo_in 연속 물수지) 우선, 없으면 채널유량 근사.
        if res_params is not None and res_name in outlets:
            if res_month_idx is not None:
                cells = [res_month_idx.get(_wrap(y, m)) for m in months]
                cells = [c for c in cells if c is not None]
                if cells:
                    pct_mean = float(np.mean([c["pct"] for c in cells]))
                    pct_min = float(np.min([c["pct_min"] for c in cells]))
                    lvl_mean = float(np.mean([c["level"] for c in cells]))
                    rec[f"{res_name}_method"] = "flo_in"
                    rec[f"{res_name}_storage_pct"] = round(pct_mean, 1)
                    rec[f"{res_name}_storage_pct_min"] = round(pct_min, 1)
                    rec[f"{res_name}_water_level_ft"] = round(lvl_mean, 2)
                    if res_name in thr and thr[res_name][3] == "reservoir":
                        q1, q2, q3, _ = thr[res_name]
                        rec[f"{res_name}_stage"] = _reservoir_stage(pct_mean, q1, q2, q3)
                        rec[f"{res_name}_stage_min"] = _reservoir_stage(pct_min, q1, q2, q3)
            else:
                init_msl, src_tag = initial_level_msl(
                    obs_ym or {}, obs_clim or {}, y, months[0], full_level_ft=full_lvl)
                bal = reservoir_season_balance(
                    _season_flows(mon_idx, res_name, y, months), init_msl=init_msl,
                    params=res_params)
                rec[f"{res_name}_method"] = "channel_approx"
                rec[f"{res_name}_init_level_ft"] = round(init_msl, 2)
                rec[f"{res_name}_init_source"] = src_tag
                rec[f"{res_name}_storage_pct"] = round(bal["storage_pct_mean"], 1) \
                    if not np.isnan(bal["storage_pct_mean"]) else np.nan
                rec[f"{res_name}_water_level_ft"] = round(bal["water_level_ft_mean"], 2) \
                    if not np.isnan(bal["water_level_ft_mean"]) else np.nan
                if res_name in thr and thr[res_name][3] == "reservoir":
                    q1, q2, q3, _ = thr[res_name]
                    rec[f"{res_name}_stage"] = classify_stage4(bal["storage_pct_mean"], q1, q2, q3)
        rows.append(rec)
    results = pd.DataFrame(rows)
    res_csv = out_dir / f"modeling_results_{suffix}.csv"
    results.to_csv(res_csv, index=False, encoding="utf-8-sig")

    # 5) 신뢰성 로그 저장
    log_path = out_dir / f"reliability_log_{suffix}.txt"
    n_sub = sum(1 for s in periods if sel[s]["substituted"])
    log_lines.append("")
    log_lines.append(f"차선 대체 {kind} 수: {n_sub}/{len(periods)}")
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print(f"[신뢰성] 결측으로 차선 대체된 {kind} {n_sub}/{len(periods)} → {log_path.name}")
    print("\n저장:")
    print(f"  최저강수 연도 : {rank_csv}")
    print(f"  모의 결과     : {res_csv}")
    print(f"  신뢰성 로그   : {log_path}")
    return {"driest": str(rank_csv), "results": str(res_csv),
            "log": str(log_path), "out_dir": str(out_dir)}


def _full_level(params, rcfg) -> float:
    """만수 저수위(ft, MSL) — registry spillway_ft, 없으면 곡선 최상단."""
    sp = getattr(rcfg, "spillway_ft", None)
    if sp is not None and sp == sp:
        return float(sp)
    return float(params.curve.elev_ft[-1]) if params.curve is not None else float("nan")


def _find_reservoir_obs(cfg, res_params) -> Tuple[Optional[str], Optional[str]]:
    """cfg.Observations 에서 저수지 수위 관측 → (경로, 컬럼). 없으면 (None, None).

    variable=="wlevel" 이고 outlet_id 가 저수지 gis_id 와 일치하는 관측을 찾는다.
    obs_file 은 상대경로면 ObservedDataDir(obs_root) 기준으로 해석.
    """
    root = getattr(cfg, "ObservedDataDir", "") or str(Path(cfg.PrjDir) / "0_database" / "obs")
    for o in getattr(cfg, "Observations", []) or []:
        if getattr(o, "variable", "") != "wlevel":
            continue
        if int(getattr(o, "outlet_id", -1)) != int(res_params.gis_id):
            continue
        of = getattr(o, "obs_file", "") or ""
        if not of:
            return None, None
        p = Path(of)
        path = str(p if p.is_absolute() else Path(root) / of)
        return path, (getattr(o, "obs_column", "") or "wlevel_ft")
    return None, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swat_py.drought.historical_worst",
                                 description="계절별 최저강수 연도 + 장기 모의결과 정리(무변수 CLI)")
    ap.add_argument("--config", default="config/swat_py.yaml",
                    help="swat_py 설정(기본값으로 무변수 실행)")
    ap.add_argument("--monthly", action="store_true",
                    help="계절(3개월) 대신 달력 월(1~12월) 단위로 분석")
    ap.add_argument("--reservoir-hindcast", action="store_true",
                    help="관측기간 저수지 재모델링(실제 유입 flo_in+취수+관측초기화) vs 관측")
    ap.add_argument("--gen-reservoir-daily", action="store_true",
                    help="장기(1985~) 저수지 일유입(flo_in) SWAT 생성 → reservoir_day CSV "
                         "(개선된 저수량%% 모의의 선행 단계, 수 분 소요)")
    args = ap.parse_args(argv)
    from swat_py.config import load_config
    cfg = load_config(args.config)
    if args.gen_reservoir_daily:
        warmup = int(cfg.CioNYSKIP)
        s = (cfg.Drought.syear or 1982) + warmup
        e = cfg.Drought.eyear or 2023
        out = Path(cfg.PrjDir) / "3_swatplus" / "forecast" / "historical_worst" \
            / f"reservoir_day_{s}_{e}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        run_reservoir_daily(cfg, save_path=out)
    elif args.reservoir_hindcast:
        reservoir_hindcast(cfg)
    else:
        build_historical_worst(cfg, by_month=args.monthly)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
