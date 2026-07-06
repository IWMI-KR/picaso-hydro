"""SWAT+ vs Tank 유량 비교 → reports/05_모형간_유량비교/.

두 모형의 관측소별 모의유량(각 검보정 결과)을 관측치와 함께 비교한다.
  - 입력: SWAT `3_swatplus/calibration/results/top1_sim_daily.csv`,
          Tank `3_swatplus/calibration-tank/results/tank_sim_daily.csv`, 관측 CSV(cfg)
  - 산출: {station}_flow_compare.png (일/월 시계열 + 월 산점도, Obs·SWAT·Tank),
          model_comparison_summary.csv (모형별 cal/val NSE·KGE·PBIAS·RMSE), README.md

실행: python -m swat_py.tank.compare [--config config/swat_py.yaml]
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

from swat_py.metrics.performance import calc_all

_C_OBS = "0.55"        # 관측 (회색)
_C_SWAT = "#1f77b4"    # SWAT (파랑)
_C_TANK = "#ff7f0e"    # Tank (주황)


def _load_wide(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["date"]).set_index("date")


def _metrics(o: np.ndarray, s: np.ndarray) -> dict:
    if o.size < 5:
        return {"nse": np.nan, "kge": np.nan, "pbias": np.nan, "rmse": np.nan}
    m = calc_all(o, s)
    return {k: m[k] for k in ("nse", "kge", "pbias", "rmse")}


def _scatter(ax, o, s, color, label, unit):
    lim = float(np.nanmax([o.max() if o.size else 1, s.max() if s.size else 1])) * 1.05
    lim = max(lim, 1e-6)
    ax.scatter(o, s, s=26, facecolors="none", edgecolors=color, linewidths=1.0)
    ax.plot([0, lim], [0, lim], "--", color="0.4", lw=1.0)
    mm = _metrics(o, s)
    ax.text(0.05, 0.93, f"{label}\nNSE={mm['nse']:.2f}", transform=ax.transAxes,
            va="top", fontsize=11, color=color)
    ax.set_xlim(0, lim); ax.set_ylim(0, lim); ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel(f"observed ({unit})"); ax.set_ylabel(f"simulated ({unit})")


def _make_compare_fig(station, unit, daily: pd.DataFrame, out_path: Path,
                      cal_period, val_period):
    """daily: index=date, cols ['obs','swat','tank'] (전체기간)."""
    daily = daily[~daily.index.duplicated()].sort_index().asfreq("D")
    mon = daily.resample("MS").mean()
    valid = daily["obs"].notna().resample("MS").mean() >= 0.5
    mon.loc[~valid, "obs"] = np.nan

    fig = plt.figure(figsize=(9.0, 11.5))
    gs = GridSpec(3, 2, figure=fig, height_ratios=[1.0, 1.0, 1.2],
                  hspace=0.40, wspace=0.30, left=0.10, right=0.97, top=0.93, bottom=0.10)
    fig.suptitle(f"{station} — SWAT+ vs Tank ({unit})", fontsize=16, fontweight="bold", y=0.975)

    for row, (df, tstep) in enumerate(((daily, "daily"), (mon, "monthly"))):
        ax = fig.add_subplot(gs[row, :])
        ax.plot(df.index, df["obs"], color=_C_OBS, lw=2.4, label="observed", zorder=1)
        ax.plot(df.index, df["swat"], color=_C_SWAT, lw=0.9, label="SWAT+", zorder=2)
        ax.plot(df.index, df["tank"], color=_C_TANK, lw=0.9, label="Tank", zorder=3)
        ax.axvspan(pd.Timestamp(cal_period[0]), pd.Timestamp(cal_period[1]), color="0.92", zorder=0)
        ax.set_ylabel(f"streamflow ({unit})"); ax.set_title(tstep, fontsize=12, pad=4)
        ax.set_xlim(df.index.min(), df.index.max()); ax.margins(y=0.05)
        if row == 0:
            ax.legend(loc="upper right", frameon=False, ncol=3, fontsize=11)

    # 월 산점도 (보정기간): SWAT, Tank
    m_ph = mon.loc[pd.Timestamp(cal_period[0]):pd.Timestamp(cal_period[1])]
    for col, (color, label, model) in zip((0, 1), ((_C_SWAT, "SWAT+", "swat"),
                                                    (_C_TANK, "Tank", "tank"))):
        ax = fig.add_subplot(gs[2, col])
        d = m_ph[["obs", model]].dropna()
        _scatter(ax, d["obs"].to_numpy(), d[model].to_numpy(), color, label, unit)
        ax.set_title(f"{label} · monthly (cal)", fontsize=11, pad=4)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def compare_swat_tank(cfg) -> Dict:
    swat_csv = Path(cfg.PrjDir) / "3_swatplus" / "calibration" / "results" / "top1_sim_daily.csv"
    tank_csv = Path(cfg.PrjDir) / "3_swatplus" / "calibration-tank" / "results" / "tank_sim_daily.csv"
    if not swat_csv.is_file():
        raise SystemExit(f"SWAT sim 없음: {swat_csv} (SWAT 검보정 최종본 필요)")
    if not tank_csv.is_file():
        raise SystemExit(f"Tank sim 없음: {tank_csv} (먼저 tank.calibrate 실행)")

    swat = _load_wide(swat_csv)
    tank = _load_wide(tank_csv)
    dest = Path(cfg.PrjDir) / "reports" / "05_모형간_유량비교"
    dest.mkdir(parents=True, exist_ok=True)

    cal_period = (cfg.CalPeriodStart or "2015-01-01", cfg.CalPeriodEnd or "2017-12-31")
    val_period = (cfg.ValPeriodStart or "2018-01-01", cfg.ValPeriodEnd or "2020-12-31")

    rows = []
    for obs in cfg.Observations:
        if obs.id not in swat.columns or obs.id not in tank.columns:
            print(f"  ! {obs.id}: SWAT 또는 Tank 열 없음 — 건너뜀"); continue
        obs_df = pd.read_csv(obs.obs_file, parse_dates=["date"]).set_index("date")
        oc = obs.obs_column
        daily = pd.DataFrame({"obs": obs_df[oc]}).join(
            swat[[obs.id]].rename(columns={obs.id: "swat"}), how="outer").join(
            tank[[obs.id]].rename(columns={obs.id: "tank"}), how="outer").sort_index()

        _make_compare_fig(obs.id, obs.unit, daily.copy(),
                          dest / f"{obs.id}_flow_compare.png", cal_period, val_period)

        # 성능 비교표 (일단위, cal/val, 두 모형)
        for phase, per in (("calibration", cal_period), ("validation", val_period)):
            sub = daily.loc[pd.Timestamp(per[0]):pd.Timestamp(per[1])]
            for model in ("swat", "tank"):
                d = sub[["obs", model]].dropna()
                mm = _metrics(d["obs"].to_numpy(), d[model].to_numpy())
                rows.append({"station": obs.id, "phase": phase, "model": model.upper(),
                             "n": len(d), "nse": round(mm["nse"], 3),
                             "kge": round(mm["kge"], 3), "pbias": round(mm["pbias"], 1),
                             "rmse": round(mm["rmse"], 4)})
        print(f"  ✔ {obs.id} 비교 그림·지표")

    summ = pd.DataFrame(rows)
    summ.to_csv(dest / "model_comparison_summary.csv", index=False, encoding="utf-8-sig")
    _write_readme(dest, summ)
    print(f"\n  비교 결과 → {dest}")
    return {"dest": str(dest), "summary": rows}


def _write_readme(dest: Path, summ: pd.DataFrame) -> None:
    (dest / "README.md").write_text(
        "# 05_모형간_유량비교 — SWAT+ vs Tank\n\n"
        "동일 관측소·기상·검보정기간(보정 2015–2017 / 검증 2018–2020)에 대해 물리기반\n"
        "준분포형 **SWAT+**와 집중형 개념 **3단 Tank** 모형의 유량 재현성을 비교한다.\n"
        "다른 유역에서도 두 모형 결과(top1_sim_daily.csv, tank_sim_daily.csv)만 있으면 동일 생성.\n\n"
        "## 파일\n"
        "- `{station}_flow_compare.png` — 일/월 시계열(Obs·SWAT·Tank) + 월 산점도(모형별)\n"
        "- `model_comparison_summary.csv` — 관측소×기간×모형 NSE·KGE·PBIAS·RMSE\n\n"
        "## 성능 요약 (일단위 NSE)\n\n"
        + _nse_pivot_md(summ) +
        "\n> 원본: SWAT `3_swatplus/calibration/`, Tank `3_swatplus/calibration-tank/`\n",
        encoding="utf-8")


def _nse_pivot_md(summ: pd.DataFrame) -> str:
    """일단위 NSE 비교표를 마크다운으로(외부 의존 없이 수기 생성)."""
    if summ.empty:
        return "(데이터 없음)\n"
    piv = summ.pivot_table(index="station", columns=["phase", "model"], values="nse")
    piv = piv.sort_index(axis=1)
    header = "| station | " + " | ".join(f"{ph[:3]}·{md}" for ph, md in piv.columns) + " |"
    sep = "|" + "---|" * (len(piv.columns) + 1)
    lines = [header, sep]
    for st, row in piv.iterrows():
        cells = " | ".join("n/a" if pd.isna(v) else f"{v:.3f}" for v in row)
        lines.append(f"| {st} | {cells} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swat_py.tank.compare")
    ap.add_argument("--config", default="config/swat_py.yaml")
    args = ap.parse_args(argv)
    from swat_py.config import load_config
    compare_swat_tank(load_config(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
