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
from typing import Callable, Dict, List, Optional, Sequence, Union

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
    """보정 실행 컨텍스트 — yaml + 폴더 + 관측 자료."""
    cfg:               object                       # EnvConfig
    default_dir:       Path                          # 마스터 TxtInOut
    runs_dir:          Path                          # calibration/runs/
    param_defs:        List                          # _CalParameter list (yaml)
    objective_name:    str = "NSE"                   # NSE | KGE | R2 | PBIAS | RMSE
    maximize:          bool = True                    # NSE/KGE/R2 → True
    obs_df:            Optional[pd.DataFrame] = None  # date + value
    obs_column:        str = ""
    n_iterations:      int = 300
    seed:              int = 1
    keep_run_dirs:     bool = False                   # True 면 runs/run_NNN/ 보존
    sim_evaluator:     Optional[Callable] = None      # mock or real SWAT
    exe_path:          Optional[Path] = None          # SWAT.exe 경로

    history_full: List[dict] = field(default_factory=list)
    # history_full[i] = {iter, x, f, is_best, sim_values, sim_dates, ...}


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
    """단일 시도 실행 — TxtInOut 복사 + 인자 변경 + SWAT 또는 mock + 메트릭.

    mock evaluator 모드 (sim_evaluator 제공) 에서는 TxtInOut 복사·인자 변경 단계
    건너뛰고 evaluator(x, ctx) 만 호출 — 기능 테스트용 (실제 SWAT 실행 없음).
    """
    if ctx.sim_evaluator is not None:
        # mock 모드 — TxtInOut 변경 없음
        sim_dates, sim_values = ctx.sim_evaluator(x, ctx)
    else:
        run_dir = ctx.runs_dir / f"run_{run_idx:04d}" / "TxtInOut"
        if run_dir.exists():
            shutil.rmtree(run_dir.parent)
        shutil.copytree(ctx.default_dir, run_dir)
        changes = _build_changes(ctx.param_defs, x)
        apply_parameter_set(run_dir, changes, model_type=ctx.cfg.ModelType)
        sim_dates, sim_values = _run_swat_and_parse(run_dir, ctx)

    # 메트릭
    obs_dates  = ctx.obs_df["date"].values
    obs_values = ctx.obs_df[ctx.obs_column].values
    metrics = _compute_metrics_paired(obs_dates, obs_values,
                                       sim_dates, sim_values)
    f = _objective_value(metrics, ctx.objective_name)

    # 정리 (실제 SWAT 모드만 — run_dir 가 만들어졌을 때)
    if ctx.sim_evaluator is None and not ctx.keep_run_dirs:
        shutil.rmtree(ctx.runs_dir / f"run_{run_idx:04d}", ignore_errors=True)

    return {
        "iter":       run_idx,
        "x":          x.copy(),
        "f":          f,
        "metrics":    metrics,
        "sim_dates":  np.array(sim_dates),
        "sim_values": np.array(sim_values),
    }


def _run_swat_and_parse(run_dir: Path, ctx: CalibrationContext):
    """SWAT.exe 실행 + channel_sd_day.txt 또는 output.rch 파싱."""
    exe = ctx.exe_path or (run_dir / ctx.cfg.Executable)
    if not exe.is_file():
        # 다운로드 또는 default 복사로 보장
        exe = ensure_swat_exe(run_dir, ctx.cfg.ModelType, ctx.cfg.Executable)
    elif not (run_dir / ctx.cfg.Executable).is_file():
        shutil.copy2(exe, run_dir / ctx.cfg.Executable)

    # 실행
    result = subprocess.run(
        [str(run_dir / ctx.cfg.Executable)],
        cwd=str(run_dir), capture_output=True, timeout=3600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"SWAT 실행 실패 (returncode={result.returncode}): "
            f"{result.stderr.decode('utf-8', errors='ignore')[:500]}"
        )

    # 출력 파싱 — SWAT-Plus channel_sd_day.txt 첫 outlet
    if ctx.cfg.ModelType == "swat_plus":
        from swat_py.output.reader_swat_plus import parse_channel_sd_day
        df = parse_channel_sd_day(run_dir / "channel_sd_day.txt")
    else:
        from swat_py.output.reader_swat import parse_output_rch
        df = parse_output_rch(run_dir / "output.rch")

    if len(df) == 0:
        raise RuntimeError("SWAT 출력 파싱 결과 빈 자료")
    return df["date"].values, df["flo_out"].values


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


def _objective_value(metrics: Dict[str, float], name: str) -> float:
    """yaml.observations[].objective 에 따라 메트릭 선택 (대소문자 무관)."""
    key = name.lower()
    if key == "pbias":
        return abs(float(metrics.get("pbias", 999.0)))
    if key == "kge" and "kge" not in metrics:
        # KGE 가 calc_all 에 없으면 NSE 로 대체 + 경고는 호출자에서
        return float(metrics.get("nse", -999.0))
    return float(metrics.get(key, -999.0 if key in ("nse", "kge", "r2") else 999.0))


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

    # 첫 번째 observation 사용 (단일 obs 우선; 추후 다중 obs 결합)
    if not cfg.Observations:
        raise RuntimeError("yaml.calibration.observations 가 비어 있습니다.")
    obs = cfg.Observations[0]
    obs_df = pd.read_csv(obs.obs_file)
    if "date" not in obs_df.columns:
        raise RuntimeError(f"관측 자료 'date' 컬럼 없음: {obs.obs_file}")
    if obs.obs_column not in obs_df.columns:
        raise RuntimeError(
            f"관측 자료에 '{obs.obs_column}' 컬럼 없음 (가능: {list(obs_df.columns)})"
        )

    # SWAT exe 보장 (mock 시 skip)
    exe_path: Optional[Path] = None
    if sim_evaluator is None:
        exe_path = ensure_swat_exe(default_dir, cfg.ModelType, cfg.Executable)

    ctx = CalibrationContext(
        cfg=cfg, default_dir=default_dir, runs_dir=runs_dir,
        param_defs=cfg.CalParameters,
        objective_name=obs.objective,
        maximize=(obs.objective.upper() in ("NSE", "KGE", "R2")),
        obs_df=obs_df,
        obs_column=obs.obs_column,
        n_iterations=cfg.CalMethod.n_iterations,
        seed=cfg.CalMethod.seed,
        keep_run_dirs=keep_run_dirs,
        sim_evaluator=sim_evaluator,
        exe_path=exe_path,
    )

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
    print(f"  objective     : {ctx.objective_name} ({'maximize' if ctx.maximize else 'minimize'})")
    print(f"  obs_file      : {obs.obs_file}")
    print(f"  obs_column    : {obs.obs_column}")
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
        r=0.20, maximize=ctx.maximize, seed=ctx.seed,
        callback=lambda i, x, f, is_best: _callback(i, x, f, is_best),
    )

    print()
    print(f"  완료: best f = {result.best_f:.4f}")

    # ── 결과 산출 ────────────────────────────────────────────────────
    all_csv  = write_all_runs_csv(history_full, param_names,
                                    results_dir / "all_runs.csv")
    top_csv  = write_top_n_csv(history_full, param_names,
                                 results_dir / f"top{top_n}_runs.csv",
                                 n=top_n, maximize=ctx.maximize)
    pchg_csv = write_parameter_summary(history_full, cfg.CalParameters,
                                         results_dir / "parameter_changes.csv",
                                         maximize=ctx.maximize)

    # 그래프
    fig_dir = results_dir / "figures"
    fig_dir.mkdir(exist_ok=True)
    plot_metric_progression(history_full, fig_dir / "metric_progression.png",
                             title=f"DDS — {ctx.objective_name}",
                             maximize=ctx.maximize)

    # 상위 N 의 sim_values 모으기
    sorted_hist = sorted(history_full, key=lambda h: h["f"],
                          reverse=ctx.maximize)
    top_records = sorted_hist[:top_n]
    sim_dict = {i + 1: rec["sim_values"] for i, rec in enumerate(top_records)}
    metric_dict = {i + 1: rec["f"] for i, rec in enumerate(top_records)}

    # 관측·모의 같은 날짜 정렬
    obs_dates_arr = pd.to_datetime(obs_df["date"].values)
    sim_dates_arr = pd.to_datetime(top_records[0]["sim_dates"])
    common = pd.Series(obs_dates_arr).isin(sim_dates_arr).values
    common_dates = obs_dates_arr[common]
    obs_aligned = obs_df.set_index(pd.to_datetime(obs_df["date"])).reindex(common_dates)[obs.obs_column].values

    sim_aligned: Dict[int, Sequence[float]] = {}
    for rank, rec in enumerate(top_records, start=1):
        sim_idx = pd.Series(rec["sim_dates"]).isin(common_dates).values
        sim_aligned[rank] = pd.Series(rec["sim_values"])[sim_idx].values

    plot_scatter_top_n(common_dates, obs_aligned, sim_aligned,
                        fig_dir / f"scatter_top{top_n}.png",
                        title=f"Observed vs Simulated (Top {top_n})",
                        metric_dict=metric_dict)
    plot_timeseries_top_n(common_dates, obs_aligned, sim_aligned,
                          fig_dir / f"timeseries_top{top_n}.png",
                          title=f"Time Series — Top {top_n}",
                          metric_dict=metric_dict)

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
    }
