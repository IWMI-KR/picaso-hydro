"""저수지 출력을 저수량(%) → 수위(ft)로 (P1-B, 회귀 방지).

요청(유진호 2026-08-26): "Ngerimel 댐의 output 이 저수량(volume)인데 **수위로
나와야 합니다. 수위예측이니까요.** 해발고도로 만수위 45 m 로 작업하신 것 같은데
현지 실측 수치는 23 m 가 만수위이니 **22 를 빼서** 출력해야 할 거예요."

고치기 전: 예측 경로에 `obs_datum_offset_ft` 가 적용되지 않아 수위가 MSL 그대로
(23.34~45.00 ft)였고, 대시보드의 주 지표는 저수량 %였다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.drought.fdc import is_level_method, stage_thresholds
from swat_py.drought.figure import _criterion_label, _is_level_outlet, _is_reservoir_outlet
from swat_py.drought.reservoir_forecast import (
    ReservoirForecastParams,
    build_reservoir_forecast_params,
    capacity_pct_to_level_ft,
    full_level_ft,
    monthly_capacity_series,
)

OFFSET = -22.0          # Ngerimel: 곡선(MSL) → 관측 눈금


def _curve(lo_ft=23.34, hi_ft=45.0, cap=103242.0):
    """Ngerimel 과 같은 범위의 (단순 선형) 수위-내용적 곡선."""
    from swat_py.io.reservoir import StageStorageCurve
    return StageStorageCurve(elev_ft=np.array([lo_ft, hi_ft]),
                             storage_m3=np.array([0.0, cap]))


def _daily(dates, flo_in=0.0):
    n = len(dates)
    return pd.DataFrame({"date": dates, "flo_in": [flo_in] * n,
                         "precip": [0.0] * n, "evap": [0.0] * n, "seep": [0.0] * n})


# ── ① 기준면 보정이 예측 수위에 적용된다 ─────────────────────────────────────

def test_series_applies_datum_offset() -> None:
    curve = _curve()
    dates = pd.date_range("2026-02-01", "2026-02-28", freq="D")
    ser = monthly_capacity_series(_daily(dates), full_m3=103242.0, init_m3=103242.0,
                                  curve=curve, datum_offset_ft=OFFSET)
    assert ser[2]["water_level_msl_ft"] == pytest.approx(45.0)   # 곡선 datum
    assert ser[2]["water_level_ft"] == pytest.approx(23.0)       # 관측 눈금 = 45 − 22


def test_series_without_offset_is_msl() -> None:
    """기본값 0 — 기존 호출부(과거분석·검보정)의 동작이 바뀌지 않는다."""
    curve = _curve()
    dates = pd.date_range("2026-02-01", "2026-02-28", freq="D")
    ser = monthly_capacity_series(_daily(dates), full_m3=103242.0, init_m3=103242.0,
                                  curve=curve)
    assert ser[2]["water_level_ft"] == pytest.approx(ser[2]["water_level_msl_ft"])


def test_params_pick_up_registry_offset() -> None:
    curve = _curve()
    source = type("S", (), {"outlets": {4: "ngerimel"}, "name": "ngerimel",
                            "init_water_level_ft": float("nan")})()
    rcfg = type("R", (), {"spillway_ft": 45.0, "bottom_ft": 23.34, "gis_id": 4,
                          "withdrawal_m3s": 0.0438, "obs_datum_offset_ft": OFFSET})()
    p = build_reservoir_forecast_params(source, rcfg, curve)
    assert p.datum_offset_ft == pytest.approx(OFFSET)
    assert full_level_ft(p) == pytest.approx(23.0)      # 설계 화면의 만수 23.0 ft


def test_full_level_nan_without_curve() -> None:
    assert np.isnan(full_level_ft(ReservoirForecastParams(
        gis_id=4, name="x", full_m3=1e5, dead_m3=0.0, init_m3=1e5)))
    assert np.isnan(full_level_ft(None))


# ── ② 저수량% 평년 → 수위 평년 환산 ─────────────────────────────────────────

def test_capacity_pct_to_level_uses_curve_not_linear_percent() -> None:
    """"85%" 를 수위 85% 로 읽으면 안 된다 — 곡선으로 되돌려야 한다."""
    p = ReservoirForecastParams(gis_id=4, name="ngerimel", full_m3=103242.0,
                                dead_m3=0.0, init_m3=103242.0, curve=_curve(),
                                datum_offset_ft=OFFSET)
    assert capacity_pct_to_level_ft(100, p) == pytest.approx(23.0)
    # 저수량 85% → 수위 23.34+0.85×21.66 = 41.75 MSL → 19.75 ft (수위 85% = 19.55 가 아님)
    assert capacity_pct_to_level_ft(85, p) == pytest.approx(19.751, abs=0.01)
    assert capacity_pct_to_level_ft(85, p) != pytest.approx(19.55, abs=0.01)


def test_capacity_pct_to_level_clips_and_handles_missing() -> None:
    p = ReservoirForecastParams(gis_id=4, name="x", full_m3=103242.0, dead_m3=0.0,
                                init_m3=103242.0, curve=_curve(), datum_offset_ft=OFFSET)
    assert capacity_pct_to_level_ft(150, p) == pytest.approx(23.0)   # 월류는 만수에서 자름
    assert np.isnan(capacity_pct_to_level_ft(float("nan"), p))
    assert np.isnan(capacity_pct_to_level_ft(80, None))              # 곡선 없음


# ── ③ 수위 기준 임계 ────────────────────────────────────────────────────────

def test_level_fraction_matches_design_screen() -> None:
    """설계 화면(팔라우 HTML)의 23.0 / 19.6 / 15.0 ft 와 일치해야 한다."""
    st = stage_thresholds([], "level_fraction", [100, 85, 65], full_level_ft=23.0)
    assert st["normal_watch"] == pytest.approx(23.0)
    assert st["watch_warning"] == pytest.approx(19.55)      # 화면 19.6
    assert st["warning_crisis"] == pytest.approx(14.95)     # 화면 15.0


def test_level_ft_is_absolute() -> None:
    st = stage_thresholds([], "level_ft", [23.0, 19.6, 15.0])
    assert [st["normal_watch"], st["watch_warning"], st["warning_crisis"]] == [23.0, 19.6, 15.0]


def test_level_fraction_without_full_level_stays_percent() -> None:
    st = stage_thresholds([], "level_fraction", [100, 85, 65])
    assert st["watch_warning"] == pytest.approx(85.0)


def test_capacity_fraction_unchanged() -> None:
    """저수량 기준은 그대로 — full_level_ft 를 줘도 영향받지 않는다."""
    st = stage_thresholds([], "capacity_fraction", [100, 85, 65], full_level_ft=23.0)
    assert st["watch_warning"] == pytest.approx(85.0)


@pytest.mark.parametrize("method,want", [
    ("level_fraction", True), ("stage_fraction", True), ("level_ft", True),
    ("wlevel_ft", True), ("capacity_fraction", False), ("fdc_exceedance", False),
])
def test_is_level_method(method, want) -> None:
    assert is_level_method(method) is want


def test_unknown_method_still_raises() -> None:
    with pytest.raises(ValueError, match="미지원 threshold method"):
        stage_thresholds([], "nonsense", [1, 2, 3])


# ── ④ 그림 — 수위 수원 판별·라벨 ────────────────────────────────────────────

def test_figure_detects_level_outlet() -> None:
    thr = {"method": "level_fraction", "variable": "water_level_ft"}
    assert _is_level_outlet(thr) and _is_reservoir_outlet(thr)
    thr_pct = {"method": "capacity_fraction", "variable": "capacity_pct"}
    assert not _is_level_outlet(thr_pct) and _is_reservoir_outlet(thr_pct)
    thr_str = {"method": "fdc_exceedance"}
    assert not _is_level_outlet(thr_str) and not _is_reservoir_outlet(thr_str)


def test_criterion_labels() -> None:
    assert _criterion_label("level_fraction", 85) == "85% of full level"
    assert _criterion_label("level_ft", 19.6) == "19.6 ft"
    assert _criterion_label("capacity_fraction", 85) == "85%"


# ── ⑤ 수위는 만수를 넘을 수 없다 — 상한 경계 ────────────────────────────────

def test_level_is_clipped_at_full() -> None:
    """유입이 아무리 많아도 **수위**는 만수에서 잘린다(저수량 %는 안 잘린다)."""
    curve = _curve()
    dates = pd.date_range("2026-02-01", "2026-04-30", freq="D")
    ser = monthly_capacity_series(_daily(dates, flo_in=1e6), full_m3=103242.0,
                                  init_m3=103242.0, curve=curve,
                                  datum_offset_ft=OFFSET)
    for m, v in ser.items():
        assert v["water_level_ft"] == pytest.approx(23.0), m      # 만수에서 잘림
        assert v["storage_pct"] > 100.0, m                        # %는 넘어간다


def test_full_reservoir_is_normal_not_watch() -> None:
    """수위 기준의 함정 — 상한 경계가 초과(>)면 월류 중인 만수가 Watch 가 된다.

    수위는 만수에서 잘리므로 `수위 > 만수` 가 영영 성립하지 않는다.
    """
    from swat_py.drought.stages import classify_stage4, stage_probabilities4
    st = stage_thresholds([], "level_fraction", [100, 85, 65], full_level_ft=23.0)
    qs = (st["normal_watch"], st["watch_warning"], st["warning_crisis"])
    assert classify_stage4(23.0, *qs) == "Watch"                       # 고치기 전
    assert classify_stage4(23.0, *qs, top_inclusive=True) == "Normal"  # 고친 뒤
    sp = stage_probabilities4([23.0] * 10, *qs, top_inclusive=True)
    assert sp["Normal"] == pytest.approx(100.0) and sp["most_likely"] == "Normal"


def test_top_inclusive_does_not_change_other_boundaries() -> None:
    """상한만 이상(>=)이다 — 중간 경계는 그대로라 하천 분류가 바뀌지 않는다."""
    from swat_py.drought.stages import classify_stage4
    qs = (23.0, 19.55, 14.95)
    for v, want in [(22.99, "Watch"), (19.55, "Warning"), (19.56, "Watch"),
                    (14.95, "Crisis"), (14.96, "Warning"), (1.34, "Crisis")]:
        assert classify_stage4(v, *qs, top_inclusive=True) == want, v
        assert classify_stage4(v, *qs) == want, v          # 기본값과 동일


def test_capacity_pct_basis_keeps_strict_top() -> None:
    """저수량 % 기준은 100%를 넘길 수 있으므로 기본(초과) 경계가 맞다."""
    from swat_py.drought.stages import classify_stage4
    st = stage_thresholds([], "capacity_fraction", [100, 85, 65])
    qs = (st["normal_watch"], st["watch_warning"], st["warning_crisis"])
    assert classify_stage4(271.0, *qs) == "Normal"     # 월류 → 100% 초과로 표현됨
    assert classify_stage4(100.0, *qs) == "Watch"      # 딱 만수는 Watch(기존 동작 유지)
