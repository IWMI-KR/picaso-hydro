"""저수지 수위 목적 3단 Tank 검보정 — SWAT+와 동일 기간·기상·관측.

기존 `tank.calibrate`(관측 **유량** NSE)와 달리, 저수지(Ngerimel)는 **수위**로 검보정한다:

  Tank 유입 q(mm→m³/s) → 저수지 물수지(유입 − 취수, 여수로 월류·사수위 하한)
    → 저류량 → 수위내용적 곡선 → 수위(MSL) → 관측 수위(staff→MSL, datum offset) 비교.

DDS 로 9개 Tank 파라미터를 최적화(기본 KGE — 관리형 저수지는 변동이 작아 NSE 착시)하고,
결정된 파라미터를 **변경 없이 ngerikiil 유역**(면적·강수만 교체)에 적용해 계산한 유량과
ngerikiil 관측 수위의 **산점도**(rating 관계)를 그린다.

산출: 3_swatplus/calibration-tank/
  params/ngerimel_tank_reservoir_params.csv, results/tank_reservoir_sim_daily.csv,
  results/cal_val_summary.csv, results/all_runs_ngerimel.csv,
  results/figures/ngerimel_wlevel_calib.png,
  transfer/ngerikiil_flow_vs_wlevel.csv + .png

실행: python -m swat_py.tank.reservoir_calibrate [--config ...] [--iters N] [--objective kge|nse]
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from swat_py.calibration.optimizer import dds_optimize
from swat_py.calibration.summary import write_all_runs_csv
from swat_py.io.reservoir import load_stage_storage, simulate_managed_storage
from swat_py.metrics.performance import calc_all
from swat_py.tank.forcing import build_forcing
from swat_py.tank.model import PARAM_ORDER, TankParams, bounds_from_config, simulate_tank

_SPINUP_START = "2016-01-01"        # Tank 스핀업 시작(관측 2018 이전 여유)


def _resolve_obs(cfg, obs_file: str) -> str:
    """obs_file(상대경로면 ObservedDataDir 기준)를 절대경로로 해석."""
    p = Path(obs_file)
    if p.is_absolute():
        return str(p)
    root = getattr(cfg, "ObservedDataDir", "") or str(Path(cfg.PrjDir) / "0_database" / "obs")
    return str(Path(root) / obs_file)


def _reservoir_obs(cfg):
    """cfg.Observations 에서 저수지(reservoir 지정) 수위 관측 → (obs, reservoir_cfg, curve)."""
    for o in cfg.Observations:
        if getattr(o, "variable", "") == "wlevel" and getattr(o, "reservoir", ""):
            rcfg = (getattr(cfg, "Reservoirs", {}) or {}).get(o.reservoir)
            if rcfg and rcfg.stage_storage_file:
                curve = load_stage_storage(rcfg.stage_storage_file, name=o.reservoir)
                return o, rcfg, curve
    raise RuntimeError("cfg.Observations 에 reservoir 지정 wlevel 관측이 없음")


def _load_obs_msl(obs_file, col, offset) -> pd.DataFrame:
    """관측 수위 CSV → [date, obs_msl].  MSL = 관측값 − datum_offset. staff≤0(센서오류) 제외."""
    df = pd.read_csv(obs_file, parse_dates=["date"])
    v = pd.to_numeric(df[col], errors="coerce")
    df = df[v > 0].copy()
    df["obs_msl"] = pd.to_numeric(df[col], errors="coerce") - float(offset)
    return df[["date", "obs_msl"]].dropna().sort_values("date").reset_index(drop=True)


def _metrics(obs_dates, obs_vals, sim_dates, sim_vals, period=None) -> dict:
    obs = pd.DataFrame({"date": pd.to_datetime(obs_dates), "obs": np.asarray(obs_vals, float)})
    sim = pd.DataFrame({"date": pd.to_datetime(sim_dates), "sim": np.asarray(sim_vals, float)})
    paired = obs.merge(sim, on="date", how="inner").dropna()
    if period is not None:
        s, e = period
        if s: paired = paired[paired["date"] >= pd.Timestamp(s)]
        if e: paired = paired[paired["date"] <= pd.Timestamp(e)]
    if len(paired) < 5:
        return {"nse": -999.0, "kge": -999.0, "r2": 0.0, "pbias": 999.0, "rmse": 999.0, "n": len(paired)}
    m = calc_all(paired["obs"].values, paired["sim"].values)
    out = {k: (float(v) if np.isfinite(v) else (-999.0 if k in ("nse", "kge", "r2") else 999.0))
           for k, v in m.items()}
    out["n"] = len(paired)
    return out


def _reservoir_level(sim_q: pd.DataFrame, *, curve, full_m3, dead_m3, withdrawal_m3s,
                     init_m3, obs_start) -> pd.DataFrame:
    """Tank 유량(q_m3s) → 저수지 물수지 → 수위(MSL) 시계열 (관측시작 이후만)."""
    q = sim_q[sim_q["date"] >= pd.Timestamp(obs_start)].reset_index(drop=True)
    rd = pd.DataFrame({"date": q["date"], "flo_in": q["q_m3s"].to_numpy() * 86400.0})
    st = simulate_managed_storage(rd, withdrawal_m3s=withdrawal_m3s, cap_m3=full_m3,
                                  dead_m3=dead_m3, init_m3=init_m3, use_losses=False)
    lvl = np.asarray(curve.storage_to_stage(st["storage_m3"].to_numpy()), float)
    return pd.DataFrame({"date": st["date"], "level_msl": lvl,
                         "storage_m3": st["storage_m3"].to_numpy(),
                         "storage_pct": st["storage_m3"].to_numpy() / full_m3 * 100.0,
                         "inflow_m3s": q["q_m3s"].to_numpy()})


def run_tank_reservoir_calibration(cfg, *, n_iterations: Optional[int] = None,
                                   objective: str = "kge",
                                   transfer_to: str = "ngerikiil") -> Dict:
    tk = cfg.Tank
    n_iter = int(n_iterations or tk.n_iterations)
    out_root = Path(cfg.CalibrationDir).parent / "calibration-tank"
    res_dir, par_dir = out_root / "results", out_root / "params"
    fig_dir, tr_dir = res_dir / "figures", out_root / "transfer"
    for d in (res_dir, par_dir, fig_dir, tr_dir):
        d.mkdir(parents=True, exist_ok=True)

    cal_period = (cfg.CalPeriodStart or None, cfg.CalPeriodEnd or None)
    val_period = (cfg.ValPeriodStart or None, cfg.ValPeriodEnd or None)
    obs_o, rcfg, curve = _reservoir_obs(cfg)
    full = float(curve.stage_to_storage(rcfg.spillway_ft))
    dead = float(curve.stage_to_storage(rcfg.bottom_ft))
    wdr = float(rcfg.withdrawal_m3s or 0.0)
    offset = float(rcfg.obs_datum_offset_ft or 0.0)

    forcing, areas = build_forcing(cfg)
    fc = forcing[obs_o.id]
    fc = fc[fc["date"] >= pd.Timestamp(_SPINUP_START)].reset_index(drop=True)
    area = areas[obs_o.id]
    bounds = bounds_from_config(tk.parameters)

    obs = _load_obs_msl(_resolve_obs(cfg, obs_o.obs_file), obs_o.obs_column, offset)
    obs_start = obs["date"].min()
    init_m3 = float(curve.stage_to_storage(float(obs.iloc[0]["obs_msl"])))

    print("=" * 66)
    print(f"  Tank 저수지 수위 검보정 (Ngerimel) — DDS {n_iter} iter · 목적 {objective.upper()}")
    print(f"  면적 {area} km² · 취수 {wdr} m³/s · 초기수위 {obs.iloc[0]['obs_msl']:.1f}ft(MSL)")
    print(f"  보정 {cal_period} · 검증 {val_period} · PET {tk.pet_method}")
    print("=" * 66)

    maximize = objective in ("kge", "nse", "r2")

    def _sim(x):
        s = simulate_tank(fc["date"], fc["pcp_mm"], fc["pet_mm"], TankParams.from_vector(x), area)
        return _reservoir_level(s, curve=curve, full_m3=full, dead_m3=dead,
                                withdrawal_m3s=wdr, init_m3=init_m3, obs_start=obs_start)

    def _evaluate(x):
        m = _sim(x)
        val = _metrics(obs["date"], obs["obs_msl"], m["date"], m["level_msl"], cal_period)[objective]
        return val if maximize else -abs(val)

    result = dds_optimize(_evaluate, bounds, n_iterations=n_iter, maximize=True, seed=tk.seed)
    best = TankParams.from_vector(result.best_x)
    sim = _sim(result.best_x)

    # 관측 병합 저장
    merged = sim.merge(obs, on="date", how="left")
    merged.to_csv(res_dir / "tank_reservoir_sim_daily.csv", index=False, encoding="utf-8-sig")
    write_all_runs_csv(result.history, list(PARAM_ORDER), res_dir / "all_runs_ngerimel.csv")
    pd.DataFrame([{"param": k, "value": getattr(best, k),
                   "range_min": bounds[i][0], "range_max": bounds[i][1]}
                  for i, k in enumerate(PARAM_ORDER)]).to_csv(
        par_dir / "ngerimel_tank_reservoir_params.csv", index=False, encoding="utf-8-sig")

    # cal/val 지표
    rows = []
    for label, period in (("calibration", cal_period), ("validation", val_period)):
        m = _metrics(obs["date"], obs["obs_msl"], sim["date"], sim["level_msl"], period)
        rows.append({"target": "ngerimel_wlevel_MSL", "phase": label,
                     "period": f"{period[0]} ~ {period[1]}", "objective": objective,
                     "n": m["n"], "nse": round(m["nse"], 4), "kge": round(m["kge"], 4),
                     "r2": round(m["r2"], 4), "pbias": round(m["pbias"], 2), "rmse": round(m["rmse"], 4)})
    pd.DataFrame(rows).to_csv(res_dir / "cal_val_summary.csv", index=False, encoding="utf-8-sig")
    _plot_wlevel(merged, rcfg, cal_period, val_period, rows, fig_dir / "ngerimel_wlevel_calib.png")
    print(f"  ✔ 최적 {objective.upper()}={result.best_f:.3f}  →  params: {best.__dict__}")
    for r in rows:
        print(f"    {r['phase']:<11s} NSE={r['nse']:+.3f} KGE={r['kge']:+.3f} "
              f"PBIAS={r['pbias']:+.1f}% RMSE={r['rmse']:.3f} (n={r['n']})")

    # ── 전이: ngerimel 파라미터 → ngerikiil 유량 vs 관측수위 산점도 ──
    transfer = _transfer_scatter(cfg, best, forcing, areas, transfer_to, tr_dir)

    print(f"\n  결과 → {out_root}")
    return {"results_dir": str(res_dir), "params": best.__dict__, "cal_val": rows,
            "transfer": transfer}


def _transfer_scatter(cfg, params: TankParams, forcing, areas, target: str, tr_dir: Path) -> Dict:
    """ngerimel 파라미터를 target(ngerikiil) 유역에 그대로 적용 → 유량 vs 관측수위 산점도+CSV."""
    obs_o = next((o for o in cfg.Observations if o.id == target), None)
    if obs_o is None or target not in forcing:
        print(f"  [전이] '{target}' 관측/forcing 없음 — 건너뜀")
        return {}
    fc = forcing[target]
    fc = fc[fc["date"] >= pd.Timestamp(_SPINUP_START)].reset_index(drop=True)
    sim = simulate_tank(fc["date"], fc["pcp_mm"], fc["pet_mm"], params, areas[target])
    obs = pd.read_csv(_resolve_obs(cfg, obs_o.obs_file), parse_dates=["date"])
    oc = obs_o.obs_column
    obs = obs[pd.to_numeric(obs[oc], errors="coerce") > 0][["date", oc]].rename(columns={oc: "obs_wlevel_ft"})
    m = sim[["date", "q_m3s"]].merge(obs, on="date", how="inner").dropna()
    csv = tr_dir / f"{target}_flow_vs_wlevel.csv"
    m.to_csv(csv, index=False, encoding="utf-8-sig")
    r = float(np.corrcoef(m["q_m3s"], m["obs_wlevel_ft"])[0, 1]) if len(m) > 2 else float("nan")
    rho = (m["q_m3s"].rank().corr(m["obs_wlevel_ft"].rank())) if len(m) > 2 else float("nan")
    _plot_scatter(m, target, r, rho, params, areas[target], tr_dir / f"{target}_flow_vs_wlevel.png")
    print(f"  [전이] {target}: 유량 vs 관측수위 산점 n={len(m)} Pearson R={r:.3f} Spearman ρ={rho:.3f}")
    return {"n": len(m), "pearson_r": r, "spearman_rho": float(rho), "csv": str(csv)}


def _plot_wlevel(merged, rcfg, cal, val, rows, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Malgun Gothic"; plt.rcParams["axes.unicode_minus"] = False
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [2.1, 1]})
    m = merged.dropna(subset=["obs_msl"])
    ax1.plot(merged["date"], merged["level_msl"], color="#C0392B", lw=1.3, label="Tank 모의 수위")
    ax1.plot(m["date"], m["obs_msl"], color="#22303C", lw=1.3, alpha=0.85, label="관측 수위")
    ax1.axhline(rcfg.spillway_ft, color="#2E9E5B", ls="--", lw=1, alpha=0.7)
    ax1.axhline(rcfg.bottom_ft, color="#D1352B", ls="--", lw=1, alpha=0.7)
    if cal[0]: ax1.axvspan(pd.Timestamp(cal[0]), pd.Timestamp(cal[1]), color="#3F7FBF", alpha=0.06, label="보정")
    if val[0]: ax1.axvspan(pd.Timestamp(val[0]), pd.Timestamp(val[1]), color="#E6B800", alpha=0.08, label="검증")
    ax1.set_ylabel("수위 (MSL, ft)"); ax1.set_title("Ngerimel 저수지 수위 — Tank 모의 vs 관측", fontweight="bold", loc="left")
    ax1.legend(fontsize=8.5, ncol=2, frameon=False); ax1.grid(color="#D8E0E6", lw=0.7)
    ax2.scatter(m["obs_msl"], m["level_msl"], s=8, alpha=0.4, color="#3F7FBF")
    lo, hi = rcfg.bottom_ft - 1, rcfg.spillway_ft + 1
    ax2.plot([lo, hi], [lo, hi], color="#888", ls="--", lw=1)
    ax2.set_xlim(lo, hi); ax2.set_ylim(lo, hi); ax2.set_aspect("equal")
    ax2.set_xlabel("관측 수위(MSL, ft)"); ax2.set_ylabel("Tank 모의 수위(MSL, ft)")
    calm = next(r for r in rows if r["phase"] == "calibration")
    ax2.set_title(f"보정 NSE={calm['nse']:.2f} KGE={calm['kge']:.2f}\nPBIAS={calm['pbias']:.1f}% RMSE={calm['rmse']:.2f}",
                  fontsize=9.5, loc="left")
    ax2.grid(color="#D8E0E6", lw=0.7)
    fig.tight_layout(); fig.savefig(out, dpi=150, facecolor="white"); plt.close(fig)


def _plot_scatter(m, target, r, rho, params, area, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Malgun Gothic"; plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(7.2, 6))
    sc = ax.scatter(m["q_m3s"], m["obs_wlevel_ft"], s=12, alpha=0.45, color="#3F7FBF",
                    edgecolors="none")
    ax.set_xlabel(f"{target} Tank 계산 유량 (m³/s)  [ngerimel 파라미터·면적 {area} km²]", fontsize=10.5)
    ax.set_ylabel(f"{target} 관측 수위 (ft)", fontsize=10.5)
    ax.set_title(f"{target} — 계산유량 vs 관측수위 산점도\nPearson R={r:.3f} · Spearman ρ={rho:.3f} · n={len(m)}",
                 fontweight="bold", loc="left", fontsize=12)
    ax.grid(color="#D8E0E6", lw=0.7)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); fig.savefig(out, dpi=150, facecolor="white"); plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swat_py.tank.reservoir_calibrate")
    ap.add_argument("--config", default="config/swat_py.yaml")
    ap.add_argument("--iters", type=int, default=None)
    ap.add_argument("--objective", default="kge", choices=["kge", "nse", "r2", "pbias"])
    ap.add_argument("--transfer-to", default="ngerikiil")
    args = ap.parse_args(argv)
    from swat_py.config import load_config
    cfg = load_config(args.config)
    run_tank_reservoir_calibration(cfg, n_iterations=args.iters, objective=args.objective,
                                   transfer_to=args.transfer_to)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
