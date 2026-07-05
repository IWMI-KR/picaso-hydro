"""가뭄위험 대시보드 outlet별 그림 (docx image1.png 중앙 차트 재현).

①평년선(파랑)·②관측(검정)·③예측평균(주황)+박스플롯·④Q275/Q355 임계선(점선) +
⑤ 단계확률 표(Watch/Warning/Crisis). series.csv/thresholds.csv/stage_prob.csv 를 읽음.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Wedge, Circle

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

from swat_py.drought.stages import STAGES4, STAGE_COLORS, STAGE_SCORE

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_STAGE_COLOR = STAGE_COLORS   # Normal(녹)-Watch(황)-Warning(주)-Crisis(적)


def _fit_ylim_above_legend(fig, ax, leg, floor, data_max, *, pad=0.06, max_reserve=0.5):
    """레전드(upper-left)와 데이터 선이 겹치지 않도록 log-Y 상한을 자동 확대.

    레전드 박스의 하단 위치를 측정해, 최대 데이터값이 그 아래에 오도록 ymax를 키운다.
    데이터 범위·레전드 크기와 무관하게 동작(범용). max_reserve 로 상단 과확대 방지.
    """
    fig.canvas.draw()
    try:
        bb = leg.get_window_extent(fig.canvas.get_renderer())
    except Exception:
        return
    y_bottom = ax.transAxes.inverted().transform((bb.x0, bb.y0))[1]  # 레전드 하단(축 비율)
    target = max(1.0 - max_reserve, y_bottom - pad)                  # 데이터 최대가 놓일 상한 비율
    lo = float(np.log10(floor))
    dm = float(np.log10(max(data_max, floor * 1.01)))
    hi = float(np.log10(ax.get_ylim()[1]))
    if hi <= lo:
        return
    frac = (dm - lo) / (hi - lo)
    if frac > target and target > 0:
        ax.set_ylim(floor, 10 ** (lo + (dm - lo) / target))


def _criterion_label(method, value) -> str:
    """임계선 레전드 기준 표기 — 하천 FDC는 Q값(예 Q70), 백분위·고정은 해당 표기."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    m = str(method).lower()
    if m.startswith("fdc") or m == "exceedance":
        return f"Q{v:g}"
    if m.startswith("nonexceed") or m == "percentile":
        return f"Q{100 - v:g}"          # 비초과 백분위 → 초과확률 Q
    if m.startswith("fixed"):
        return f"{v:g} m³/s"
    return f"{v:g}"


def _draw_gauge(ax, probs: dict, most_likely: str, title: str) -> None:
    """반원 4단계 게이지 + 위험도 바늘 (⑤).

    섹터(좌→우): Normal(녹)·Watch(황)·Warning(주)·Crisis(적), 각 45°.
    바늘 각도 = 심각도 기대점수 Σ(prob·score)/100 (0=안전 180° … 1=위기 0°).
    """
    R, r = 1.0, 0.60
    for i, s in enumerate(STAGES4):          # 좌(180°)→우(0°) 순: Normal…Crisis
        th1 = 180 - i * 45
        ax.add_patch(Wedge((0, 0), R, th1 - 45, th1, width=R - r,
                           facecolor=STAGE_COLORS[s], edgecolor="white", lw=2))
    score = sum(probs.get(s, 0.0) * STAGE_SCORE[s] for s in STAGES4) / 100.0
    score = min(max(score, 0.0), 1.0)
    ang = np.deg2rad(180 - 180 * score)
    ax.plot([0, 0.78 * np.cos(ang)], [0, 0.78 * np.sin(ang)],
            color="black", lw=3, solid_capstyle="round", zorder=5)
    ax.add_patch(Circle((0, 0), 0.06, color="black", zorder=6))
    ax.text(0, -0.22, title, ha="center", va="top", fontsize=12, fontweight="bold")
    ax.text(0, -0.42, f"{most_likely}", ha="center", va="top", fontsize=11,
            color=STAGE_COLORS.get(most_likely, "black"), fontweight="bold")
    ax.set_xlim(-1.15, 1.15); ax.set_ylim(-0.55, 1.12)
    ax.set_aspect("equal"); ax.axis("off")


def make_stage_gauges(out_dir) -> "Path":
    """outlet의 예측월별 ⑤ 4단계 게이지 (stage_prob.csv). dashboard_{outlet}_gauge.png."""
    out_dir = Path(out_dir)
    sp = pd.read_csv(out_dir / "stage_prob.csv")
    outlet = out_dir.name
    n = max(len(sp), 1)
    fig, axes = plt.subplots(1, n, figsize=(3.1 * n, 3.3))
    if n == 1:
        axes = [axes]
    for ax, (_, r) in zip(axes, sp.iterrows()):
        probs = {s: float(r.get(s, 0.0)) for s in STAGES4}
        _draw_gauge(ax, probs, r["most_likely"],
                    f"{int(r['month'])}월  ({_MONTHS[int(r['month'])-1]})")
    fig.suptitle(f"⑤ Water Supply Forecast — {outlet}", fontsize=14, fontweight="bold", y=1.02)
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color=STAGE_COLORS[s], label=s) for s in STAGES4],
               loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.04))
    out = out_dir / f"dashboard_{outlet}_gauge.png"
    fig.savefig(out, dpi=160, bbox_inches="tight"); plt.close(fig)
    return out


def make_outlet_figure(out_dir: Path) -> Path:
    series = pd.read_csv(out_dir / "series.csv")
    thr = pd.read_csv(out_dir / "thresholds.csv").iloc[0]
    stage = pd.read_csv(out_dir / "stage_prob.csv") if (out_dir / "stage_prob.csv").is_file() else pd.DataFrame()
    outlet = out_dir.name
    fc_period = out_dir.parent.name.replace("dashboard_", "").replace("_", "-")  # 예: 2016-AMJ

    fig = plt.figure(figsize=(11, 7))
    gs = GridSpec(2, 1, height_ratios=[3.2, 1.0], hspace=0.35,
                  left=0.08, right=0.97, top=0.92, bottom=0.08)
    ax = fig.add_subplot(gs[0])
    x = series["month"].values

    # 임계 경계유량 + 레전드용 기준값(Q값 등)
    nw = thr.get("normal_watch", thr.get("Q185_normal_watch"))
    ww = thr.get("watch_warning", thr.get("Q275_watch_warning"))
    wc = thr.get("warning_crisis", thr.get("Q355_warning_crisis"))
    method = str(thr.get("method", "fdc_exceedance"))
    lbl_nw = _criterion_label(method, thr.get("nw_input"))
    lbl_ww = _criterion_label(method, thr.get("ww_input"))
    lbl_wc = _criterion_label(method, thr.get("wc_input"))
    n_ens = int(thr.get("n_ensemble", 0) or 0)

    # log 축 하한(floor) — 임계 최저(Warning-Crisis)의 0.3배로 두어 0 근처 값을 그 부근에
    # 클립(선 연속·박스 과대신장 방지). 상한은 최대 유량의 1.6배.
    thr_pos = [v for v in [nw, ww, wc] if v and v > 0]
    data_pos = []
    for col in ["hist_mean", "observed", "forecast_mean", "p5", "p25", "p50", "p75", "p95"]:
        if col in series:
            data_pos += [v for v in series[col].dropna().tolist() if v > 0]
    floor = (min(thr_pos) * 0.3) if thr_pos else ((min(data_pos) * 0.5) if data_pos else 1e-4)
    ymax = (max(data_pos + thr_pos) * 1.6) if (data_pos or thr_pos) else 1.0

    def _c(v):    # 스칼라 floor 클립
        return max(float(v), floor) if v == v else np.nan

    # ── ① 평년선 ──
    ax.plot(x, series["hist_mean"].clip(lower=floor), "-o", color="#1f77b4", lw=2, ms=4,
            label="Historical Mean (2006–2024)", zorder=3)
    # ── ② 관측 ──
    obs = series.dropna(subset=["observed"])
    if len(obs):
        ax.plot(obs["month"], obs["observed"].clip(lower=floor), "-", color="black", lw=3,
                label="Observed", zorder=4)
    # ── ③ 예측평균 + 박스플롯 ──
    if "forecast_mean" in series:
        fc = series.dropna(subset=["forecast_mean"])
        ax.plot(fc["month"], fc["forecast_mean"].clip(lower=floor), "-o", color="#ff7f0e",
                lw=2.5, ms=5, label=f"Forecast Mean ({n_ens} ens)", zorder=5)
        bx = [{"med": _c(r["p50"]), "q1": _c(r["p25"]), "q3": _c(r["p75"]),
               "whislo": _c(r["p5"]), "whishi": _c(r["p95"]), "fliers": []}
              for _, r in fc.iterrows()]
        if bx:
            ax.bxp(bx, positions=fc["month"].values, widths=0.25, showfliers=False,
                   boxprops=dict(color="#ff7f0e"), medianprops=dict(color="#ff7f0e"),
                   whiskerprops=dict(color="#ff7f0e"), capprops=dict(color="#ff7f0e"),
                   manage_ticks=False, zorder=2)
    # ── ④ 임계선 (기준값 괄호 표기) ──
    if nw is not None:
        ax.axhline(_c(nw), ls="--", color="#2ca02c", lw=1.8, label=f"Normal–Watch ({lbl_nw})")
    ax.axhline(_c(ww), ls="--", color="#f5c518", lw=2.0, label=f"Watch–Warning ({lbl_ww})")
    ax.axhline(_c(wc), ls="--", color="#d62728", lw=2.0, label=f"Warning–Crisis ({lbl_wc})")

    ax.set_yscale("log")
    # log 눈금 십진 표기 (한글폰트의 위첨자 마이너스 미지원 회피)
    from matplotlib.ticker import FuncFormatter, LogLocator
    ax.yaxis.set_major_locator(LogLocator(base=10.0))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.yaxis.set_minor_formatter(FuncFormatter(lambda v, _: ""))
    ax.set_xticks(range(1, 13)); ax.set_xticklabels(_MONTHS)
    ax.set_ylabel("flow (m³/s, log)"); ax.set_xlim(0.5, 12.5)
    ax.set_ylim(floor, ymax)
    ax.set_title(f"Drought-Risk Hydrological Outlook — {outlet}  ({fc_period})",
                 fontweight="bold")
    leg = ax.legend(loc="upper left", fontsize=8, frameon=True, framealpha=0.85, ncol=2)
    # 레전드와 데이터(특히 Historical Mean) 비중첩 — Y 상한 자동 확대(범용)
    data_max = max(data_pos + thr_pos) if (data_pos or thr_pos) else 1.0
    _fit_ylim_above_legend(fig, ax, leg, floor, data_max)

    # ⑤ 단계확률 표
    axt = fig.add_subplot(gs[1]); axt.axis("off")
    if len(stage):
        stage_cols = [s for s in STAGES4 if s in stage.columns]
        cell = [[f"{int(r['month'])}월"] +
                [f"{r[c]:.0f}%" for c in stage_cols] +
                [r["most_likely"]] for _, r in stage.iterrows()]
        tb = axt.table(cellText=cell,
                       colLabels=["월"] + list(stage_cols) + ["최빈단계"],
                       loc="center", cellLoc="center")
        tb.auto_set_font_size(False); tb.set_fontsize(10); tb.scale(1, 1.5)
        ml_col = len(stage_cols) + 1
        for j, (_, r) in enumerate(stage.iterrows(), start=1):
            tb[(j, ml_col)].set_facecolor(STAGE_COLORS.get(r["most_likely"], "white"))
            tb[(j, ml_col)].set_text_props(color="white", weight="bold")
        axt.set_title("⑤ Water Supply Forecast (단계별 확률)", fontsize=10, pad=2)

    out = out_dir / f"dashboard_{outlet}.png"
    fig.savefig(out, dpi=160); plt.close(fig)
    return out


def make_all_figures(out_root: Path) -> int:
    n = 0
    for d in sorted(out_root.iterdir()):
        if d.is_dir() and (d / "series.csv").is_file():
            make_outlet_figure(d)
            if (d / "stage_prob.csv").is_file():
                make_stage_gauges(d)          # ⑤ 게이지
            n += 1
    print(f"  그림 {n}장(+⑤ 게이지) → {out_root}")
    return n
