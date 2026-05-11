"""swat_py.calibration — SWAT 보정 모듈.

서브 모듈
---------
- parameters : 변수별 표준 보정 인자 카탈로그 (flow/ss/tn/tp)
- modify     : SWAT 입력 파일 인자값 변경 (absval/abschg/relchg/pctchg)
- synthetic  : 합성 관측 자료 생성 (기능 테스트용)
- analysis_swat_plus / analysis_swat : 보정·검증 통합 분석
"""
from swat_py.calibration.analysis_swat import run_calibration_analysis
from swat_py.calibration.analysis_swat_plus import run_calibration_analysis_plus
from swat_py.calibration.modify import (
    ParameterChange,
    apply_change,
    apply_parameter_set,
    backup_txtinout,
    modify_swat2012_file,
    modify_swat_plus_file,
)
from swat_py.calibration.parameters import (
    CATALOG,
    CHANGE_TYPES,
    FLOW_PARAMETERS,
    SS_PARAMETERS,
    TN_PARAMETERS,
    TP_PARAMETERS,
    ParameterDef,
    find_parameter,
    get_parameters,
    list_all_parameters,
    summary_dataframe,
)
from swat_py.calibration.synthetic import (
    generate_synthetic_flow,
    generate_synthetic_obs_for_calibration,
    generate_synthetic_water_quality,
)

__all__ = [
    # 기존
    "run_calibration_analysis", "run_calibration_analysis_plus",
    # parameters
    "CATALOG", "CHANGE_TYPES",
    "FLOW_PARAMETERS", "SS_PARAMETERS", "TN_PARAMETERS", "TP_PARAMETERS",
    "ParameterDef", "find_parameter", "get_parameters",
    "list_all_parameters", "summary_dataframe",
    # modify
    "ParameterChange", "apply_change", "apply_parameter_set",
    "backup_txtinout", "modify_swat2012_file", "modify_swat_plus_file",
    # synthetic
    "generate_synthetic_flow", "generate_synthetic_water_quality",
    "generate_synthetic_obs_for_calibration",
]
