"""⑥ 3분위(BN·NN·AN) 확률 — 기후예측과 같은 형식의 유량/저수량 전망.

4단계 가뭄단계(Normal·Watch·Warning·Crisis)는 **절대 경계**(FDC Q70/Q90/Q95,
저수량 %, 수위 ft)로 "얼마나 위험한가"를 말한다. 반면 기후예측 현업이 쓰는
3분위는 **평년 분포 안에서의 상대 위치**로 "평년보다 많은가 적은가"를 말한다.
둘은 다른 질문에 답하므로 함께 낸다.

  BN(Below Normal) — 평년 하위 1/3. 평년보다 적은 쪽
  NN(Near Normal)  — 평년 가운데 1/3. 평년과 비슷한 쪽
  AN(Above Normal) — 평년 상위 1/3. 평년보다 많은 쪽

경계(t33·t67)는 평년 산출물의 **같은 달 분포**에서 뽑는다 —
``4_drought_risk/climatology/channel_monthly_{tag}.csv`` (수원별 월 시계열,
1985~2023 이면 달마다 39개 값)의 33.3·66.7 백분위다. 3개월 평균 전망은 같은
계절의 **연도별 3개월 평균** 분포에서 뽑은 경계를 쓴다.

★ 전제(확인 사항): 경계와 예측이 **같은 모형**에서 나온다. 평년은 관측기상으로
  구동한 SWAT+ 모의이고 앙상블도 같은 검보정 SWAT+ 다 — 4단계 경계(FDC)가
  이미 같은 파일을 쓰므로 기준이 일관된다. 관측 유량과 직접 대조한 편의보정은
  하지 않았다.

★ 적용 대상은 **하천 수원만**이다. 저수지(저수량 %·수위 ft)는 3분위를 내지 않는다 —
  저수량은 만수에서 위가 막히고 운영(취수·전환)이 값을 정하므로 '평년 대비 상대
  위치'가 가뭄 정보가 되지 않는다(만수 해가 몰리면 분위 경계 자체가 붙어 버린다).
  저수지는 절대 경계(만수 대비 %·수위 ft)로 보는 4단계 가뭄단계만 쓴다.
  판별은 수원 폴더의 ``thresholds.csv`` 로 하고(is_reservoir_outlet), 건너뛴 사유를
  한 줄로 보고한다.

산출물 (수원 폴더마다)
  tercile_prob.csv        예측월별 BN/NN/AN 확률 + 경계값(t33·t67)   ← 파이 원본
  tercile_prob_season.csv 3개월 평균 1행                             ← 파이 원본
예측연월 폴더에는 summary_tercile.csv·summary_tercile_season.csv 를 모아 둔다.

실행(기존 산출물에 소급 적용 — SWAT 재실행 없음, ensemble_members.csv 를 읽는다)
  python -m swat_py.drought.tercile --forecast 2026_SON
  python -m swat_py.drought.tercile --all          # 모든 예측연월에 일괄 적용
  python -m swat_py.drought.tercile --dashboard-root <폴더> --config config/swat_py.yaml
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

#: 3분위 코드 — 적은 쪽 → 많은 쪽. CSV 열 이름·most_likely 값으로 쓴다.
TERCILES = ("BN", "NN", "AN")

#: 코드 → 영문 full name
TERCILE_LABELS = {"BN": "Below Normal", "NN": "Near Normal", "AN": "Above Normal"}

#: 코드 → 우리말 한 줄 풀이(그림 범례용)
TERCILE_LABELS_KO = {"BN": "평년 하위 1/3", "NN": "평년 중간 1/3", "AN": "평년 상위 1/3"}

#: 색 — 4단계(녹·황·주·적)와 **겹치지 않는** 갈-회-청 발산형.
#:  갈색=적음, 회색=평년 수준, 청색=많음 (기후예측 강수 3분위 관례).
TERCILE_COLORS = {"BN": "#a6611a", "NN": "#9e9e9e", "AN": "#2c7fb8"}

#: 제목 글자색 — 파이 조각 색 그대로 쓰면 회색(NN)이 흰 바탕에서 읽히지 않는다.
TERCILE_TEXT_COLORS = {"BN": "#8c5214", "NN": "#595959", "AN": "#1f6499"}

#: 3분위 경계 백분위
TERCILE_Q = (1.0 / 3.0, 2.0 / 3.0)

#: 경계를 뽑기 위해 필요한 최소 평년 표본 수(연수). 이보다 적으면 경계를 내지 않는다.
MIN_CLIM_SAMPLE = 10


# ── 순수 계산 ────────────────────────────────────────────────────────────────

def tercile_bounds(values) -> Tuple[float, float]:
    """평년 표본 → (t33, t67) 경계. 표본이 MIN_CLIM_SAMPLE 미만이면 (nan, nan).

    >>> t33, t67 = tercile_bounds(range(1, 100))
    >>> round(t33, 1), round(t67, 1)
    (33.7, 66.3)
    >>> tercile_bounds([1, 2, 3])
    (nan, nan)
    """
    v = np.asarray(list(values), dtype=float)
    v = v[~np.isnan(v)]
    if len(v) < MIN_CLIM_SAMPLE:
        return (float("nan"), float("nan"))
    t33, t67 = np.quantile(v, TERCILE_Q)
    return float(t33), float(t67)


def classify_tercile(value: float, t33: float, t67: float) -> str:
    """단일 값 → BN·NN·AN. 경계는 **아래쪽 포함**(value ≤ t33 → BN).

    4단계 ``classify_stage4`` 와 같은 관례다(경계값은 더 건조한 쪽에 넣는다).

    >>> classify_tercile(0.5, 1.0, 2.0)
    'BN'
    >>> classify_tercile(1.0, 1.0, 2.0)
    'BN'
    >>> classify_tercile(1.5, 1.0, 2.0)
    'NN'
    >>> classify_tercile(3.0, 1.0, 2.0)
    'AN'
    """
    if value != value or t33 != t33 or t67 != t67:
        return "NA"
    if value > t67:
        return "AN"
    if value > t33:
        return "NN"
    return "BN"


def tercile_probabilities(values: Sequence[float], t33: float, t67: float) -> Dict:
    """앙상블 값 → BN/NN/AN 확률(%) + 최빈분위.

    동률이면 선언 순서상 첫 항목(BN→NN→AN)을 택한다 — 가뭄 전망에서 덜 안전한
    쪽으로 기울이는 것이 안전하다.

    평년 표본이 모자라 경계가 nan 이면 확률도 nan 이고 most_likely 는 "NA" 다
    — 0% 로 적어 "평년 이하 확률 없음"처럼 보이게 하지 않는다.
    """
    vals = np.asarray(list(values), dtype=float)
    vals = vals[~np.isnan(vals)]
    n = len(vals)
    if n == 0 or t33 != t33 or t67 != t67:
        return {k: float("nan") for k in TERCILES} | {"most_likely": "NA", "n": n}
    counts = {k: 0 for k in TERCILES}
    for v in vals:
        c = classify_tercile(v, t33, t67)
        if c in counts:
            counts[c] += 1
    probs = {k: round(counts[k] / n * 100.0, 1) for k in TERCILES}
    probs["most_likely"] = max(TERCILES, key=lambda k: counts[k])
    probs["n"] = n
    return probs


# ── 평년 표본 ────────────────────────────────────────────────────────────────

def monthly_values(clim: pd.DataFrame, outlet: str) -> pd.Series:
    """평년 wide CSV → ``(연, 월) → 값`` Series.

    ``channel_monthly_{tag}.csv`` 는 이미 월 시계열이지만, 일자료가 들어와도
    같은 결과가 나오도록 (연, 월) 평균으로 모은다.
    """
    s = clim[["date", outlet]].dropna().copy()
    s["date"] = pd.to_datetime(s["date"])
    g = s.groupby([s["date"].dt.year, s["date"].dt.month])[outlet].mean()
    g.index = g.index.set_names(["year", "month"])
    return g


def month_samples(mv: pd.Series) -> Dict[int, np.ndarray]:
    """``(연, 월) → 값`` → ``{달: 연도별 값 배열}`` (달마다 평년 표본)."""
    return {int(m): grp.to_numpy(dtype=float)
            for m, grp in mv.groupby(level="month")}


def season_sample(mv: pd.Series, months: Sequence[int]) -> np.ndarray:
    """계절(3개월) **연도별 평균** 표본 — 해를 넘는 NDJ·DJF 도 올바르게 모은다.

    시작연도마다 ``period_ym`` 으로 (연, 월) 을 풀어 세 달이 **모두 있는** 해만
    쓴다. 기록의 첫 해·마지막 해에서 계절이 잘리면 그 해는 빠진다.
    """
    from swat_py.drought.season import period_ym
    d = {(int(y), int(m)): float(v) for (y, m), v in mv.items()}
    out: List[float] = []
    for y in sorted({y for y, _ in d}):
        keys = [(int(yy), int(mm)) for yy, mm in period_ym(y, months)]
        if all(k in d for k in keys):
            out.append(float(np.mean([d[k] for k in keys])))
    return np.asarray(out, dtype=float)


# ── 행 만들기 ────────────────────────────────────────────────────────────────

def tercile_rows(mem: Optional[pd.DataFrame], months: Sequence[int],
                 mon_ym: Dict[int, str], samples: Dict[int, np.ndarray], *,
                 clim_years: str = "") -> List[Dict]:
    """예측월별 3분위 확률 행. ``mem`` = DataFrame[member × month(정수 열)]."""
    rows: List[Dict] = []
    if mem is None:
        return rows
    for m in months:
        m = int(m)
        if m not in mem.columns:
            continue
        samp = np.asarray(samples.get(m, []), dtype=float)
        t33, t67 = tercile_bounds(samp)
        tp = tercile_probabilities(mem[m].dropna().values, t33, t67)
        rows.append({"month": m, "ym": mon_ym.get(m, ""),
                     **{k: tp[k] for k in TERCILES},
                     "most_likely": tp["most_likely"], "n": tp["n"],
                     "t33": t33, "t67": t67,
                     "clim_n": int(np.sum(~np.isnan(samp))),
                     "clim_years": clim_years})
    return rows


def tercile_season_row(mem: Optional[pd.DataFrame], months: Sequence[int],
                       season: str, sample, *,
                       clim_years: str = "") -> Optional[Dict]:
    """3개월 평균 3분위 확률 1행 — 멤버별 3개월 평균을 계절 평년 분포와 견준다.

    월별 확률의 평균이 아니다. 멤버마다 먼저 3개월 평균을 내고 그 분포를 쓴다
    (``_seasonal_stage_row`` 와 같은 방식).
    """
    if mem is None:
        return None
    cols = [int(m) for m in months if int(m) in mem.columns]
    if not cols:
        return None
    season_vals = mem[cols].mean(axis=1).dropna()
    if not len(season_vals):
        return None
    samp = np.asarray(sample, dtype=float)
    t33, t67 = tercile_bounds(samp)
    tp = tercile_probabilities(season_vals.values, t33, t67)
    return {"season": season, **{k: tp[k] for k in TERCILES},
            "most_likely": tp["most_likely"], "n": tp["n"],
            "t33": t33, "t67": t67,
            "clim_n": int(np.sum(~np.isnan(samp))),
            "clim_years": clim_years}


def write_tercile_csvs(out_dir, rows: List[Dict],
                       season_row: Optional[Dict]) -> List[Path]:
    """``tercile_prob.csv`` + ``tercile_prob_season.csv`` 저장 (파이 원본 CSV)."""
    out_dir = Path(out_dir)
    written: List[Path] = []
    if rows:
        p = out_dir / "tercile_prob.csv"
        pd.DataFrame(rows).to_csv(p, index=False, encoding="utf-8-sig")
        written.append(p)
    if season_row:
        p = out_dir / "tercile_prob_season.csv"
        pd.DataFrame([season_row]).to_csv(p, index=False, encoding="utf-8-sig")
        written.append(p)
    return written


# ── 기존 산출물에 소급 적용 ──────────────────────────────────────────────────

def load_members(out_dir) -> Tuple[Optional[pd.DataFrame], Dict[int, str]]:
    """``ensemble_members.csv`` → (DataFrame[member × month(정수)], {달: "YYYY-MM"}).

    저장된 열 이름은 연-월("2026-09")이다 — 계산은 월 번호 키를 쓰므로 되돌린다.
    """
    p = Path(out_dir) / "ensemble_members.csv"
    if not p.is_file():
        return None, {}
    df = pd.read_csv(p, index_col=0)
    mon_ym: Dict[int, str] = {}
    ren: Dict[str, int] = {}
    for c in df.columns:
        txt = str(c)
        try:
            m = int(txt.split("-")[1]) if "-" in txt else int(txt)
        except (IndexError, ValueError):
            continue
        ren[c] = m
        mon_ym[m] = txt
    if not ren:
        return None, {}
    return df[list(ren)].rename(columns=ren), mon_ym


#: thresholds.csv 의 저수지 판별값 — figure.py 와 같은 기준을 쓴다.
_RESERVOIR_VARIABLES = ("capacity_pct", "water_level_ft")
_RESERVOIR_METHODS = ("capacity_fraction", "pool_fraction", "fill_fraction",
                      "level_fraction", "stage_fraction", "wlevel_fraction",
                      "level_ft", "fixed_level", "stage_ft", "wlevel_ft")


def is_reservoir_outlet(out_dir) -> bool:
    """수원 폴더가 **저수지**인가 — 저수지는 3분위를 내지 않는다(모듈 설명 참조).

    판별 근거는 폴더의 ``thresholds.csv`` 한 줄(variable·method)이다. 파일이
    없으면 판별할 수 없으므로 하천으로 보지 않고 **저수지가 아니다**(False)로
    둔다 — 하천 폴더에는 언제나 이 파일이 있다.
    """
    p = Path(out_dir) / "thresholds.csv"
    if not p.is_file():
        return False
    try:
        thr = pd.read_csv(p).iloc[0]
    except Exception:
        return False
    return (str(thr.get("variable", "")).lower() in _RESERVOIR_VARIABLES
            or str(thr.get("method", "")).lower() in _RESERVOIR_METHODS)


def outlet_monthly_values(cfg, outlet: str, out_dir, *,
                          channel: Optional[pd.DataFrame] = None) -> Optional[pd.Series]:
    """하천 수원의 평년 월 시계열 — ``channel_monthly_{tag}.csv`` 의 해당 열.

    저수지는 3분위 대상이 아니므로 평년 시계열도 읽지 않는다(``None``).
    평년 파일에 열이 없는 하천(이름 불일치 등)도 ``None`` — 호출부가 사유를
    적어 건너뛴다.
    """
    if channel is not None and outlet in channel.columns:
        return monthly_values(channel, outlet)
    return None


def build_terciles(cfg, forecast: str, *, dashboard_root=None,
                   make_figure: bool = True, verbose: bool = True) -> Dict:
    """예측연월 폴더의 수원마다 3분위 CSV(+파이)를 만든다 — SWAT 재실행 없음.

    평년 분포는 설정의 climatology 산출물에서 읽고, 예측 분포는 각 수원 폴더에
    저장된 ``ensemble_members.csv`` 를 쓴다.

    ``verbose=False`` 면 수원별 한 줄 출력을 생략한다(--all 일괄 실행용).
    """
    from swat_py.drought.climatology import (
        climatology_daily_path, climatology_tag, load_daily_flow,
    )
    from swat_py.drought.season import season_months

    season = str(forecast).split("_")[1] if "_" in str(forecast) else ""
    months = season_months(season) if season else []
    out_root = (Path(dashboard_root) if dashboard_root
                else Path(cfg.PrjDir) / "4_drought_risk" / "forecast" / forecast)
    if not out_root.is_dir():
        raise SystemExit(f"대시보드 폴더 없음: {out_root}\n"
                         f"  → 먼저 dashboard_data.build(cfg, '{forecast}') 로 생성하세요.")
    clim_csv = climatology_daily_path(cfg)
    channel = load_daily_flow(clim_csv) if Path(clim_csv).is_file() else None
    years = climatology_tag(cfg)

    rows_all: List[Dict] = []
    season_all: List[Dict] = []
    skipped: List[tuple] = []
    n_ok = 0
    for d in sorted(p for p in out_root.iterdir() if p.is_dir()):
        outlet = d.name
        if is_reservoir_outlet(d):
            # 저수지는 설계상 제외 — 만수에서 막히고 운영이 값을 정해 '평년 대비
            # 상대 위치'가 가뭄 정보가 되지 않는다. 4단계 가뭄단계만 쓴다.
            skipped.append((outlet, "저수지 — 3분위 미적용(4단계 가뭄단계만 사용)"))
            continue
        mem, mon_ym = load_members(d)
        if mem is None:
            skipped.append((outlet, "ensemble_members.csv 없음"))
            continue
        mv = outlet_monthly_values(cfg, outlet, d, channel=channel)
        if mv is None or not len(mv):
            skipped.append((outlet, "평년 월 시계열 없음(3분위 경계 산정 불가)"))
            continue
        ms = months or sorted(int(c) for c in mem.columns)
        rows = tercile_rows(mem, ms, mon_ym, month_samples(mv), clim_years=years)
        srow = (tercile_season_row(mem, ms, season, season_sample(mv, ms),
                                   clim_years=years) if season else None)
        write_tercile_csvs(d, rows, srow)
        if make_figure:
            from swat_py.drought.figure import make_tercile_pie
            make_tercile_pie(d)
        for r in rows:
            rows_all.append({"outlet": outlet, "ym": r["ym"], "month": r["month"],
                             "most_likely": r["most_likely"],
                             **{k: r[k] for k in TERCILES}})
        if srow:
            season_all.append({"outlet": outlet, "season": srow["season"],
                               "most_likely": srow["most_likely"],
                               **{k: srow[k] for k in TERCILES}})
        n_ok += 1
        if verbose:
            print(f"  ✔ {outlet:<12s} 3분위={[r['most_likely'] for r in rows]}"
                  + (f" / 3개월평균={srow['most_likely']}" if srow else ""))

    if rows_all:
        pd.DataFrame(rows_all).to_csv(out_root / "summary_tercile.csv", index=False,
                                      encoding="utf-8-sig")
    if season_all:
        pd.DataFrame(season_all).to_csv(out_root / "summary_tercile_season.csv",
                                        index=False, encoding="utf-8-sig")
    if verbose:
        for outlet, why in skipped:
            print(f"  ⚠ {outlet:<12s} 건너뜀 — {why}")
        print(f"\n3분위(BN·NN·AN) {n_ok} outlet → {out_root}")
    return {"out_root": str(out_root), "n_outlets": n_ok, "skipped": skipped}


def build_terciles_all(cfg, *, make_figure: bool = True) -> Dict:
    """``4_drought_risk/forecast`` 아래 **모든 예측연월 폴더**에 3분위를 적용한다.

    폴더 이름에서 계절을 떼어 쓴다(초기조건 꼬리표가 붙은 폴더도 계절은 같다).
    아는 계절이 아니면 건너뛰고 사유를 모아 끝에 보고한다. 이미 만들어 둔
    폴더도 다시 계산해 덮어쓴다(멱등).
    """
    from swat_py.drought.season import SEASON_MONTHS

    root = Path(cfg.PrjDir) / "4_drought_risk" / "forecast"
    if not root.is_dir():
        raise SystemExit(f"예측 폴더 없음: {root}")
    periods = sorted(d for d in root.iterdir() if d.is_dir())
    done: List[str] = []
    skipped_periods: List[tuple] = []
    skipped_outlets: List[tuple] = []
    n_outlets = 0
    for i, d in enumerate(periods, start=1):
        name = d.name
        season = name.split("_")[1] if "_" in name else ""
        if season not in SEASON_MONTHS:
            skipped_periods.append((name, "예측연월 폴더가 아님(계절 미해석)"))
            continue
        res = build_terciles(cfg, name, dashboard_root=d,
                             make_figure=make_figure, verbose=False)
        n_outlets += res["n_outlets"]
        done.append(name)
        skipped_outlets += [(name, o, w) for o, w in res["skipped"]]
        print(f"  [{i:3d}/{len(periods)}] {name:<28s} {res['n_outlets']:2d} outlet"
              + (f"  (건너뜀 {len(res['skipped'])})" if res["skipped"] else ""),
              flush=True)

    print(f"\n3분위(BN·NN·AN) 일괄 적용 완료 — 예측연월 {len(done)}개 / "
          f"수원 {n_outlets}개 → {root}")
    if skipped_periods:
        print(f"  ⚠ 건너뛴 폴더 {len(skipped_periods)}개:")
        for name, why in skipped_periods:
            print(f"      · {name} — {why}")
    if skipped_outlets:
        reasons: Dict[str, int] = {}
        for _, _, why in skipped_outlets:
            reasons[why] = reasons.get(why, 0) + 1
        print(f"  ⚠ 건너뛴 수원 {len(skipped_outlets)}건:")
        for why, c in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"      · {why} — {c}건")
        for name, outlet, why in skipped_outlets[:20]:
            print(f"      예: {name}/{outlet} — {why}")
    return {"root": str(root), "n_periods": len(done), "n_outlets": n_outlets,
            "skipped_periods": skipped_periods, "skipped_outlets": skipped_outlets}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="swat_py.drought.tercile",
        description="⑥ 3분위(BN·NN·AN) 확률 CSV + 파이 생성 (SWAT 재실행 없음)")
    ap.add_argument("--config", default="config/swat_py.yaml",
                    help="swat_py 설정 (같은 폴더의 picaso-hydro.yaml 공통값 자동 병합)")
    ap.add_argument("--forecast", default=None,
                    help="예측연월 {year}_{season} (기본: config 의 forecast.period)")
    ap.add_argument("--dashboard-root", default=None,
                    help="대상 폴더 직접 지정 (기본: 4_drought_risk/forecast/{period})")
    ap.add_argument("--no-figure", action="store_true", help="CSV만 만들고 그림은 생략")
    ap.add_argument("--all", action="store_true",
                    help="4_drought_risk/forecast 아래 모든 예측연월에 일괄 적용")
    args = ap.parse_args(argv)

    from swat_py.config import load_config
    cfg = load_config(args.config)
    if args.all:
        build_terciles_all(cfg, make_figure=not args.no_figure)
        return 0
    forecast = args.forecast or getattr(cfg.Drought, "forecast", None)
    if not forecast:
        raise SystemExit("예측연월 미지정 — --forecast 또는 config forecast.period 필요")
    build_terciles(cfg, forecast,
                   dashboard_root=Path(args.dashboard_root) if args.dashboard_root else None,
                   make_figure=not args.no_figure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
