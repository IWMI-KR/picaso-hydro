"""swat_py.drought — 가뭄위험 대시보드 데이터(①~⑤) 생산.

SWAT+ 장기 기후(①평년·④FDC) + 계절예측 구동 앙상블(③평균·⑤단계확률)을 12개 소유역
outlet 별로 산출한다. 설정은 yaml `drought:` 블록(env._DroughtCfg) / CLI.

진입점
- run_ensemble(...)                    : 예측 앙상블 SWAT+ (③⑤ 원자료)
- fdc_thresholds(daily_q)              : 유황 대표유량 Q95d~Q355d (참조값, 경계 아님)
- stage_thresholds(q, method, values)  : ④ 단계 경계 3개 (기본 Q70/Q90/Q95)
- stage_probabilities4(vals, *bounds)  : ⑤ 4단계 확률
- tercile_probabilities(vals, t33, t67): ⑥ 3분위 확률 BN·NN·AN(평년 대비 상대위치)
- build_terciles(cfg, forecast)        : ⑥ 3분위 CSV·파이 (기존 산출물 소급 적용)
- dashboard_data.build(cfg, forecast)  : 12 outlet ①~⑤ 조립·저장
"""
from swat_py.drought.fdc import (
    flow_duration_curve, q_at, fdc_thresholds, FLOW_REGIME_DAYS,
)
from swat_py.drought.stages import classify_stage, stage_probabilities, STAGES
from swat_py.drought.climatology import (
    load_daily_flow, monthly_climatology, outlet_climatology_and_thresholds,
)
from swat_py.drought.ensemble_flow import run_ensemble, OUTLETS
from swat_py.drought.fdc import stage_thresholds
from swat_py.drought.stages import (
    classify_stage4, stage_probabilities4, STAGES4, STAGE_COLORS,
)
from swat_py.drought.climatology_run import run_climatology
from swat_py.drought.ensemble_weather import generate_ensemble_weather
from swat_py.drought.reclassify import reclassify_stages
from swat_py.drought.tercile import (
    TERCILES, build_terciles, tercile_bounds, tercile_probabilities,
)
from swat_py.drought.run import run_pipeline

__all__ = [
    "flow_duration_curve", "q_at", "fdc_thresholds", "stage_thresholds",
    "FLOW_REGIME_DAYS",
    "classify_stage", "stage_probabilities", "STAGES",
    "classify_stage4", "stage_probabilities4", "STAGES4", "STAGE_COLORS",
    "load_daily_flow", "monthly_climatology", "outlet_climatology_and_thresholds",
    "run_ensemble", "OUTLETS",
    "run_climatology", "generate_ensemble_weather", "reclassify_stages",
    "run_pipeline",
    "TERCILES", "tercile_bounds", "tercile_probabilities", "build_terciles",
]
