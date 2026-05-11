"""
swat_py 사용 예시 스크립트 (swat_py.yaml 기반)

전체 워크플로우:
  1. 환경 설정 로드
  2. 보정 / 검증 실행 및 분석
  3. 기준 기간 시뮬레이션
  4. 기후변화 시나리오 실행 및 분석
  5. acidwg_py 1000개 앙상블 확률예보 (신규)
  6. 계절 예보 (단일 멤버)
"""

from swat_py.config.env import load_config
from swat_py.calibration.analysis_swat_plus import (
    run_observation_plus,
    run_calibration_analysis_plus,
)
from swat_py.cchange.runner_swat_plus import run_cchange_plus
from swat_py.cchange.analysis_swat_plus import analyse_cchange_cha_plus
from swat_py.viz.cchange_lines import plot_cchange_lines
from swat_py.forecast.ensemble import EnsembleConfig, run_ensemble_forecast, plot_ensemble_forecast
from swat_py.forecast.seasonal import run_seasonal_forecast, analyse_seasonal_forecast

# ── 1. 환경 설정 로드 ─────────────────────────────────────────────────────────
cfg = load_config("swat_py.yaml")

# simulation 섹션에서 분석 변수 목록을 가져옵니다
OUT_TYPES = cfg.SimOutputTypes  # e.g. ["flow", "sedc", "tnc", "tpc"]

# ── 2. 보정 (Calibration) ──────────────────────────────────────────────────────
run_observation_plus(
    cfg,
    sim_type="Calibration",
    syear=cfg.CalibrationStartYear,
    eyear=cfg.CalibrationEndYear,
)
run_calibration_analysis_plus(
    cfg,
    sim_type="Calibration",
    out_types=OUT_TYPES,
    syear=cfg.CalibrationStartYear,
)

# ── 3. 검증 (Validation) ───────────────────────────────────────────────────────
run_observation_plus(
    cfg,
    sim_type="Validation",
    syear=cfg.ValidationStartYear,
    eyear=cfg.ValidationEndYear,
)
run_calibration_analysis_plus(
    cfg,
    sim_type="Validation",
    out_types=OUT_TYPES,
    syear=cfg.ValidationStartYear,
)

# ── 4. 역사 기준 기간 (Historical baseline) ────────────────────────────────────
run_observation_plus(
    cfg,
    sim_type="observed",
    syear=cfg.BaselineStartYear,
    eyear=cfg.BaselineEndYear,
)
run_calibration_analysis_plus(
    cfg,
    sim_type="observed",
    out_types=OUT_TYPES,
    syear=cfg.BaselineStartYear,
)

# ── 5. 기후변화 시나리오 실행 ─────────────────────────────────────────────────
if cfg.CChangeOpt.lower() == "on":
    run_cchange_plus(cfg)
    analyse_cchange_cha_plus(cfg, out_types=OUT_TYPES)
    plot_cchange_lines(cfg, out_types=OUT_TYPES)

# ── 6. acidwg_py 앙상블 확률예보 (신규 기능) ───────────────────────────────────
if cfg.EnsembleForecastEnabled:
    ens_cfg = EnsembleConfig(
        ensemble_dir=cfg.EnsembleDir,
        n_members=cfg.EnsembleNMembers,
        parallel=cfg.EnsembleParallel.enabled,
        n_workers=cfg.EnsembleParallel.n_workers,
        out_types=["flow"],
        quantiles=cfg.EnsembleQuantiles,
    )
    results = run_ensemble_forecast(
        cfg=cfg,
        ens_cfg=ens_cfg,
        syear=cfg.EnsembleStartYear,
        eyear=cfg.EnsembleEndYear,
    )
    plot_ensemble_forecast(
        results=results,
        outlet_nm=cfg.OutletFlowNms[0] if cfg.OutletFlowNms else "",
    )

# ── 7. 계절 예보 (단일 멤버) ──────────────────────────────────────────────────
if cfg.SForecastOpt.lower() == "on":
    import datetime
    fiyearmon = f"{cfg.Syear_Fcst}-01"  # 실제 사용 시 원하는 월로 변경
    run_seasonal_forecast(cfg, fiyearmon=fiyearmon)
    analyse_seasonal_forecast(cfg, fiyearmon=fiyearmon)

print("swat_py 워크플로우 완료")
