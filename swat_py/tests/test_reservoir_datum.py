"""저수지 설정 수위의 기준면 — 자(staff gauge) 눈금으로 통일.

결정 (유진호 박사 확인, 2026-11-02)
-----------------------------------
기준면은 해발고도(MSL)가 아니라 **만수가 23 ft 가 되는 실측 자 눈금**이다.
``%`` 의 정의도 그 수위 기준이다.

따라서 사용자가 설정에 적는 **운영값**은 모두 자 눈금이다 —
``init_water_level_ft``, ``diversion_target_ft``.
수위-내용적 곡선(stage_storage CSV)과 측량 제원(``spillway_ft``·``bottom_ft``·
``crest_ft``)만 측량 성과라 MSL 로 남고, ``obs_datum_offset_ft`` 가 둘을 잇는다.

왜 테스트가 필요한가
--------------------
기준면을 섞는 실수는 **오류 없이 그럴듯한 숫자**를 낸다. 업체 지적(2026-10-20):
현장 눈금 22.5 를 그대로 넣으면 엔진이 MSL 22.5 로 읽어 사수위(23.34 MSL)보다
낮다고 보고 **시작하자마자 Crisis** 가 됐다.

여기서는 Ngerimel 실제 제원(오프셋 −22.0)을 그대로 쓴다. 오프셋이 0 인 합성
설정으로는 변환 경로를 아예 밟지 않아 회귀를 잡지 못한다.
"""
from __future__ import annotations

import numpy as np
import pytest

from swat_py.config.env import _DroughtSource, _Reservoir
from swat_py.drought.reservoir_forecast import (
    build_reservoir_forecast_params,
    full_level_ft,
)
from swat_py.io.reservoir import StageStorageCurve

# Ngerimel 실제 제원 — 곡선은 MSL, 자 눈금 = MSL − 22.0
OFFSET = -22.0
BOTTOM_MSL, FULL_MSL, CREST_MSL = 23.34, 45.0, 51.0
BOTTOM_G, FULL_G, CREST_G = 1.34, 23.0, 29.0        # 자 눈금 환산


def _curve():
    return StageStorageCurve(
        elev_ft=np.array([BOTTOM_MSL, 34.0, FULL_MSL, CREST_MSL]),
        storage_m3=np.array([0.0, 40000.0, 100000.0, 190000.0]))


def _rcfg(**kw):
    base = dict(name="ngerimel", gis_id=4, spillway_ft=FULL_MSL, bottom_ft=BOTTOM_MSL,
                crest_ft=CREST_MSL, obs_datum_offset_ft=OFFSET)
    base.update(kw)
    return _Reservoir(**base)


def _src(**kw):
    base = dict(name="ngerimel", type="reservoir", reservoir="ngerimel",
                outlets={4: "ngerimel"}, threshold_method="level_fraction",
                threshold_values=[95, 85, 65])
    base.update(kw)
    return _DroughtSource(**base)


# ── 만수는 자 눈금 23.0 ──────────────────────────────────────────────────────

def test_만수는_자_눈금_23ft_다():
    p = build_reservoir_forecast_params(_src(), _rcfg(), _curve())
    assert full_level_ft(p) == pytest.approx(FULL_G, abs=0.001)


# ── 초기수위: 자 눈금으로 읽는다 ─────────────────────────────────────────────

def test_초기수위를_자_눈금으로_해석한다():
    """자 눈금 22.0 = MSL 44.0 — 곡선에서 그 저류량이 나와야 한다."""
    curve = _curve()
    p = build_reservoir_forecast_params(_src(init_water_level_ft=22.0), _rcfg(), curve)
    assert p.init_m3 == pytest.approx(float(curve.stage_to_storage(44.0)))


def test_만수_눈금을_넣으면_만수_저류량이_된다():
    p = build_reservoir_forecast_params(_src(init_water_level_ft=FULL_G), _rcfg(), _curve())
    assert p.init_m3 == pytest.approx(p.full_m3, rel=1e-6)


def test_미지정이면_만수에서_시작한다():
    p = build_reservoir_forecast_params(_src(), _rcfg(), _curve())
    assert p.init_m3 == pytest.approx(p.full_m3)


# ── ★ 업체가 보고한 사고: 현장 눈금이 즉시 Crisis 가 되던 문제 ───────────────

def test_현장눈금_22_5_가_Crisis_로_떨어지지_않는다():
    """옛 동작에서는 MSL 로 읽혀 사수위 아래 → 즉시 Crisis 였다."""
    p = build_reservoir_forecast_params(_src(init_water_level_ft=22.5), _rcfg(), _curve())
    assert p.init_m3 > p.dead_m3, "사수위 아래로 해석됐다 — 기준면이 어긋났다"
    frac = p.init_m3 / p.full_m3 * 100.0
    assert frac > 65.0, f"Crisis 구간으로 떨어졌다({frac:.1f}%)"


# ── 보충 목표 수위도 자 눈금 ─────────────────────────────────────────────────

def test_보충_목표수위도_자_눈금이다():
    curve = _curve()
    p = build_reservoir_forecast_params(
        _src(), _rcfg(diversion_from_outlet=1, diversion_max_m3s=0.15,
                      diversion_target_ft=22.0), curve)
    assert p.diversion_target_m3 == pytest.approx(float(curve.stage_to_storage(44.0)))


# ── 기준면을 섞으면 중단한다 ─────────────────────────────────────────────────

@pytest.mark.parametrize("bad, 설명", [
    (44.0, "옛 MSL 값을 그대로 둔 경우"),
    (45.0, "MSL 만수를 그대로 둔 경우"),
    (0.5,  "사수위보다 낮은 값"),
    (35.0, "댐마루보다 높은 값"),
])
def test_범위밖_초기수위는_중단한다(bad, 설명):
    with pytest.raises(ValueError, match="자\\(staff gauge\\) 눈금 범위를 벗어났다"):
        build_reservoir_forecast_params(_src(init_water_level_ft=bad), _rcfg(), _curve())


def test_옛_MSL_값에는_변환식을_알려준다():
    with pytest.raises(ValueError) as ei:
        build_reservoir_forecast_params(_src(init_water_level_ft=44.0), _rcfg(), _curve())
    msg = str(ei.value)
    assert "곡선 datum(MSL) 로 보인다" in msg
    assert "22.00" in msg, "바꿔 적을 자 눈금 값을 알려 주지 않는다"


def test_범위밖_보충목표도_중단한다():
    with pytest.raises(ValueError, match="diversion_target_ft"):
        build_reservoir_forecast_params(
            _src(), _rcfg(diversion_from_outlet=1, diversion_max_m3s=0.15,
                          diversion_target_ft=44.0), _curve())


def test_제원이_없으면_검사를_건너뛴다():
    """crest_ft/bottom_ft 가 없는 합성 설정은 막지 않는다(하위호환)."""
    rc = _Reservoir(name="x", gis_id=4, spillway_ft=FULL_MSL, obs_datum_offset_ft=0.0)
    p = build_reservoir_forecast_params(_src(init_water_level_ft=44.0), rc, _curve())
    assert p.init_m3 > 0


# ── 결과 폴더 태그도 자 눈금 값을 쓴다 ───────────────────────────────────────

def test_폴더_태그가_자_눈금_값을_쓴다():
    from swat_py.config.env import _DroughtCfg
    dc = _DroughtCfg(sources=[_src(init_water_level_ft=22.0, measured=False)])
    assert dc.forecast_suffix() == "__ic22.0ft-scn", (
        "폴더 태그가 옛 MSL 값(ic44.0ft)으로 남아 있으면 "
        "기준면이 섞인 결과가 한 폴더에 쌓인다")


# ── % 정의는 수위 기준 ───────────────────────────────────────────────────────

def test_단계_경계는_자_눈금_만수_대비_퍼센트다():
    from swat_py.drought.fdc import stage_thresholds
    p = build_reservoir_forecast_params(_src(), _rcfg(), _curve())
    thr = stage_thresholds([], "level_fraction", [95, 85, 65],
                           full_level_ft=full_level_ft(p))
    assert thr["normal_watch"] == pytest.approx(21.85, abs=0.01)
    assert thr["watch_warning"] == pytest.approx(19.55, abs=0.01)
    assert thr["warning_crisis"] == pytest.approx(14.95, abs=0.01)


# ── 검보정 경로와 예측 경로가 같은 기준면을 써야 한다 ───────────────────────

def test_검보정_경로도_예측_경로와_같은_기준면을_쓴다():
    """``analysis_swat_plus`` 가 운영값을 MSL 로 읽으면 검보정만 어긋난다.

    c808f3a 에서 전환유입을 검보정 경로까지 확장했는데, 그쪽은
    ``diversion_target_ft`` 를 곡선에 그대로 넘기고 있었다. 자 눈금으로 통일한 뒤
    그 자리를 고치지 않으면 **검보정만 조용히 다른 목표수위**로 돌아간다.
    """
    import inspect

    from swat_py.calibration import analysis_swat_plus as asp

    src = inspect.getsource(asp)
    # 곡선 조회 시 offset 을 되돌리지 않은 호출이 남아 있으면 안 된다
    bad = [ln.strip() for ln in src.splitlines()
           if "stage_to_storage(" in ln
           and ("init_level_ft" in ln or "diversion_target" in ln or "_tgt_g" in ln)
           and "datum_offset_ft" not in ln]
    assert not bad, ("운영값을 곡선(MSL)에 그대로 넘기는 자리가 남아 있다 — "
                     "자 눈금이므로 '− datum_offset_ft' 가 필요하다:\n  " + "\n  ".join(bad))


def test_같은_자눈금_값이면_두_경로의_저류량이_같다():
    """예측 경로와 검보정 경로가 자 눈금 22.0 에 대해 같은 저류량을 내야 한다."""
    curve = _curve()
    p = build_reservoir_forecast_params(_src(init_water_level_ft=22.0), _rcfg(), curve)
    # 검보정 경로가 하는 계산과 동일한 식
    calib_init_m3 = float(curve.stage_to_storage(22.0 - OFFSET))
    assert p.init_m3 == pytest.approx(calib_init_m3), "두 경로의 기준면이 어긋났다"
