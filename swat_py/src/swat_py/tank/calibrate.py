"""3단 Tank 모형 관측소별 DDS 검보정 — SWAT+와 동일 관측·기간·목적함수.

run_tank_calibration(cfg):
  1. build_forcing → 유역별 강수·PET·면적
  2. 관측소마다 DDS(NSE, 보정기간)로 Tank 9개 파라미터 최적화
  3. 최적 파라미터로 전기간 모의 → cal/val 지표 → 3_swatplus/calibration-tank/ 저장
     - params/{station}_tank_params.csv
     - results/tank_sim_daily.csv, cal_val_summary.csv, all_runs_{station}.csv
     - results/figures/{station}_cal|val_flow.png (공용 5-패널)

실행: python -m swat_py.tank.calibrate [--config config/swat_py.yaml] [--iters N]
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from swat_py.calibration.optimizer import dds_optimize
from swat_py.calibration.summary import write_all_runs_csv
from swat_py.metrics.performance import calc_all
from swat_py.tank.forcing import build_forcing
from swat_py.tank.model import (
    PARAM_ORDER, TankParams, bounds_from_config, simulate_tank,
)
from swat_py.viz.pub_report import make_report


def _metrics_paired(obs_dates, obs_vals, sim_dates, sim_vals, period=None) -> dict:
    """관측·모의 같은 날짜 매칭 후(선택 기간 필터) 성능지표."""
    obs = pd.DataFrame({"date": pd.to_datetime(obs_dates),
                        "obs": np.asarray(obs_vals, float)})
    sim = pd.DataFrame({"date": pd.to_datetime(sim_dates),
                        "sim": np.asarray(sim_vals, float)})
    obs.loc[obs["obs"] < -50, "obs"] = np.nan
    paired = obs.merge(sim, on="date", how="inner").dropna()
    if period is not None:
        s, e = period
        if s is not None:
            paired = paired[paired["date"] >= pd.Timestamp(s)]
        if e is not None:
            paired = paired[paired["date"] <= pd.Timestamp(e)]
    if len(paired) < 5:
        return {"nse": -999.0, "kge": -999.0, "r2": 0.0,
                "pbias": 999.0, "rmse": 999.0, "rsr": 999.0, "n": len(paired)}
    m = calc_all(paired["obs"].values, paired["sim"].values)
    out = {k: (float(v) if np.isfinite(v) else (-999.0 if k in ("nse", "kge", "r2") else 999.0))
           for k, v in m.items()}
    out["n"] = len(paired)
    return out


def run_tank_calibration(cfg, *, n_iterations: Optional[int] = None) -> Dict:
    tk = cfg.Tank
    n_iter = int(n_iterations or tk.n_iterations)
    # Tank 결과는 SWAT+ 검보정 폴더(3_swatplus/calibration) 옆
    # 3_swatplus/calibration-tank/ 에 저장 (extras.tank_dir 로 재정의 가능).
    out_root = Path(cfg.extras.get("tank_dir", "")) if cfg.extras.get("tank_dir") else \
        Path(cfg.CalibrationDir).parent / "calibration-tank"
    res_dir = out_root / "results"
    par_dir = out_root / "params"
    fig_dir = res_dir / "figures"
    for d in (res_dir, par_dir, fig_dir):
        d.mkdir(parents=True, exist_ok=True)

    cal_period = (cfg.CalPeriodStart or None, cfg.CalPeriodEnd or None)
    val_period = (cfg.ValPeriodStart or None, cfg.ValPeriodEnd or None)
    sim_start = pd.Timestamp(cfg.SimStartDate or "2012-01-01")
    sim_end = pd.Timestamp(cfg.SimEndDate or "2020-12-31")

    forcing, areas = build_forcing(cfg)
    bounds = bounds_from_config(tk.parameters)

    print("=" * 64)
    print(f"  Tank 모형 검보정 — DDS ({n_iter} iter) · PET={tk.pet_method}")
    print(f"  관측소 {len(cfg.Observations)}개 · 보정 {cal_period} · 검증 {val_period}")
    print("=" * 64)

    sim_wide: Dict[str, pd.Series] = {}
    summary_rows = []
    params_rows = []
    fig_index = []

    for obs in cfg.Observations:
        fc = forcing[obs.id]
        fc = fc[(fc["date"] >= sim_start) & (fc["date"] <= sim_end)].reset_index(drop=True)
        area = areas[obs.id]
        obs_df = pd.read_csv(obs.obs_file, parse_dates=["date"])
        oc = obs.obs_column

        def _evaluate(x: np.ndarray) -> float:
            sim = simulate_tank(fc["date"], fc["pcp_mm"], fc["pet_mm"],
                                TankParams.from_vector(x), area)
            m = _metrics_paired(obs_df["date"].values, obs_df[oc].values,
                                sim["date"].values, sim["q_m3s"].values, period=cal_period)
            return m["nse"]

        result = dds_optimize(_evaluate, bounds, n_iterations=n_iter,
                              maximize=True, seed=tk.seed)
        best = TankParams.from_vector(result.best_x)
        sim = simulate_tank(fc["date"], fc["pcp_mm"], fc["pet_mm"], best, area)
        sim_wide[obs.id] = sim.set_index("date")["q_m3s"]

        # 파라미터 저장
        prow = {"station": obs.id, "area_km2": area, "pet_method": tk.pet_method,
                "cal_nse": round(result.best_f, 4), **best.__dict__}
        params_rows.append(prow)
        pd.DataFrame([{"param": k, "value": getattr(best, k),
                       "range_min": bounds[i][0], "range_max": bounds[i][1]}
                      for i, k in enumerate(PARAM_ORDER)]).to_csv(
            par_dir / f"{obs.id}_tank_params.csv", index=False, encoding="utf-8-sig")
        write_all_runs_csv(result.history, list(PARAM_ORDER),
                           res_dir / f"all_runs_{obs.id}.csv")

        # cal/val 지표
        for label, period, pname in (("calibration", cal_period, "calibration"),
                                     ("validation", val_period, "validation")):
            m = _metrics_paired(obs_df["date"].values, obs_df[oc].values,
                                sim["date"].values, sim["q_m3s"].values, period=period)
            summary_rows.append({
                "obs_id": obs.id, "outlet_id": obs.outlet_id, "phase": label,
                "period": f"{period[0]} ~ {period[1]}", "objective": obs.objective,
                "n": m["n"], "nse": round(m["nse"], 4), "kge": round(m["kge"], 4),
                "r2": round(m["r2"], 4), "pbias": round(m["pbias"], 2),
                "rmse": round(m["rmse"], 4),
            })

        # 5-패널 그림 (cal/val)
        daily = (obs_df.set_index("date")[[oc]].rename(columns={oc: "obs"})
                 .join(sim.set_index("date")[["q_m3s"]].rename(columns={"q_m3s": "sim"}),
                       how="outer").sort_index())
        for phase_key, period in (("cal", (*cal_period, "calibration")),
                                  ("val", (*val_period, "validation"))):
            fpath = fig_dir / f"{obs.id}_{phase_key}_{obs.variable}.png"
            r = make_report(obs.id, obs.unit, phase_key, daily.copy(), fpath, period)
            fig_index.append({"station": obs.id, "phase": phase_key,
                              "d_nse": round(r["daily"]["nse"], 3),
                              "m_nse": round(r["monthly"]["nse"], 3), "file": fpath.name})
        print(f"  ✔ {obs.id:<12s} cal NSE={result.best_f:.3f}")

    # wide sim 저장
    wide = pd.DataFrame(sim_wide).reset_index().rename(columns={"index": "date"})
    wide.to_csv(res_dir / "tank_sim_daily.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(summary_rows).to_csv(res_dir / "cal_val_summary.csv",
                                      index=False, encoding="utf-8-sig")
    pd.DataFrame(params_rows).to_csv(par_dir / "all_stations_params.csv",
                                     index=False, encoding="utf-8-sig")
    pd.DataFrame(fig_index).to_csv(res_dir / "pub_report_index.csv",
                                   index=False, encoding="utf-8-sig")
    print(f"\n  결과 → {res_dir}")
    return {"results_dir": str(res_dir), "params_dir": str(par_dir),
            "summary": summary_rows, "sim_daily": str(res_dir / "tank_sim_daily.csv")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swat_py.tank.calibrate")
    ap.add_argument("--config", default="config/swat_py.yaml")
    ap.add_argument("--iters", type=int, default=None, help="DDS 반복수(기본 yaml)")
    args = ap.parse_args(argv)
    from swat_py.config import load_config
    cfg = load_config(args.config)
    run_tank_calibration(cfg, n_iterations=args.iters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
