"""물리적으로 불가능한 관측 수위를 결측으로 돌린다 (업체 지적 §5).

    "팔라우 실측 수위 자료에 2019-03-01~04 나흘이 0.0 ft 로 들어 있습니다.
     사수위(눈금 1.34 ft)보다 낮아 결측을 0으로 적은 것으로 보입니다. …
     결측으로 처리해 주시고, 검보정 지표 계산에도 같은 자료를 쓰셨다면 함께 확인
     부탁합니다."

0.0 이 월평균에 섞여 2019년 3월 observed 가 19.68 ft(Watch)로 나왔다. 빼면 22.60 ft
(Normal) — **단계가 통째로 뒤집히는** 크기다. 자료만 고치면 새 자료로 또 생기므로
읽는 쪽에서 막는다.

기준선 두 가지
  · 저수지 : 레지스트리 제원에서 **사수위(자 눈금)** 를 자동 산출
  · 그 외  : ``observations[].min_valid`` 로 명시 (하천 수위처럼 기준선이 없는 경우)
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from swat_py.io.reservoir import dead_level_gauge_ft, sanitize_observed_level

NGERIMEL = SimpleNamespace(bottom_ft=23.34, obs_datum_offset_ft=-22.0)


def _obs(values, start="2019-02-25"):
    return pd.DataFrame({
        "date": pd.date_range(start, periods=len(values), freq="D"),
        "wlevel_ft": values,
    })


# ── 사수위 산출 ─────────────────────────────────────────────────────────────

def test_사수위를_자_눈금으로_환산한다():
    """곡선·제원은 MSL, 관측은 자 눈금 — 비교하려면 offset 을 더해야 한다."""
    assert dead_level_gauge_ft(NGERIMEL) == pytest.approx(1.34)


def test_제원이_없으면_NaN_이라_검사하지_않는다():
    v = dead_level_gauge_ft(SimpleNamespace(obs_datum_offset_ft=-22.0))
    assert v != v
    df = _obs([0.0, 22.9])
    out, n = sanitize_observed_level(df, "wlevel_ft", dead_level_ft=v)
    assert n == 0 and out["wlevel_ft"].notna().all()


def test_저수지가_없으면_NaN():
    v = dead_level_gauge_ft(None)
    assert v != v


# ── ★ 업체가 지적한 그 상황 ─────────────────────────────────────────────────

def test_2019년_3월_사례를_그대로_재현한다():
    """앞뒤 22.9 사이에 0.0 이 나흘 — 월평균이 19.68 → 22.60 으로 바뀐다."""
    vals = [22.9167, 22.9167, 22.9167, 22.9167,          # 02-25~28
            0.0, 0.0, 0.0, 0.0,                           # 03-01~04
            22.5833, 22.5, 22.5, 22.25]                   # 03-05~08
    df = _obs(vals)
    march = df[df["date"].dt.month == 3]
    assert march["wlevel_ft"].mean() == pytest.approx(11.2292, abs=0.001)  # 0 포함

    out, n = sanitize_observed_level(df, "wlevel_ft",
                                     dead_level_ft=dead_level_gauge_ft(NGERIMEL))
    assert n == 4
    march2 = out[out["date"].dt.month == 3]
    assert march2["wlevel_ft"].notna().sum() == 4
    assert march2["wlevel_ft"].mean() == pytest.approx(22.4583, abs=0.001)  # 0 제외


def test_정상값은_건드리지_않는다():
    df = _obs([22.9167, 8.0, 1.5, 23.0])      # 전부 사수위(1.34) 이상
    out, n = sanitize_observed_level(df, "wlevel_ft",
                                     dead_level_ft=dead_level_gauge_ft(NGERIMEL))
    assert n == 0
    pd.testing.assert_frame_equal(out, df)


def test_경계값은_남긴다():
    """사수위 '미만'만 버린다 — 정확히 사수위인 값은 유효하다."""
    out, n = sanitize_observed_level(_obs([1.34, 1.33]), "wlevel_ft",
                                     dead_level_ft=1.34)
    assert n == 1
    assert out["wlevel_ft"].tolist()[0] == pytest.approx(1.34)
    assert pd.isna(out["wlevel_ft"].tolist()[1])


def test_원본을_바꾸지_않는다():
    df = _obs([0.0, 22.9])
    before = df["wlevel_ft"].tolist()
    sanitize_observed_level(df, "wlevel_ft", dead_level_ft=1.34)
    assert df["wlevel_ft"].tolist() == before, "입력 DataFrame 을 수정하면 안 된다"


def test_없는_열은_그냥_넘어간다():
    df = _obs([0.0])
    out, n = sanitize_observed_level(df, "없는열", dead_level_ft=1.34)
    assert n == 0 and out is df


def test_이미_결측인_값은_세지_않는다():
    df = _obs([None, 0.0, 22.9])
    _, n = sanitize_observed_level(df, "wlevel_ft", dead_level_ft=1.34)
    assert n == 1


def test_무엇을_지웠는지_알려준다(capsys):
    df = _obs([0.0, 0.0, 22.9])
    sanitize_observed_level(df, "wlevel_ft", dead_level_ft=1.34, label="ngerimel.csv")
    out = capsys.readouterr().out
    assert "ngerimel.csv" in out and "2개" in out
    assert "2019-02-25" in out, "언제 자료인지 밝혀야 한다"
    assert "1.34" in out, "어떤 기준으로 걸렀는지 밝혀야 한다"


def test_조용히_쓸_수도_있다(capsys):
    sanitize_observed_level(_obs([0.0]), "wlevel_ft", dead_level_ft=1.34, verbose=False)
    assert capsys.readouterr().out == ""


# ── 하천처럼 기준선이 없는 관측 — min_valid ─────────────────────────────────

def test_min_valid_설정을_읽는다(tmp_path):
    """Ngerikiil 은 사수위가 없어 설정으로 기준선을 준다."""
    import yaml

    from swat_py.config.env import _normalize_nested
    raw = yaml.safe_load("""
model: {type: swat_plus}
project: {root: "/tmp/x"}
calibration:
  observations:
    - {id: ngerikiil, outlet_id: 1, variable: wlevel, unit: ft, min_valid: 1.0}
    - {id: other, outlet_id: 2, variable: flow, unit: m3/s}
""")
    flat = _normalize_nested(raw)
    obs = {o.id: o for o in flat["Observations"]}
    assert obs["ngerikiil"].min_valid == pytest.approx(1.0)
    assert obs["other"].min_valid != obs["other"].min_valid      # 미지정 → NaN


def test_ngerikiil_사례_하천_수위():
    """7.83 → 0.0(4일) → 7.58 — 하천이 순간 마르고 복귀할 수는 없다."""
    df = _obs([7.8333, 7.8333, 0.0, 0.0, 0.0, 0.0, 7.5833, 7.5833])
    out, n = sanitize_observed_level(df, "wlevel_ft", dead_level_ft=1.0)
    assert n == 4
    assert out["wlevel_ft"].min() == pytest.approx(7.5833)


# ── 호출부 연결 (회귀 방지) ─────────────────────────────────────────────────

def test_검보정_경로가_관측을_정화한다():
    """업체가 '검보정 지표에도 같은 자료를 썼다면' 이라고 물은 자리."""
    import inspect

    from swat_py.calibration import analysis_swat_plus

    src = inspect.getsource(analysis_swat_plus)
    assert "sanitize_observed_level" in src, "검보정 지표가 오염된 관측을 그대로 쓴다"
    assert "min_valid" in src, "min_valid 기준선을 쓰지 않는다"


def test_대시보드_경로가_관측을_정화한다():
    import inspect

    from swat_py.drought import dashboard_data

    src = inspect.getsource(dashboard_data)
    assert src.count("sanitize_observed_level") >= 2, (
        "observed 와 보유기간 산출 양쪽에서 정화해야 한다")


def test_저수지_장기_물수지도_정화한다():
    import inspect

    from swat_py.drought import historical_worst

    src = inspect.getsource(historical_worst.load_obs_level_msl)
    assert "sanitize_observed_level" in src
