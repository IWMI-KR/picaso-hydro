"""가뭄위험 대시보드 outlet별 그림 (docx image1.png 중앙 차트 재현).

①평년선(파랑)·②관측(검정)·③예측평균(주황)+박스플롯·④Q275/Q355 임계선(점선) +
⑤ 단계확률 표(Watch/Warning/Crisis). series.csv/thresholds.csv/stage_prob.csv 를 읽음.
"""
from __future__ import annotations

import argparse
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
    if m.startswith("pool") or m.startswith("capacity") or m.startswith("fill"):
        return f"{v:g}%"          # 저수지 만수 대비 %
    return f"{v:g}"


def _draw_gauge(ax, probs: dict, most_likely: str, title: str) -> None:
    """반원 4단계 게이지 + 위험도 바늘 (⑤).

    섹터(좌→우): Normal(녹)·Watch(황)·Warning(주)·Crisis(적), 각 45°.
    바늘 = **최빈단계(most_likely) 섹터 중앙** — 시계열 표·색·요약과 일치.

    주의: 기대심각도 Σ(prob·score) 방식은 Normal+Crisis 양극(bimodal) 분포에서
    평균이 중간(Warning)을 가리켜 최빈단계(Crisis)와 불일치했다. 저수지처럼 습윤/
    건조 멤버로 확률이 양극에 몰릴 때 바늘이 확률 낮은 중간 단계를 가리키는 오해를
    막기 위해, 표·요약과 동일한 최빈단계 기준으로 바늘을 놓는다.
    """
    R, r = 1.0, 0.60
    for i, s in enumerate(STAGES4):          # 좌(180°)→우(0°) 순: Normal…Crisis
        th1 = 180 - i * 45
        ax.add_patch(Wedge((0, 0), R, th1 - 45, th1, width=R - r,
                           facecolor=STAGE_COLORS[s], edgecolor="white", lw=2))
    # 최빈단계 섹터 중앙 각도: Normal→157.5°, Watch→112.5°, Warning→67.5°, Crisis→22.5°
    idx = STAGES4.index(most_likely) if most_likely in STAGES4 else 0
    ang = np.deg2rad(180 - (idx + 0.5) * 45)
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


_CAPACITY_METHODS = ("capacity_fraction", "pool_fraction", "fill_fraction")


def _is_reservoir_outlet(thr) -> bool:
    """thresholds.csv 행이 저수지(만수대비% capacity)인지 판별."""
    return (str(thr.get("variable", "")).lower() == "capacity_pct"
            or str(thr.get("method", "")).lower() in _CAPACITY_METHODS)


def _plot_stage_table(axt, stage) -> None:
    """예측월별 4단계 확률 표(하단 공통)."""
    axt.axis("off")
    if not len(stage):
        return
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


def _plot_reservoir_timeseries(ax, series, thr, outlet, fc_period) -> None:
    """저수지 만수 대비 저수량 %(capacity_fraction) 시계열 — 선형축, 단계 배경대."""
    nw = float(thr.get("normal_watch", 100.0))   # 만수 100
    ww = float(thr.get("watch_warning", 85.0))
    wc = float(thr.get("warning_crisis", 65.0))
    n_ens = int(thr.get("n_ensemble", 0) or 0)
    fc = series.dropna(subset=["forecast_capacity_pct"]) if "forecast_capacity_pct" in series else pd.DataFrame()

    top = 110.0
    if len(fc) and "p95" in fc:
        top = max(top, float(np.nanmax(fc["p95"])) + 5)
    # 단계 배경대: Normal(≥100 녹)·Watch(85–100 황)·Warning(65–85 주)·Crisis(<65 적)
    ax.axhspan(nw, top, facecolor=STAGE_COLORS["Normal"],  alpha=0.12)
    ax.axhspan(ww, nw,  facecolor=STAGE_COLORS["Watch"],   alpha=0.12)
    ax.axhspan(wc, ww,  facecolor=STAGE_COLORS["Warning"], alpha=0.12)
    ax.axhspan(0,  wc,  facecolor=STAGE_COLORS["Crisis"],  alpha=0.12)
    for y, s, lbl in [(nw, "Normal", f"Normal–Watch ({nw:g}%)"),
                      (ww, "Watch", f"Watch–Warning ({ww:g}%)"),
                      (wc, "Warning", f"Warning–Crisis ({wc:g}%)")]:
        ax.axhline(y, ls="--", lw=1.6, color=STAGE_COLORS[s], label=lbl)

    if len(fc):
        ax.plot(fc["month"], fc["forecast_capacity_pct"], "-o", color="#ff7f0e",
                lw=2.5, ms=6, label=f"Forecast Mean ({n_ens} ens)", zorder=5)
        if {"p5", "p25", "p50", "p75", "p95"} <= set(fc.columns):
            bx = [{"med": r["p50"], "q1": r["p25"], "q3": r["p75"],
                   "whislo": r["p5"], "whishi": r["p95"], "fliers": []}
                  for _, r in fc.iterrows()]
            ax.bxp(bx, positions=fc["month"].values, widths=0.25, showfliers=False,
                   boxprops=dict(color="#ff7f0e"), medianprops=dict(color="#ff7f0e"),
                   whiskerprops=dict(color="#ff7f0e"), capprops=dict(color="#ff7f0e"),
                   manage_ticks=False, zorder=2)
    ax.set_xticks(range(1, 13)); ax.set_xticklabels(_MONTHS)
    ax.set_xlim(0.5, 12.5); ax.set_ylim(0, top)
    ax.set_ylabel("Reservoir storage (% of full capacity)")
    ax.set_title(f"Drought-Risk Reservoir Outlook — {outlet}  ({fc_period})",
                 fontweight="bold")
    ax.legend(loc="lower left", fontsize=8, frameon=True, framealpha=0.85, ncol=2)


def _season_panel(out_dir):
    """stage_prob_season.csv → (title, probs, most_likely) 또는 None."""
    fp = Path(out_dir) / "stage_prob_season.csv"
    if not fp.is_file():
        return None
    sdf = pd.read_csv(fp)
    if not len(sdf):
        return None
    r = sdf.iloc[0]
    return (f"{r.get('season', '')} 3-month mean",
            {s: float(r.get(s, 0.0)) for s in STAGES4}, r["most_likely"])


def make_stage_pie(out_dir) -> "Path":
    """월별(예: 3개월) + 3개월 평균(1개) 4단계 확률 파이 → dashboard_{outlet}_pie.png.

    예: 2016_AMJ → 4월·5월·6월 + 3개월평균 = 4개 파이.
    """
    out_dir = Path(out_dir)
    sp = pd.read_csv(out_dir / "stage_prob.csv")
    outlet = out_dir.name
    panels = [(f"{int(r['month'])}월 ({_MONTHS[int(r['month'])-1]})",
               {s: float(r.get(s, 0.0)) for s in STAGES4}, r["most_likely"])
              for _, r in sp.iterrows()]
    season = _season_panel(out_dir)     # 3개월 평균 파이(있으면 마지막)
    if season is not None:
        panels.append(season)

    n = max(len(panels), 1)
    fig, axes = plt.subplots(1, n, figsize=(3.2 * n, 3.6))
    if n == 1:
        axes = [axes]
    for ax, (title, probs, ml) in zip(axes, panels):
        vals = [probs[s] for s in STAGES4]
        wedges, _ = ax.pie(vals, colors=[STAGE_COLORS[s] for s in STAGES4],
                           startangle=90, counterclock=False,
                           wedgeprops=dict(edgecolor="white", linewidth=1.5))
        for w, v in zip(wedges, vals):
            if v >= 5:
                ang = np.deg2rad((w.theta1 + w.theta2) / 2)
                ax.text(0.65 * np.cos(ang), 0.65 * np.sin(ang), f"{v:.0f}%",
                        ha="center", va="center", fontsize=9, color="white",
                        fontweight="bold")
        ax.set_title(f"{title}\n→ {ml}", fontsize=10,
                     color=STAGE_COLORS.get(ml, "black"), fontweight="bold")
        ax.set_aspect("equal")
    fig.suptitle(f"⑤ Water Supply Forecast (단계확률 파이) — {outlet}",
                 fontsize=13, fontweight="bold", y=1.03)
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color=STAGE_COLORS[s], label=s) for s in STAGES4],
               loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.06))
    out = out_dir / f"dashboard_{outlet}_pie.png"
    fig.savefig(out, dpi=160, bbox_inches="tight"); plt.close(fig)
    return out


def make_season_pie(out_dir) -> "Path | None":
    """계절(3개월 평균) **단일** 4단계 확률 파이 → dashboard_{outlet}_season_pie.png.

    저수지=3개월 평균 저수량%, 하천=3개월 평균 유출량 기반. stage_prob_season.csv(1행) 사용.
    """
    out_dir = Path(out_dir)
    fp = out_dir / "stage_prob_season.csv"
    if not fp.is_file():
        return None
    sp = pd.read_csv(fp)
    if not len(sp):
        return None
    r = sp.iloc[0]
    outlet = out_dir.name
    season = str(r.get("season", ""))
    vals = [float(r.get(s, 0.0)) for s in STAGES4]
    fig, ax = plt.subplots(figsize=(4.4, 4.8))
    wedges, _ = ax.pie(vals, colors=[STAGE_COLORS[s] for s in STAGES4],
                       startangle=90, counterclock=False,
                       wedgeprops=dict(edgecolor="white", linewidth=1.5))
    for w, v in zip(wedges, vals):
        if v >= 4:
            ang = np.deg2rad((w.theta1 + w.theta2) / 2)
            ax.text(0.62 * np.cos(ang), 0.62 * np.sin(ang), f"{v:.0f}%",
                    ha="center", va="center", fontsize=11, color="white", fontweight="bold")
    ax.set_title(f"{outlet} — {season} 3-month mean risk\n→ {r['most_likely']}",
                 fontsize=12, color=STAGE_COLORS.get(r["most_likely"], "black"),
                 fontweight="bold")
    ax.set_aspect("equal")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=STAGE_COLORS[s], label=s) for s in STAGES4],
              loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.08),
              fontsize=9)
    out = out_dir / f"dashboard_{outlet}_season_pie.png"
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
    is_res = _is_reservoir_outlet(thr)   # 저수지도 우선 stream(Cook)과 동일 형식 사용
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
    ax.set_ylabel("storage (% of full capacity, log)" if is_res else "flow (m³/s, log)")
    ax.set_xlim(0.5, 12.5)
    ax.set_ylim(floor, ymax)
    _kind = "Reservoir Storage" if is_res else "Hydrological"
    ax.set_title(f"Drought-Risk {_kind} Outlook — {outlet}  ({fc_period})",
                 fontweight="bold")
    leg = ax.legend(loc="upper left", fontsize=8, frameon=True, framealpha=0.85, ncol=2)
    # 레전드와 데이터(특히 Historical Mean) 비중첩 — Y 상한 자동 확대(범용)
    data_max = max(data_pos + thr_pos) if (data_pos or thr_pos) else 1.0
    _fit_ylim_above_legend(fig, ax, leg, floor, data_max)

    # ⑤ 단계확률 표 — 월별 + (맨 아래) 3개월 평균 행
    axt = fig.add_subplot(gs[1]); axt.axis("off")
    # (라벨, {stage:prob}, most_likely) 행 구성
    rows_tbl = []
    stage_cols = [s for s in STAGES4 if s in stage.columns] if len(stage) else list(STAGES4)
    for _, r in stage.iterrows():
        rows_tbl.append((f"{int(r['month'])}월",
                         {c: float(r.get(c, 0.0)) for c in stage_cols}, r["most_likely"]))
    season = _season_panel(out_dir)   # 3개월 평균 행(있으면 마지막)
    if season is not None:
        rows_tbl.append(("3개월평균", season[1], season[2]))
    if rows_tbl:
        cell = [[lbl] + [f"{probs[c]:.0f}%" for c in stage_cols] + [ml]
                for lbl, probs, ml in rows_tbl]
        tb = axt.table(cellText=cell,
                       colLabels=["월"] + list(stage_cols) + ["최빈단계"],
                       loc="center", cellLoc="center")
        tb.auto_set_font_size(False); tb.set_fontsize(10); tb.scale(1, 1.4)
        ml_col = len(stage_cols) + 1
        for j, (lbl, probs, ml) in enumerate(rows_tbl, start=1):
            tb[(j, ml_col)].set_facecolor(STAGE_COLORS.get(ml, "white"))
            tb[(j, ml_col)].set_text_props(color="white", weight="bold")
            if lbl == "3개월평균":                 # 평균 행 강조
                for c in range(len(stage_cols) + 2):
                    tb[(j, c)].set_text_props(weight="bold")
                    tb[(j, c)].set_facecolor("#eef2f7" if c != ml_col
                                             else STAGE_COLORS.get(ml, "white"))
        axt.set_title("⑤ Water Supply Forecast (단계별 확률: 월별 + 3개월평균)",
                      fontsize=10, pad=2)

    out = out_dir / f"dashboard_{outlet}.png"
    fig.savefig(out, dpi=160); plt.close(fig)
    return out


def make_all_figures(out_root: Path) -> int:
    """outlet별 예측그래프 2종(Cook/라로통가 동일 형식): ① timeseries
    (dashboard_{outlet}.png) ② gauge(dashboard_{outlet}_gauge.png).
    (파이는 make_stage_pie 로 별도 호출 가능)"""
    n = 0
    for d in sorted(out_root.iterdir()):
        if d.is_dir() and (d / "series.csv").is_file():
            make_outlet_figure(d)                 # ① 시계열(표: 월별+3개월평균 행)
            if (d / "stage_prob.csv").is_file():
                make_stage_gauges(d)              # ② 게이지(월별) — Cook 동일
                make_stage_pie(d)                 # ③ 파이(월별 + 3개월평균 = 4개)
            n += 1
    print(f"  예측그래프 {n} outlet (시계열+게이지+파이) → {out_root}")
    return n


def resolve_out_root(cfg, forecast: str) -> Path:
    """예측연월의 대시보드 폴더 경로 — dashboard_data.build 산출 위치와 동일."""
    return Path(cfg.PrjDir) / "4_drought_risk" / "forecast" / forecast


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swat_py.drought.figure",
                                 description="가뭄위험 대시보드 outlet별 그림 + ⑤ 게이지 생성")
    ap.add_argument("--config", default="config/swat_py.yaml",
                    help="swat_py 설정 (같은 폴더의 picaso-hydro.yaml 공통값 자동 병합)")
    ap.add_argument("--forecast", default=None,
                    help="예측연월 (기본: config 의 forecast.period)")
    ap.add_argument("--out-root", default=None,
                    help="대시보드 폴더 직접 지정 (기본: 4_drought_risk/forecast/{period})")
    args = ap.parse_args(argv)

    if args.out_root:
        out_root = Path(args.out_root)
    else:
        from swat_py.config import load_config
        cfg = load_config(args.config)
        forecast = args.forecast or getattr(cfg.Drought, "forecast", None)
        if not forecast:
            raise SystemExit("예측연월 미지정 — --forecast 또는 config forecast.period 필요")
        out_root = resolve_out_root(cfg, forecast)
    if not out_root.is_dir():
        raise SystemExit(f"대시보드 폴더 없음: {out_root}\n"
                         f"  → 먼저 dashboard_data.build 로 series.csv 등을 생성하세요.")
    make_all_figures(out_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
