"""SWAT 출력 단위 변환 유틸.

yaml.calibration.observations[].unit 의 허용값과 변환 로직을 통합 관리.

지원 변수 + 단위
----------------
flow : m3/s (기본) | mm/day (depth) | l/s | m3/day
ss   : t/day (기본) | mg/L
tn   : kg/day (기본) | mg/L | t/day
tp   : kg/day (기본) | mg/L | t/day

변환 공식 핵심
--------------
flow (mm/day) = flow_m3s × 86400 × 1000 / basin_area_m2
load (mg/L)   = load_kgday / (flow_m3s × 86.4)
load (t/day)  = load_kgday / 1000
"""
from __future__ import annotations

from typing import Optional


# ── 변수별 SWAT 기본 출력 단위 + 허용 사용자 단위 ───────────────────────────

_BASE_UNIT = {
    "flow": "m3/s",
    "ss":   "t/day",
    "tn":   "kg/day",
    "tp":   "kg/day",
}

_ALLOWED_UNITS = {
    "flow": {"m3/s", "mm/day", "l/s", "m3/day"},
    "ss":   {"t/day", "mg/L"},
    "tn":   {"kg/day", "mg/L", "t/day"},
    "tp":   {"kg/day", "mg/L", "t/day"},
}


# ── 검증 ────────────────────────────────────────────────────────────────────

def validate_unit(variable: str, unit: str) -> None:
    """변수·단위 쌍이 지원되는지 검사. 미지원 시 ValueError."""
    var_lc = variable.lower()
    if var_lc not in _ALLOWED_UNITS:
        raise ValueError(
            f"지원하지 않는 variable: '{variable}'. "
            f"허용: {sorted(_ALLOWED_UNITS.keys())}"
        )
    if unit not in _ALLOWED_UNITS[var_lc]:
        raise ValueError(
            f"variable='{variable}' 의 허용 단위가 아님: '{unit}'. "
            f"허용: {sorted(_ALLOWED_UNITS[var_lc])}"
        )


def base_unit(variable: str) -> str:
    """SWAT 의 기본 출력 단위 반환 (변환 출발점)."""
    return _BASE_UNIT[variable.lower()]


# ── flow 변환 ───────────────────────────────────────────────────────────────

def convert_flow(
    value: float,
    from_unit: str,
    to_unit: str,
    *,
    basin_area_m2: Optional[float] = None,
) -> float:
    """유량 단위 변환.

    Parameters
    ----------
    value          : 변환 대상 값
    from_unit      : 입력 단위 (m3/s | mm/day | l/s | m3/day)
    to_unit        : 출력 단위 (동일 집합)
    basin_area_m2  : mm/day 변환 시 필요한 유역 면적 (m²)
    """
    if from_unit == to_unit:
        return float(value)
    # 모두 m3/s 로 우선 환산
    if from_unit == "m3/s":
        v_m3s = float(value)
    elif from_unit == "l/s":
        v_m3s = float(value) / 1000.0
    elif from_unit == "m3/day":
        v_m3s = float(value) / 86400.0
    elif from_unit == "mm/day":
        if basin_area_m2 is None or basin_area_m2 <= 0:
            raise ValueError("mm/day ↔ m3/s 변환은 basin_area_m2 필요")
        # depth_mm/day × area_m2 / (1000 mm/m) / (86400 s/day) = m3/s
        v_m3s = float(value) * basin_area_m2 / 1000.0 / 86400.0
    else:
        validate_unit("flow", from_unit)   # 명확한 에러
        v_m3s = 0.0
    # m3/s → 출력 단위
    if to_unit == "m3/s":
        return v_m3s
    if to_unit == "l/s":
        return v_m3s * 1000.0
    if to_unit == "m3/day":
        return v_m3s * 86400.0
    if to_unit == "mm/day":
        if basin_area_m2 is None or basin_area_m2 <= 0:
            raise ValueError("m3/s → mm/day 변환은 basin_area_m2 필요")
        return v_m3s * 86400.0 * 1000.0 / basin_area_m2
    validate_unit("flow", to_unit)
    return v_m3s


# ── 부하 ↔ 농도 변환 (수질) ────────────────────────────────────────────────

def load_to_concentration(load_kgday: float, flow_m3s: float) -> float:
    """kg/day 부하 → mg/L 농도.

    농도 (mg/L) = load (kg/day) × 1e6 mg/kg / (flow (m3/s) × 86400 s/day × 1000 L/m3)
                = load (kg/day) / (flow (m3/s) × 86.4)
    """
    if flow_m3s <= 0:
        return 0.0
    return float(load_kgday) / (float(flow_m3s) * 86.4)


def concentration_to_load(conc_mgl: float, flow_m3s: float) -> float:
    """mg/L 농도 → kg/day 부하."""
    return float(conc_mgl) * float(flow_m3s) * 86.4


# ── 일반 변환 (variable + from/to unit 자동 분기) ───────────────────────────

def convert(
    value: float,
    variable: str,
    from_unit: str,
    to_unit: str,
    *,
    flow_m3s: Optional[float] = None,
    basin_area_m2: Optional[float] = None,
) -> float:
    """variable 의 from_unit → to_unit 단위 변환.

    Parameters
    ----------
    value          : 변환 대상 값
    variable       : flow | ss | tn | tp
    from_unit      : 입력 단위
    to_unit        : 출력 단위
    flow_m3s       : 부하 ↔ 농도 변환 시 동시점 유량 (m3/s)
    basin_area_m2  : flow mm/day ↔ m3/s 변환 시 유역 면적

    Returns
    -------
    변환된 값
    """
    var_lc = variable.lower()
    validate_unit(var_lc, from_unit)
    validate_unit(var_lc, to_unit)
    if from_unit == to_unit:
        return float(value)

    if var_lc == "flow":
        return convert_flow(value, from_unit, to_unit,
                             basin_area_m2=basin_area_m2)

    # 수질 (ss/tn/tp) — kg/day | t/day | mg/L
    # 1) load 표준 (kg/day) 로 통일
    if from_unit == "kg/day":
        v_kgday = float(value)
    elif from_unit == "t/day":
        v_kgday = float(value) * 1000.0
    elif from_unit == "mg/L":
        if flow_m3s is None or flow_m3s <= 0:
            raise ValueError(f"{var_lc}: mg/L ↔ kg/day 변환은 flow_m3s 필요")
        v_kgday = concentration_to_load(value, flow_m3s)
    else:
        raise ValueError(f"미지원 from_unit: {from_unit}")

    # 2) 출력 단위로
    if to_unit == "kg/day":
        return v_kgday
    if to_unit == "t/day":
        return v_kgday / 1000.0
    if to_unit == "mg/L":
        if flow_m3s is None or flow_m3s <= 0:
            raise ValueError(f"{var_lc}: kg/day → mg/L 변환은 flow_m3s 필요")
        return load_to_concentration(v_kgday, flow_m3s)
    raise ValueError(f"미지원 to_unit: {to_unit}")
