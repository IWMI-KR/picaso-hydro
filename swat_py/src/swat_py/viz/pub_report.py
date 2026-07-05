"""논문용 5-패널 검보정 그림 (모형 무관 공용).

한 페이지: ①일 시계열 ②월 시계열 ③일 산점도 ④월 산점도 + 일(NSE/RMSE/RSR/%Error)·
월(NSE/RMSE/RSR) 성능지표. 관측=회색, 모의=검정 점선. 시계열은 전체 공통기간(해당
기간 음영), 산점도·지표는 선택 기간(cal/val)만.

SWAT·Tank 등 어떤 모형이든 obs·sim 일 시계열만 있으면 동일 형식으로 생성한다.
`make_report(station, unit, phase, daily, out_path, period)` — daily: index=date,
columns=['obs','sim'](전체기간), period=(start, end, phase_name).
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

from swat_py.metrics.performance import nse, rmse, rsr, pbias, r2

_GRAY = "0.62"
_BLACK = "black"

# 기본 분할표본 기간 (calibrate 에서 cfg 값으로 덮어씀)
DEFAULT_PHASES = {
    "cal": ("2015-01-01", "2017-12-31", "calibration"),
    "val": ("2018-01-01", "2020-12-31", "validation"),
}


def _pair(obs: pd.Series, sim: pd.Series):
    d = pd.concat([obs.rename("o"), sim.rename("s")], axis=1).dropna()
    return d["o"].to_numpy(), d["s"].to_numpy()


def _fmt(v, nd=2):
    return "n/a" if (v is None or not np.isfinite(v)) else f"{v:.{nd}f}"


def _scatter(ax, o, s, unit):
    lim = float(np.nanmax([o.max() if o.size else 1, s.max() if s.size else 1])) * 1.05
    lim = max(lim, 1e-6)
    ax.scatter(o, s, s=34, facecolors="none", edgecolors=_BLACK, linewidths=1.0)
    ax.plot([0, lim], [0, lim], "--", color=_BLACK, lw=1.1)
    if o.size >= 2 and np.ptp(o) > 0:
        a, b = np.polyfit(o, s, 1)
        xs = np.array([0.0, lim])
        ax.plot(xs, a * xs + b, "-", color=_BLACK, lw=2.6)
        ax.text(0.05, 0.93, f"y = {a:.3f}x {'+' if b >= 0 else '-'} {abs(b):.3f}",
                transform=ax.transAxes, va="top", fontsize=12.5)
        ax.text(0.05, 0.845, f"$R^2$ = {r2(o, s):.4f}",
                transform=ax.transAxes, va="top", fontsize=12.5)
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel(f"observed streamflow ({unit})")
    ax.set_ylabel(f"simulated streamflow ({unit})")


def make_report(station: str, unit: str, phase_key: str,
                daily: pd.DataFrame, out_path: Path,
                period: Tuple[str, str, str]) -> dict:
    """daily: index=date, columns ['obs','sim'] (전체기간). 그림 1장 생성 + 지표 반환."""
    p0, p1, phase_name = period
    t0, t1 = pd.Timestamp(p0), pd.Timestamp(p1)

    daily = daily[~daily.index.duplicated()].sort_index().asfreq("D")
    mon = daily.resample("MS").mean()
    valid = daily["obs"].notna().resample("MS").mean() >= 0.5
    mon.loc[~valid, "obs"] = np.nan

    d_ph, m_ph = daily.loc[t0:t1], mon.loc[t0:t1]
    od, sd = _pair(d_ph["obs"], d_ph["sim"])
    om, sm = _pair(m_ph["obs"], m_ph["sim"])

    fig = plt.figure(figsize=(8.3, 11.2))
    gs = GridSpec(3, 2, figure=fig, height_ratios=[1.0, 1.0, 1.35],
                  hspace=0.42, wspace=0.30, left=0.12, right=0.96, top=0.93, bottom=0.16)
    fig.suptitle(f"{station}  —  {phase_name}  ({unit})",
                 fontsize=16, fontweight="bold", y=0.975)

    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(daily.index, daily["obs"], color=_GRAY, lw=2.6, label="observed",
             solid_capstyle="round", zorder=1)
    ax1.plot(daily.index, daily["sim"], color=_BLACK, lw=0.7, ls=":", label="simulated", zorder=2)
    ax1.axvspan(t0, t1, color="0.90", zorder=0)
    ax1.set_ylabel(f"streamflow ({unit})")
    ax1.set_xlim(daily.index.min(), daily.index.max()); ax1.margins(y=0.05)
    ax1.legend(loc="upper right", frameon=False, ncol=2, fontsize=12, handlelength=2.4)

    ax2 = fig.add_subplot(gs[1, :])
    ax2.fill_between(mon.index, 0, mon["obs"], color=_GRAY, zorder=1, label="observed")
    ax2.plot(mon.index, mon["sim"], color=_BLACK, lw=0.9, ls=":", zorder=2)
    ax2.plot(mon.index, mon["sim"], "o", color=_BLACK, ms=3.2, zorder=3, label="simulated")
    ax2.axvspan(t0, t1, color="0.90", zorder=0)
    ax2.set_ylabel(f"streamflow ({unit})")
    ax2.set_xlim(mon.index.min(), mon.index.max()); ax2.margins(y=0.05)
    ax2.legend(loc="upper right", frameon=False, ncol=2, fontsize=12, handlelength=2.4)

    ax3 = fig.add_subplot(gs[2, 0])
    _scatter(ax3, od, sd, unit)
    m_d = {"nse": nse(od, sd), "rmse": rmse(od, sd), "rsr": rsr(od, sd),
           "pbias": pbias(od, sd), "r2": r2(od, sd), "n": int(od.size)}
    fig.text(ax3.get_position().x0 + ax3.get_position().width / 2, 0.115,
             f"NSE = {_fmt(m_d['nse'])}\nRMSE = {_fmt(m_d['rmse'], 3)}\n"
             f"RSR = {_fmt(m_d['rsr'])}\n% Error = {_fmt(m_d['pbias'], 1)}",
             ha="center", va="top", fontsize=12.5)
    ax3.set_title(f"daily  (n = {od.size})", fontsize=12.5, pad=6)

    ax4 = fig.add_subplot(gs[2, 1])
    _scatter(ax4, om, sm, unit)
    m_m = {"nse": nse(om, sm), "rmse": rmse(om, sm), "rsr": rsr(om, sm),
           "pbias": pbias(om, sm), "r2": r2(om, sm), "n": int(om.size)}
    fig.text(ax4.get_position().x0 + ax4.get_position().width / 2, 0.115,
             f"NSE = {_fmt(m_m['nse'])}\nRMSE = {_fmt(m_m['rmse'], 3)}\nRSR = {_fmt(m_m['rsr'])}",
             ha="center", va="top", fontsize=12.5)
    ax4.set_title(f"monthly  (n = {om.size})", fontsize=12.5, pad=6)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return {"station": station, "phase": phase_key, "daily": m_d, "monthly": m_m,
            "file": str(out_path)}
