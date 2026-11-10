"""PICASO 계절 강수예측(tercile) 분석 — ①최저강수 예측 탐색 ②실제 가뭄 대비 예측성.

입력
----
- 예측: 1_acidwg/picaso/{year}_{season}_picaso.csv (station 91843=라로통가)
        컬럼 station_id,month,variable,AN,NN,BN  (%, 합100). BN↑ = 정상이하(가뭄) 예측.
- 관측: 0_database/obs/weather/{STATION}.csv (date, pcp_mm, …)
        STATION 기본 918430(라로통가). 환경변수 PICASO_OBS_STATION 으로 변경.
  ※ 경로는 PICASO_ROOT(또는 0_database 를 가진 상위 폴더)에서 자동 해석

산출 (reports/06_계절예측_가뭄예측성/)
- forecast_prcp_tidy.csv     : 예측 tercile 정리(대상 연·월 매핑)
- observed_monthly_tercile.csv: 관측 월강수 + 기후terciles(AN/NN/BN)
- file_skill.csv             : 파일별 RPSS·BN예측성·가뭄적중
- driest_forecast.csv        : 최저강수 예측 순위
콘솔에 ①최저강수 예측 ②가뭄 예측성 top3 출력.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd


def _picaso_root() -> Path:
    """프로젝트 루트 — PICASO_ROOT 환경변수 → 0_database 를 가진 상위 폴더 → cwd.

    util_py 가 설치돼 있으면 그 구현을 그대로 쓴다(단일 규칙 유지).
    """
    try:
        from util_py.config import find_project_root
        return find_project_root()
    except Exception:
        import os
        if env := os.environ.get("PICASO_ROOT"):
            return Path(env)
        cwd = Path.cwd().resolve()
        for parent in [cwd, *cwd.parents]:
            if (parent / "0_database").is_dir():
                return parent
        return cwd


#: 대상 관측소 — 환경변수 PICASO_OBS_STATION 으로 교체 가능 (기본: 라로통가 918430)
STATION = os.environ.get("PICASO_OBS_STATION", "918430")

ROOT = _picaso_root()
PICASO = ROOT / "1_acidwg" / "picaso"
OBS_CSV = ROOT / "0_database" / "obs" / "weather" / f"{STATION}.csv"
OUT = ROOT / "reports" / "06_계절예측_가뭄예측성"
OUT.mkdir(parents=True, exist_ok=True)

CATS = ["BN", "NN", "AN"]          # 건조→습윤 순 (tercile)


# ── 1. 예측 파싱 ─────────────────────────────────────────────────────────────
def parse_forecasts() -> pd.DataFrame:
    rows = []
    for f in sorted(PICASO.glob("*_picaso.csv")):
        if f.stem.startswith("forecast"):        # 샘플/템플릿 제외
            continue
        year_s, season = f.stem.split("_")[0], f.stem.split("_")[1]
        try:
            file_year = int(year_s)
        except ValueError:
            continue
        df = pd.read_csv(f)
        prcp = df[df["variable"] == "prcp"].reset_index(drop=True)
        # 시즌 순서대로 대상 연·월 부여 (월이 감소하면 연도+1: NDJ/DJF 경계)
        yr, prev = file_year, None
        for _, r in prcp.iterrows():
            m = int(r["month"])
            if prev is not None and m < prev:
                yr += 1
            prev = m
            rows.append({
                "file": f.name, "file_year": file_year, "season": season,
                "target_year": yr, "target_month": m,
                "AN": float(r["AN"]), "NN": float(r["NN"]), "BN": float(r["BN"]),
            })
    out = pd.DataFrame(rows)
    out["dry_index"] = out["BN"] - out["AN"]      # ↑ 건조 예측 강도
    return out


# ── 2. 관측 월강수 + 기후 terciles ───────────────────────────────────────────
def observed_monthly_tercile() -> pd.DataFrame:
    df = pd.read_csv(OBS_CSV, parse_dates=["date"])
    df = df[["date", "pcp_mm"]].dropna(subset=["pcp_mm"])
    df["ym"] = df["date"].dt.to_period("M")
    g = df.groupby("ym")["pcp_mm"].agg(pcp_month="sum", nday="count").reset_index()
    g = g[g["nday"] >= 25].copy()                 # 결측 많은 달 제외
    g["year"] = g["ym"].dt.year
    g["month"] = g["ym"].dt.month
    # 월별(1~12) 기후 terciles (33·67 백분위) → merge
    terc = (g.groupby("month")["pcp_month"].quantile([1/3, 2/3])
            .unstack().rename(columns={1/3: "t33", 2/3: "t67"}))
    g = g.merge(terc, left_on="month", right_index=True)
    g["obs_cat"] = np.where(g["pcp_month"] <= g["t33"], "BN",
                    np.where(g["pcp_month"] <= g["t67"], "NN", "AN"))
    return g[["year", "month", "pcp_month", "t33", "t67", "obs_cat"]]


# ── 3. 스킬 지표 ─────────────────────────────────────────────────────────────
def _rps(fcst_probs, obs_cat):
    """Ranked Probability Score (categories 건조→습윤). 낮을수록 좋음."""
    p = np.array(fcst_probs, float) / 100.0
    o = np.array([1.0 if c == obs_cat else 0.0 for c in CATS])
    Pc, Oc = np.cumsum(p), np.cumsum(o)
    return float(np.sum((Pc - Oc) ** 2))          # K-1 항 (마지막은 0)

_RPS_CLIM = None
def _rps_clim(obs_cat):
    return _rps([100/3, 100/3, 100/3], obs_cat)


def main() -> int:
    fc = parse_forecasts()
    obs = observed_monthly_tercile()
    fc.to_csv(OUT / "forecast_prcp_tidy.csv", index=False, encoding="utf-8-sig")
    obs.to_csv(OUT / "observed_monthly_tercile.csv", index=False, encoding="utf-8-sig")

    # ── ① 최저강수 예측 ─────────────────────────────────────────────
    driest_month = fc.sort_values(["BN", "dry_index"], ascending=False)
    driest_season = (fc.groupby(["file", "file_year", "season"])
                     .agg(mean_BN=("BN", "mean"), mean_AN=("AN", "mean"),
                          mean_dry=("dry_index", "mean"), n=("BN", "size"))
                     .reset_index().sort_values("mean_BN", ascending=False))
    driest_season.to_csv(OUT / "driest_forecast.csv", index=False, encoding="utf-8-sig")

    print("=" * 70)
    print("① 가장 강수량이 적게 예측된 경우 (BN=정상이하 확률 최대)")
    print("=" * 70)
    top_m = driest_month.iloc[0]
    print(f"  [월 단위 최강 가뭄예측] {top_m['file']}  "
          f"대상 {int(top_m['target_year'])}-{int(top_m['target_month']):02d}  "
          f"AN/NN/BN = {top_m['AN']:.0f}/{top_m['NN']:.0f}/{top_m['BN']:.0f}%")
    print("  월단위 상위 5:")
    for _, r in driest_month.head(5).iterrows():
        print(f"    {r['file']:<24s} {int(r['target_year'])}-{int(r['target_month']):02d} "
              f"BN={r['BN']:.0f}% AN={r['AN']:.0f}% (dry_idx={r['dry_index']:.0f})")
    print("  [시즌(파일) 단위 최강 가뭄예측] 평균 BN 상위 5:")
    for _, r in driest_season.head(5).iterrows():
        print(f"    {r['file']:<24s} 평균BN={r['mean_BN']:.1f}% (dry={r['mean_dry']:.1f})")

    # ── ② 실제 가뭄 대비 예측성 ─────────────────────────────────────
    m = fc.merge(obs, left_on=["target_year", "target_month"],
                 right_on=["year", "month"], how="inner")
    m["fcst_cat"] = m[["BN", "NN", "AN"]].idxmax(axis=1)
    m["rps"] = m.apply(lambda r: _rps([r.BN, r.NN, r.AN], r.obs_cat), axis=1)
    m["rps_clim"] = m["obs_cat"].apply(_rps_clim)
    m["obs_dry"] = (m["obs_cat"] == "BN")
    m["dry_hit"] = m["obs_dry"] & (m["fcst_cat"] == "BN")

    # 파일별 집계
    fs = (m.groupby(["file", "file_year", "season"])
          .agg(n=("rps", "size"), obs_dry_months=("obs_dry", "sum"),
               dry_hits=("dry_hit", "sum"), mean_BN=("BN", "mean"),
               mean_rps=("rps", "mean"), mean_rps_clim=("rps_clim", "mean"),
               mean_obs_pcp=("pcp_month", "mean"))
          .reset_index())
    fs["RPSS"] = 1 - fs["mean_rps"] / fs["mean_rps_clim"]       # >0 = 기후보다 우수
    # 실제 가뭄 시즌 = 관측 BN 이 과반 (n의 절반 이상)
    fs["is_drought"] = fs["obs_dry_months"] >= np.ceil(fs["n"] / 2)
    # 가뭄 예측성 점수: 실제가뭄 & 높은 RPSS & 가뭄월 적중
    fs["drought_skill"] = np.where(
        fs["is_drought"], fs["RPSS"] + 0.05 * fs["dry_hits"], np.nan)
    fs = fs.sort_values(["is_drought", "drought_skill"], ascending=[False, False])
    fs.to_csv(OUT / "file_skill.csv", index=False, encoding="utf-8-sig")

    drought_files = fs[fs["is_drought"]].sort_values("drought_skill", ascending=False)
    print()
    print("=" * 70)
    print("② 실제 가뭄(관측 BN 과반) 시즌 중 예측성 높은 파일")
    print("=" * 70)
    print(f"  검증가능 파일 {len(fs)}개 · 실제가뭄 시즌 {int(fs['is_drought'].sum())}개")
    print("  [가뭄 예측성 top] file | RPSS | 가뭄월적중 | 평균BN% | 관측월강수(mm)")
    for _, r in drought_files.head(8).iterrows():
        print(f"    {r['file']:<24s} RPSS={r['RPSS']:+.2f} "
              f"hit={int(r['dry_hits'])}/{int(r['n'])} BN={r['mean_BN']:.0f}% "
              f"obsP={r['mean_obs_pcp']:.0f}")
    print(f"\n  → 산출물 저장: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
