"""Environment configuration — loads swat_py.yaml and resolves cross-references.

지원 형식
---------
1. **신규 중첩 구조** (swat_py.yaml):
   섹션별로 논리적으로 분리된 YAML.  ``$(project.root)`` 같은 점-경로 참조 지원.

2. **구 단순 구조** (rSWAT.yaml 호환):
   최상위 키-값 쌍으로만 구성된 기존 YAML.  ``$(PrjDir)`` 참조 지원.
   자동 감지 후 내부적으로 같은 :class:`EnvConfig` 로 변환합니다.
"""

from __future__ import annotations

import os
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml


# ── 환경변수 치환 ${env:VAR} / ${env:VAR:default} ────────────────────────────

_ENV_PATTERN = re.compile(r"\$\{env:([A-Z_][A-Z0-9_]*)(?::([^}]*))?\}")


def _resolve_env_vars(text: str) -> str:
    """문자열 내 ``${env:VAR}`` / ``${env:VAR:default}`` 환경변수 치환."""
    def _sub(m: "re.Match[str]") -> str:
        var, default = m.group(1), m.group(2)
        return os.environ.get(var, default if default is not None else "")
    return _ENV_PATTERN.sub(_sub, text)


# ══════════════════════════════════════════════════════════════════════════════
#  SWAT 버전 → 출력 폴더 매핑
#  yaml 의 model.type 으로 output_root 가 자동 결정됩니다.
#  - swat_plus → $(project.root)/3_swatplus/...
#  - swat2012  → $(project.root)/3_swat2012/...
#  사용자가 output.swat_run 등을 yaml 에 명시하면 그게 우선이며,
#  명시한 경로 안에 '다른 버전' 폴더명이 들어 있으면 경고 출력.
# ══════════════════════════════════════════════════════════════════════════════

VALID_MODEL_TYPES = ("swat_plus", "swat2012")

_VERSION_TO_OUTPUT_SUBDIR = {
    "swat_plus": "3_swatplus",
    "swat2012":  "3_swat2012",
}


def _auto_output_root(prj_dir: str, model_type: str) -> str:
    """``$(project.root)/3_swatplus`` 또는 ``$(project.root)/3_swat2012`` 산출."""
    if not prj_dir:
        return ""
    sub = _VERSION_TO_OUTPUT_SUBDIR.get(model_type)
    return f"{prj_dir}/{sub}" if sub else ""


def _warn_if_version_mismatch(name: str, path: str, model_type: str) -> None:
    """사용자가 명시한 경로의 폴더명이 model.type 과 불일치하면 경고."""
    if not path:
        return
    expected = _VERSION_TO_OUTPUT_SUBDIR.get(model_type)
    other_type = "swat2012" if model_type == "swat_plus" else "swat_plus"
    other = _VERSION_TO_OUTPUT_SUBDIR.get(other_type)
    if not expected or not other:
        return
    if other in path and expected not in path:
        warnings.warn(
            f"[swat_py] {name}='{path}' 가 model.type='{model_type}' 와 "
            f"일치하지 않는 폴더('{other}')를 가리킵니다. "
            f"yaml.model.type 또는 경로를 확인하세요.",
            UserWarning, stacklevel=3,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  내부 설정 데이터클래스 — 모든 세부 설정을 담는 중간 표현
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class _FuturePeriod:
    start_year: int
    end_year: int
    label: str = ""


@dataclass
class _EnsembleParallelCfg:
    enabled: bool = True
    n_workers: int = 4


# ── 신규 — calibration 확장 (관측점 × 변수 × 단위, 인자 범위, 알고리즘) ───────

@dataclass
class _Observation:
    """yaml.calibration.observations[] 항목.

    yaml 에서 obs_file / obs_column / outlet_name 생략 가능 — 컨벤션 기반 자동 산출:
        obs_file   = {obs_root}/{variable}/{time_step}/{outlet_name}.csv
        obs_column = {variable}_{unit_suffix} (예: flow_m3s, tn_mgl)
        outlet_name = yaml.outlets.flow.names 에서 outlet_id 로 lookup
    """
    id:         str
    outlet_id:  int
    variable:   str           # flow | ss | tn | tp
    unit:       str           # m3/s, mm/day, mg/L, kg/day 등
    obs_file:   str = ""       # 미명시 시 자동 산출
    obs_column: str = ""       # 미명시 시 자동 산출
    outlet_name: str = ""      # 미명시 시 outlets.flow.names lookup
    time_step:  str = "daily"  # daily | monthly | 10day
    weight:     float = 1.0
    objective:  str = "NSE"    # NSE | KGE | R2 | PBIAS | RMSE


@dataclass
class _CalParameter:
    """yaml.calibration.parameters[] 항목."""
    file:        str           # 입력 파일명 (basin.bsn, hydrology.hyd 등)
    key:         str           # 인자 이름
    range:       List[float]   # [min, max]
    change_type: str = "absval"  # absval | relchg | abschg


@dataclass
class _CalMethodCfg:
    """yaml.calibration.method 블록."""
    name:         str = "manual"   # manual | sufi2 | pso | de | sce-ua
    n_iterations: int = 100
    seed:         int = 1
    parallel:     _EnsembleParallelCfg = field(default_factory=_EnsembleParallelCfg)


@dataclass
class _CalOutputCfg:
    """yaml.calibration.output 블록."""
    save_all_runs:           bool = False
    save_best_n:             int  = 5
    auto_parameter_changes:  bool = True


@dataclass
class EnvConfig:
    """swat_py 전체 설정을 담는 데이터클래스.

    :func:`load_config` 가 반환합니다.
    신규 중첩 YAML과 구 단순 YAML 모두 이 클래스로 정규화됩니다.
    """

    # ── 디렉토리 ──────────────────────────────────────────────────────────────
    PrjDir: str = ""          # project.root
    DbDir: str = ""           # project.database
    QswatTxtInOut: str = ""   # project.qswat_txtinout — promote 원본 (QSWAT+ TxtInOut)
    ObsDayDir: str = ""       # project.input.observed_weather
    ObservedDataDir: str = ""  # project.input.observed (★ 신규 — 관측 자료 루트, obs/)
    CcDataDir: str = ""       # project.input.cc_weather
    FcstDataDir: str = ""     # project.input.forecast_weather
    SwatRunDir: str = ""      # 호환 alias — CalibratedDir 와 동일
    SwatObsDir: str = ""      # 호환 alias — CalibrationDir 와 동일
    SwatCcDir: str = ""       # 호환 alias — CchangeDir 와 동일
    SwatFcstDir: str = ""     # 호환 alias — ForecastDir 와 동일
    SwatDbDir: str = ""       # project.output.database (관측 자료 DB)
    SmplDir: str = ""         # (미사용 / 하위 호환)

    # ── 옵션 C 마스터 + 작업 폴더 (model.type 기반 자동 산출) ─────────────────
    # 마스터 (READ-ONLY)
    DefaultDir: str = ""      # $(root)/3_swatplus/default — QSWAT+ 출력
    CalibratedDir: str = ""   # $(root)/3_swatplus/calibrated — 보정 완료
    # 작업 (runs/ + results/ 하위 구조)
    CalibrationDir: str = ""  # $(root)/3_swatplus/calibration
    ForecastDir: str = ""     # $(root)/3_swatplus/forecast
    CchangeDir: str = ""      # $(root)/3_swatplus/cchange

    # ── 모델 ──────────────────────────────────────────────────────────────────
    ModelType: str = "swat_plus"    # "swat_plus" | "swat2012"
    Executable: str = "SWAT-Plus.exe"
    CioNYSKIP: int = 3              # warm_up_years
    OutputTypes: List[str] = field(default_factory=lambda: ["sd"])

    # ── 관측소 ────────────────────────────────────────────────────────────────
    StnFile: str = ""
    StnIDs: List[str] = field(default_factory=list)

    # ── 모니터링 지점 ─────────────────────────────────────────────────────────
    OutletFlowIDs: List[int] = field(default_factory=list)
    OutletFlowNms: List[str] = field(default_factory=list)
    OutletWqIDs: List[int] = field(default_factory=list)
    OutletWqNms: List[str] = field(default_factory=list)

    # ── 관측 자료 ─────────────────────────────────────────────────────────────
    ObsFlowFile: str = ""
    ObsWqFile: str = ""

    # ── 시뮬레이션 기간 및 분석 변수 ─────────────────────────────────────────
    # 옛 (호환 alias)
    SimOutputTypes: List[str] = field(default_factory=lambda: ["flow"])
    CalibrationStartYear: int = 0
    CalibrationEndYear: int = 0
    ValidationStartYear: int = 0
    ValidationEndYear: int = 0
    BaselineStartYear: int = 0
    BaselineEndYear: int = 0
    # 신규 — 일자 단위 (YYYY-MM-DD)
    SimStartDate: str = ""           # simulation.start_date
    SimEndDate:   str = ""           # simulation.end_date
    SimTimeStep:  str = "daily"      # daily | monthly
    CalPeriodStart: str = ""         # calibration.period.start
    CalPeriodEnd:   str = ""
    ValPeriodStart: str = ""         # calibration.validation.start
    ValPeriodEnd:   str = ""
    # 신규 — observations / parameters / method / output
    Observations:   List[_Observation]  = field(default_factory=list)
    CalParameters:  List[_CalParameter] = field(default_factory=list)
    CalMethod:      _CalMethodCfg       = field(default_factory=_CalMethodCfg)
    CalOutput:      _CalOutputCfg       = field(default_factory=_CalOutputCfg)

    # ── 기후변화 ──────────────────────────────────────────────────────────────
    CChangeOpt: str = "off"         # "on" | "off"
    MdlNms: List[str] = field(default_factory=list)
    ScnNms: List[str] = field(default_factory=list)
    Syear_hist: int = 1981
    Eyear_hist: int = 2010
    Syear_rcp: List[int] = field(default_factory=list)
    Eyear_rcp: List[int] = field(default_factory=list)
    FuturePeriods: List[_FuturePeriod] = field(default_factory=list)

    # ── 앙상블 확률예보 (acidwg_py) ───────────────────────────────────────────
    EnsembleForecastEnabled: bool = False
    EnsembleDir: str = ""
    EnsembleNMembers: int = 1000
    EnsembleParallel: _EnsembleParallelCfg = field(
        default_factory=_EnsembleParallelCfg
    )
    EnsembleQuantiles: List[float] = field(
        default_factory=lambda: [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]
    )
    EnsembleStartYear: int = 0
    EnsembleEndYear: int = 0

    # ── 계절 예보 ─────────────────────────────────────────────────────────────
    SForecastOpt: str = "off"       # "on" | "off"
    Syear_Fcst: int = 0
    Eyear_Fcst: int = 0
    SeasonalLookbackYears: int = 3
    fiyearmode: bool = False        # (하위 호환)

    # ── 기타 (하위 호환 / 확장) ───────────────────────────────────────────────
    extras: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.CioNYSKIP = int(self.CioNYSKIP)
        if isinstance(self.StnIDs, str):
            self.StnIDs = [self.StnIDs]
        self.OutletFlowIDs = _to_int_list(self.OutletFlowIDs)
        self.OutletWqIDs   = _to_int_list(self.OutletWqIDs)
        if isinstance(self.Syear_rcp, int):
            self.Syear_rcp = [self.Syear_rcp]
        if isinstance(self.Eyear_rcp, int):
            self.Eyear_rcp = [self.Eyear_rcp]


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _to_int_list(val: Any) -> List[int]:
    if isinstance(val, (int, str)):
        return [int(val)]
    return [int(x) for x in (val or [])]


def _get_nested(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """점-경로로 중첩 dict 에서 값을 꺼냅니다.

    >>> _get_nested({"a": {"b": 1}}, "a", "b")
    1
    """
    node: Any = data
    for k in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(k, default)
        if node is None:
            return default
    return node


# ══════════════════════════════════════════════════════════════════════════════
#  $(섹션.키) 참조 해석
# ══════════════════════════════════════════════════════════════════════════════

_REF_PATTERN = re.compile(r"\$\(([^)]+)\)")


def _flatten_for_refs(data: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
    """중첩 dict 를 '섹션.키' 형태의 단일 dict 로 평탄화합니다.

    예) ``{"project": {"root": "/foo"}}``  →  ``{"project.root": "/foo"}``
    """
    result: Dict[str, str] = {}
    for k, v in data.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten_for_refs(v, full_key))
        elif not isinstance(v, (list, dict)):
            result[full_key] = str(v) if v is not None else ""
    return result


def _resolve_refs(data: Dict[str, Any]) -> Dict[str, Any]:
    """모든 문자열 값의 ``$(키)`` / ``$(섹션.키)`` 참조를 실제 값으로 치환합니다.

    3회 반복하여 체인 참조(A→B→C)를 완전히 해소합니다.
    """
    for _ in range(3):
        flat = _flatten_for_refs(data)
        data = _resolve_node(data, flat)
    return data


def _resolve_node(node: Any, flat: Dict[str, str]) -> Any:
    if isinstance(node, str):
        # 1) ${env:VAR[:default]} 환경변수 먼저 치환
        node = _resolve_env_vars(node)
        # 2) $(섹션.키) 교차참조 치환
        def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
            ref_key = m.group(1)
            return flat.get(ref_key, m.group(0))
        return _REF_PATTERN.sub(_replace, node)
    if isinstance(node, dict):
        return {k: _resolve_node(v, flat) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_node(item, flat) for item in node]
    return node


# ══════════════════════════════════════════════════════════════════════════════
#  형식 감지 및 정규화
# ══════════════════════════════════════════════════════════════════════════════

def _is_nested_format(raw: Dict[str, Any]) -> bool:
    """신규 중첩 형식인지 판별합니다.

    ``project``, ``model``, ``stations`` 중 하나 이상이 dict 이면 신규 형식입니다.
    """
    for key in ("project", "model", "stations", "outlets"):
        if isinstance(raw.get(key), dict):
            return True
    return False


def _normalize_nested(raw: Dict[str, Any]) -> Dict[str, Any]:
    """중첩 YAML → 내부 단순 키-값 dict 로 변환합니다.

    model.type 으로 output 경로 자동 산출 — 사용자가 yaml 에 명시하면 그것 우선.
    """
    flat: Dict[str, Any] = {}

    # 1. 모델 (output 자동 산출 전 model.type 필요)
    mdl = raw.get("model", {})
    model_type = str(mdl.get("type", "swat_plus"))
    if model_type not in VALID_MODEL_TYPES:
        raise ValueError(
            f"model.type 는 {VALID_MODEL_TYPES} 중 하나여야 합니다: '{model_type}'"
        )
    flat["ModelType"]    = model_type
    flat["Executable"]   = mdl.get("executable", "SWAT-Plus.exe")
    flat["CioNYSKIP"]    = mdl.get("warm_up_years", 3)
    flat["OutputTypes"]  = _as_list(mdl.get("output_types", ["sd"]))

    # 2. 디렉토리
    proj = raw.get("project", {})
    flat["PrjDir"]     = proj.get("root", "")
    flat["DbDir"]      = proj.get("database", "")
    flat["QswatTxtInOut"] = proj.get("qswat_txtinout", "") or ""
    inp                = proj.get("input", {})
    flat["ObsDayDir"]  = inp.get("observed_weather", "")
    flat["CcDataDir"]  = inp.get("cc_weather", "")
    flat["FcstDataDir"]= inp.get("forecast_weather", "")
    # 관측 자료 루트 — 미명시 시 $(project.database)/obs 자동
    flat["ObservedDataDir"] = inp.get("observed") or (
        f"{flat['DbDir']}/obs" if flat.get("DbDir") else ""
    )

    # output 경로 — model.type 기반 자동 산출 (사용자 명시 시 그게 우선)
    # 옵션 C 구조: 마스터 2개 (default/calibrated) + 작업 폴더 3개 (calibration/forecast/cchange)
    auto_root = _auto_output_root(flat["PrjDir"], model_type)
    out = proj.get("output", {})

    # 옵션 C 신규 키 (yaml 에서 명시 가능, 미명시 시 자동)
    flat["DefaultDir"]     = out.get("default")     or (f"{auto_root}/default"     if auto_root else "")
    flat["CalibratedDir"]  = out.get("calibrated")  or (f"{auto_root}/calibrated"  if auto_root else "")
    flat["CalibrationDir"] = out.get("calibration") or (f"{auto_root}/calibration" if auto_root else "")
    flat["ForecastDir"]    = out.get("forecast")    or (f"{auto_root}/forecast"    if auto_root else "")
    flat["CchangeDir"]     = out.get("climate_change") or (f"{auto_root}/cchange"  if auto_root else "")

    # 호환 alias — 옛 코드용
    flat["SwatRunDir"]  = out.get("swat_run") or flat["CalibratedDir"]
    flat["SwatObsDir"]  = flat["CalibrationDir"]
    flat["SwatCcDir"]   = flat["CchangeDir"]
    flat["SwatFcstDir"] = flat["ForecastDir"]
    flat["SwatDbDir"]   = out.get("database", "")

    # mismatch 경고 — 사용자 명시 경로가 다른 버전 폴더를 가리키는지 검사
    for name, path in (
        ("output.default",        flat["DefaultDir"]),
        ("output.calibrated",     flat["CalibratedDir"]),
        ("output.calibration",    flat["CalibrationDir"]),
        ("output.forecast",       flat["ForecastDir"]),
        ("output.climate_change", flat["CchangeDir"]),
    ):
        _warn_if_version_mismatch(name, str(path), model_type)

    # 3. 관측소
    stns = raw.get("stations", {})
    flat["StnFile"] = stns.get("metadata_file", "")
    flat["StnIDs"]  = _as_list(stns.get("ids", []))

    # 4. 모니터링 지점
    outlets  = raw.get("outlets", {})
    flow_out = outlets.get("flow", {})
    wq_out   = outlets.get("water_quality", {})
    flat["OutletFlowIDs"] = _as_list(flow_out.get("ids", []))
    flat["OutletFlowNms"] = _as_list(flow_out.get("names", []))
    flat["OutletWqIDs"]   = _as_list(wq_out.get("ids", []))
    flat["OutletWqNms"]   = _as_list(wq_out.get("names", []))

    # 5. 관측 자료
    obs      = raw.get("observed", {})
    flow_obs = obs.get("flow", {})
    wq_obs   = obs.get("water_quality", {})
    flat["ObsFlowFile"] = flow_obs.get("file", "")
    flat["ObsWqFile"]   = wq_obs.get("file", "")

    # 6. 시뮬레이션 기간 — 신규 일자 단위 + 옛 연도 호환
    sim  = raw.get("simulation", {})
    flat["SimOutputTypes"] = _as_list(sim.get("output_types", ["flow"]))
    flat["SimStartDate"]   = str(sim.get("start_date", "") or "")
    flat["SimEndDate"]     = str(sim.get("end_date",   "") or "")
    flat["SimTimeStep"]    = str(sim.get("time_step", "daily") or "daily")
    # 옛 simulation.calibration / validation / baseline (호환)
    cal  = sim.get("calibration", {})
    flat["CalibrationStartYear"] = int(cal.get("start_year", 0) or 0)
    flat["CalibrationEndYear"]   = int(cal.get("end_year",   0) or 0)
    val  = sim.get("validation", {})
    flat["ValidationStartYear"]  = int(val.get("start_year", 0) or 0)
    flat["ValidationEndYear"]    = int(val.get("end_year",   0) or 0)
    base = sim.get("baseline", {})
    flat["BaselineStartYear"]    = int(base.get("start_year", 0) or 0)
    flat["BaselineEndYear"]      = int(base.get("end_year",   0) or 0)

    # 6b. calibration — 신규 블록 (★ observations / parameters / method)
    cal_new = raw.get("calibration", {})
    period = cal_new.get("period", {})
    flat["CalPeriodStart"] = str(period.get("start", "") or "")
    flat["CalPeriodEnd"]   = str(period.get("end",   "") or "")
    val_new = cal_new.get("validation", {})
    flat["ValPeriodStart"] = str(val_new.get("start", "") or "")
    flat["ValPeriodEnd"]   = str(val_new.get("end",   "") or "")

    obs_list_raw = cal_new.get("observations", []) or []
    observations = [
        _Observation(
            id=          str(o.get("id", f"obs_{i}")),
            outlet_id=   int(o.get("outlet_id", 0)),
            variable=    str(o.get("variable", "flow")).lower(),
            unit=        str(o.get("unit", "m3/s")),
            obs_file=    str(o.get("obs_file", "") or ""),
            obs_column=  str(o.get("obs_column", "") or ""),
            outlet_name= str(o.get("outlet_name", "") or ""),
            time_step=   str(o.get("time_step", "daily")),
            weight=      float(o.get("weight", 1.0)),
            objective=   str(o.get("objective", "NSE")).upper(),
        )
        for i, o in enumerate(obs_list_raw)
    ]
    # 관측 자료 obs_file/obs_column/outlet_name 자동 산출
    # (yaml 에 명시되어 있으면 그게 우선)
    flow_ids   = _as_list(outlets.get("flow",          {}).get("ids", []))
    flow_names = _as_list(outlets.get("flow",          {}).get("names", []))
    wq_ids     = _as_list(outlets.get("water_quality", {}).get("ids", []))
    wq_names   = _as_list(outlets.get("water_quality", {}).get("names", []))
    id_to_name: Dict[int, str] = {}
    for ids, names in ((flow_ids, flow_names), (wq_ids, wq_names)):
        for i, oid in enumerate(ids):
            try:
                id_to_name[int(oid)] = str(names[i]) if i < len(names) else ""
            except (TypeError, ValueError):
                continue

    obs_root = flat["ObservedDataDir"]
    for obs in observations:
        # outlet_name 자동
        if not obs.outlet_name:
            obs.outlet_name = id_to_name.get(obs.outlet_id, f"outlet_{obs.outlet_id}")
        # obs_column 자동
        if not obs.obs_column:
            try:
                from swat_py.units import default_column_name
                obs.obs_column = default_column_name(obs.variable, obs.unit)
            except Exception:
                pass
        # obs_file 해석:
        #   - 디렉토리 포함 경로 → 그대로 사용 (절대·상대)
        #   - 파일명만 지정 → {obs_root}/{variable}/{time_step}/ 아래로 해석
        #   - 미지정 → {obs_root}/{variable}/{time_step}/{outlet_name}.csv 자동
        if obs.obs_file:
            has_dir = ("/" in obs.obs_file) or ("\\" in obs.obs_file)
            if not has_dir and obs_root:
                obs.obs_file = (
                    f"{obs_root}/{obs.variable}/{obs.time_step}/{obs.obs_file}"
                )
        elif obs_root:
            obs.obs_file = (
                f"{obs_root}/{obs.variable}/{obs.time_step}/{obs.outlet_name}.csv"
            )
    flat["Observations"] = observations

    param_list_raw = cal_new.get("parameters", []) or []
    flat["CalParameters"] = [
        _CalParameter(
            file=         str(p.get("file", "")),
            key=          str(p.get("key", "")),
            range=        [float(x) for x in (p.get("range") or [0.0, 1.0])],
            change_type=  str(p.get("change_type", "absval")),
        )
        for p in param_list_raw
    ]

    mth = cal_new.get("method", {}) or {}
    mth_par = mth.get("parallel", {}) or {}
    flat["CalMethod"] = _CalMethodCfg(
        name=         str(mth.get("name", "manual")),
        n_iterations= int(mth.get("n_iterations", 100) or 100),
        seed=         int(mth.get("seed", 1) or 1),
        parallel=     _EnsembleParallelCfg(
            enabled=   bool(mth_par.get("enabled", True)),
            n_workers= int(mth_par.get("n_workers", 4) or 4),
        ),
    )

    cal_out = cal_new.get("output", {}) or {}
    flat["CalOutput"] = _CalOutputCfg(
        save_all_runs=          bool(cal_out.get("save_all_runs", False)),
        save_best_n=            int(cal_out.get("save_best_n", 5) or 5),
        auto_parameter_changes= bool(cal_out.get("auto_parameter_changes", True)),
    )

    # 7. 기후변화
    cc = raw.get("climate_change", {})
    flat["CChangeOpt"] = "on" if cc.get("enabled", False) else "off"
    flat["MdlNms"]     = _as_list(cc.get("models", []))
    flat["ScnNms"]     = _as_list(cc.get("scenarios", []))
    hist_p = cc.get("historical_period", {})
    flat["Syear_hist"] = int(hist_p.get("start_year", 1981) or 1981)
    flat["Eyear_hist"] = int(hist_p.get("end_year",   2010) or 2010)
    future_periods_raw = cc.get("future_periods", [])
    flat["Syear_rcp"]  = [int(p["start_year"]) for p in future_periods_raw if "start_year" in p]
    flat["Eyear_rcp"]  = [int(p["end_year"])   for p in future_periods_raw if "end_year"   in p]
    flat["FuturePeriods"] = [
        _FuturePeriod(
            start_year=int(p.get("start_year", 0)),
            end_year=int(p.get("end_year", 0)),
            label=str(p.get("label", "")),
        )
        for p in future_periods_raw
    ]

    # 8. 앙상블 확률예보
    ens = raw.get("ensemble_forecast", {})
    flat["EnsembleForecastEnabled"] = bool(ens.get("enabled", False))
    flat["EnsembleDir"]             = str(ens.get("ensemble_dir", ""))
    flat["EnsembleNMembers"]        = int(ens.get("n_members", 1000) or 1000)
    par = ens.get("parallel", {})
    flat["EnsembleParallel"] = _EnsembleParallelCfg(
        enabled=bool(par.get("enabled", True)),
        n_workers=int(par.get("n_workers", 4) or 4),
    )
    flat["EnsembleQuantiles"] = _as_list(
        ens.get("quantiles", [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
    )
    fcst_p = ens.get("forecast_period", {})
    flat["EnsembleStartYear"] = int(fcst_p.get("start_year", 0) or 0)
    flat["EnsembleEndYear"]   = int(fcst_p.get("end_year",   0) or 0)

    # 9. 계절 예보
    sf = raw.get("seasonal_forecast", {})
    flat["SForecastOpt"] = "on" if sf.get("enabled", False) else "off"
    sf_p = sf.get("forecast_period", {})
    flat["Syear_Fcst"]         = int(sf_p.get("start_year", 0) or 0)
    flat["Eyear_Fcst"]         = int(sf_p.get("end_year",   0) or 0)
    flat["SeasonalLookbackYears"] = int(sf.get("lookback_years", 3) or 3)

    return flat


def _normalize_legacy(raw: Dict[str, Any]) -> Dict[str, Any]:
    """구 단순 YAML → 내부 단순 키-값 dict 로 변환합니다 (대부분 1:1 매핑)."""
    flat: Dict[str, Any] = dict(raw)

    # 구 형식에 없는 신규 필드 기본값 설정
    flat.setdefault("ModelType",   "swat_plus")
    if flat["ModelType"] not in VALID_MODEL_TYPES:
        raise ValueError(
            f"ModelType 은 {VALID_MODEL_TYPES} 중 하나여야 합니다: '{flat['ModelType']}'"
        )

    # output 경로 자동 산출 (사용자 명시 시 우선) — 옵션 C 구조
    prj_dir = str(flat.get("PrjDir", ""))
    auto_root = _auto_output_root(prj_dir, flat["ModelType"])
    if auto_root:
        flat["DefaultDir"]     = flat.get("DefaultDir")     or f"{auto_root}/default"
        flat["CalibratedDir"]  = flat.get("CalibratedDir")  or f"{auto_root}/calibrated"
        flat["CalibrationDir"] = flat.get("CalibrationDir") or f"{auto_root}/calibration"
        flat["ForecastDir"]    = flat.get("ForecastDir")    or f"{auto_root}/forecast"
        flat["CchangeDir"]     = flat.get("CchangeDir")     or f"{auto_root}/cchange"
        # 호환 alias
        flat["SwatRunDir"]  = flat.get("SwatRunDir") or flat["CalibratedDir"]
        flat["SwatObsDir"]  = flat["CalibrationDir"]
        flat["SwatCcDir"]   = flat["CchangeDir"]
        flat["SwatFcstDir"] = flat["ForecastDir"]
    for name, path in (
        ("DefaultDir",     flat.get("DefaultDir", "")),
        ("CalibratedDir",  flat.get("CalibratedDir", "")),
        ("CalibrationDir", flat.get("CalibrationDir", "")),
        ("ForecastDir",    flat.get("ForecastDir", "")),
        ("CchangeDir",     flat.get("CchangeDir", "")),
    ):
        _warn_if_version_mismatch(name, str(path), flat["ModelType"])

    flat.setdefault("Executable",  "SWAT-Plus.exe")
    flat.setdefault("SimOutputTypes", flat.get("OutputTypes", ["flow"]))
    flat.setdefault("EnsembleForecastEnabled", False)
    flat.setdefault("EnsembleDir", "")
    flat.setdefault("EnsembleNMembers", 1000)
    flat.setdefault("EnsembleParallel", _EnsembleParallelCfg())
    flat.setdefault("EnsembleQuantiles", [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
    flat.setdefault("EnsembleStartYear", 0)
    flat.setdefault("EnsembleEndYear", 0)
    flat.setdefault("SeasonalLookbackYears", 3)
    flat.setdefault("CalibrationStartYear", 0)
    flat.setdefault("CalibrationEndYear", 0)
    flat.setdefault("ValidationStartYear", 0)
    flat.setdefault("ValidationEndYear", 0)
    flat.setdefault("BaselineStartYear", flat.get("Syear_hist", 0))
    flat.setdefault("BaselineEndYear",   flat.get("Eyear_hist", 0))
    flat.setdefault("FuturePeriods", [])
    return flat


def _as_list(val: Any) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


# ══════════════════════════════════════════════════════════════════════════════
#  디렉토리 자동 생성
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_dirs(cfg: EnvConfig) -> None:
    """존재하지 않는 출력 디렉토리를 자동으로 생성합니다 (옵션 C 마스터+작업 분리)."""
    dirs = [
        cfg.ObsDayDir,
        cfg.SwatDbDir,
        # 마스터 (READ-ONLY 의도, 폴더만 미리 생성)
        cfg.DefaultDir,
        cfg.CalibratedDir,
        # 작업 폴더 + runs/results 하위 컨벤션
        cfg.CalibrationDir,
        f"{cfg.CalibrationDir}/runs"    if cfg.CalibrationDir else "",
        f"{cfg.CalibrationDir}/results" if cfg.CalibrationDir else "",
        cfg.ForecastDir,
        cfg.CchangeDir,
        f"{cfg.CchangeDir}/runs"    if cfg.CchangeDir else "",
        f"{cfg.CchangeDir}/summary" if cfg.CchangeDir else "",
    ]
    for d in dirs:
        if d:
            Path(d).mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  공개 API
# ══════════════════════════════════════════════════════════════════════════════

def load_config(
    envfile: Union[str, Path],
    override: Optional[Dict[str, Any]] = None,
) -> EnvConfig:
    """swat_py YAML 설정 파일을 읽어 :class:`EnvConfig` 를 반환합니다.

    신규 중첩 형식(swat_py.yaml)과 구 단순 형식(rSWAT.yaml) 모두 지원합니다.

    Parameters
    ----------
    envfile:
        YAML 설정 파일 경로.
    override:
        로드 후 덮어쓸 키-값 dict.
        예) ``{"CioNYSKIP": 5}`` 또는 ``{"model": {"warm_up_years": 5}}``.
    """
    envfile = Path(envfile)
    with envfile.open("r", encoding="utf-8") as fh:
        raw: Dict[str, Any] = yaml.safe_load(fh) or {}

    # $(참조) 해석
    raw = _resolve_refs(raw)

    # override 적용
    if override:
        _deep_update(raw, override)

    # 형식 감지 및 평탄화
    if _is_nested_format(raw):
        flat = _normalize_nested(raw)
    else:
        flat = _normalize_legacy(raw)

    # EnvConfig 생성
    known = set(EnvConfig.__dataclass_fields__) - {"extras"}
    cfg_kwargs: Dict[str, Any] = {}
    extras: Dict[str, Any] = {}
    for k, v in flat.items():
        if k in known:
            cfg_kwargs[k] = v
        else:
            extras[k] = v

    cfg = EnvConfig(**cfg_kwargs, extras=extras)
    _ensure_dirs(cfg)
    return cfg


def _deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> None:
    """base dict 를 updates 로 재귀적으로 갱신합니다 (중첩 dict 병합)."""
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
