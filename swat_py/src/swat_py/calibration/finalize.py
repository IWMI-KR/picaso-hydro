"""검보정 후처리(발행) 파이프라인 — 패키지 모듈.

자동보정(:func:`swat_py.calibration.auto.run_auto_calibration`)이 남긴 결과로부터
논문·보고서용 최종 산출물을 생성한다. **지역보정(regionalization, rows)을 정확히
반영**하여 Top1(최적) 입력세트를 재현한다.

기존 로컬 스크립트(3_swatplus/calibration/scripts/*.py)를 대체하는 패키지 구현이다.

단계
----
1. load_best_changes  : cfg.CalParameters(rows 포함) + parameter_changes.csv best_value 를
                        **위치(순서)로 결합** → rows 손실 없이 최적 파라미터 복원.
2. run_top1_sim       : Top1 파라미터로 SWAT+ 1회 실행 → results/top1_sim_daily.csv.
3. generate_pub_figures: viz.pub_report.make_report 재사용 → {관측소}_{cal|val}_{항목}.png
                        + pub_report_index.csv.
4. write_param_history : 최종 파라미터(rows 포함)와 검보정 단계별 성능 이력을 영속 저장.
5. promote_to_reports  : 그림·요약표를 6_reports/04_검보정결과 로 편입 + README.
6. finalize            : 위 단계를 순서대로 수행.

CLI:
    python -m swat_py.calibration.finalize --config config/swat_py.yaml
    python -m swat_py.calibration.finalize --config ... --steps sim,figs,history,promote
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from swat_py.calibration.exe_download import ensure_swat_exe
from swat_py.calibration.modify import ParameterChange, apply_parameter_set
from swat_py.output.reader_swat_plus import parse_channel_sd_day
from swat_py.viz.pub_report import make_report


# ── 최적 파라미터 복원 (rows 정확 반영) ──────────────────────────────────────

def load_best_changes(cfg, results_dir: Path) -> List[ParameterChange]:
    """cfg.CalParameters(rows 포함) + parameter_changes.csv best_value → ParameterChange.

    ★ 핵심: parameter_changes.csv 는 rows 컬럼이 없고 file::key 가 지역보정 시 중복되므로,
    이름이 아니라 **위치(순서)** 로 cfg.CalParameters 와 결합해 rows 를 복원한다.
    두 목록의 길이·(file,key) 가 위치별로 일치하지 않으면 오류(설정↔결과 불일치).
    """
    pchg = pd.read_csv(results_dir / "parameter_changes.csv")
    n_cfg, n_csv = len(cfg.CalParameters), len(pchg)
    if n_cfg != n_csv:
        raise ValueError(
            f"파라미터 수 불일치: config {n_cfg}개 ≠ parameter_changes.csv {n_csv}개. "
            f"config 가 이 결과와 다른 상태입니다(재보정 또는 config 복원 필요)."
        )
    changes: List[ParameterChange] = []
    for i, (p, (_, r)) in enumerate(zip(cfg.CalParameters, pchg.iterrows())):
        if p.file != r["file"] or p.key != r["parameter"]:
            raise ValueError(
                f"위치 {i} 파라미터 불일치: config {p.file}::{p.key} ≠ "
                f"csv {r['file']}::{r['parameter']}. 순서가 어긋났습니다."
            )
        changes.append(ParameterChange(
            file=p.file, parameter=p.key, value=float(r["best_value"]),
            change_type=p.change_type, rows=getattr(p, "rows", None),
        ))
    return changes


# ── 경로 헬퍼 ────────────────────────────────────────────────────────────────

def _results_dir(cfg) -> Path:
    return Path(cfg.CalibrationDir) / "results"


def _reports04_dir(cfg) -> Path:
    return Path(cfg.PrjDir) / "6_reports" / "04_검보정결과"


def _phase_periods(cfg) -> Dict[str, tuple]:
    """cfg 의 보정·검증 기간 → make_report 용 period 딕셔너리."""
    return {
        "cal": (cfg.CalPeriodStart or "2015-01-01",
                cfg.CalPeriodEnd or "2017-12-31", "calibration"),
        "val": (cfg.ValPeriodStart or "2018-01-01",
                cfg.ValPeriodEnd or "2020-12-31", "validation"),
    }


# ── 1. Top1 모의 재실행 ──────────────────────────────────────────────────────

def run_top1_sim(cfg, work_dir: Optional[Path] = None) -> Path:
    """Top1 파라미터(지역보정 포함)로 SWAT+ 1회 실행 → results/top1_sim_daily.csv."""
    default_dir = Path(cfg.DefaultDir)
    results_dir = _results_dir(cfg)
    work = Path(work_dir) if work_dir else results_dir / "_top1_run" / "TxtInOut"
    if work.parent.exists():
        shutil.rmtree(work.parent)
    shutil.copytree(default_dir, work)

    changes = load_best_changes(cfg, results_dir)
    print(f"[top1] 파라미터 {len(changes)}개 적용(지역보정 rows 포함)")
    apply_parameter_set(work, changes, model_type=cfg.ModelType)

    exe = work / cfg.Executable
    if not exe.is_file():
        ensure_swat_exe(work, cfg.ModelType, cfg.Executable)
    res = subprocess.run([str(exe)], cwd=str(work), capture_output=True, timeout=3600)
    if res.returncode != 0:
        sys.stderr.write(res.stderr.decode("utf-8", "ignore")[:1000])
        raise RuntimeError(f"SWAT 실행 실패 rc={res.returncode}")

    sdate = cfg.SimStartDate or "2015-01-01"
    merged: Optional[pd.DataFrame] = None
    for obs in cfg.Observations:
        df = parse_channel_sd_day(work / "channel_sd_day.txt",
                                  outlet=obs.outlet_id, sdate=sdate)
        if df is None:
            print(f"  ! {obs.id}: gis_id={obs.outlet_id} 데이터 없음"); continue
        col = df[["date", "flo_out"]].rename(columns={"flo_out": obs.id})
        merged = col if merged is None else merged.merge(col, on="date", how="outer")
    if merged is None:
        raise RuntimeError("추출된 관측소 시계열이 없습니다.")
    merged = merged.sort_values("date").reset_index(drop=True)
    out_csv = results_dir / "top1_sim_daily.csv"
    merged.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"[top1] 저장 → {out_csv} (shape={merged.shape})")
    return out_csv


# ── 2. 논문용 5-패널 그림 ────────────────────────────────────────────────────

def generate_pub_figures(cfg) -> List[dict]:
    """top1_sim_daily.csv + 관측 → {관측소}_{cal|val}_{항목}.png + pub_report_index.csv."""
    results_dir = _results_dir(cfg)
    fig_dir = results_dir / "figures"
    sim_csv = results_dir / "top1_sim_daily.csv"
    if not sim_csv.is_file():
        raise FileNotFoundError(f"모의 시계열 없음: {sim_csv} — run_top1_sim 먼저 실행.")
    sim = pd.read_csv(sim_csv, parse_dates=["date"]).set_index("date")
    periods = _phase_periods(cfg)

    index_rows: List[dict] = []
    for obs in cfg.Observations:
        if obs.id not in sim.columns:
            print(f"  ! {obs.id}: 모의열 없음 — 건너뜀"); continue
        obs_df = (pd.read_csv(obs.obs_file, parse_dates=["date"])
                  .set_index("date")[[obs.obs_column]]
                  .rename(columns={obs.obs_column: "obs"}))
        daily = obs_df.join(sim[[obs.id]].rename(columns={obs.id: "sim"}),
                            how="outer").sort_index()
        span = daily[["obs", "sim"]].dropna(how="all")
        if span.empty:
            print(f"  ! {obs.id}: 공통자료 없음 — 건너뜀"); continue
        daily = daily.loc[span.index.min():span.index.max()]
        for pk in ("cal", "val"):
            out = fig_dir / f"{obs.id}_{pk}_{obs.variable}.png"
            r = make_report(obs.id, obs.unit, pk, daily.copy(), out, periods[pk])
            index_rows.append({
                "station": obs.id, "phase": pk,
                "d_nse": round(r["daily"]["nse"], 3), "d_n": r["daily"]["n"],
                "m_nse": round(r["monthly"]["nse"], 3), "m_n": r["monthly"]["n"],
                "file": out.name,
            })
            print(f"  ✔ {out.name} (일 NSE={r['daily']['nse']:.3f}, 월 NSE={r['monthly']['nse']:.3f})")
    pd.DataFrame(index_rows).to_csv(results_dir / "pub_report_index.csv",
                                    index=False, encoding="utf-8-sig")
    return index_rows


# ── 3. 파라미터·이력 저장 ────────────────────────────────────────────────────

def write_param_history(cfg, stage_history: Optional[List[dict]] = None) -> Dict[str, Path]:
    """최종 파라미터(rows 포함)와 검보정 단계별 성능 이력을 results/ 에 영속 저장.

    - final_parameters.csv : 지역보정 rows 를 포함한 최종 최적 파라미터(발행용 정본).
      (parameter_changes.csv 는 rows 컬럼이 없어 지역보정 재현 불가 → 이 파일이 보완)
    - calibration_stage_history.csv : 단계별(매핑정정→지역화→가중) 검증 NSE 변화(선택).
    """
    results_dir = _results_dir(cfg)
    changes = load_best_changes(cfg, results_dir)
    rows_out = []
    for i, (p, ch) in enumerate(zip(cfg.CalParameters, changes)):
        rows = getattr(p, "rows", None)
        rows_str = "" if not rows else ";".join(str(r) for r in rows)  # CSV 안전(쉼표 없음)
        rows_out.append(dict(idx=i, file=p.file, key=p.key,
                             change_type=p.change_type,
                             range_min=p.range[0], range_max=p.range[1],
                             best_value=ch.value, rows=rows_str,
                             scope=("global" if not rows else "regional")))
    fp = results_dir / "final_parameters.csv"
    pd.DataFrame(rows_out).to_csv(fp, index=False, encoding="utf-8-sig")
    print(f"[history] 최종 파라미터(rows 포함) → {fp}")

    out = {"final_parameters": fp}
    if stage_history:
        hp = results_dir / "calibration_stage_history.csv"
        pd.DataFrame(stage_history).to_csv(hp, index=False, encoding="utf-8-sig")
        print(f"[history] 단계별 이력 → {hp}")
        out["stage_history"] = hp
    return out


# ── 4. 6_reports/04 편입 ─────────────────────────────────────────────────────

def promote_to_reports(cfg) -> Path:
    """그림·요약표를 6_reports/04_검보정결과 로 복사 편입 + README 갱신."""
    results_dir = _results_dir(cfg)
    fig_dir = results_dir / "figures"
    dest = _reports04_dir(cfg)
    dest.mkdir(parents=True, exist_ok=True)
    figs = sorted(fig_dir.glob("*_cal_*.png")) + sorted(fig_dir.glob("*_val_*.png"))
    for f in figs:
        shutil.copy2(f, dest / f.name)
    for name in ("cal_val_summary.csv", "top5_runs.csv", "parameter_changes.csv",
                 "final_parameters.csv", "calibration_stage_history.csv",
                 "pub_report_index.csv"):
        src = results_dir / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    n_par = len(cfg.CalParameters)
    n_reg = sum(1 for p in cfg.CalParameters if getattr(p, "rows", None))
    (dest / "README.md").write_text(
        f"# 04_검보정결과 — 모델 검보정 성능 (최종)\n\n"
        f"SWAT+ 자동보정(DDS, {n_par}-parameter: 전역 {n_par-n_reg} + 지역보정 {n_reg}) 최종 "
        f"Top1 결과. 관측소별 일/월 시계열·산점도·성능지표를 한 페이지에 담았다.\n\n"
        f"편입 그림: {len(figs)}장 (`{{관측소}}_cal_{{항목}}.png` / `{{관측소}}_val_{{항목}}.png`)\n\n"
        "## 파일\n"
        "- `{관측소}_cal_flow.png` / `{관측소}_val_flow.png` — 일/월 시계열·산점도·지표\n"
        "- `cal_val_summary.csv` — 관측소별 보정/검증 NSE·KGE·R²·PBIAS·RMSE·표본수\n"
        "- `final_parameters.csv` — ★ 지역보정(rows) 포함 최종 파라미터(재현용 정본)\n"
        "- `calibration_stage_history.csv` — 단계별 검증 NSE 변화 이력\n"
        "- `parameter_changes.csv` / `top5_runs.csv` / `pub_report_index.csv`\n\n"
        "> 생성: `python -m swat_py.calibration.finalize` · 원본: `3_swatplus/calibration/results/`\n",
        encoding="utf-8")
    print(f"[promote] {len(figs)}개 그림 + 요약표 → {dest}")
    return dest


# ── 5. calibrated/ 승격 ──────────────────────────────────────────────────────

def promote_calibrated(cfg, run: bool = True) -> Path:
    """Top1 파라미터(지역보정 포함)를 default → calibrated/ 로 승격(작동 입력세트 생성).

    기존 calibrated/ 는 calibrated_backup_YYYYMMDD 로 이동 보존하지 않고(타임스탬프 없음),
    존재 시 통째 교체한다. run=True 면 SWAT+ 1회 실행으로 입력세트 작동을 검증한다.
    """
    default_dir = Path(cfg.DefaultDir)
    calibrated = Path(cfg.CalibratedDir)
    results_dir = _results_dir(cfg)
    if calibrated.exists():
        # Windows: 읽기전용/삭제지연 대응 — 오류 무시 후 실제 소멸까지 대기
        shutil.rmtree(calibrated, ignore_errors=True)
        for _ in range(25):
            if not calibrated.exists():
                break
            time.sleep(0.2)
    shutil.copytree(default_dir, calibrated)
    changes = load_best_changes(cfg, results_dir)
    apply_parameter_set(calibrated, changes, model_type=cfg.ModelType)
    # 적용 이력 기록(rows 포함)
    pd.DataFrame([dict(file=c.file, parameter=c.parameter, value=c.value,
                       change_type=c.change_type,
                       rows=("" if not c.rows else ";".join(str(r) for r in c.rows)))
                  for c in changes]
                 ).to_csv(calibrated / "promotion_info.csv", index=False,
                          encoding="utf-8-sig")
    if run:
        exe = calibrated / cfg.Executable
        if not exe.is_file():
            ensure_swat_exe(calibrated, cfg.ModelType, cfg.Executable)
        res = subprocess.run([str(exe)], cwd=str(calibrated),
                             capture_output=True, timeout=3600)
        if res.returncode != 0:
            raise RuntimeError(f"calibrated 실행 검증 실패 rc={res.returncode}")
    print(f"[promote-calibrated] {len(changes)}개 파라미터 적용 → {calibrated}")
    return calibrated


# ── 통합 ─────────────────────────────────────────────────────────────────────

def finalize(cfg, steps=("sim", "figs", "history", "promote"),
             stage_history: Optional[List[dict]] = None) -> None:
    if "sim" in steps:
        run_top1_sim(cfg)
    if "figs" in steps:
        generate_pub_figures(cfg)
    if "history" in steps:
        write_param_history(cfg, stage_history=stage_history)
    if "promote" in steps:
        promote_to_reports(cfg)
    print("✔ finalize 완료")


def main(argv=None) -> int:
    from swat_py.config import load_config
    ap = argparse.ArgumentParser(description="검보정 후처리(발행) 파이프라인")
    ap.add_argument("--config", required=True)
    ap.add_argument("--steps", default="all",
                    help="쉼표구분: sim,figs,history,promote 또는 all")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    steps = ("sim", "figs", "history", "promote") if args.steps == "all" \
        else tuple(s.strip() for s in args.steps.split(","))
    finalize(cfg, steps=steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
