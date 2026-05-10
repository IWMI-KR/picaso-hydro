"""ERA5 격자점 vs 관측소(GSOD/local) 산점 검증.

워크플로우
----------
1. ERA5 grid_points-era5.csv 와 obs station 메타 (GSOD/local) 읽기
2. 각 ERA5 격자점에 대해 **haversine 최근접 관측소 1개** 선정
3. 표준 일자료 CSV 두 개 로드 → ``date`` 기준 inner join + NaN 행 제거
4. 변수별 1:1 산점도 (학술지 스타일, 빈 원 마커)
5. pair × 변수 통계 → ``statistics.csv``

출력 구조
---------
{output_dir}/
├── nearest_pairs.csv            ERA5 → 최근접 obs 매칭 + 거리
├── statistics.csv               pair × 변수 통계 (N, R², RMSE, MAE, Bias 등)
└── plots/
    ├── pcp_mm/
    │   ├── {era5_id}__{obs_id}.png
    │   └── ...
    └── (변수별)/

ERA5 라벨 = X 축, 관측 = Y 축 (사용자 요구).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

# 비교 가능 변수 + 단위 라벨 + 표준 컬럼명
_VAR_LABELS: Dict[str, Tuple[str, str]] = {
    "pcp_mm":   ("Precipitation", "mm/day"),
    "tmax_c":   ("Maximum temperature", "°C"),
    "tmin_c":   ("Minimum temperature", "°C"),
    "tavg_c":   ("Mean temperature", "°C"),
    "tdew_c":   ("Dewpoint temperature", "°C"),
    "hmd_pct":  ("Relative humidity", "%"),
    "ws10_ms":  ("10-m wind speed", "m/s"),
    "ws2_ms":   ("2-m wind speed", "m/s"),
    "slr_mjm2": ("Solar radiation", "MJ/m²/day"),
}

DEFAULT_VARIABLES = ["pcp_mm", "tmax_c", "tmin_c", "tavg_c",
                     "tdew_c", "hmd_pct", "ws10_ms"]


# ── 거리 + 매칭 ──────────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2) -> float | np.ndarray:
    """Haversine 거리 (km)."""
    R = 6371.0088
    lat1, lon1, lat2, lon2 = (np.radians(lat1), np.radians(lon1),
                              np.radians(lat2), np.radians(lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2.0 * R * np.arcsin(np.sqrt(a))


def find_nearest_pairs(
    era5_pts: pd.DataFrame,
    obs_pts: pd.DataFrame,
    *,
    radius_km: Optional[float] = 10.0,
    era5_lat="Lat", era5_lon="Lon", era5_id="ID",
    obs_lat="LAT", obs_lon="LON", obs_id="STATION_ID",
) -> pd.DataFrame:
    """각 ERA5 격자점에 대해 obs station pair 생성.

    매칭 규칙
    ----------
    * ``radius_km`` 이내에 station 이 1개 이상 있으면 → **모두 pair 생성** (다중)
    * ``radius_km`` 이내에 없으면 → **가장 가까운 1개** (fallback)
    * ``radius_km=None`` 또는 0 → 항상 nearest 1개 (옛 동작)

    Returns
    -------
    DataFrame with columns:
      era5_id, era5_lat, era5_lon, obs_id, obs_lat, obs_lon, distance_km, within_radius
    """
    rows = []
    obs_lat_arr = obs_pts[obs_lat].to_numpy()
    obs_lon_arr = obs_pts[obs_lon].to_numpy()
    obs_id_arr  = obs_pts[obs_id].astype(str).to_numpy()

    use_radius = radius_km is not None and radius_km > 0

    for _, r in era5_pts.iterrows():
        d = haversine_km(float(r[era5_lat]), float(r[era5_lon]),
                         obs_lat_arr, obs_lon_arr)

        if use_radius:
            within_idx = np.where(d <= radius_km)[0]
            if len(within_idx) > 0:
                # 거리 오름차순 정렬
                within_idx = within_idx[np.argsort(d[within_idx])]
                for idx in within_idx:
                    rows.append({
                        "era5_id":       str(r[era5_id]),
                        "era5_lat":      round(float(r[era5_lat]), 4),
                        "era5_lon":      round(float(r[era5_lon]), 4),
                        "obs_id":        obs_id_arr[idx],
                        "obs_lat":       round(float(obs_lat_arr[idx]), 4),
                        "obs_lon":       round(float(obs_lon_arr[idx]), 4),
                        "distance_km":   round(float(d[idx]), 2),
                        "within_radius": True,
                    })
                continue

        # fallback: nearest 1개
        idx = int(np.argmin(d))
        rows.append({
            "era5_id":       str(r[era5_id]),
            "era5_lat":      round(float(r[era5_lat]), 4),
            "era5_lon":      round(float(r[era5_lon]), 4),
            "obs_id":        obs_id_arr[idx],
            "obs_lat":       round(float(obs_lat_arr[idx]), 4),
            "obs_lon":       round(float(obs_lon_arr[idx]), 4),
            "distance_km":   round(float(d[idx]), 2),
            "within_radius": False,
        })
    return pd.DataFrame(rows)


# ── 통계 ─────────────────────────────────────────────────────────────────────

def compute_stats(x: pd.Series, y: pd.Series) -> Dict[str, float]:
    """ERA5(x) vs OBS(y) 통계.

    Returns dict: n, r, r2, rmse, mae, bias, slope, intercept, mean_x, mean_y
    """
    valid = (~x.isna()) & (~y.isna())
    x = x[valid].to_numpy(dtype=float)
    y = y[valid].to_numpy(dtype=float)
    n = len(x)
    out: Dict[str, float] = {"n": n}
    if n < 2:
        for k in ("r", "r2", "rmse", "mae", "bias", "slope", "intercept",
                  "mean_x", "mean_y"):
            out[k] = float("nan")
        return out
    r = float(np.corrcoef(x, y)[0, 1])
    rmse = float(np.sqrt(np.mean((y - x) ** 2)))
    mae  = float(np.mean(np.abs(y - x)))
    bias = float(np.mean(y - x))
    slope, intercept = np.polyfit(x, y, 1)
    out.update({
        "r":         round(r, 4),
        "r2":        round(r ** 2, 4),
        "rmse":      round(rmse, 4),
        "mae":       round(mae, 4),
        "bias":      round(bias, 4),
        "slope":     round(float(slope), 4),
        "intercept": round(float(intercept), 4),
        "mean_x":    round(float(np.mean(x)), 4),
        "mean_y":    round(float(np.mean(y)), 4),
    })
    return out


# ── 산점도 (학술지 스타일) ──────────────────────────────────────────────────

def _draw_scatter_on_axes(
    ax,
    x: pd.Series,
    y: pd.Series,
    xlabel: str,
    ylabel: str,
    *,
    title: Optional[str] = None,
    marker_size: float = 25.0,
    show_regression: bool = False,
) -> None:
    """주어진 Axes 에 1:1 산점도 그리기 (학술지 스타일)."""
    valid = (~x.isna()) & (~y.isna())
    xv = x[valid].to_numpy(dtype=float)
    yv = y[valid].to_numpy(dtype=float)

    if len(xv) > 0:
        ax.scatter(xv, yv,
                   s=marker_size, marker="o",
                   facecolors="none", edgecolors="black",
                   linewidths=0.6, alpha=0.7)

        lo = min(xv.min(), yv.min())
        hi = max(xv.max(), yv.max())
        margin = (hi - lo) * 0.05 if hi > lo else 0.5
        lo, hi = lo - margin, hi + margin

        # 1:1 라인 (학술지 표준)
        ax.plot([lo, hi], [lo, hi], color="black", linewidth=0.7, linestyle="-")

        # 회귀선 (옵션)
        if show_regression and len(xv) >= 2:
            slope, intercept = np.polyfit(xv, yv, 1)
            xx = np.array([lo, hi])
            ax.plot(xx, slope * xx + intercept,
                    color="gray", linewidth=0.7, linestyle="--")

        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
    else:
        ax.text(0.5, 0.5, "no valid data", ha="center", va="center",
                transform=ax.transAxes, fontsize=10, color="gray")

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    if title:
        ax.set_title(title, fontsize=10)
    ax.tick_params(labelsize=9)
    ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.5)
    for spine in ax.spines.values():
        spine.set_linewidth(0.6)


def plot_scatter_one_to_one(
    x: pd.Series,
    y: pd.Series,
    xlabel: str,
    ylabel: str,
    output_path: Union[str, Path],
    *,
    title: Optional[str] = None,
    dpi: int = 300,
    figsize: Tuple[float, float] = (4.5, 4.5),
    marker_size: float = 25.0,
    show_regression: bool = False,
) -> Path:
    """학술지 스타일 1:1 산점도 (단일 변수, 단일 페이지)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    _draw_scatter_on_axes(ax, x, y, xlabel, ylabel,
                           title=title, marker_size=marker_size,
                           show_regression=show_regression)
    plt.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return output_path


def plot_combined_pair(
    df_merged: pd.DataFrame,
    output_path: Union[str, Path],
    *,
    variables: List[str],
    obs_source: str = "GSOD",
    suptitle: Optional[str] = None,
    ncols: int = 4,
    dpi: int = 300,
    show_regression: bool = False,
) -> Path:
    """한 (era5, obs) pair 의 **모든 변수**를 한 페이지 다중 패널로.

    Parameters
    ----------
    df_merged       : ERA5+OBS 가 ``date`` 로 join 된 DataFrame.
                      ERA5 컬럼: ``{var}_era5``, OBS 컬럼: ``{var}_obs``
    output_path     : 결과 PNG 경로
    variables       : 패널화할 변수 목록 (순서대로)
    obs_source      : Y축 라벨 prefix
    suptitle        : 페이지 상단 제목
    ncols           : subplot 열 수 (기본 4)
    """
    import math

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    nrows = math.ceil(len(variables) / ncols)
    panel_size = 3.4
    fig, axes = plt.subplots(nrows, ncols,
                              figsize=(panel_size * ncols, panel_size * nrows + 0.4),
                              dpi=dpi)
    axes_flat = axes.flatten() if hasattr(axes, "flatten") else [axes]

    for i, var in enumerate(variables):
        ax = axes_flat[i]
        era_col = f"{var}_era5"
        obs_col = f"{var}_obs"
        if era_col not in df_merged.columns or obs_col not in df_merged.columns:
            ax.text(0.5, 0.5, f"{var}\nno data", ha="center", va="center",
                    transform=ax.transAxes, fontsize=10, color="gray")
            ax.set_xticks([]); ax.set_yticks([])
            continue

        x = df_merged[era_col]
        y = df_merged[obs_col]
        label, unit = _VAR_LABELS.get(var, (var, ""))
        xlabel = f"ERA5 ({unit})"
        ylabel = f"{obs_source} ({unit})"

        # subplot title: 변수 + N + R²
        s = compute_stats(x, y)
        n = s["n"]; r2 = s["r2"]
        title = f"{label}  (n={n}, R²={r2:.3f})" if not pd.isna(r2) else f"{label}  (n={n})"

        _draw_scatter_on_axes(ax, x, y, xlabel, ylabel,
                               title=title, show_regression=show_regression)

    # 미사용 패널 숨김
    for j in range(len(variables), len(axes_flat)):
        axes_flat[j].set_visible(False)

    if suptitle:
        fig.suptitle(suptitle, fontsize=12, y=0.99)

    fig.tight_layout(rect=[0, 0, 1, 0.97] if suptitle else None)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return output_path


# ── 메인 함수 ────────────────────────────────────────────────────────────────

def scatter_compare_era5_obs(
    era5_grid_points_csv: Union[str, Path],
    era5_std_dir: Union[str, Path],
    obs_station_csv: Union[str, Path],
    obs_std_dir: Union[str, Path],
    output_dir: Union[str, Path],
    *,
    variables: Optional[List[str]] = None,
    obs_source: str = "GSOD",
    era5_id_col: str = "ID",
    era5_lat_col: str = "Lat",
    era5_lon_col: str = "Lon",
    obs_id_col: str = "STATION_ID",
    obs_lat_col: str = "LAT",
    obs_lon_col: str = "LON",
    radius_km: Optional[float] = 10.0,
    show_regression: bool = False,
    write_per_variable: bool = True,
    write_combined: bool = True,
    combined_ncols: int = 4,
) -> Dict[str, Path]:
    """ERA5 격자점 vs 관측소 산점 검증 일괄 실행.

    Parameters
    ----------
    era5_grid_points_csv : ERA5 격자점 메타 CSV (Lon, Lat, ID, ...)
    era5_std_dir         : ERA5 표준 일자료 폴더 (각 ID 별 .csv)
    obs_station_csv      : obs station 메타 CSV
    obs_std_dir          : obs 표준 일자료 폴더
    output_dir           : 결과 저장 폴더 (analysis/era5_vs_{source})
    variables            : 비교 변수 (기본 7개 SWAT 핵심)
    obs_source           : "GSOD" | "USER" (출력 메타 표기용)
    radius_km            : 매칭 반경 (km). 이내 모든 station 채택, 없으면 nearest 1개.
                           ``None`` 또는 0 이면 항상 nearest 1개.
    show_regression      : 그래프에 회귀선 추가 (기본 1:1 만)
    write_per_variable   : 변수별 단일 패널 PNG (plots/{var}/) 작성
    write_combined       : pair 별 다변수 통합 PNG (plots/combined/) 작성
    combined_ncols       : combined plot 의 subplot 열 수 (기본 4)

    Returns
    -------
    dict : {"pairs": Path, "stats": Path, "plots_dir": Path}
    """
    variables = variables or DEFAULT_VARIABLES
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    era5_pts = pd.read_csv(era5_grid_points_csv)
    obs_pts  = pd.read_csv(obs_station_csv)

    # ── 1. 매칭 (10km 이내 다수 / 없으면 nearest 1) ──────────────────────
    pairs = find_nearest_pairs(
        era5_pts, obs_pts, radius_km=radius_km,
        era5_lat=era5_lat_col, era5_lon=era5_lon_col, era5_id=era5_id_col,
        obs_lat=obs_lat_col, obs_lon=obs_lon_col, obs_id=obs_id_col,
    )
    pairs_csv = output_dir / "nearest_pairs.csv"
    pairs.to_csv(pairs_csv, index=False)

    n_within = int(pairs["within_radius"].sum()) if "within_radius" in pairs.columns else 0
    n_fallback = len(pairs) - n_within

    print("=" * 68)
    print(f"  ERA5 vs {obs_source} 산점 검증")
    print("=" * 68)
    print(f"  ERA5 격자점       : {len(era5_pts)}")
    print(f"  관측소             : {len(obs_pts)}")
    print(f"  반경 임계          : {radius_km} km")
    print(f"  매칭 pair          : {len(pairs)} (이내 {n_within}, fallback {n_fallback})")
    print(f"  변수               : {variables}")
    print(f"  output_dir         : {output_dir}")
    print(f"  매칭 거리 분포      : median={pairs['distance_km'].median():.1f} km, "
          f"max={pairs['distance_km'].max():.1f} km")
    print(f"  per-variable PNG   : {write_per_variable}")
    print(f"  combined PNG       : {write_combined}")
    print("=" * 68)
    print()

    plots_dir = output_dir / "plots"
    combined_dir = plots_dir / "combined"
    stats_rows: List[Dict] = []

    era5_std = Path(era5_std_dir)
    obs_std  = Path(obs_std_dir)

    for _, p in pairs.iterrows():
        era5_csv = era5_std / f"{p['era5_id']}.csv"
        obs_csv  = obs_std  / f"{p['obs_id']}.csv"
        if not era5_csv.is_file() or not obs_csv.is_file():
            print(f"  [MISS] {p['era5_id']} or {p['obs_id']}: std 파일 없음")
            continue

        df_era = pd.read_csv(era5_csv, parse_dates=["date"])
        df_obs = pd.read_csv(obs_csv,  parse_dates=["date"])
        df = df_era.merge(df_obs, on="date", suffixes=("_era5", "_obs"))

        # 변수별 통계 + (옵션) 단일 패널 PNG
        for var in variables:
            era_col = f"{var}_era5"
            obs_col = f"{var}_obs"
            if era_col not in df.columns or obs_col not in df.columns:
                continue
            x = df[era_col]
            y = df[obs_col]
            valid = (~x.isna()) & (~y.isna())
            n_valid = int(valid.sum())

            stats = compute_stats(x, y)
            stats_rows.append({
                "era5_id":     p["era5_id"],
                "obs_id":      p["obs_id"],
                "distance_km": p["distance_km"],
                "variable":    var,
                **stats,
            })

            if not write_per_variable or n_valid < 2:
                continue

            label, unit = _VAR_LABELS.get(var, (var, ""))
            xlabel = f"ERA5 {label} ({unit})"
            ylabel = f"{obs_source} {label} ({unit})"
            title  = (f"{p['era5_id']}  vs  {p['obs_id']}   "
                      f"(d={p['distance_km']} km, n={stats['n']}, R²={stats['r2']})")
            out_png = plots_dir / var / f"{p['era5_id']}__{p['obs_id']}.png"
            plot_scatter_one_to_one(
                x, y, xlabel, ylabel, out_png,
                title=title, show_regression=show_regression,
            )

        # 다변수 통합 PNG
        if write_combined:
            suptitle = (f"ERA5 vs {obs_source}:  {p['era5_id']}  ↔  {p['obs_id']}   "
                        f"(d={p['distance_km']:.1f} km)")
            out_combined = combined_dir / f"{p['era5_id']}__{p['obs_id']}.png"
            plot_combined_pair(
                df, out_combined,
                variables=variables, obs_source=obs_source,
                suptitle=suptitle, ncols=combined_ncols,
                show_regression=show_regression,
            )

        print(f"  [OK]  {p['era5_id']:<10s} ↔ {p['obs_id']:<14s} "
              f"(d={p['distance_km']:>5.1f} km, "
              f"{'within' if p.get('within_radius', False) else 'nearest'})")

    # 통계 테이블 저장
    stats_df = pd.DataFrame(stats_rows)
    stats_csv = output_dir / "statistics.csv"
    stats_df.to_csv(stats_csv, index=False)

    n_plots = sum(1 for _ in plots_dir.rglob("*.png")) if plots_dir.is_dir() else 0
    n_combined = (sum(1 for _ in combined_dir.glob("*.png"))
                  if combined_dir.is_dir() else 0)
    print()
    print("=" * 68)
    print(f"  완료")
    print(f"  - nearest_pairs : {pairs_csv.name}  ({len(pairs)} rows)")
    print(f"  - statistics    : {stats_csv.name}  ({len(stats_df)} rows)")
    print(f"  - plots         : {n_plots}개 (per-var {n_plots - n_combined}, "
          f"combined {n_combined})")
    print(f"  - 출력 폴더     : {plots_dir}")
    print("=" * 68)

    return {"pairs": pairs_csv, "stats": stats_csv,
            "plots_dir": plots_dir, "combined_dir": combined_dir}
