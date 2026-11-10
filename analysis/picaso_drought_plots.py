"""PICASO 가뭄예측성 시각화 — 히트맵 + 최저강수/최고예측성 상세.

picaso_drought_skill.py 산출 CSV(reports/06_계절예측_가뭄예측성/)를 읽어:
  - forecast_bn_heatmap.png : 연×시즌 예측 BN%(가뭄확률) 히트맵 + 실제가뭄 표시
  - drought_skill_top.png   : 가뭄 예측성 top 파일의 예측 tercile vs 관측
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Malgun Gothic"   # 한글 폰트 (Windows)
plt.rcParams["axes.unicode_minus"] = False


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


OUT = _picaso_root() / "reports" / "06_계절예측_가뭄예측성"
SEASON_ORDER = ["JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA",
                "JAS", "ASO", "SON", "OND", "NDJ", "DJF"]


def heatmap():
    fs = pd.read_csv(OUT / "file_skill.csv")
    fc = pd.read_csv(OUT / "forecast_prcp_tidy.csv")
    mean_bn = (fc.groupby(["file_year", "season"])["BN"].mean().reset_index())
    piv = mean_bn.pivot(index="file_year", columns="season", values="BN")
    piv = piv.reindex(columns=SEASON_ORDER)
    drought = fs.set_index(["file_year", "season"])["is_drought"].to_dict()

    fig, ax = plt.subplots(figsize=(12, 7))
    im = ax.imshow(piv.values, aspect="auto", cmap="YlOrBr", vmin=20, vmax=80)
    ax.set_xticks(range(len(SEASON_ORDER))); ax.set_xticklabels(SEASON_ORDER)
    ax.set_yticks(range(len(piv.index))); ax.set_yticklabels(piv.index)
    ax.set_xlabel("season (3-month)"); ax.set_ylabel("forecast year")
    ax.set_title("PICASO 예측 강수 정상이하(BN) 확률 [%] — 라로통가(91843)\n"
                 "값↑=가뭄 예측 강함 · ● = 실제 관측 가뭄 시즌(관측 BN 과반)", fontsize=13)
    for i, yr in enumerate(piv.index):
        for j, se in enumerate(SEASON_ORDER):
            v = piv.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7.5,
                        color="black" if v < 55 else "white")
                if drought.get((yr, se), False):
                    ax.plot(j, i, "o", ms=4, mfc="none", mec="#1f77b4", mew=1.6)
    fig.colorbar(im, ax=ax, label="mean BN prob (%)", fraction=0.025)
    fig.tight_layout(); fig.savefig(OUT / "forecast_bn_heatmap.png", dpi=180)
    plt.close(fig)


def top_detail():
    fs = pd.read_csv(OUT / "file_skill.csv")
    fc = pd.read_csv(OUT / "forecast_prcp_tidy.csv")
    obs = pd.read_csv(OUT / "observed_monthly_tercile.csv")
    top = fs[fs["is_drought"]].sort_values("drought_skill", ascending=False).head(3)

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6))
    for ax, (_, r) in zip(axes, top.iterrows()):
        sub = fc[fc["file"] == r["file"]].sort_values(["target_year", "target_month"])
        x = np.arange(len(sub))
        ax.bar(x, sub["BN"], color="#c44", label="BN(가뭄)")
        ax.bar(x, sub["NN"], bottom=sub["BN"], color="#ccc", label="NN")
        ax.bar(x, sub["AN"], bottom=sub["BN"] + sub["NN"], color="#48c", label="AN")
        # 관측 실제 tercile 표시
        for xi, (_, s) in zip(x, sub.iterrows()):
            o = obs[(obs.year == s.target_year) & (obs.month == s.target_month)]
            cat = o["obs_cat"].iloc[0] if len(o) else "?"
            ax.text(xi, 103, f"관측:{cat}", ha="center", fontsize=8,
                    color="#c44" if cat == "BN" else "#333")
        ax.set_xticks(x)
        ax.set_xticklabels([f"{int(s.target_year)}-{int(s.target_month):02d}"
                            for _, s in sub.iterrows()], rotation=45, fontsize=8)
        ax.set_ylim(0, 112); ax.set_ylabel("tercile prob (%)")
        ax.set_title(f"{r['file']}\nRPSS={r['RPSS']:+.2f} 적중 {int(r['dry_hits'])}/{int(r['n'])}",
                     fontsize=10)
    axes[0].legend(loc="lower left", fontsize=8, ncol=3)
    fig.suptitle("실제 가뭄 대비 예측성 상위 3개 파일 — 예측 tercile vs 관측", fontsize=13)
    fig.tight_layout(); fig.savefig(OUT / "drought_skill_top.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    heatmap(); top_detail()
    print(f"그림 저장 → {OUT}")
