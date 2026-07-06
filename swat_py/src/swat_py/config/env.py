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
        outlet_name = 미명시 시 "outlet_{outlet_id}" 로 산출
    """
    id:         str
    outlet_id:  int
    variable:   str           # flow | ss | tn | tp
    unit:       str           # m3/s, mm/day, mg/L, kg/day 등
    obs_file:   str = ""       # 미명시 시 자동 산출
    obs_column: str = ""       # 미명시 시 자동 산출
    outlet_name: str = ""      # 미명시 시 "outlet_{outlet_id}" 자동
    time_step:  str = "daily"  # daily | monthly | 10day
    weight:     float = 1.0
    objective:  str = "NSE"    # NSE | KGE | R2 | PBIAS | RMSE
    # 저수지(댐) 수위 관측 전용 — variable="wlevel" 일 때만 사용.
    reservoir:  str = ""       # reservoirs: 레지스트리 참조(이름). 지정 시 곡선·datum 상속.
    #   (곡선 없을 때 fallback) stage(m) = datum_m + shape_factor · V/A
    shape_factor: float = 1.0  # 1.0=각주형(평균수심), 2.0=쐐기형
    datum_m:      float = 0.0  # 수위계 기준면 오프셋(m)


@dataclass
class _Reservoir:
    """yaml.reservoirs.<name> 항목 — 저수지 물성·수위내용적 곡선.

    stage_storage_file 는 로드 후 obs/reservoir/ 하위로 해석된 경로.
    """
    name:               str
    gis_id:             int = 0        # SWAT+ reservoir_con.gis_id (reservoir_day 필터)
    stage_storage_file: str = ""       # 수위-내용적 CSV 경로
    obs_datum_offset_ft: float = 0.0   # 관측 staff-gauge → 곡선 datum 보정(보정 자유변수)
    interp:             str = "pchip"  # linear | pchip
    crest_ft:           float = float("nan")
    spillway_ft:        float = float("nan")
    bottom_ft:          float = float("nan")
    # 취수(상수도 등) — 저수지 물수지에서 차감. simulate_managed_storage 로 반영.
    withdrawal_m3s:     float = 0.0            # 상수 취수(m³/s). 예: 1 MGD=0.0438
    withdrawal_monthly_m3s: Optional[List[float]] = None  # 월별(1~12월) 취수(선택, 상수보다 우선)
    cap_level_ft:       float = float("nan")  # 월류 임계 수위. 미지정 시 spillway_ft 사용
    init_level_ft:      float = float("nan")  # 초기 수위. 미지정 시 만수(cap)


@dataclass
class _CalParameter:
    """yaml.calibration.parameters[] 항목."""
    file:        str           # 입력 파일명 (basin.bsn, hydrology.hyd 등)
    key:         str           # 인자 이름
    range:       List[float]   # [min, max]
    change_type: str = "absval"  # absval | relchg | abschg
    rows:        Optional[List[int]] = None  # SWAT+ 파일 특정 행(0-based)만 적용
                                             # None=전체행. 지역화(regionalization)용.


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
class _TankCfg:
    """yaml.tank 블록 — 3단 Tank 모형 검보정 설정 (관측소·기간은 calibration 공유).

    기상자료(강수 CSV·관측소 위도)는 SWAT+와 동일한 소스를 쓴다 — 강수 CSV 폴더는
    ``cfg.ObsDayDir``(공통 obs_weather_std), 관측소 위도는 ``cfg.ObsDayDir/cfg.StnFile``
    (stations 메타 CSV). 따라서 tank 블록에 별도 weather_dir/station_meta_csv 를 두지 않는다.

    precip_mapping : {"default": "918430", "<obs_id>": "code" | [[code, w], ...]}
    parameters     : {param_name: [lo, hi]} — 미지정은 model.DEFAULT_BOUNDS.
    basin_areas    : {obs_id: area_km2} — 없으면 basin_area_csv 에서 로드.
    """
    pet_method:      str = "hargreaves"
    precip_mapping:  Dict[str, Any] = field(default_factory=lambda: {"default": "918430"})
    basin_areas:     Dict[str, float] = field(default_factory=dict)
    basin_area_csv:  str = ""
    basin_area_key:  str = "station"
    basin_area_col:  str = "subbasin_area_km2"
    parameters:      Dict[str, Any] = field(default_factory=dict)
    default_lat:     float = 0.0
    n_iterations:    int = 300
    seed:            int = 1


@dataclass
class _DroughtCfg:
    """yaml.drought 블록 — 가뭄위험 대시보드(①~⑤) 설정.

    outlets : {gis_id(int): name(str)} — 12개 소유역 outlet 채널. 미계측은 outlet_chNN.
    """
    outlets:         Dict[int, str] = field(default_factory=dict)
    forecast:        str = "2016_AMJ"
    n_members:       int = 100
    forecast_station: str = ""    # 미지정 시 obs_weather_std/stations-acidwg.csv 로 결정
    climatology_csv: str = ""
    climatology_years: List[int] = field(default_factory=lambda: [2003, 2024])
    # 장기 기후(평년·FDC) 재실행 기간 — acidwg observation(syear/eyear)과 동일 값 사용.
    # SWAT+ sim=[syear, eyear], 웜업(CioNYSKIP) 제외 후 출력. climatology 파일명에 사용.
    syear:           int = 0           # 0 이면 climatology_years[0] 로 대체(하위호환)
    eyear:           int = 0           # 0 이면 climatology_years[-1]
    ensemble_root:   str = ""          # 미지정 시 1_acidwg/forecast/{year}_{season}
    # 운영 예보 시 warm-up 을 최근접 ERA5 격자 일자료로 재구성(그 전 관측이 없을 때).
    #   true → 0_database/era5/grid_daily_std 사용(util-era5-update 로 최신화 필요). 기본 false.
    era5_warmup:     bool = False
    # ── 4단계 급수단계 경계 (설정 가능) ──────────────────────────────────────
    #  method: fdc_exceedance | nonexceed_percentile | fixed_flow
    #  values: [Normal|Watch, Watch|Warning, Warning|Crisis] — method 별 의미 상이(fdc.stage_thresholds).
    threshold_method: str = "fdc_exceedance"
    threshold_values: List[float] = field(
        default_factory=lambda: [70.0, 90.0, 95.0])   # Q70/Q90/Q95 (USDM D0/D2/D3, WMO Q95)


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

    # ── 관측소 (SWAT+·Tank 공용 기상관측소 메타 — 기본 stations-hydro.csv) ──────
    StnFile: str = "stations-hydro.csv"
    StnIDs: List[str] = field(default_factory=list)

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
    Reservoirs:     Dict[str, "_Reservoir"] = field(default_factory=dict)
    CalParameters:  List[_CalParameter] = field(default_factory=list)
    CalMethod:      _CalMethodCfg       = field(default_factory=_CalMethodCfg)
    CalOutput:      _CalOutputCfg       = field(default_factory=_CalOutputCfg)
    # ── Tank 모형 (선택) ──────────────────────────────────────────────────────
    Tank:           _TankCfg            = field(default_factory=_TankCfg)
    # ── 가뭄위험 대시보드 (선택) ──────────────────────────────────────────────
    Drought:        _DroughtCfg         = field(default_factory=_DroughtCfg)

    # ── 기후변화 ──────────────────────────────────────────────────────────────
    CChangeOpt: str = "off"         # "on" | "off"
    # cchange 전용 기상관측소 메타(예: stations-cchange.csv) — CMIP6 상세화 기상작성용.
    CChangeStnFile: str = "stations-cchange.csv"
    CChangeStnIDs: List[str] = field(default_factory=list)  # 비우면 파일 내 전체 관측소
    MdlNms: List[str] = field(default_factory=list)
    ScnNms: List[str] = field(default_factory=list)
    Syear_hist: int = 1981
    Eyear_hist: int = 2010
    Syear_rcp: List[int] = field(default_factory=list)
    Eyear_rcp: List[int] = field(default_factory=list)
    FuturePeriods: List[_FuturePeriod] = field(default_factory=list)

    # (구 계절/앙상블 예측 파이프라인 제거 — 예측은 swat_py.drought 로 일원화)

    # ── 기타 (하위 호환 / 확장) ───────────────────────────────────────────────
    extras: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.CioNYSKIP = int(self.CioNYSKIP)
        if isinstance(self.StnIDs, str):
            self.StnIDs = [self.StnIDs]
        if isinstance(self.Syear_rcp, int):
            self.Syear_rcp = [self.Syear_rcp]
        if isinstance(self.Eyear_rcp, int):
            self.Eyear_rcp = [self.Eyear_rcp]

    # ── outlet 목록 산출 (calibration.observations[] 기반) ─────────────────────
    def outlets_for(self, *, flow: bool) -> "tuple[List[int], List[str]]":
        """observations[] 에서 (outlet_id, outlet_name) 목록을 산출합니다.

        구 ``outlets`` (모니터링 지점) 블록을 대체 — 분석/시각화 루프용.

        flow=True  → variable=='flow' 관측점,
        flow=False → 수질(ss/tn/tp) 관측점.
        같은 outlet_id 는 첫 등장만 유지(순서 보존)합니다.
        """
        wq = ("ss", "tn", "tp")
        ids: List[int] = []
        names: List[str] = []
        seen: set = set()
        for o in self.Observations:
            is_flow = o.variable == "flow"
            if is_flow != flow:
                continue
            if not is_flow and o.variable not in wq:
                continue
            if o.outlet_id in seen:
                continue
            seen.add(o.outlet_id)
            ids.append(o.outlet_id)
            names.append(o.outlet_name)
        return ids, names


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

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

    ``project``, ``path``, ``model``, ``stations`` 중 하나 이상이 dict 이면 신규 형식입니다.
    """
    for key in ("project", "path", "model", "stations"):
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
    #    신규: swat 전용 경로는 `path:` 섹션. 구 `project.input/output` 하위호환 유지.
    #    (root/database/observed_weather 는 공통 picaso-hydro.yaml → project 로 주입)
    proj = raw.get("project", {})
    pth  = raw.get("path", {}) or {}
    inp  = proj.get("input", {})
    out  = proj.get("output", {})
    flat["PrjDir"]     = proj.get("root", "")
    flat["DbDir"]      = proj.get("database", "")
    flat["QswatTxtInOut"] = pth.get("qswat_txtinout") or proj.get("qswat_txtinout") or ""
    flat["ObsDayDir"]  = inp.get("observed_weather", "")
    flat["CcDataDir"]  = pth.get("cc_weather") or inp.get("cc_weather", "")
    # 관측 자료 루트 — 미명시 시 $(project.database)/obs 자동
    flat["ObservedDataDir"] = pth.get("observed") or inp.get("observed") or (
        f"{flat['DbDir']}/obs" if flat.get("DbDir") else ""
    )

    # output 경로 — model.type 기반 자동 산출 (사용자 명시 시 그게 우선)
    # 옵션 C 구조: 마스터 2개 (default/calibrated) + 작업 폴더 3개 (calibration/forecast/cchange)
    auto_root = _auto_output_root(flat["PrjDir"], model_type)

    # 옵션 C 신규 키 (yaml 에서 명시 가능, 미명시 시 자동)
    # DefaultDir(=SWAT+ TxtInOut 마스터): 신규 path.swatplus_txtinout / 구 output.default
    flat["DefaultDir"]     = pth.get("swatplus_txtinout") or out.get("default") or (f"{auto_root}/default" if auto_root else "")
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
    # stations 섹션은 선택 — 미지정 시 SWAT+·Tank 공용 stations-hydro.csv 기본.
    stns = raw.get("stations", {})
    flat["StnFile"] = stns.get("metadata_file") or "stations-hydro.csv"
    flat["StnIDs"]  = _as_list(stns.get("ids", []))

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
            reservoir=   str(o.get("reservoir", "") or ""),
            shape_factor=float(o.get("shape_factor", 1.0)),
            datum_m=     float(o.get("datum_m", 0.0)),
        )
        for i, o in enumerate(obs_list_raw)
    ]
    # 관측 자료 obs_file/obs_column/outlet_name 자동 산출
    # (yaml 에 명시되어 있으면 그게 우선)
    obs_root = flat["ObservedDataDir"]
    for obs in observations:
        # outlet_name 미명시 시 outlet_{id} 로 산출 (명시값 우선)
        if not obs.outlet_name:
            obs.outlet_name = f"outlet_{obs.outlet_id}"
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

    # 저수지 레지스트리 (reservoirs:) — 수위-내용적 곡선·물성
    reservoirs_raw = raw.get("reservoirs", {}) or {}
    reservoirs: Dict[str, _Reservoir] = {}
    for rname, rv in reservoirs_raw.items():
        rv = rv or {}
        ssf = str(rv.get("stage_storage_file", "") or "")
        # stage_storage_file 해석: 디렉토리 포함 → 그대로 / 파일명만 → obs/reservoir/
        if ssf and not (("/" in ssf) or ("\\" in ssf)) and obs_root:
            ssf = f"{obs_root}/reservoir/{ssf}"
        wmon = rv.get("withdrawal_monthly_m3s", None)
        reservoirs[str(rname)] = _Reservoir(
            name=               str(rname),
            gis_id=             int(rv.get("gis_id", 0) or 0),
            stage_storage_file= ssf,
            obs_datum_offset_ft=float(rv.get("obs_datum_offset_ft", 0.0) or 0.0),
            interp=             str(rv.get("interp", "pchip") or "pchip"),
            crest_ft=           float(rv.get("crest_ft", float("nan"))),
            spillway_ft=        float(rv.get("spillway_ft", float("nan"))),
            bottom_ft=          float(rv.get("bottom_ft", float("nan"))),
            withdrawal_m3s=     float(rv.get("withdrawal_m3s", 0.0) or 0.0),
            withdrawal_monthly_m3s=([float(x) for x in wmon] if wmon else None),
            cap_level_ft=       float(rv.get("cap_level_ft", float("nan"))),
            init_level_ft=      float(rv.get("init_level_ft", float("nan"))),
        )
    flat["Reservoirs"] = reservoirs

    # observation.reservoir 링크 시 outlet_id 미지정(0)이면 저수지 gis_id 상속
    for obs in observations:
        if obs.reservoir and obs.reservoir in reservoirs and not obs.outlet_id:
            obs.outlet_id = reservoirs[obs.reservoir].gis_id

    param_list_raw = cal_new.get("parameters", []) or []
    flat["CalParameters"] = [
        _CalParameter(
            file=         str(p.get("file", "")),
            key=          str(p.get("key", "")),
            range=        [float(x) for x in (p.get("range") or [0.0, 1.0])],
            change_type=  str(p.get("change_type", "absval")),
            rows=         ([int(r) for r in p.get("rows")]
                          if p.get("rows") is not None else None),
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

    # 6c. tank — 3단 Tank 모형 (선택). 미지정 시 기본값(_TankCfg) 사용.
    tk = raw.get("tank", {}) or {}
    tk_mth = tk.get("method", {}) or {}
    flat["Tank"] = _TankCfg(
        pet_method=      str(tk.get("pet_method", "hargreaves") or "hargreaves"),
        precip_mapping=  dict(tk.get("precip_mapping", {"default": "918430"}) or {"default": "918430"}),
        basin_areas=     {str(k): float(v) for k, v in (tk.get("basin_areas", {}) or {}).items()},
        basin_area_csv=  str(tk.get("basin_area_csv", "") or ""),
        basin_area_key=  str(tk.get("basin_area_key", "station") or "station"),
        basin_area_col=  str(tk.get("basin_area_col", "subbasin_area_km2") or "subbasin_area_km2"),
        parameters=      {str(k): [float(x) for x in v]
                          for k, v in (tk.get("parameters", {}) or {}).items()},
        default_lat=     float(tk.get("default_lat", 0.0) or 0.0),
        n_iterations=    int(tk_mth.get("n_iterations", 300) or 300),
        seed=            int(tk_mth.get("seed", 1) or 1),
    )

    # 6d. drought — 가뭄위험 대시보드 (선택). 미지정 시 기본값(_DroughtCfg).
    dr = raw.get("drought", {}) or {}
    dr_ens = dr.get("ensemble", {}) or {}
    dr_thr = dr.get("thresholds", {}) or {}
    flat["Drought"] = _DroughtCfg(
        outlets=          {int(k): str(v) for k, v in (dr.get("outlets", {}) or {}).items()},
        forecast=         str(dr.get("forecast", "2016_AMJ") or "2016_AMJ"),
        n_members=        int(dr_ens.get("n_members", 100) or 100),
        forecast_station= str(dr.get("forecast_station", "") or ""),
        climatology_csv=  str(dr.get("climatology_csv", "") or ""),
        climatology_years=[int(x) for x in (dr.get("climatology_years", [2003, 2024]) or [2003, 2024])],
        syear=            int(dr.get("syear", 0) or 0),
        eyear=            int(dr.get("eyear", 0) or 0),
        ensemble_root=    str(dr_ens.get("root", "") or ""),
        era5_warmup=      bool(dr.get("era5_warmup", False)),
        threshold_method= str(dr_thr.get("method", "fdc_exceedance") or "fdc_exceedance"),
        threshold_values= [float(x) for x in (dr_thr.get("values", [50.685, 75.342, 97.260])
                                              or [50.685, 75.342, 97.260])],
    )

    # 7. 기후변화
    cc = raw.get("climate_change", {})
    flat["CChangeOpt"] = "on" if cc.get("enabled", False) else "off"
    # cchange 전용 관측소 메타/ids (CMIP6 상세화 기상작성). 미지정 시 stations-cchange.csv.
    flat["CChangeStnFile"] = cc.get("metadata_file") or "stations-cchange.csv"
    flat["CChangeStnIDs"]  = _as_list(cc.get("ids", []))
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

    # 8~9. (구 앙상블/계절 예측 설정 제거 — 예측은 swat_py.drought 로 일원화)

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
        # CchangeDir(3_swatplus/cchange)는 여기서 미리 만들지 않는다 — 실제 기후변화
        #   자료 생성 시 cchange 모듈(runner/analysis)이 Output·Analysis·Summary 를
        #   parents=True 로 생성한다(불필요한 빈 폴더 방지).
    ]
    for d in dirs:
        if d:
            Path(d).mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  공개 API
# ══════════════════════════════════════════════════════════════════════════════

def _load_shared_yaml(envfile: Union[str, Path],
                      shared_file: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """같은 config 폴더(또는 지정 경로)의 공통 picaso-hydro.yaml 로드(없으면 {})."""
    p = Path(shared_file) if shared_file else Path(envfile).parent / "picaso-hydro.yaml"
    if not p.is_file():
        return {}
    with p.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _merge_shared_swat(shared: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    """공통(중립) 키를 swat 설정 구조로 주입. tool(swat_py.yaml) 값이 있으면 우선."""
    if not shared:
        return raw
    # project: 공통 root/database/obs_weather_std + swat 전용(qswat_txtinout/input/output)
    raw["project"] = {**(shared.get("project") or {}), **(raw.get("project") or {})}
    # 공통 관측기상 경로(project.obs_weather_std) → project.input.observed_weather (ObsDayDir)
    ows = (shared.get("project") or {}).get("obs_weather_std")
    if ows is not None:
        raw["project"].setdefault("input", {}).setdefault("observed_weather", ows)
    wu = (shared.get("simulation") or {}).get("warm_up_years")
    if wu is not None:                          # warm-up → model.warm_up_years (env 가 읽는 위치)
        raw.setdefault("model", {}).setdefault("warm_up_years", wu)
    f = shared.get("forecast") or {}
    d = raw.setdefault("drought", {})
    if f.get("period") is not None:
        d.setdefault("forecast", f["period"])
    # forecast_station 은 obs_weather_std/stations-acidwg.csv 에서 런타임 결정(설정에 두지 않음)
    de = d.setdefault("ensemble", {})
    nm = (shared.get("ensemble") or {}).get("n_members")
    if nm is not None:
        de.setdefault("n_members", nm)
    # ensemble.root(멤버 루트)는 공통에서 제거됨 → swat 은 dashboard_data 의 기본경로
    # (PrjDir/1_acidwg/hindcast) 로 자동 해석(acidwg output_root/hindcast 와 동일).
    return raw


def load_config(
    envfile: Union[str, Path],
    override: Optional[Dict[str, Any]] = None,
    shared_file: Optional[Union[str, Path]] = None,
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

    # PICASO_ROOT 미설정 시 config 파일 위치(<project>/config/)에서 프로젝트 루트 자동 유도.
    #   → picaso-hydro.yaml 의 ${env:PICASO_ROOT:<하드코딩 fallback>} 오해석(리눅스에서 윈도우
    #     경로로 떨어지는 문제) 방지. 환경변수가 이미 있으면 존중.
    if not os.environ.get("PICASO_ROOT"):
        cf = envfile.resolve()
        if cf.parent.name == "config":
            os.environ["PICASO_ROOT"] = str(cf.parent.parent)

    with envfile.open("r", encoding="utf-8") as fh:
        raw: Dict[str, Any] = yaml.safe_load(fh) or {}

    # 공통 picaso-hydro.yaml 병합 (공통값을 swat 구조로 주입)
    raw = _merge_shared_swat(_load_shared_yaml(envfile, shared_file), raw)

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
