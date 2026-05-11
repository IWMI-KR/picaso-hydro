"""보정 결과 표·그래프 산출.

기능
----
- write_all_runs_csv      : 모든 시도 (수렴 분석용)
- write_top_n_csv         : 상위 N등 (보정 후보)
- write_parameter_changes : default vs best 인자 변경 표
- plot_metric_progression : 반복 vs 목적함수 진화
- plot_scatter_top_n      : 관측 vs 모의 산점도 (상위 N)
- plot_timeseries_top_n   : 관측 + 상위 N 시계열
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd


# ── 표 산출 ─────────────────────────────────────────────────────────────────

def write_all_runs_csv(
    history: List[dict],
    param_names: List[str],
    output_csv: Union[str, Path],
) -> Path:
    """history → CSV.

    컬럼: iter, [params...], f, [is_best, n_dims_changed], [detail 키...]
    history[i] 에 'iter', 'x', 'f' 외에 임의의 추가 필드가 있으면 모두 포함.
    """
    _SKIP = {"iter", "x", "f"}
    rows = []
    for h in history:
        row = {"iter": h["iter"]}
        for i, name in enumerate(param_names):
            row[name] = h["x"][i]
        row["f"] = h["f"]
        # 추가 필드 (is_best, n_dims_changed, detail__keys, metrics_per_obs 제외)
        for k, v in h.items():
            if k in _SKIP:
                continue
            if isinstance(v, (int, float, bool, str)):
                row[k] = v
        rows.append(row)
    df = pd.DataFrame(rows)
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    return output_csv


def write_top_n_csv(
    history: List[dict],
    param_names: List[str],
    output_csv: Union[str, Path],
    *,
    n: int = 5,
    maximize: bool = True,
) -> Path:
    """상위 N개 시도 → CSV (랭킹, iter, params, f, 그 외 스칼라 필드)."""
    _SKIP = {"iter", "x", "f"}
    records = []
    for h in history:
        rec = {"iter": h["iter"]}
        for i, name in enumerate(param_names):
            rec[name] = h["x"][i]
        rec["f"] = h["f"]
        for k, v in h.items():
            if k in _SKIP:
                continue
            if isinstance(v, (int, float, bool, str)):
                rec[k] = v
        records.append(rec)
    df_all = pd.DataFrame(records)
    df_sorted = df_all.sort_values("f", ascending=not maximize).head(n).copy()
    df_sorted.insert(0, "rank", range(1, len(df_sorted) + 1))
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df_sorted.to_csv(output_csv, index=False)
    return output_csv


def write_parameter_summary(
    history: List[dict],
    param_defs: List,         # ParameterChange or ParameterDef-like
    output_csv: Union[str, Path],
    *,
    maximize: bool = True,
) -> Path:
    """default 값 vs best 값 비교 표.

    param_defs[i] 는 .file, .parameter (or .key), .range, .change_type 속성 필요.
    """
    # best run 찾기
    fs = [h["f"] for h in history]
    best_idx = int(np.argmax(fs) if maximize else np.argmin(fs))
    best_x = history[best_idx]["x"]

    rows = []
    for i, p in enumerate(param_defs):
        name = getattr(p, "key", None) or getattr(p, "parameter", None) \
               or getattr(p, "name_swat_plus", None)
        rows.append({
            "file":        getattr(p, "file", ""),
            "parameter":   name,
            "range_min":   p.range[0] if hasattr(p, "range") else "",
            "range_max":   p.range[1] if hasattr(p, "range") else "",
            "best_value":  best_x[i],
            "change_type": getattr(p, "change_type", "absval"),
        })
    df = pd.DataFrame(rows)
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    return output_csv


# ── 그래프 ─────────────────────────────────────────────────────────────────

def plot_metric_progression(
    history: List[dict],
    output_png: Union[str, Path],
    *,
    title: str = "DDS Calibration Progress",
    maximize: bool = True,
) -> Path:
    """반복 횟수 vs 목적함수 — best (누적) + each iteration."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    iters = [h["iter"] for h in history]
    fs    = [h["f"]    for h in history]
    running_best = []
    cur = fs[0]
    for f in fs:
        if (maximize and f > cur) or (not maximize and f < cur):
            cur = f
        running_best.append(cur)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.scatter(iters, fs, s=10, alpha=0.4, c="steelblue", label="each iteration")
    ax.plot(iters, running_best, "r-", lw=2, label="best so far")
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Objective" + (" (maximize)" if maximize else " (minimize)"))
    ax.set_title(title)
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=150)
    plt.close(fig)
    return output_png


def plot_scatter_top_n(
    obs_dates:    Sequence,
    obs_values:   Sequence[float],
    sim_dict:     Dict[int, Sequence[float]],  # {rank: sim_values}
    output_png:   Union[str, Path],
    *,
    title: str = "Observed vs Simulated (Top-N)",
    metric_dict:  Optional[Dict[int, float]] = None,
) -> Path:
    """관측 vs 모의 산점도 (상위 N 멤버 색별)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    obs_arr = np.asarray(obs_values, dtype=float)
    mask = ~np.isnan(obs_arr) & (obs_arr > -50)
    obs_v = obs_arr[mask]

    colors = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd"]
    for rank, sim in sim_dict.items():
        sim_arr = np.asarray(sim, dtype=float)[mask]
        c = colors[(rank - 1) % len(colors)]
        lbl = f"Rank {rank}"
        if metric_dict and rank in metric_dict:
            lbl += f" (f={metric_dict[rank]:.3f})"
        ax.scatter(obs_v, sim_arr, s=15, alpha=0.5,
                   facecolors="none", edgecolors=c, label=lbl)

    # 1:1 line
    lim_max = max(obs_v.max(), max(np.max(np.asarray(s, dtype=float)[mask])
                                    for s in sim_dict.values()))
    lim_min = min(obs_v.min(), min(np.min(np.asarray(s, dtype=float)[mask])
                                    for s in sim_dict.values()))
    ax.plot([lim_min, lim_max], [lim_min, lim_max], "k-", lw=1.0, alpha=0.7)
    ax.set_xlim(lim_min, lim_max); ax.set_ylim(lim_min, lim_max)
    ax.set_xlabel("Observed"); ax.set_ylabel("Simulated")
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=150)
    plt.close(fig)
    return output_png


def plot_timeseries_top_n(
    obs_dates:    Sequence,
    obs_values:   Sequence[float],
    sim_dict:     Dict[int, Sequence[float]],
    output_png:   Union[str, Path],
    *,
    title: str = "Time Series — Observed + Top-N",
    metric_dict:  Optional[Dict[int, float]] = None,
) -> Path:
    """관측 + 상위 N 시뮬레이션 시계열."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4.5))
    dates = pd.to_datetime(obs_dates)
    obs = np.asarray(obs_values, dtype=float)
    obs_masked = np.where((obs > -50) & ~np.isnan(obs), obs, np.nan)
    ax.plot(dates, obs_masked, "k-", lw=1.2, alpha=0.9, label="Observed")

    colors = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd"]
    for rank, sim in sim_dict.items():
        c = colors[(rank - 1) % len(colors)]
        lbl = f"Rank {rank}"
        if metric_dict and rank in metric_dict:
            lbl += f" (f={metric_dict[rank]:.3f})"
        ax.plot(dates, sim, "-", lw=0.8, alpha=0.7, color=c, label=lbl)

    ax.set_xlabel("Date"); ax.set_ylabel("Value")
    ax.set_title(title)
    ax.legend(loc="best", fontsize=8, ncol=2)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()

    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=150)
    plt.close(fig)
    return output_png
