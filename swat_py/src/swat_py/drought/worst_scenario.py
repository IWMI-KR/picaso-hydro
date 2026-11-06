"""Worst Scenario 산출 — ① 관측 기반 월별 최저, ② 예측 기반 계절별 최악.

요청(2026-11-06)
    ① 실제 관측자료가 있는 기간에서 **결측을 제외**하고, 달력 월(1~12월)별로 가장
       낮았던 연도를 찾아 **월평균**과 **일최저**를 정리한다.
    ② 전체 예측 기간(예측 결과가 있는 모든 연도) 중에서 12개 계절(JFM~DJF)별로
       **대표통계(중앙값/평균) 기준 저수위·저유량이 가장 낮고 그 기간이 길었던**
       기간을 하나 골라, 3개월 예측 결과(월별 대표값·단계·확률)를 정리한다.
    ③ 관측이 바뀌거나 새 예측이 추가될 때마다 **다시 돌리면 갱신**되도록 한다.

산출 → ``{PrjDir}/4_drought_risk/worst/``

    worst_observed_monthly.csv      ① 월별 최저 연도 (수원 × 12개월)
    worst_observed_reliability.txt  ① 결측·자료부족으로 제외/차선대체한 내역
    worst_forecast_seasonal.csv     ② 선정 기간의 3개월 상세 (수원 × 12계절 × 3개월)
    worst_forecast_selection.csv    ② 어느 기간을 왜 골랐는지(선정 근거·후보 순위)

선정 규칙 (② — 사용자 확정 2026-11-06)
    **비정상 개월수 우선 → 최저값**. 즉 Normal|Watch 경계보다 낮은 달의 수(0~3)가
    많은 기간을 먼저 고르고, 같으면 3개월 중 대표값 최저가 더 낮은 기간을 고른다.
    ("낮고 **기간이 길었던**" 에서 길이를 1순위로 본다 — 한 달만 급락한 기간보다
     석 달 내내 낮았던 기간을 최악으로 본다.)

    위 두 값이 **완전히 같을 때만** 비정상 위험확률(3개월 평균 100−Normal%)이 큰
    기간을 고른다. 팔라우 Ngerimel 은 관리형 저수지라 중앙값이 만수 23.00 ft 에
    고정되어 비정상 개월수가 전 기간 0, 최저값도 23.00 으로 동점이 되는 계절이
    있다 — 그대로 두면 연도순 첫 후보가 '최악'으로 뽑힌다. 동점 여부는
    ``n_tied_by_rule``·``tiebreak`` 열에 그대로 남기므로 선정이 임의였는지
    표에서 확인할 수 있다.

대표통계
    기본값은 ``drought.climatology_stat`` 을 그대로 따른다 — 팔라우 ``median``,
    쿡 ``mean``. 두 사업이 다른 것은 의도된 설정이다(저수지 수위는 위가 만수로
    막히고 아래 꼬리가 길어 중앙값, 하천 유량은 평균). ``--stat`` 로 덮어쓸 수 있다.

단위 주의
    수원마다 변수가 다르다. 팔라우 Ngerimel 은 수위(ft), 하천은 유량(m³/s)이다.
    팔라우 Ngerikiil 은 **관측이 수위(ft)인데 예측은 유량(m³/s)** 이고 수위-유량
    환산곡선이 없다 → ①은 ft, ②는 m³/s 로 나간다. 그래서 모든 행에 variable·unit
    열을 붙인다. 두 표를 같은 축에서 비교하지 말 것.

프로그램: from swat_py.drought.worst_scenario import build_worst
실행    : python -m swat_py.drought.worst_scenario          (무변수, yaml 설정만)
"""
from __future__ import annotations

import argparse
import calendar
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# 계절 라벨 12종 — drought.season.season_months 와 같은 정의.
SEASONS = ["JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA",
           "JAS", "ASO", "SON", "OND", "NDJ", "DJF"]
STAGES = ["Normal", "Watch", "Warning", "Crisis"]

OUT_DIRNAME = "worst"


# ─────────────────────────────────────────────────────────────────────────────
#  공통
# ─────────────────────────────────────────────────────────────────────────────
def worst_dir(cfg) -> Path:
    """산출 폴더 ``4_drought_risk/worst`` (없으면 생성)."""
    d = Path(cfg.PrjDir) / "4_drought_risk" / OUT_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_stat(cfg, stat: Optional[str] = None) -> str:
    """대표통계 결정 — 인자 > drought.worst_stat > drought.climatology_stat > mean."""
    if stat:
        s = str(stat).lower()
    else:
        dc = getattr(cfg, "Drought", None)
        s = str(getattr(dc, "worst_stat", "") or
                getattr(dc, "climatology_stat", "") or "mean").lower()
    if s not in ("mean", "median"):
        raise ValueError(f"stat 은 mean|median 이어야 함: {s!r}")
    return s


def _as_int(v, default: int = 0) -> int:
    """NaN·빈값·문자열을 섞어 받아도 죽지 않는 정수 변환."""
    n = pd.to_numeric(v, errors="coerce")
    return default if n != n else int(n)


def classify_stage(value: float, nw: float, ww: float, wc: float) -> str:
    """경계 3개로 4단계 분류. **낮을수록 나쁘다**(수위·유량 공통).

    >>> classify_stage(22.0, 21.85, 19.55, 14.95)
    'Normal'
    >>> classify_stage(20.0, 21.85, 19.55, 14.95)
    'Watch'
    >>> classify_stage(14.9, 21.85, 19.55, 14.95)
    'Crisis'
    """
    if value != value:                 # NaN
        return ""
    if value >= nw:
        return "Normal"
    if value >= ww:
        return "Watch"
    if value >= wc:
        return "Warning"
    return "Crisis"


# ─────────────────────────────────────────────────────────────────────────────
#  ① 관측 기반 — 월별 최저 연도
# ─────────────────────────────────────────────────────────────────────────────
def _obs_entries(cfg) -> List[dict]:
    """cfg.Observations 중 **일단위 파일이 실제로 있는** 항목 → 해석된 목록.

    outlet 이 drought 수원에 속하지 않는 관측은 제외한다(대시보드와 짝이 맞는
    수원만 Worst Scenario 대상). 반환 항목: name/variable/unit/path/column/min_valid.
    """
    root = (getattr(cfg, "ObservedDataDir", "") or
            str(Path(cfg.PrjDir) / "0_database" / "obs"))
    dc = getattr(cfg, "Drought", None)
    out: List[dict] = []
    for o in getattr(cfg, "Observations", []) or []:
        if str(getattr(o, "time_step", "daily")).lower() != "daily":
            continue
        of = getattr(o, "obs_file", "") or ""
        if not of:
            continue
        p = Path(of)
        path = p if p.is_absolute() else Path(root) / of
        if not path.is_file():
            continue
        name = str(getattr(o, "id", "") or getattr(o, "outlet_name", "") or path.stem)
        var = str(getattr(o, "variable", "") or "")
        col = str(getattr(o, "obs_column", "") or
                  ("wlevel_ft" if var == "wlevel" else "flow_m3s"))
        # drought 수원에 속하는지 — 이름 또는 outlet_id 로 판정(저수지는 레지스트리 이름).
        in_drought = True
        if dc is not None and getattr(dc, "sources", None):
            in_drought = bool(dc.source_for(name))
            if not in_drought:
                oid = getattr(o, "outlet_id", None)
                if oid is not None:
                    in_drought = bool(dc.source_for(int(oid)))
            if not in_drought and getattr(o, "reservoir", ""):
                in_drought = any(s.reservoir == o.reservoir for s in dc.sources)
        elif dc is not None and getattr(dc, "outlets", None):
            in_drought = name in {str(v) for v in dc.outlets.values()}
        if not in_drought:
            continue
        # 저수지는 **사수위(자 눈금)** 를 기준선으로 자동 산출한다 — 결측을 0 으로
        # 적어 둔 행이 '역대 최저'로 뽑히는 것을 막는다(2019-03 사례, 자료수정이력).
        # 하천처럼 기준선이 없는 관측은 observations[].min_valid 로 명시한다.
        floor = float(getattr(o, "min_valid", float("nan")))
        if floor != floor and getattr(o, "reservoir", ""):
            rcfg = (getattr(cfg, "Reservoirs", {}) or {}).get(o.reservoir)
            if rcfg is not None:
                try:
                    from swat_py.io.reservoir import dead_level_gauge_ft
                    floor = float(dead_level_gauge_ft(rcfg))
                except Exception:               # noqa: BLE001 — 제원 미상이면 검사 생략
                    floor = float("nan")
        out.append({"name": name, "variable": var or "flow", "column": col,
                    "unit": str(getattr(o, "unit", "") or ""),
                    "path": path, "min_valid": floor})
    return out


def _read_obs_daily(entry: dict) -> pd.DataFrame:
    """관측 CSV → DataFrame[date, value] (결측·min_valid 미만 제거)."""
    df = pd.read_csv(entry["path"], encoding="utf-8-sig")
    cols = {c.strip().lower(): c for c in df.columns}
    dcol = cols.get("date") or list(df.columns)[0]
    vcol = cols.get(entry["column"].lower())
    if vcol is None:                                  # 열 이름이 다르면 2번째 열
        vcol = [c for c in df.columns if c != dcol][0]
    out = pd.DataFrame({
        "date": pd.to_datetime(df[dcol], errors="coerce"),
        "value": pd.to_numeric(df[vcol], errors="coerce"),
    }).dropna(subset=["date"])
    mv = entry["min_valid"]
    if mv == mv:                                      # NaN 아니면 적용
        out.loc[out["value"] < mv, "value"] = float("nan")
    return out.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)


def build_observed_monthly_worst(cfg, *, min_coverage: float = 0.90
                                 ) -> Tuple[pd.DataFrame, List[str]]:
    """① 관측 기반 월별 최저 연도 → (표, 로그줄들).

    각 달력 월에 대해 **유효일 비율이 min_coverage 이상인 연도**만 후보로 두고,
    월평균이 가장 낮은 연도를 고른다. 후보가 없으면 유효일이 가장 많은 연도를
    차선으로 쓰고(``relaxed``) 로그에 남긴다 — 결과가 통째로 비는 것보다 낫다.
    """
    rows: List[dict] = []
    log: List[str] = [f"# Worst Scenario ① 관측 월별 최저 — 유효일 기준 {min_coverage:.0%}", ""]
    entries = _obs_entries(cfg)
    if not entries:
        log.append("관측 일자료가 없어 ① 을 건너뛰었다.")
        return pd.DataFrame(), log

    for e in entries:
        df = _read_obs_daily(e)
        if df.empty:
            log.append(f"[{e['name']}] 유효 관측 0건 — 건너뜀 ({e['path'].name})")
            continue
        df["year"] = df["date"].dt.year
        df["month"] = df["date"].dt.month
        p0, p1 = df["date"].min().date(), df["date"].max().date()
        log.append(f"[{e['name']}] {e['variable']}({e['unit']}) {p0}~{p1} "
                   f"유효 {len(df):,}일 · 파일 {e['path'].name}")
        for m in range(1, 13):
            sub = df[df["month"] == m]
            if sub.empty:
                log.append(f"  {m:2d}월: 관측 없음 — 산출 제외")
                continue
            stats = []
            for y, g in sub.groupby("year"):
                dim = calendar.monthrange(int(y), m)[1]
                cov = len(g) / dim
                imin = g["value"].idxmin()
                stats.append({"year": int(y), "n": len(g), "dim": dim, "cov": cov,
                              "mean": float(g["value"].mean()),
                              "min": float(g.loc[imin, "value"]),
                              "min_date": g.loc[imin, "date"].date().isoformat()})
            cands = [s for s in stats if s["cov"] >= min_coverage]
            relaxed = not cands
            if relaxed:
                cands = [max(stats, key=lambda s: s["cov"])]
                log.append(f"  {m:2d}월: 유효일 {min_coverage:.0%} 이상인 연도 없음 → "
                           f"차선 {cands[0]['year']}년(유효 {cands[0]['n']}/{cands[0]['dim']}일)")
            best = min(cands, key=lambda s: s["mean"])
            rows.append({
                "source": e["name"], "variable": e["variable"], "unit": e["unit"],
                "month": m, "worst_year": best["year"],
                "monthly_mean": round(best["mean"], 6),
                "daily_min": round(best["min"], 6), "daily_min_date": best["min_date"],
                "n_days_valid": best["n"], "days_in_month": best["dim"],
                "coverage_pct": round(100.0 * best["cov"], 1),
                "n_years_candidate": len(cands), "n_years_observed": len(stats),
                "selection": "relaxed" if relaxed else "ok",
                "obs_start": p0.isoformat(), "obs_end": p1.isoformat(),
                "obs_file": e["path"].name,
            })
        log.append("")
    return pd.DataFrame(rows), log


# ─────────────────────────────────────────────────────────────────────────────
#  ② 예측 기반 — 계절별 최악 기간
# ─────────────────────────────────────────────────────────────────────────────
def _forecast_periods(cfg) -> List[Tuple[str, int, str, Path]]:
    """4_drought_risk/forecast 하위 → [(라벨, 연도, 계절, 경로)] (연도순)."""
    fdir = Path(cfg.PrjDir) / "4_drought_risk" / "forecast"
    out = []
    if not fdir.is_dir():
        return out
    for d in sorted(p for p in fdir.iterdir() if p.is_dir()):
        key = d.name.split("__")[0]
        if len(key) < 8 or key[4] != "_":
            continue
        yr, se = key[:4], key[5:8]
        if not yr.isdigit() or se not in SEASONS:
            continue
        out.append((d.name, int(yr), se, d))
    return sorted(out, key=lambda t: (t[2], t[1]))


def _read_period_outlet(path: Path, stat: str) -> Optional[dict]:
    """한 기간·한 수원 폴더 → 3개월 대표값·단계확률·임계. 자료 불완전하면 None."""
    sp, se, th = path / "stage_prob.csv", path / "series.csv", path / "thresholds.csv"
    if not (sp.is_file() and se.is_file() and th.is_file()):
        return None
    prob = pd.read_csv(sp, encoding="utf-8-sig")
    ser = pd.read_csv(se, encoding="utf-8-sig")
    thr = pd.read_csv(th, encoding="utf-8-sig")
    if prob.empty or ser.empty or thr.empty:
        return None
    col = "p50" if stat == "median" else "forecast_mean"
    if col not in ser.columns:
        return None
    t = thr.iloc[0]
    try:
        nw, ww, wc = (float(t["normal_watch"]), float(t["watch_warning"]),
                      float(t["warning_crisis"]))
    except (KeyError, ValueError):
        return None
    vmap = {str(r["ym"]): r for _, r in ser.iterrows()}
    months = []
    for _, r in prob.iterrows():
        ym = str(r["ym"])
        srow = vmap.get(ym)
        v = float("nan") if srow is None else pd.to_numeric(srow[col], errors="coerce")
        v = float(v) if v == v else float("nan")
        stage = classify_stage(v, nw, ww, wc)
        months.append({
            "ym": ym, "month": int(r["month"]), "value": v, "stage": stage,
            "prob_of_stage": (float(r[stage]) if stage in prob.columns else float("nan")),
            **{f"prob_{s.lower()}": float(r[s]) for s in STAGES if s in prob.columns},
            "most_likely": str(r.get("most_likely", "")),
            "n_members": _as_int(r.get("n", 0)),
        })
    if not months or any(m["value"] != m["value"] for m in months):
        return None
    vals = [m["value"] for m in months]
    # 비정상 위험확률 — 3개월 평균 (100 − Normal 확률). 대표값이 만수에 고정돼
    # 단계가 늘 Normal 로 나오는 저수지에서도 앙상블 하위꼬리의 위험을 구분한다.
    risk = [100.0 - m.get("prob_normal", float("nan")) for m in months]
    risk = [r for r in risk if r == r]
    return {
        "months": months, "thr": (nw, ww, wc),
        "min_value": min(vals), "mean_value": sum(vals) / len(vals),
        "n_below_watch": sum(1 for m in months if m["stage"] and m["stage"] != "Normal"),
        "risk_pct": (sum(risk) / len(risk)) if risk else 0.0,
        "variable": str(t["variable"]) if "variable" in thr.columns else "flow_m3s",
    }


def build_forecast_seasonal_worst(cfg, *, stat: Optional[str] = None
                                  ) -> Tuple[pd.DataFrame, pd.DataFrame, str]:
    """② 계절별 최악 기간 → (월별 상세표, 선정근거표, 사용한 통계명).

    선정 규칙: ``비정상 개월수`` 내림차순 → ``3개월 최저 대표값`` 오름차순.
    """
    st = resolve_stat(cfg, stat)
    periods = _forecast_periods(cfg)
    detail: List[dict] = []
    select: List[dict] = []
    if not periods:
        return pd.DataFrame(), pd.DataFrame(), st

    # 수원 목록 — 예측 폴더에 실제로 있는 하위 폴더(대시보드 산출 기준).
    sources: List[str] = []
    for _, _, _, d in periods:
        for s in sorted(p.name for p in d.iterdir() if p.is_dir()):
            if s not in sources:
                sources.append(s)

    for src in sources:
        for se in SEASONS:
            cands = []
            for label, yr, s2, d in periods:
                if s2 != se:
                    continue
                got = _read_period_outlet(d / src, st)
                if got:
                    got.update({"label": label, "year": yr})
                    cands.append(got)
            if not cands:
                continue
            # 확정 규칙: 비정상 개월수 ↓ → 최저 대표값 ↑.
            # 그 둘이 **완전히 같을 때만** 비정상 위험확률 ↓ 으로 가른다 — 팔라우
            # Ngerimel 처럼 중앙값이 만수(23.0)에 고정되면 앞의 두 값이 전 기간
            # 동점이 되어 연도순 첫 후보가 뽑히는 문제를 막는다(임의 선택 금지).
            cands.sort(key=lambda c: (-c["n_below_watch"], c["min_value"], -c["risk_pct"]))
            best = cands[0]
            tied = [c for c in cands
                    if c["n_below_watch"] == best["n_below_watch"]
                    and abs(c["min_value"] - best["min_value"]) < 1e-12]
            tiebreak = "비정상확률" if len(tied) > 1 else ""
            nw, ww, wc = best["thr"]
            unit = "ft" if str(best["variable"]).endswith("_ft") else "m3/s"
            for i, m in enumerate(best["months"], 1):
                detail.append({
                    "source": src, "variable": best["variable"], "unit": unit,
                    "season": se, "selected_period": best["label"],
                    "month_index": i, "ym": m["ym"], "month": m["month"],
                    "stat": st, "value": round(m["value"], 6), "stage": m["stage"],
                    "prob_of_stage_pct": m["prob_of_stage"],
                    **{f"prob_{s.lower()}_pct": m.get(f"prob_{s.lower()}", float("nan"))
                       for s in STAGES},
                    "most_likely": m["most_likely"], "n_members": m["n_members"],
                    "thr_normal_watch": nw, "thr_watch_warning": ww,
                    "thr_warning_crisis": wc,
                })
            ranked = "; ".join(
                f"{c['label']}(비정상{c['n_below_watch']}/최저{c['min_value']:.4g}"
                f"/위험{c['risk_pct']:.1f}%)" for c in cands[:3])
            select.append({
                "source": src, "variable": best["variable"], "unit": unit,
                "season": se, "selected_period": best["label"],
                "stat": st,
                "n_months_below_watch": best["n_below_watch"],
                "min_value": round(best["min_value"], 6),
                "mean_value": round(best["mean_value"], 6),
                "risk_nonnormal_pct": round(best["risk_pct"], 2),
                "n_tied_by_rule": len(tied), "tiebreak": tiebreak,
                # 3개월 중 **가장 나쁜** 단계(STAGES 뒤쪽이 더 나쁘다).
                "worst_stage": max((m["stage"] for m in best["months"]),
                                   key=lambda s: STAGES.index(s) if s in STAGES else -1,
                                   default=""),
                "n_candidates": len(cands),
                "year_range": f"{min(c['year'] for c in cands)}~{max(c['year'] for c in cands)}",
                "rule": "비정상 개월수 우선 → 최저값",
                "top3": ranked,
            })
    return pd.DataFrame(detail), pd.DataFrame(select), st


# ─────────────────────────────────────────────────────────────────────────────
#  오케스트레이션
# ─────────────────────────────────────────────────────────────────────────────
def build_worst(cfg, *, stat: Optional[str] = None, min_coverage: float = 0.90,
                observed: bool = True, forecast: bool = True, quiet: bool = False
                ) -> Dict[str, str]:
    """① ② 를 산출해 ``4_drought_risk/worst`` 에 저장. 매번 덮어써 **갱신**한다."""
    out = worst_dir(cfg)
    made: Dict[str, str] = {}

    def say(*a):
        if not quiet:
            print(*a)

    if observed:
        df, log = build_observed_monthly_worst(cfg, min_coverage=min_coverage)
        f1 = out / "worst_observed_monthly.csv"
        f2 = out / "worst_observed_reliability.txt"
        if not df.empty:
            df.to_csv(f1, index=False, encoding="utf-8-sig")
            made["observed_monthly"] = str(f1)
            say(f"[① 관측 월별 최저] 수원 {df['source'].nunique()}개 × "
                f"{len(df)}행 → {f1}")
            relaxed = int((df["selection"] == "relaxed").sum())
            if relaxed:
                say(f"    자료부족으로 차선 대체한 월 {relaxed}건 — {f2.name} 참조")
        else:
            say("[① 관측 월별 최저] 산출 없음 — 관측 일자료가 없거나 수원과 짝이 없다")
        f2.write_text("\n".join(log) + "\n", encoding="utf-8")
        made["observed_reliability"] = str(f2)

    if forecast:
        det, sel, st = build_forecast_seasonal_worst(cfg, stat=stat)
        if not det.empty:
            f3 = out / "worst_forecast_seasonal.csv"
            f4 = out / "worst_forecast_selection.csv"
            det.to_csv(f3, index=False, encoding="utf-8-sig")
            sel.to_csv(f4, index=False, encoding="utf-8-sig")
            made["forecast_seasonal"] = str(f3)
            made["forecast_selection"] = str(f4)
            say(f"[② 예측 계절별 최악] 통계 {st} · 수원 {det['source'].nunique()}개 × "
                f"계절 {sel['season'].nunique()}종 → {f3}")
            say(f"    선정 근거(후보 순위 포함) → {f4}")
        else:
            say("[② 예측 계절별 최악] 산출 없음 — 4_drought_risk/forecast 에 "
                "완성된 예측 결과가 없다")
    return made


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="swat_py.drought.worst_scenario",
        description="Worst Scenario — 관측 월별 최저 + 예측 계절별 최악(무변수 CLI)")
    ap.add_argument("--config", default="config/swat_py.yaml",
                    help="swat_py 설정(기본값으로 무변수 실행)")
    ap.add_argument("--stat", choices=["mean", "median"], default=None,
                    help="예측 대표통계 (기본: drought.climatology_stat)")
    ap.add_argument("--min-coverage", type=float, default=0.90,
                    help="① 월 유효일 비율 하한 (기본 0.90)")
    ap.add_argument("--observed-only", action="store_true", help="① 만 산출")
    ap.add_argument("--forecast-only", action="store_true", help="② 만 산출")
    args = ap.parse_args(argv)
    from swat_py.config import load_config
    cfg = load_config(args.config)
    build_worst(cfg, stat=args.stat, min_coverage=args.min_coverage,
                observed=not args.forecast_only, forecast=not args.observed_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
