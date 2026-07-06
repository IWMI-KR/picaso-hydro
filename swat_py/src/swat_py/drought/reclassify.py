"""기존 대시보드 산출물을 4단계(Normal/Watch/Warning/Crisis)로 **재분류** — SWAT 재실행 없음.

이미 저장된 앙상블 유량 분위(series.csv 의 p5..p95)에서 경험적 CDF로 4단계 확률을
재구성하고, ④ 임계선에 Q185(Normal–Watch)를 추가한 뒤 ⑤ 표·게이지·그림을 4단계로 갱신한다.
임계 method/values 변경 후 전량 재실행 없이 단계 경계만 다시 적용할 때 쓴다.

경로는 `cfg.PrjDir`/climatology_daily_path(cfg) 로 산출되어 OS·설치 위치에 무관하다.
대상 폴더 기본값은 dashboard_data.build 산출 위치와 동일: `4_drought_risk/forecast/{period}`.

실행: python -m swat_py.drought.reclassify [--forecast 2016_AMJ] [--config config/swat_py.yaml]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from swat_py.drought.climatology import (
    climatology_daily_path,
    load_daily_flow,
    outlet_climatology_and_thresholds,
)
from swat_py.drought.fdc import stage_thresholds
from swat_py.drought.figure import make_outlet_figure, make_stage_gauges
from swat_py.drought.stages import STAGES4, stage_probabilities4_from_quantiles

QCOLS = [("p5", 0.05), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p95", 0.95)]


def reclassify_stages(cfg, forecast: str, *, n_ensemble: int = 0,
                      dashboard_root: Optional[Path] = None) -> Dict[str, str]:
    """대상 대시보드 폴더의 outlet 들을 4단계로 재분류하고 산출물을 갱신한다.

    반환: {"out_root": ..., "n_outlets": N} 경로 dict.
    """
    prj = Path(cfg.PrjDir)
    dc = cfg.Drought
    clim = load_daily_flow(dc.climatology_csv or climatology_daily_path(cfg))
    out_root = (Path(dashboard_root) if dashboard_root
                else prj / "4_drought_risk" / "forecast" / forecast)
    if not out_root.is_dir():
        raise SystemExit(f"대시보드 폴더 없음: {out_root}\n"
                         f"  → 먼저 dashboard_data.build(cfg, '{forecast}') 로 생성하세요.")

    summary = []
    for outlet_dir in sorted(p for p in out_root.iterdir() if p.is_dir()):
        outlet = outlet_dir.name
        series_f = outlet_dir / "series.csv"
        if outlet not in clim.columns or not series_f.is_file():
            continue
        thr = outlet_climatology_and_thresholds(clim, outlet)["thresholds"]
        st = stage_thresholds(clim[outlet].dropna().values,
                              dc.threshold_method, dc.threshold_values)
        q185, q275, q355 = st["normal_watch"], st["watch_warning"], st["warning_crisis"]
        series = pd.read_csv(series_f)

        # 예측월 = p5 가 있는 행
        fc = series.dropna(subset=["p5"])
        stage_rows = []
        for _, r in fc.iterrows():
            sp = stage_probabilities4_from_quantiles(
                [lv for _, lv in QCOLS], [r[c] for c, _ in QCOLS], q185, q275, q355)
            stage_rows.append({"month": int(r["month"]), **sp})
        pd.DataFrame(stage_rows).to_csv(outlet_dir / "stage_prob.csv", index=False,
                                        encoding="utf-8-sig")
        # ④ thresholds (설정 method + 입력값 + 앙상블수 + 경계유량 + 참조 유황유량)
        old = (pd.read_csv(outlet_dir / "thresholds.csv").iloc[0].to_dict()
               if (outlet_dir / "thresholds.csv").is_file() else {})
        n_ens = n_ensemble or int(old.get("n_ensemble", 0) or 0)
        tv = list(dc.threshold_values)
        pd.DataFrame([{"method": dc.threshold_method,
                       "nw_input": tv[0], "ww_input": tv[1], "wc_input": tv[2],
                       "n_ensemble": n_ens,
                       "normal_watch": q185, "watch_warning": q275, "warning_crisis": q355,
                       **{k: thr[k] for k in ("Q95d", "Q185d", "Q275d", "Q355d")}}]
                     ).to_csv(outlet_dir / "thresholds.csv", index=False, encoding="utf-8-sig")
        # dashboard.json 갱신
        dj = json.loads((outlet_dir / "dashboard.json").read_text(encoding="utf-8"))
        dj["thresholds"] = {"normal_watch": q185, "watch_warning": q275, "warning_crisis": q355}
        dj["stages"] = stage_rows
        (outlet_dir / "dashboard.json").write_text(
            json.dumps(dj, ensure_ascii=False, indent=1), encoding="utf-8")
        # 그림 재생성
        make_outlet_figure(outlet_dir)
        make_stage_gauges(outlet_dir)
        for sr in stage_rows:
            summary.append({"outlet": outlet, "month": sr["month"],
                            "most_likely": sr["most_likely"],
                            **{s: sr[s] for s in STAGES4}})
        print(f"  ✔ {outlet:<12s} {[s['most_likely'] for s in stage_rows]}")

    pd.DataFrame(summary).to_csv(out_root / "summary.csv", index=False, encoding="utf-8-sig")
    print(f"\n4단계 재분류 완료 → {out_root}")
    return {"out_root": str(out_root), "n_outlets": len(summary)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swat_py.drought.reclassify",
                                 description="대시보드 산출물 4단계 재분류(SWAT 재실행 없음)")
    ap.add_argument("--config", default="config/swat_py.yaml")
    ap.add_argument("--forecast", default=None,
                    help="예측연월 (기본: config 의 forecast.period)")
    ap.add_argument("--n-ensemble", type=int, default=0,
                    help="앙상블 멤버 수(레전드 표기용). 0이면 기존 값 유지")
    ap.add_argument("--dashboard-root", default=None,
                    help="대상 대시보드 폴더(기본: 4_drought_risk/forecast/{period})")
    args = ap.parse_args(argv)
    from swat_py.config import load_config
    cfg = load_config(args.config)
    forecast = args.forecast or getattr(cfg.Drought, "forecast", None)
    if not forecast:
        raise SystemExit("예측연월 미지정 — --forecast 또는 config forecast.period 필요")
    reclassify_stages(cfg, forecast, n_ensemble=args.n_ensemble,
                      dashboard_root=Path(args.dashboard_root) if args.dashboard_root else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
