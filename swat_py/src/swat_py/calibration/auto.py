"""자동 보정 통합 — DDS + SWAT 실행 + 결과 기록.

run_auto_calibration(cfg) 가 다음을 자동 수행:
  1. yaml.calibration.parameters 에서 보정 인자 범위·변경 방식 추출
  2. SWAT.exe 자동 다운로드 (필요 시)
  3. DDS 알고리즘으로 N 회 반복:
     a. 인자 샘플링
     b. default/ → calibration/runs/run_NNN/ 복사
     c. 인자 변경 (apply_parameter_set)
     d. SWAT 실행 (또는 mock evaluator)
     e. 출력 파싱 + 관측 vs 모의 비교 → 목적함수
     f. 시도 기록
  4. 결과 산출:
     a. all_runs.csv, top5_runs.csv
     b. parameter_changes.csv (default vs best)
     c. figures/ (metric_progression, scatter_top5, timeseries_top5)
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from swat_py.calibration.exe_download import ensure_swat_exe
from swat_py.calibration.modify import ParameterChange, apply_parameter_set
from swat_py.calibration.optimizer import dds_optimize
from swat_py.calibration.summary import (
    plot_metric_progression,
    plot_scatter_top_n,
    plot_timeseries_top_n,
    write_all_runs_csv,
    write_parameter_summary,
    write_top_n_csv,
)
from swat_py.metrics.performance import calc_all as calc_metrics


# ── 단일 시도 evaluator ─────────────────────────────────────────────────────

@dataclass
class CalibrationContext:
    """보정 실행 컨텍스트 — yaml + 폴더 + 다중 관측 자료."""
    cfg:               object                       # EnvConfig
    default_dir:       Path                          # 마스터 TxtInOut
    runs_dir:          Path                          # calibration/runs/
    param_defs:        List                          # _CalParameter list (yaml)
    observations:      List = field(default_factory=list)   # _Observation list (모두)
    obs_dfs:           Dict[str, pd.DataFrame] = field(default_factory=dict)
    # obs_dfs: {obs_id: DataFrame(date, value_column)}
    n_iterations:      int = 300
    seed:              int = 1
    keep_run_dirs:     bool = False                   # True 면 runs/run_NNN/ 보존
    sim_evaluator:     Optional[Callable] = None      # mock or real SWAT
    exe_path:          Optional[Path] = None          # SWAT.exe 경로

    history_full: List[dict] = field(default_factory=list)


# ── 가중 합 결합 (다중 obs) ────────────────────────────────────────────────

def _normalize_metric(value: float, objective: str) -> float:
    """objective 별 정규화 — 1.0 이 최선, 0.0 근처가 최악 (모두 max 방향).

    NSE/KGE/R² : 그대로  (이미 1.0 best, 음수면 더 나쁨)
    |PBIAS|    : 1 - |v|/100         (0% → 1.0, 100% → 0.0, 음수 → 1+v 까지)
    RMSE       : 1 / (1 + |v|)        (0 → 1.0, ∞ → 0)
    """
    obj = objective.upper()
    v = float(value)
    if obj in ("NSE", "KGE", "R2"):
        return v
    if obj == "PBIAS":
        return max(-1.0, 1.0 - abs(v) / 100.0)   # 200% bound 안에서 음수 방어
    if obj == "RMSE":
        return 1.0 / (1.0 + abs(v))
    return v


def _combined_objective(
    per_obs_metrics: List[Dict],
    observations: List,
) -> Tuple[float, Dict]:
    """obs 별 메트릭 + weight → 단일 스칼라 결합 (가중 합).

    Returns
    -------
    (combined_f, detail) — detail 에 각 obs 의 원본 메트릭·정규화값 포함
    """
    total = 0.0
    detail: Dict = {}
    for m, obs in zip(per_obs_metrics, observations):
        key = obs.objective.lower()
        v = m.get(key, -999.0 if key in ("nse", "kge", "r2") else 999.0)
        norm = _normalize_metric(v, obs.objective)
        total += float(obs.weight) * norm
        detail[f"{obs.id}__{obs.objective.lower()}"] = float(v)
        detail[f"{obs.id}__norm"] = float(norm)
    return total, detail


def _build_changes(param_defs, x: np.ndarray) -> List[ParameterChange]:
    """yaml.calibration.parameters[] + 값 벡터 → ParameterChange 리스트."""
    return [
        ParameterChange(
            file=p.file, parameter=p.key, value=float(x[i]),
            change_type=p.change_type,
        )
        for i, p in enumerate(param_defs)
    ]


def _evaluate_run(
    ctx: CalibrationContext,
    run_idx: int,
    x: np.ndarray,
) -> Dict:
    """단일 시도 — 모든 observations 에 대해 메트릭 계산 + 가중 합 결합.

    sim_evaluator 반환 형식 (mock 모드)
    -----------------------------------
    옵션 1: dict {obs_id: (dates, values)} — 다중 obs 명시
    옵션 2: tuple (dates, values) — 모든 obs 에 동일 시계열 적용 (단일 obs 호환)
    """
    if ctx.sim_evaluator is not None:
        sim_result = ctx.sim_evaluator(x, ctx)
        if isinstance(sim_result, dict):
            sim_by_obs = sim_result
        else:
            # tuple → 모든 obs 에 동일 시계열 (단일 obs 케이스 호환)
            sim_by_obs = {obs.id: sim_result for obs in ctx.observations}
    else:
        run_dir = ctx.runs_dir / f"run_{run_idx:04d}" / "TxtInOut"
        if run_dir.exists():
            shutil.rmtree(run_dir.parent)
        shutil.copytree(ctx.default_dir, run_dir)
        changes = _build_changes(ctx.param_defs, x)
        apply_parameter_set(run_dir, changes, model_type=ctx.cfg.ModelType)
        sim_by_obs = _extract_obs_from_swat_output(run_dir, ctx)

    # 각 obs 별 메트릭
    per_obs_metrics: List[Dict] = []
    for obs in ctx.observations:
        if obs.id not in sim_by_obs:
            per_obs_metrics.append({
                "nse": -999.0, "kge": -999.0, "r2": 0.0,
                "pbias": 999.0, "rmse": 999.0, "n": 0,
            })
            continue
        sim_dates, sim_values = sim_by_obs[obs.id]
        obs_df = ctx.obs_dfs[obs.id]
        m = _compute_metrics_paired(
            obs_df["date"].values, obs_df[obs.obs_column].values,
            sim_dates, sim_values,
        )
        per_obs_metrics.append(m)

    f_combined, detail = _combined_objective(per_obs_metrics, ctx.observations)

    # 정리 (실제 SWAT 모드만)
    if ctx.sim_evaluator is None and not ctx.keep_run_dirs:
        shutil.rmtree(ctx.runs_dir / f"run_{run_idx:04d}", ignore_errors=True)

    return {
        "iter":            run_idx,
        "x":               x.copy(),
        "f":               float(f_combined),
        "metrics_per_obs": per_obs_metrics,
        "detail":          detail,
        "sim_by_obs":      sim_by_obs,
    }


def _extract_obs_from_swat_output(run_dir: Path, ctx: CalibrationContext) -> Dict:
    """실제 SWAT 실행 후 outlet × variable 별로 시계열 추출 (run_swat + parse)."""
    exe = ctx.exe_path or (run_dir / ctx.cfg.Executable)
    if not exe.is_file():
        exe = ensure_swat_exe(run_dir, ctx.cfg.ModelType, ctx.cfg.Executable)
    elif not (run_dir / ctx.cfg.Executable).is_file():
        shutil.copy2(exe, run_dir / ctx.cfg.Executable)

    result = subprocess.run(
        [str(run_dir / ctx.cfg.Executable)],
        cwd=str(run_dir), capture_output=True, timeout=3600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"SWAT 실행 실패 (returncode={result.returncode}): "
            f"{result.stderr.decode('utf-8', errors='ignore')[:500]}"
        )

    # 각 obs 의 (outlet_id, variable) 에 맞는 컬럼 추출
    # SWAT-Plus 의 channel_sd_day.txt 컬럼: flo_out, sed_out, no3_out, solp_out, ...
    var_column_map_plus = {
        "flow": "flo_out",
        "ss":   "sed_out",     # ton/day
        "tn":   "no3_out",     # kg/day (단순화 — 실제는 no3 + org_n + nh4 + no2)
        "tp":   "solp_out",
    }
    out: Dict = {}
    if ctx.cfg.ModelType == "swat_plus":
        from swat_py.output.reader_swat_plus import parse_channel_sd_day
        df = parse_channel_sd_day(run_dir / "channel_sd_day.txt")
        for obs in ctx.observations:
            col = var_column_map_plus.get(obs.variable, "flo_out")
            sub = df[df.get("gis_id", df.get("unit", 0)) == obs.outlet_id]
            if len(sub) == 0:
                sub = df   # outlet 못 찾으면 전체 (fallback)
            out[obs.id] = (sub["date"].values, sub[col].values)
    else:
        from swat_py.output.reader_swat import parse_output_rch
        df = parse_output_rch(run_dir / "output.rch")
        for obs in ctx.observations:
            sub = df[df.get("RCH", 0) == obs.outlet_id]
            out[obs.id] = (sub["date"].values, sub.get("FLOW_OUTcms", sub["flo_out"]).values)
    return out


def _compute_metrics_paired(obs_dates, obs_values, sim_dates, sim_values):
    """관측·모의 같은 날짜로 매칭 후 메트릭 계산."""
    obs = pd.DataFrame({"date": pd.to_datetime(obs_dates),
                        "obs":  np.asarray(obs_values, dtype=float)})
    sim = pd.DataFrame({"date": pd.to_datetime(sim_dates),
                        "sim":  np.asarray(sim_values, dtype=float)})
    obs.loc[(obs["obs"] < -50), "obs"] = np.nan
    paired = obs.merge(sim, on="date", how="inner").dropna()
    if len(paired) < 5:
        return {"nse": -999.0, "kge": -999.0, "r2": 0.0,
                "pbias": 999.0, "rmse": 999.0, "n": len(paired)}
    m = calc_metrics(paired["obs"].values, paired["sim"].values)
    # NaN → -999 / 999 (DDS 안전)
    out = {}
    for k, v in m.items():
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            out[k.lower()] = -999.0 if k.lower() in ("nse","kge","r2") else 999.0
        else:
            out[k.lower()] = v
    return out


# ── 통합 함수 ──────────────────────────────────────────────────────────────

def run_auto_calibration(
    cfg,
    *,
    sim_evaluator: Optional[Callable] = None,
    keep_run_dirs: bool = False,
    top_n: int = 5,
) -> Dict:
    """yaml.calibration 설정 따라 자동 보정 (DDS 알고리즘).

    Parameters
    ----------
    cfg            : load_config 의 결과 EnvConfig
    sim_evaluator  : (run_dir, x, ctx) → (dates, values) — None 이면 실제 SWAT
                     실행. 기능 테스트 시 mock 함수 주입 가능.
    keep_run_dirs  : True 면 runs/run_NNN/ 보존 (디버깅)
    top_n          : 상위 N 등 추출

    Returns
    -------
    dict — {best_x, best_f, history_full, results_dir, files}
    """
    # 1. 컨텍스트 준비
    default_dir = Path(cfg.DefaultDir)
    runs_dir    = Path(cfg.CalibrationDir) / "runs"
    results_dir = Path(cfg.CalibrationDir) / "results"
    runs_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    if not default_dir.is_dir() or not list(default_dir.iterdir()):
        raise RuntimeError(
            f"default 폴더가 비어 있음: {default_dir}\n"
            f"  QSWAT+ 결과 TxtInOut 을 default/ 에 배치하세요."
        )

    if not cfg.Observations:
        raise RuntimeError("yaml.calibration.observations 가 비어 있습니다.")

    # 모든 obs 의 자료 로드
    obs_dfs: Dict[str, pd.DataFrame] = {}
    for obs in cfg.Observations:
        df = pd.read_csv(obs.obs_file)
        if "date" not in df.columns:
            raise RuntimeError(f"관측 자료 'date' 컬럼 없음: {obs.obs_file}")
        if obs.obs_column not in df.columns:
            raise RuntimeError(
                f"관측 자료 '{obs.id}' 에 '{obs.obs_column}' 컬럼 없음 "
                f"(가능: {list(df.columns)})"
            )
        obs_dfs[obs.id] = df

    # SWAT exe 보장 (mock 시 skip)
    exe_path: Optional[Path] = None
    if sim_evaluator is None:
        exe_path = ensure_swat_exe(default_dir, cfg.ModelType, cfg.Executable)

    ctx = CalibrationContext(
        cfg=cfg, default_dir=default_dir, runs_dir=runs_dir,
        param_defs=cfg.CalParameters,
        observations=list(cfg.Observations),
        obs_dfs=obs_dfs,
        n_iterations=cfg.CalMethod.n_iterations,
        seed=cfg.CalMethod.seed,
        keep_run_dirs=keep_run_dirs,
        sim_evaluator=sim_evaluator,
        exe_path=exe_path,
    )

    # 결합 가중 합은 항상 큰 값이 좋음 (정규화 후 max 방향)
    ctx_maximize = True

    # DDS bounds
    bounds = [(p.range[0], p.range[1]) for p in cfg.CalParameters]
    param_names = [f"{p.file}::{p.key}" for p in cfg.CalParameters]
    history_full: List[Dict] = []

    iter_counter = [0]
    def _eval_wrapper(x: np.ndarray) -> float:
        iter_counter[0] += 1
        rec = _evaluate_run(ctx, iter_counter[0], x)
        history_full.append(rec)
        return rec["f"]

    print("=" * 64)
    print(f"  Auto-Calibration — DDS ({ctx.n_iterations} iterations)")
    print("=" * 64)
    print(f"  default       : {default_dir}")
    print(f"  n_parameters  : {len(cfg.CalParameters)}")
    print(f"  n_observations: {len(ctx.observations)}")
    for o in ctx.observations:
        print(f"    {o.id:<20s} outlet={o.outlet_id} var={o.variable}({o.unit}) "
              f"step={o.time_step} w={o.weight} obj={o.objective}")
    print(f"  결합 방식     : 가중 합 (정규화 후), maximize")
    print(f"  perturbation  : r=0.20")
    print(f"  seed          : {ctx.seed}")
    print("=" * 64)

    def _callback(i, x, f, is_best):
        marker = "★" if is_best else "  "
        if i <= 5 or i % 20 == 0 or is_best:
            print(f"  {marker} iter {i:>4d}  f={f:8.4f}  "
                  f"n_changed={history_full[-1].get('n_dims_changed','?')}")

    result = dds_optimize(
        evaluate=_eval_wrapper, bounds=bounds,
        n_iterations=ctx.n_iterations,
        r=0.20, maximize=ctx_maximize, seed=ctx.seed,
        callback=lambda i, x, f, is_best: _callback(i, x, f, is_best),
    )

    print()
    print(f"  완료: best f_combined = {result.best_f:.4f}")

    # ── 결과 산출 ────────────────────────────────────────────────────
    # history_summary: iter, f_combined, obs 별 메트릭 추가
    history_summary = []
    for h in history_full:
        rec = {"iter": h["iter"], "x": h["x"], "f": h["f"]}
        for k, v in h.get("detail", {}).items():
            rec[k] = v
        history_summary.append(rec)

    all_csv  = write_all_runs_csv(history_summary, param_names,
                                    results_dir / "all_runs.csv")
    top_csv  = write_top_n_csv(history_summary, param_names,
                                 results_dir / f"top{top_n}_runs.csv",
                                 n=top_n, maximize=ctx_maximize)
    pchg_csv = write_parameter_summary(history_full, cfg.CalParameters,
                                         results_dir / "parameter_changes.csv",
                                         maximize=ctx_maximize)

    # 그래프
    fig_dir = results_dir / "figures"
    fig_dir.mkdir(exist_ok=True)
    plot_metric_progression(history_full, fig_dir / "metric_progression.png",
                             title="DDS — Combined Objective (weighted sum)",
                             maximize=ctx_maximize)

    # obs 별 그래프 (상위 N 의 sim 시계열)
    sorted_hist = sorted(history_full, key=lambda h: h["f"], reverse=ctx_maximize)
    top_records = sorted_hist[:top_n]

    obs_figures: List[Path] = []
    for obs in ctx.observations:
        # 각 obs 의 sim_dict 구성
        sim_dict: Dict[int, Sequence[float]] = {}
        metric_dict: Dict[int, float] = {}
        for rank, rec in enumerate(top_records, start=1):
            if obs.id not in rec.get("sim_by_obs", {}):
                continue
            sim_dates, sim_values = rec["sim_by_obs"][obs.id]
            sim_dict[rank] = sim_values
            # 해당 obs 의 메트릭 (이 시도에서)
            try:
                obs_idx = [o.id for o in ctx.observations].index(obs.id)
                metric_dict[rank] = rec["metrics_per_obs"][obs_idx].get(
                    obs.objective.lower(), 0.0
                )
            except Exception:
                metric_dict[rank] = 0.0

        if not sim_dict:
            continue

        obs_df = ctx.obs_dfs[obs.id]
        obs_dates = pd.to_datetime(obs_df["date"].values)
        ref_dates = pd.to_datetime(top_records[0]["sim_by_obs"][obs.id][0])
        common = pd.Series(obs_dates).isin(ref_dates).values
        common_dates = obs_dates[common]
        obs_aligned = obs_df.set_index(pd.to_datetime(obs_df["date"])
                                       ).reindex(common_dates)[obs.obs_column].values

        sim_aligned: Dict[int, Sequence[float]] = {}
        for rank, rec in enumerate(top_records, start=1):
            if obs.id not in rec.get("sim_by_obs", {}):
                continue
            sd, sv = rec["sim_by_obs"][obs.id]
            sim_idx = pd.Series(pd.to_datetime(sd)).isin(common_dates).values
            sim_aligned[rank] = pd.Series(sv)[sim_idx].values

        f_scatter = fig_dir / f"scatter_top{top_n}_{obs.id}.png"
        f_ts      = fig_dir / f"timeseries_top{top_n}_{obs.id}.png"
        plot_scatter_top_n(common_dates, obs_aligned, sim_aligned, f_scatter,
                            title=f"{obs.id} — Observed vs Simulated (Top {top_n})",
                            metric_dict=metric_dict)
        plot_timeseries_top_n(common_dates, obs_aligned, sim_aligned, f_ts,
                              title=f"{obs.id} — Time Series (Top {top_n})",
                              metric_dict=metric_dict)
        obs_figures.extend([f_scatter, f_ts])

    return {
        "best_x":       result.best_x,
        "best_f":       result.best_f,
        "history_full": history_full,
        "results_dir":  results_dir,
        "files": {
            "all_runs":          all_csv,
            "top_runs":          top_csv,
            "parameter_changes": pchg_csv,
            "figures":           fig_dir,
        },
        "obs_figures": obs_figures,
    }
