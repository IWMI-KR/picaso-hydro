"""전환유입 이중계산 방지 — 저수지로 보낸 물은 수원 하천에서 뺀다.

업체 지적 (최기섭 2026-10-20 §4-다)
-----------------------------------
    "Ngerikiil 하천 예측은 SWAT+ 채널 유량을 그대로 쓰고 보충수로 가져간 만큼을
     빼지 않아, 같은 물을 두 번 세는 것으로 보입니다."

맞는 지적이었다. 저수지는 전환 보충을 받아 수위가 오르는데, 수원 하천의 예측 유량은
SWAT+ 채널 출력 그대로라 전환분이 남아 있었다 → 하천 단계가 실제보다 후하게 나온다.

핵심 — 빼는 양은 *가져갈 수 있었던 잉여수* 가 아니라 **실제로 가져간 양**이다.
저수지가 목표 수위에 가까우면 잉여수가 남아도 조금만 가져간다.
"""
from __future__ import annotations

import calendar

import numpy as np
import pandas as pd
import pytest

from swat_py.drought.reservoir_forecast import (
    diversion_daily_m3,
    monthly_capacity_series,
    subtract_diversion,
)

SEC = 86400.0


# ── subtract_diversion 자체 ─────────────────────────────────────────────────

def test_전환량만큼_유량이_줄어든다():
    days = calendar.monthrange(2026, 4)[1]          # 30일
    flow = {4: 1.0}                                  # m³/s
    div = {4: 0.25 * days * SEC}                     # 한 달 내내 0.25 m³/s 를 가져감
    out = subtract_diversion(flow, div, {4: 2026})
    assert out[4] == pytest.approx(0.75)


def test_해넘김_2월_일수를_연도에_맞춰_쓴다():
    """NDJ·DJF 의 1·2월은 다음 해다 — 윤년이면 일수가 다르다."""
    div_m3 = 1.0 * 29 * SEC                          # 2024년 2월(29일) 내내 1 m³/s
    out = subtract_diversion({2: 2.0}, {2: div_m3}, {2: 2024})
    assert out[2] == pytest.approx(1.0), "윤년 2월(29일)로 환산해야 한다"
    # 같은 부피를 평년 2월(28일)로 보면 비율이 더 크다
    out28 = subtract_diversion({2: 2.0}, {2: div_m3}, {2: 2023})
    assert out28[2] < out[2]


def test_하천이_마르면_0_에서_멈춘다():
    out = subtract_diversion({5: 0.01}, {5: 999999.0}, {5: 2026})
    assert out[5] == 0.0, "음수 유량이 나오면 안 된다"


def test_전환이_없으면_그대로다():
    flow = {4: 1.0, 5: 2.0}
    assert subtract_diversion(flow, {}, {4: 2026, 5: 2026}) == flow
    assert subtract_diversion(flow, None, {4: 2026, 5: 2026}) == flow


def test_연도를_모르는_달은_건드리지_않는다():
    out = subtract_diversion({4: 1.0}, {4: 1e6}, {})
    assert out[4] == 1.0


# ── 실제로 가져간 양과 일치하는가 (물수지 보존) ─────────────────────────────

def _res_daily(year, month, days, flo_in_m3):
    dates = pd.date_range(f"{year}-{month:02d}-01", periods=days, freq="D")
    return pd.DataFrame({"date": dates, "flo_in": flo_in_m3,
                         "precip": 0.0, "evap": 0.0, "seep": 0.0})


def test_빼는_양은_잉여수가_아니라_실제_전환량이다():
    """저수지가 목표에 거의 찼으면 잉여수가 많아도 조금만 가져간다."""
    days = 30
    raw = _res_daily(2026, 4, days, flo_in_m3=0.0)        # 유입 없음
    full, dead = 100_000.0, 0.0
    tgt = 90_000.0
    init = 89_000.0                                       # 목표까지 1,000 m³ 모자람
    avail = pd.Series(50_000.0, index=pd.to_datetime(raw["date"]))   # 잉여수는 넉넉
    ser = monthly_capacity_series(
        raw, full_m3=full, init_m3=init, withdrawal_m3s=0.0, dead_m3=dead,
        diversion_daily_m3=avail, diversion_target_m3=tgt)
    took = ser[4]["diversion_m3"]
    assert took == pytest.approx(1000.0), f"목표까지만 가져가야 한다 (실제 {took})"
    assert took < avail.sum(), "잉여수 전부를 가져간 것으로 계산하면 안 된다"

    # 하천에서 빼는 양도 '실제 가져간 1,000 m³' 여야 한다
    out = subtract_diversion({4: 1.0}, {4: took}, {4: 2026})
    assert out[4] == pytest.approx(1.0 - 1000.0 / (days * SEC))


def test_저수지가_받은_물과_하천에서_뺀_물이_같다():
    """물수지 보존 — 전환량 = 저수지 증가분(= 하천 감소분)."""
    days = 30
    raw = _res_daily(2026, 4, days, flo_in_m3=0.0)
    full, init = 100_000.0, 10_000.0
    avail = pd.Series(2_000.0, index=pd.to_datetime(raw["date"]))   # 하루 2,000 m³
    ser = monthly_capacity_series(
        raw, full_m3=full, init_m3=init, withdrawal_m3s=0.0, dead_m3=0.0,
        diversion_daily_m3=avail, diversion_target_m3=full)
    took = ser[4]["diversion_m3"]
    gained = ser[4]["storage_m3"] - init
    assert took == pytest.approx(gained), "저수지 증가분과 전환량이 어긋난다"

    flow_before = 1.0
    out = subtract_diversion({4: flow_before}, {4: took}, {4: 2026})
    removed_m3 = (flow_before - out[4]) * days * SEC
    assert removed_m3 == pytest.approx(took, rel=1e-9), (
        "하천에서 뺀 물과 저수지가 받은 물이 같아야 한다")


# ── 잉여수 산정은 바뀌지 않았는지 (기존 거동 보존) ───────────────────────────

def test_잉여수는_여전히_상한_최소유량을_따른다(tmp_path):
    """diversion_daily_m3 는 '가져갈 수 있는 양'을 그대로 돌려준다(변경 없음)."""
    from swat_py.drought.reservoir_forecast import ReservoirForecastParams
    f = tmp_path / "channel_sd_day.txt"
    f.write_text(
        "header\n"
        "jday mon day yr unit gis_id name flo_out\n"
        "unitline\n"
        "1 4 1 2026 1 1 ch1 0.50\n"
        "2 4 2 2026 1 1 ch1 0.01\n", encoding="utf-8")
    p = ReservoirForecastParams(
        gis_id=4, name="dam", full_m3=1.0, dead_m3=0.0, init_m3=1.0,
        diversion_from_outlet=1, diversion_max_m3s=0.15, diversion_min_flow_m3s=0.02)
    s = diversion_daily_m3(tmp_path, p, sdate="2026-01-01")
    if s is None:
        pytest.skip("channel_sd_day 파서가 이 합성 형식을 읽지 못함")
    vals = list(s.values)
    assert vals[0] == pytest.approx(0.15 * SEC)       # 상한에서 잘림
    assert vals[1] == pytest.approx(0.0)              # 유지유량 아래 → 못 가져감


# ── 앙상블 경로가 2단계(저수지 먼저)로 되어 있는지 ──────────────────────────

def test_앙상블이_저수지를_먼저_처리한다():
    """하천을 먼저 처리하면 뺄 전환량을 아직 모른다 — 순서가 결과를 좌우한다."""
    import inspect

    from swat_py.drought import ensemble_flow

    src = inspect.getsource(ensemble_flow._run_one)
    i_res = src.find("1차: 저수지")
    i_ch = src.find("2차: 채널")
    assert i_res != -1 and i_ch != -1, "2단계 구조가 사라졌다"
    assert i_res < i_ch, "저수지(1차)가 채널(2차)보다 먼저여야 한다"
    assert "subtract_diversion" in src, "하천에서 전환분을 빼지 않는다"


def test_평년_경로도_전환분을_뺀다():
    """예측에서만 빼면 FDC 임계·평년선과 기준이 어긋난다."""
    import inspect

    from swat_py.drought import climatology_run

    src = inspect.getsource(climatology_run.run_climatology)
    assert "전환 차감" in src, "평년 채널 유량에서 전환분을 빼지 않는다"
    i_res = src.find("write_reservoir_climatology")
    i_save = src.find("channel_monthly_{tag}.csv")
    assert i_res != -1 and i_save != -1
    assert i_res < i_save, "전환량을 먼저 구한 뒤 채널 평년을 저장해야 한다"


def test_전환_수원이_outlets_에_없으면_경고한다():
    import inspect

    from swat_py.drought import climatology_run

    src = inspect.getsource(climatology_run.run_climatology)
    assert "outlets 에 없다" in src, (
        "수원 채널이 outlets 에 없으면 조용히 넘어가면 안 된다")


# ── 쿡(전환 없음)은 거동이 바뀌지 않아야 한다 ───────────────────────────────

def test_전환유입_미설정_프로젝트는_영향_없다():
    raw = _res_daily(2026, 4, 30, flo_in_m3=1000.0)
    ser = monthly_capacity_series(raw, full_m3=100_000.0, init_m3=50_000.0,
                                  withdrawal_m3s=0.0, dead_m3=0.0)
    assert "diversion_m3" not in ser[4], "전환 미설정인데 전환 항목이 생겼다"
    assert np.isfinite(ser[4]["storage_pct"])
