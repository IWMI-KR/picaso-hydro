"""가뭄위험 대시보드 데이터 오케스트레이션 (outlet × ①~⑤) → 4_drought_risk/forecast/{period}.

단계
  0. base 준비: calibrated(검보정 완료·지역화 포함) + time.sim(예측기간, 관측 선행) → 앙상블용
  1. ① 평년 + ④ FDC : 장기 기후 CSV(channel_daily_YYYY.csv)
  2. ② 관측/모의    : 장기 기후 CSV의 예측 직전월(예 2016 Jan–Mar) 모의(관측기상)
  3. ③⑤ 예측 앙상블 : ensemble_flow.run_ensemble → 채널별 [member×month]
       → SWAT+ 결과는 3_swatplus/forecast/{period}/ensemble_monthly_flow.csv 로 저장
       → 평균/분위·단계확률은 4_drought_risk/forecast/{period}/{outlet}/ 로 저장
  4. outlet별 series.csv/thresholds.csv/stage_prob.csv/dashboard.json + summary.csv 저장

CLI: python -m swat_py.drought.dashboard_data --forecast 2016_AMJ [--members 100] [--demo N]
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from swat_py.drought.climatology import (
    climatology_daily_path, load_daily_flow, outlet_climatology_and_thresholds,
)
from swat_py.drought.fdc import stage_thresholds
from swat_py.drought.ensemble_flow import OUTLETS, run_ensemble
from swat_py.drought.stages import stage_probabilities4

SEASON_MONTHS = {"JFM": [1, 2, 3], "FMA": [2, 3, 4], "MAM": [3, 4, 5], "AMJ": [4, 5, 6],
                 "MJJ": [5, 6, 7], "JJA": [6, 7, 8], "JAS": [7, 8, 9], "ASO": [8, 9, 10],
                 "SON": [9, 10, 11], "OND": [10, 11, 12], "NDJ": [11, 12, 1], "DJF": [12, 1, 2]}
QLEVELS = [0.05, 0.25, 0.50, 0.75, 0.95]


def _forecast_station(cfg) -> str:
    """obs_weather_std/stations-acidwg.csv 의 (주) 스테이션 ID — 예측 상세화 기준."""
    csv = Path(cfg.ObsDayDir) / "stations-acidwg.csv"
    df = pd.read_csv(csv)
    idcol = "ID" if "ID" in df.columns else df.columns[min(3, df.shape[1] - 1)]
    return str(df[idcol].iloc[0])


def _member_dir(cfg, fyear: int, season: str) -> Path:
    """예측 연·계절의 앙상블 멤버 폴더 — hindcast(과거·검증) 우선, 없으면 operational(이후).

    acidwg 는 hindcast 연도는 1_acidwg/hindcast/, 이후(operational) 연도는
    1_acidwg/operational/ 아래에 member_XXXX 를 둔다. 실제 멤버가 있는 폴더를 자동 선택.
    """
    dc = getattr(cfg, "Drought", None)
    base = Path(cfg.PrjDir) / "1_acidwg"
    cands = []
    if dc and dc.ensemble_root:                       # 설정 우선(있으면)
        cands.append(Path(dc.ensemble_root) / str(fyear) / season)
    cands += [base / "hindcast" / str(fyear) / season,
              base / "operational" / str(fyear) / season]
    for d in cands:
        if d.is_dir() and any(d.glob("member_*")):
            return d
    return cands[-2] if len(cands) >= 2 else cands[-1]   # 기본: hindcast


def prepare_base(cfg, base_dir: Path, fyear: int, months: List[int]) -> None:
    """calibrated(검보정 완료·지역화 포함, 파라미터 baked-in) 복사 + time.sim(웜업 선행 ~
    예측끝월) → 예측 앙상블 base TxtInOut. default+수동적용이 아닌 calibrated 를 그대로 사용."""
    if base_dir.parent.exists():
        # Windows: 삭제지연/읽기전용 대응 — 오류 무시 후 소멸 대기
        shutil.rmtree(base_dir.parent, ignore_errors=True)
        for _ in range(25):
            if not base_dir.parent.exists():
                break
            time.sleep(0.2)
    shutil.copytree(Path(cfg.CalibratedDir), base_dir)
    nyskip = int(cfg.CioNYSKIP)                   # 마스터 warm_up_years (단일 관리)
    start_yr = fyear - nyskip                      # 웜업 nyskip년 → 출력 fyear
    last = pd.Timestamp(fyear, months[-1], 1) + pd.offsets.MonthEnd(0)
    ts = base_dir / "time.sim"
    lines = ts.read_text().splitlines()
    lines[2] = f"       1      {start_yr}       {last.dayofyear}      {fyear}         0"
    ts.write_text("\n".join(lines) + "\n")
    # print.prt nyskip 을 warm_up_years 로 동기화 (출력 시작 = fyear)
    pp = base_dir / "print.prt"
    pl = pp.read_text().splitlines()
    if len(pl) >= 3:
        toks = pl[2].split()
        if toks:
            toks[0] = str(nyskip)
            pl[2] = "  ".join(toks)
            pp.write_text("\n".join(pl) + "\n")
    exe = base_dir / cfg.Executable
    if not exe.is_file():
        shutil.copy2(Path(cfg.DefaultDir) / cfg.Executable, exe)


def _observed_monthly(daily: pd.DataFrame, outlet: str, fyear: int,
                      obs_months: List[int]) -> Dict[int, float]:
    """예측 직전월(관측기상 모의) 월평균 유량."""
    s = daily[["date", outlet]].copy()
    s = s[(s["date"].dt.year == fyear) & (s["date"].dt.month.isin(obs_months))]
    return {int(m): float(v) for m, v in s.groupby(s["date"].dt.month)[outlet].mean().items()}


def build(cfg, forecast: str, *, n_members: int = 100, n_workers: int = 6) -> Dict:
    fyear = int(forecast.split("_")[0]); season = forecast.split("_")[1]
    months = SEASON_MONTHS[season]
    obs_months = [m for m in range(1, months[0]) if m >= 1] or []   # 예측 시작 이전월(동일 연도)
    dc = getattr(cfg, "Drought", None)
    outlets = (dict(dc.outlets) if dc and dc.outlets else OUTLETS)
    station = (dc.forecast_station if (dc and dc.forecast_station)
               else _forecast_station(cfg))
    root = Path(cfg.PrjDir) / "4_drought_risk"
    # 파일명 자동 산출(하드코딩 없음): {syear+warmup}_{eyear}. climatology_csv 명시 시 우선.
    clim_csv = climatology_daily_path(cfg)
    member_dir = _member_dir(cfg, fyear, season)   # hindcast 또는 operational 자동 선택
    out_root = root / "forecast" / forecast         # 4_drought_risk/forecast/{period}
    out_root.mkdir(parents=True, exist_ok=True)
    daily = load_daily_flow(clim_csv)

    # ── 예측 앙상블 (③⑤) ──
    base = root / "scripts" / "_ens_base" / "TxtInOut"
    print(f"[base] 예측 앙상블용 모델 준비 (fyear={fyear}, months={months})")
    prepare_base(cfg, base, fyear, months)
    print(f"[ensemble] {n_members} 멤버 SWAT+ 실행")
    print(f"[ensemble] 멤버 폴더: {member_dir}")
    ens = run_ensemble(base, member_dir,
                       fyear=fyear, months=months, exe_name=cfg.Executable,
                       n_members=n_members, n_workers=n_workers,
                       outlets=outlets, station=station)

    # SWAT+ 앙상블 예측 결과(멤버×월 채널유량) → 3_swatplus/forecast/{period}
    swat_fc = Path(cfg.PrjDir) / "3_swatplus" / "forecast" / forecast
    swat_fc.mkdir(parents=True, exist_ok=True)
    long_rows = []
    for ch_name, mem_df in ens.items():
        for member, row in mem_df.iterrows():
            for month in mem_df.columns:
                long_rows.append({"channel": ch_name, "member": member,
                                  "month": int(month), "flo_m3s": row[month]})
    pd.DataFrame(long_rows).to_csv(swat_fc / "ensemble_monthly_flow.csv",
                                   index=False, encoding="utf-8-sig")
    print(f"[forecast] SWAT+ 앙상블 결과({len(ens)}채널×{n_members}멤버) → {swat_fc}")

    summary_rows = []
    for outlet in outlets.values():
        if outlet not in daily.columns:
            continue
        ct = outlet_climatology_and_thresholds(daily, outlet)
        thr = ct["thresholds"]     # 참조용 유황유량(Q95/Q185/Q275/Q355)
        # 4단계 경계 — 설정(method/values) 기반
        thr_method = dc.threshold_method if dc else "fdc_exceedance"
        thr_values = dc.threshold_values if dc else None
        st = stage_thresholds(daily[outlet].dropna().values, thr_method, thr_values)
        q185, q275, q355 = st["normal_watch"], st["watch_warning"], st["warning_crisis"]
        clim = ct["monthly"].set_index("month")

        obs = _observed_monthly(daily, outlet, fyear, obs_months)
        mem = ens.get(outlet)   # DataFrame [member × month]

        # ① 평년(1~12), ② 관측(직전월), ③ 예측 평균+분위(예측월)
        series = pd.DataFrame({"month": range(1, 13)})
        series["hist_mean"] = series["month"].map(clim["mean"])
        series["observed"] = series["month"].map(obs)
        if mem is not None:
            fmean = mem.mean(axis=0)
            series["forecast_mean"] = series["month"].map(fmean.to_dict())
            for q in QLEVELS:
                series[f"p{int(q*100)}"] = series["month"].map(
                    mem.quantile(q, axis=0).to_dict())
        out_dir = out_root / outlet
        out_dir.mkdir(exist_ok=True)
        series.to_csv(out_dir / "series.csv", index=False, encoding="utf-8-sig")
        tv = list(thr_values) if thr_values else [None, None, None]
        n_ens = int(mem.shape[0]) if mem is not None else 0
        pd.DataFrame([{"method": thr_method,
                       "nw_input": tv[0], "ww_input": tv[1], "wc_input": tv[2],
                       "n_ensemble": n_ens,
                       "normal_watch": q185, "watch_warning": q275, "warning_crisis": q355,
                       **{k: thr[k] for k in ("Q95d", "Q185d", "Q275d", "Q355d")}}]
                     ).to_csv(out_dir / "thresholds.csv", index=False, encoding="utf-8-sig")
        # 원시 앙상블 멤버 유량(member×month) 저장 → 재분류 시 SWAT 재실행 불필요
        if mem is not None:
            mem.rename_axis("member").to_csv(out_dir / "ensemble_members.csv",
                                             encoding="utf-8-sig")

        # ⑤ 단계확률 (예측월) — 4단계(Normal/Watch/Warning/Crisis)
        stage_rows = []
        if mem is not None:
            for m in months:
                if m in mem.columns:
                    sp = stage_probabilities4(mem[m].dropna().values, q185, q275, q355)
                    stage_rows.append({"month": m, **sp})
        pd.DataFrame(stage_rows).to_csv(out_dir / "stage_prob.csv", index=False,
                                        encoding="utf-8-sig")

        # dashboard.json
        (out_dir / "dashboard.json").write_text(json.dumps({
            "outlet": outlet, "forecast": forecast, "months": months,
            "thresholds": {"normal_watch": q185, "watch_warning": q275,
                           "warning_crisis": q355},
            "series": series.where(pd.notna(series), None).to_dict(orient="list"),
            "stages": stage_rows,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

        for sr in stage_rows:
            summary_rows.append({"outlet": outlet, "month": sr["month"],
                                 "most_likely": sr["most_likely"],
                                 "Normal": sr["Normal"], "Watch": sr["Watch"],
                                 "Warning": sr["Warning"], "Crisis": sr["Crisis"]})
        print(f"  ✔ {outlet:<12s} Q275={q275:.4f} Q355={q355:.4f} "
              f"단계={[s['most_likely'] for s in stage_rows]}")

    pd.DataFrame(summary_rows).to_csv(out_root / "summary.csv", index=False,
                                      encoding="utf-8-sig")
    print(f"\n산출물 → {out_root}")
    return {"out_root": str(out_root), "n_outlets": len(outlets)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swat_py.drought.dashboard_data")
    ap.add_argument("--config", default="config/swat_py.yaml")
    ap.add_argument("--forecast", default="2016_AMJ")
    ap.add_argument("--members", type=int, default=100)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--demo", type=int, default=0, help=">0 이면 그 수만큼만(검증)")
    args = ap.parse_args(argv)
    from swat_py.config import load_config
    cfg = load_config(args.config)
    n = args.demo if args.demo else args.members
    res = build(cfg, args.forecast, n_members=n, n_workers=args.workers)
    from swat_py.drought.figure import make_all_figures
    make_all_figures(Path(res["out_root"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
