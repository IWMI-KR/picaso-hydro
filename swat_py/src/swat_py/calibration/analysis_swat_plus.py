"""SWAT-Plus calibration/validation analysis workflow.

Mirrors calibration-plus.R :: Swat.Observation.Run.Plus() and
Swat.Observation.Cha.Analysis.Plus().
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

import pandas as pd

from swat_py.config.env import EnvConfig
from swat_py.io.station import load_station_csv
from swat_py.io.weather_swat_plus import write_all_weather_plus
from swat_py.io.config_swat_plus import write_time_sim, patch_print_prt
from swat_py.output.reader_swat_plus import (
    parse_channel_sd_day, extract_cha_outtype,
    parse_reservoir_day, extract_res_outtype,
)
from swat_py.output.aggregator import add_date_parts, aggregate_output
from swat_py.metrics import calc_all
from swat_py.runner.executor import SwatExecutor
from swat_py.runner.file_manager import rename_outputs, setup_run_dir
from swat_py.viz.summary import plot_summary_figure


# ── outtype metadata ───────────────────────────────────────────────────────────

_OUTTYPE_META = {
    "flow":  {"funtype": "mean", "obs_col": "inflow_cms", "sim_col": "flow_cms",  "use_flow_obs": True},
    "flowd": {"funtype": "sum",  "obs_col": "inflow_cms", "sim_col": "flow_mm",   "use_flow_obs": True},
    "sedc":  {"funtype": "mean", "obs_col": "ss_mgl",     "sim_col": "Sed_mgl",   "use_flow_obs": False},
    "tnc":   {"funtype": "mean", "obs_col": "tn_mgl",     "sim_col": "TN_mgl",    "use_flow_obs": False},
    "tpc":   {"funtype": "mean", "obs_col": "tp_mgl",     "sim_col": "TP_mgl",    "use_flow_obs": False},
}

_YLABEL = {
    "flow":  "streamflow (cms)",
    "flowd": "streamflow (mm)",
    "sedc":  "sediment (mg/l)",
    "tnc":   "TN (mg/l)",
    "tpc":   "TP (mg/l)",
}


# ── run ────────────────────────────────────────────────────────────────────────

def run_observation_plus(
    cfg: EnvConfig,
    sim_type: str,
    syear: int,
    eyear: int,
    exe_name: str = "SWAT-Plus.exe",
) -> None:
    """Write weather inputs, run SWAT-Plus, rename outputs.

    Mirrors Swat.Observation.Run.Plus().

    Parameters
    ----------
    cfg:       Loaded :class:`EnvConfig`.
    sim_type:  Descriptive tag, e.g. ``"Calibration"`` or ``"Validation"``.
    syear:     First year of the analysis period (before warm-up).
    eyear:     Last year of the analysis period.
    exe_name:  SWAT-Plus executable filename.
    """
    nyskip = int(cfg.CioNYSKIP)
    run_dir = Path(cfg.SwatRunDir)
    obs_dir = Path(cfg.SwatObsDir) / "Output"
    setup_run_dir(obs_dir)

    # Write weather inputs
    stations = load_station_csv(
        Path(cfg.ObsDayDir) / cfg.StnFile,
        cfg.StnIDs,
    )
    write_all_weather_plus(
        stations=stations,
        wthr_dir=Path(cfg.ObsDayDir),
        out_dir=run_dir,
        fnamestr=None,
    )

    # Update time.sim and print.prt
    nbyr = eyear - syear + 1 + nyskip
    iyr = syear - nyskip
    write_time_sim(run_dir, nbyr, iyr)
    patch_print_prt(run_dir, nbyr, iyr, nyskip)

    # Run SWAT-Plus
    executor = SwatExecutor(run_dir, exe_name)
    executor.run()

    # Rename outputs
    rename_outputs(
        run_dir=run_dir,
        out_dir=obs_dir,
        output_types=cfg.OutputTypes,
        scenario_name=sim_type,
        model="swat_plus",
    )


# ── analysis ──────────────────────────────────────────────────────────────────

def run_calibration_analysis_plus(
    cfg: EnvConfig,
    sim_type: str,
    out_types: List[str],
    syear: int,
) -> None:
    """Parse outputs, compare with observations, save CSV + PNG.

    Mirrors Swat.Observation.Cha.Analysis.Plus().

    Parameters
    ----------
    cfg:       Loaded :class:`EnvConfig`.
    sim_type:  Tag matching the run (e.g. ``"Calibration"``).
    out_types: List of output types, e.g. ``["flow", "sedc", "tnc", "tpc"]``.
    syear:     Analysis start year (before warm-up skip).
    """
    nyskip = int(cfg.CioNYSKIP)
    out_dir = Path(cfg.SwatObsDir) / "Output"
    analysis_dir = Path(cfg.SwatObsDir) / "Analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    sdate = f"{syear}-01-01"
    sdate2 = f"{syear + nyskip}-01-01"

    for outtype in out_types:
        meta = _OUTTYPE_META[outtype]
        funtype: str = meta["funtype"]
        use_flow_obs: bool = meta["use_flow_obs"]
        obs_col: str = meta["obs_col"]
        sim_col: str = meta["sim_col"]

        outlets, outlet_nms = cfg.outlets_for(flow=use_flow_obs)
        obs_file = cfg.ObsFlowFile if use_flow_obs else cfg.ObsWqFile

        obs_df = pd.read_csv(
            Path(cfg.SwatDbDir) / obs_file,
            encoding="utf-8-sig",
        )

        for outlet, outlet_nm in zip(outlets, outlet_nms):
            cha_path = out_dir / f"channel_sd_day-{sim_type}.txt"
            raw = parse_channel_sd_day(cha_path, outlet, sdate)
            if raw is None:
                print(f"[WARN] No data for outlet {outlet} in {cha_path}")
                continue

            sim_typed = extract_cha_outtype(raw, outtype)
            sim_typed = add_date_parts(sim_typed)

            # Filter warm-up period
            sim_typed = sim_typed[sim_typed["date"] >= pd.Timestamp(sdate2)]

            # Prepare observed DataFrame
            obs_sub = _prepare_obs(obs_df, outtype, obs_col)

            # Join sim + obs on date
            sim_col_renamed = sim_col
            sim_join = sim_typed[["date", sim_col_renamed]].rename(
                columns={sim_col_renamed: "sim"}
            )
            obs_join = obs_sub.rename(columns={obs_col: "obs"})

            sim_join["date"] = pd.to_datetime(sim_join["date"])
            obs_join["date"] = pd.to_datetime(obs_join["date"])

            daily = pd.merge(sim_join, obs_join, on="date", how="left")

            # Monthly aggregation
            daily_tmp = add_date_parts(daily)
            msim = daily_tmp.groupby("yearmon")["sim"].mean().reset_index()
            mobs = daily_tmp.groupby("yearmon")["obs"].mean().reset_index()
            monthly = pd.merge(msim, mobs, on="yearmon", how="left")

            # Save CSVs
            tag = f"{sim_type}_{outtype}_{outlet}-{outlet_nm}"
            daily.to_csv(analysis_dir / f"{tag}-daily.csv", index=False)
            monthly.to_csv(analysis_dir / f"{tag}-monthly.csv", index=False)

            # Save summary PNG
            plot_summary_figure(
                out_dir=analysis_dir,
                name=tag,
                title=tag,
                daily_df=daily,
                monthly_df=monthly,
                outtype=outtype,
            )


def _prepare_obs(
    obs_df: pd.DataFrame,
    outtype: str,
    obs_col: str,
) -> pd.DataFrame:
    """Normalise observed data to a date + value DataFrame."""
    df = obs_df.copy()
    if "day" in df.columns and "mon" in df.columns and "year" in df.columns:
        df["date"] = pd.to_datetime(
            df[["year", "mon", "day"]].rename(columns={"mon": "month"})
        )
    elif "date" not in df.columns:
        raise KeyError("Observed data must have either (year/mon/day) or 'date' columns.")
    else:
        df["date"] = pd.to_datetime(df["date"])

    if obs_col not in df.columns:
        raise KeyError(f"Column '{obs_col}' not found in observed data.")

    return df[["date", obs_col]]


# ── 관측점(observations[]) 기반 통합 분석 (채널 + 저수지) ────────────────────────
#
#  run_calibration_analysis_plus() 는 레거시 flat 경로(공유 ObsFlowFile 단일 파일)를
#  쓰는 채널 전용이다. 아래 함수들은 신규 calibration.observations[] 스키마를 돌며
#  변수(variable)에 따라 채널(channel_sd_day) 또는 저수지(reservoir_day) 리더로
#  자동 라우팅한다. 댐 수위(wlevel) 보정을 지원한다.

# variable → (source, outtype)
_VARIABLE_ROUTE = {
    "flow":    ("channel",   "flow"),
    "ss":      ("channel",   "sedc"),
    "tn":      ("channel",   "tnc"),
    "tp":      ("channel",   "tpc"),
    "wlevel":  ("reservoir", "wlevel"),
    "resstor": ("reservoir", "resstor"),
    "resflow": ("reservoir", "resflow"),
}

# outtype → 모의 컬럼명(extract_* 산출) · 관측 컬럼 기본값
_SIM_COL = {
    "flow": "flow_cms", "sedc": "Sed_mgl", "tnc": "TN_mgl", "tpc": "TP_mgl",
    "wlevel": "wlevel_ft", "resstor": "stor_m3", "resflow": "flow_cms",
}
_DEFAULT_OBS_COL = {
    "flow": "flow_m3s", "sedc": "ss_mgl", "tnc": "tn_mgl", "tpc": "tp_mgl",
    "wlevel": "wlevel_ft", "resstor": "resstor_m3", "resflow": "resflow_m3s",
}


def build_reservoir_sim(
    raw: pd.DataFrame,
    obs,
    outtype: str,
    reservoirs: Optional[dict] = None,
) -> pd.DataFrame:
    """저수지 raw(reservoir_day) → 파생 시계열(wlevel_ft 등).

    obs.reservoir 레지스트리에서 **실측 수위-내용적 곡선**과 **취수 물수지**,
    **datum 오프셋**을 적용한다(있으면). analyze_one_observation_plus 와
    auto-calibration(_extract_obs_from_swat_output) 이 공유한다.
    """
    curve = None
    datum_offset_ft = 0.0
    interp = "pchip"
    storage_override = None
    res = (reservoirs or {}).get(getattr(obs, "reservoir", "") or "")

    if res is not None and getattr(res, "stage_storage_file", ""):
        try:
            from swat_py.io.reservoir import load_stage_storage
            curve = load_stage_storage(res.stage_storage_file, name=res.name)
            datum_offset_ft = res.obs_datum_offset_ft
            interp = res.interp
        except Exception as e:
            print(f"[WARN] 수위-내용적 곡선 로드 실패({res.name}): {e} → V/A fallback")

    # 취수 반영: 취수량이 설정되고 곡선이 있으면 물수지 재계산(SWAT+ 유입 − 취수)
    if res is not None and curve is not None and (
        (getattr(res, "withdrawal_m3s", 0.0) or 0.0) > 0
        or getattr(res, "withdrawal_monthly_m3s", None)
    ):
        try:
            from swat_py.io.reservoir import simulate_managed_storage
            import math as _math
            cap_lvl = res.cap_level_ft if not _math.isnan(res.cap_level_ft) else res.spillway_ft
            cap_m3 = float(curve.stage_to_storage(cap_lvl)) if not _math.isnan(cap_lvl) else None
            dead_m3 = float(curve.stage_to_storage(res.bottom_ft)) if not _math.isnan(res.bottom_ft) else 0.0
            init_m3 = float(curve.stage_to_storage(res.init_level_ft)) if not _math.isnan(res.init_level_ft) else cap_m3
            wdr = res.withdrawal_monthly_m3s or res.withdrawal_m3s
            bal = simulate_managed_storage(
                raw, withdrawal_m3s=wdr, cap_m3=cap_m3, dead_m3=dead_m3, init_m3=init_m3,
            )
            storage_override = bal["storage_m3"]
        except Exception as e:
            print(f"[WARN] 취수 물수지 계산 실패({getattr(res,'name','?')}): {e} → 원 flo_stor 사용")

    return extract_res_outtype(
        raw, outtype, curve=curve, datum_offset_ft=datum_offset_ft,
        interp=interp, storage_override=storage_override,
        shape_factor=getattr(obs, "shape_factor", 1.0),
        datum_m=getattr(obs, "datum_m", 0.0),
    )


def _resolve_obs_path(obs_file: str, obs_root: Optional[str]) -> Path:
    """관측 CSV 경로 해석: 절대 → 그대로 / 존재하면 그대로 / else obs_root 기준."""
    p = Path(obs_file)
    if p.is_absolute():
        return p
    if p.exists():
        return p
    if obs_root:
        cand = Path(obs_root) / obs_file
        if cand.exists():
            return cand
    return p


def analyze_one_observation_plus(
    obs,
    sim_type: str,
    syear: int,
    nyskip: int,
    out_dir: Path,
    analysis_dir: Path,
    obs_root: Optional[str] = None,
    make_plot: bool = True,
    reservoirs: Optional[dict] = None,
) -> Optional[dict]:
    """단일 관측점(_Observation) 분석: 모의 출력 파싱 → 관측 비교 → CSV/PNG/지표.

    variable 에 따라 채널(channel_sd_day-{sim}.txt) 또는 저수지
    (reservoir_day-{sim}.txt) 출력을 읽어 일·월 비교 및 성능지표를 산출한다.

    Returns
    -------
    dict(성능 요약) 또는 자료 없을 시 ``None``.
    """
    variable = obs.variable.lower()
    if variable not in _VARIABLE_ROUTE:
        print(f"[WARN] 미지원 variable '{variable}' (obs id={obs.id}) — 건너뜀")
        return None
    source, outtype = _VARIABLE_ROUTE[variable]
    sim_col = _SIM_COL[outtype]
    obs_col = obs.obs_column or _DEFAULT_OBS_COL[outtype]

    sdate  = f"{syear}-01-01"
    sdate2 = f"{syear + nyskip}-01-01"

    # ── 모의 출력 파싱 + 파생 컬럼 ──
    if source == "reservoir":
        sim_path = out_dir / f"reservoir_day-{sim_type}.txt"
        raw = parse_reservoir_day(sim_path, obs.outlet_id, sdate)
        if raw is None:
            print(f"[WARN] 저수지 {obs.outlet_id} 자료 없음: {sim_path}")
            return None
        # 곡선·취수·datum 반영 저수지 시계열 (공용 헬퍼)
        sim_typed = build_reservoir_sim(raw, obs, outtype, reservoirs)
    else:
        sim_path = out_dir / f"channel_sd_day-{sim_type}.txt"
        raw = parse_channel_sd_day(sim_path, obs.outlet_id, sdate)
        if raw is None:
            print(f"[WARN] 채널 {obs.outlet_id} 자료 없음: {sim_path}")
            return None
        sim_typed = extract_cha_outtype(raw, outtype)

    sim_typed = add_date_parts(sim_typed)
    sim_typed = sim_typed[sim_typed["date"] >= pd.Timestamp(sdate2)]

    # ── 관측 로드 ──
    obs_path = _resolve_obs_path(obs.obs_file, obs_root)
    if not obs_path.exists():
        print(f"[WARN] 관측 파일 없음: {obs_path} (obs id={obs.id})")
        return None
    obs_df = pd.read_csv(obs_path, encoding="utf-8-sig")
    if obs_col not in obs_df.columns:
        print(f"[WARN] 관측 컬럼 '{obs_col}' 없음 in {obs_path.name} "
              f"(있는 컬럼: {list(obs_df.columns)})")
        return None
    obs_sub = _prepare_obs(obs_df, outtype, obs_col)

    # ── 일 단위 병합 ──
    sim_join = sim_typed[["date", sim_col]].rename(columns={sim_col: "sim"})
    obs_join = obs_sub.rename(columns={obs_col: "obs"})
    sim_join["date"] = pd.to_datetime(sim_join["date"])
    obs_join["date"] = pd.to_datetime(obs_join["date"])
    daily = pd.merge(sim_join, obs_join, on="date", how="inner")

    # ── 월 단위 집계 ──
    daily_tmp = add_date_parts(daily)
    msim = daily_tmp.groupby("yearmon")["sim"].mean().reset_index()
    mobs = daily_tmp.groupby("yearmon")["obs"].mean().reset_index()
    monthly = pd.merge(msim, mobs, on="yearmon", how="inner")

    # ── 성능지표 (관측 있는 날만) ──
    pair = daily.dropna(subset=["obs", "sim"])
    metrics_d = calc_all(pair["obs"].values, pair["sim"].values) if len(pair) else {}
    mpair = monthly.dropna(subset=["obs", "sim"])
    metrics_m = calc_all(mpair["obs"].values, mpair["sim"].values) if len(mpair) else {}

    # ── 저장 ──
    analysis_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{sim_type}_{obs.id}_{variable}_{obs.outlet_id}"
    daily.to_csv(analysis_dir / f"{tag}-daily.csv", index=False)
    monthly.to_csv(analysis_dir / f"{tag}-monthly.csv", index=False)
    if make_plot:
        try:
            plot_summary_figure(
                out_dir=analysis_dir, name=tag, title=tag,
                daily_df=daily, monthly_df=monthly, outtype=outtype,
            )
        except Exception as e:                       # 시각화 실패는 치명적 아님
            print(f"[WARN] plot 실패 ({tag}): {e}")

    summary = {
        "id": obs.id, "variable": variable, "source": source,
        "outlet_id": obs.outlet_id, "objective": obs.objective,
        "weight": obs.weight, "n_daily": int(len(pair)),
        "n_monthly": int(len(mpair)),
    }
    for k, v in metrics_d.items():
        summary[f"daily_{k}"] = v
    for k, v in metrics_m.items():
        summary[f"monthly_{k}"] = v
    return summary


def run_observation_analysis_plus(
    cfg: EnvConfig,
    sim_type: str,
    syear: int,
    *,
    out_dir: Optional[Path] = None,
    analysis_dir: Optional[Path] = None,
    make_plot: bool = True,
) -> pd.DataFrame:
    """calibration.observations[] 전체를 돌며 채널·저수지 관측 비교 + 지표 CSV.

    Parameters
    ----------
    cfg:          로드된 :class:`EnvConfig` (cfg.Observations 사용).
    sim_type:     실행 태그 (예: ``"Calibration"`` / ``"Validation"``).
    syear:        분석 시작 연도(warm-up 포함).
    out_dir:      SWAT+ 출력 폴더(rename 된 ``*_day-{sim_type}.txt`` 위치).
                  미지정 시 ``{SwatObsDir}/Output``.
    analysis_dir: 결과 저장 폴더. 미지정 시 ``{SwatObsDir}/Analysis``.

    Returns
    -------
    관측점별 성능지표 요약 DataFrame(가중 목적함수 구성용). 동시에
    ``{sim_type}_observation_metrics.csv`` 로 저장.
    """
    nyskip = int(cfg.CioNYSKIP)
    base = Path(getattr(cfg, "SwatObsDir", ".") or ".")
    out_dir = Path(out_dir) if out_dir is not None else base / "Output"
    analysis_dir = Path(analysis_dir) if analysis_dir is not None else base / "Analysis"
    obs_root = getattr(cfg, "ObservedDataDir", "") or getattr(cfg, "SwatDbDir", "")

    observations = getattr(cfg, "Observations", []) or []
    if not observations:
        print("[WARN] cfg.Observations 비어 있음 — 분석할 관측점 없음")
        return pd.DataFrame()
    reservoirs = getattr(cfg, "Reservoirs", {}) or {}

    rows = []
    for obs in observations:
        s = analyze_one_observation_plus(
            obs, sim_type, syear, nyskip, out_dir, analysis_dir,
            obs_root=obs_root, make_plot=make_plot, reservoirs=reservoirs,
        )
        if s is not None:
            rows.append(s)

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        analysis_dir.mkdir(parents=True, exist_ok=True)
        summary_df.to_csv(
            analysis_dir / f"{sim_type}_observation_metrics.csv", index=False,
        )
    return summary_df
