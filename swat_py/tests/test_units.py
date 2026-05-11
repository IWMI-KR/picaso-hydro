"""swat_py.units — 단위 변환 검증."""
from __future__ import annotations

import pytest

from swat_py.units import (
    base_unit,
    concentration_to_load,
    convert,
    convert_flow,
    load_to_concentration,
    validate_unit,
)


# ── validate / base ─────────────────────────────────────────────────────────

def test_base_unit_flow_is_m3s() -> None:
    assert base_unit("flow") == "m3/s"


def test_base_unit_loads_are_kgday() -> None:
    assert base_unit("tn") == "kg/day"
    assert base_unit("tp") == "kg/day"


def test_validate_unit_ok() -> None:
    validate_unit("flow", "m3/s")
    validate_unit("flow", "mm/day")
    validate_unit("tn",   "mg/L")
    validate_unit("ss",   "t/day")


def test_validate_unit_unknown_variable_raises() -> None:
    with pytest.raises(ValueError, match="variable"):
        validate_unit("temperature", "C")


def test_validate_unit_disallowed_unit_raises() -> None:
    with pytest.raises(ValueError, match="허용 단위"):
        validate_unit("flow", "kg/day")


# ── flow 변환 ───────────────────────────────────────────────────────────────

def test_flow_m3s_to_ls() -> None:
    assert convert_flow(1.0, "m3/s", "l/s") == pytest.approx(1000.0)


def test_flow_m3s_to_m3day() -> None:
    assert convert_flow(1.0, "m3/s", "m3/day") == pytest.approx(86400.0)


def test_flow_m3s_to_mm_day_round_trip() -> None:
    """유역 100 km² (= 1e8 m²) 에서 1 m3/s 는 0.864 mm/day."""
    area = 1e8
    mmday = convert_flow(1.0, "m3/s", "mm/day", basin_area_m2=area)
    assert mmday == pytest.approx(0.864, rel=1e-6)
    # 역변환
    back = convert_flow(mmday, "mm/day", "m3/s", basin_area_m2=area)
    assert back == pytest.approx(1.0)


def test_flow_mm_day_requires_area() -> None:
    with pytest.raises(ValueError, match="basin_area_m2"):
        convert_flow(1.0, "m3/s", "mm/day")


def test_flow_identity() -> None:
    assert convert_flow(7.5, "m3/s", "m3/s") == 7.5


# ── 부하 ↔ 농도 ────────────────────────────────────────────────────────────

def test_load_to_concentration() -> None:
    """1 kg/day @ 1 m3/s = 1/86.4 mg/L ≈ 0.01157."""
    c = load_to_concentration(1.0, 1.0)
    assert c == pytest.approx(1.0 / 86.4, rel=1e-6)


def test_concentration_to_load() -> None:
    """1 mg/L @ 1 m3/s = 86.4 kg/day."""
    l = concentration_to_load(1.0, 1.0)
    assert l == pytest.approx(86.4)


def test_load_concentration_round_trip() -> None:
    load = 100.0
    flow = 5.0
    conc = load_to_concentration(load, flow)
    back = concentration_to_load(conc, flow)
    assert back == pytest.approx(load)


def test_load_to_concentration_zero_flow() -> None:
    assert load_to_concentration(10.0, 0.0) == 0.0


# ── convert() 일반 ────────────────────────────────────────────────────────

def test_convert_tn_kgday_to_mgl() -> None:
    out = convert(100.0, "tn", "kg/day", "mg/L", flow_m3s=10.0)
    assert out == pytest.approx(100.0 / (10.0 * 86.4), rel=1e-6)


def test_convert_ss_tday_to_mgl() -> None:
    """t/day → mg/L (먼저 kg/day 환산)."""
    # 0.864 t/day = 864 kg/day @ 10 m3/s = 1 mg/L
    out = convert(0.864, "ss", "t/day", "mg/L", flow_m3s=10.0)
    assert out == pytest.approx(1.0, rel=1e-4)


def test_convert_identity() -> None:
    assert convert(5.0, "flow", "m3/s", "m3/s") == 5.0
    assert convert(2.0, "tn",   "mg/L", "mg/L", flow_m3s=1.0) == 2.0


def test_convert_invalid_pair_raises() -> None:
    with pytest.raises(ValueError, match="허용 단위"):
        convert(1.0, "flow", "kg/day", "m3/s")


def test_convert_load_concentration_needs_flow() -> None:
    with pytest.raises(ValueError, match="flow_m3s"):
        convert(1.0, "tn", "kg/day", "mg/L")
