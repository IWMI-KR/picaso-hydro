"""평년선 통계 선택 + 평년 설정 지문 (업체 지적 §4-라).

① "평균인 평년선이 3월에 Watch 구간으로 그려지는 것이 의도한 결과인가,
   중앙값을 쓰는 편이 나은가"
   → ``drought.climatology_stat`` (mean 기본 | median) 으로 고른다.
     기본을 mean 으로 둔 것은 기존 프로젝트(쿡)의 화면을 말없이 바꾸지 않기 위해서다.

② "설정을 바꾸면 평년도 다시 계산해야 하는데, 지금은 예전 설정으로 만든 평년 파일이
   남아 있어도 대시보드가 그대로 읽고 경고하지 않는다"
   → 평년 산출물 옆에 설정 지문 JSON 을 남기고, 읽을 때 대조해 경고한다.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from swat_py.drought.climatology import (
    check_climatology_fingerprint,
    climatology_fingerprint,
    climatology_stat,
    fingerprint_path,
    warn_if_climatology_stale,
    write_climatology_fingerprint,
)


def _cfg(tmp_path, **drought):
    d = dict(syear=1982, eyear=2023, base_weather="single_station",
             climatology_stat="mean", sources=[], climatology_years=[2003, 2024])
    d.update(drought)
    res = d.pop("_reservoirs", {})
    return SimpleNamespace(
        PrjDir=str(tmp_path), CioNYSKIP=3,
        Drought=SimpleNamespace(**d), Reservoirs=res)


def _reservoir(**kw):
    base = dict(stage_storage_file="x.csv", obs_datum_offset_ft=-22.0, interp="pchip",
                spillway_ft=45.0, bottom_ft=23.34, crest_ft=51.0,
                withdrawal_m3s=0.0438, withdrawal_monthly_m3s=None,
                diversion_from_outlet=1, diversion_max_m3s=0.15,
                diversion_min_flow_m3s=0.02, diversion_target_ft=22.0)
    base.update(kw)
    return SimpleNamespace(**base)


# ── ① 평년선 통계 ───────────────────────────────────────────────────────────

def test_기본은_평균이다(tmp_path):
    """기존 프로젝트(쿡)의 화면이 말없이 바뀌면 안 된다."""
    assert climatology_stat(_cfg(tmp_path)) == "mean"


def test_median_을_고를_수_있다(tmp_path):
    assert climatology_stat(_cfg(tmp_path, climatology_stat="median")) == "median"


def test_오타는_중단한다(tmp_path):
    with pytest.raises(ValueError, match="climatology_stat"):
        climatology_stat(_cfg(tmp_path, climatology_stat="mediann"))


def test_가뭄해가_평균을_끌어내린다는_전제_확인():
    """왜 median 인지 — 위가 막히고 아래로 꼬리가 긴 분포에서 둘이 갈린다."""
    # 만수 23.0 근처에 몰려 있고 가뭄 해 몇 개가 아래로 떨어지는 전형적 분포
    yrs = [23.0, 22.9, 22.8, 23.0, 22.7, 22.9, 23.0, 14.0, 12.0, 22.8]
    mean = sum(yrs) / len(yrs)
    sv = sorted(yrs)
    median = (sv[4] + sv[5]) / 2
    assert mean < 21.85 <= median, (
        f"평균 {mean:.2f} 는 Normal|Watch(21.85) 아래, "
        f"중앙값 {median:.2f} 는 위 — 이것이 평년선이 Watch 로 그려지던 이유다")


# ── ② 설정 지문 ─────────────────────────────────────────────────────────────

def test_지문에_평년을_좌우하는_설정이_들어간다(tmp_path):
    cfg = _cfg(tmp_path, _reservoirs={"ngerimel": _reservoir()})
    fp = climatology_fingerprint(cfg)
    assert fp["syear"] == 1982 and fp["eyear"] == 2023
    assert fp["base_weather"] == "single_station"
    assert fp["climatology_stat"] == "mean"
    r = fp["reservoirs"]["ngerimel"]
    for k in ("withdrawal_m3s", "diversion_max_m3s", "diversion_min_flow_m3s",
              "diversion_target_ft", "obs_datum_offset_ft", "spillway_ft"):
        assert k in r, f"{k} 가 지문에 없다 — 바뀌어도 알아채지 못한다"


def test_지문을_쓰고_다시_읽으면_일치한다(tmp_path):
    cfg = _cfg(tmp_path, _reservoirs={"ngerimel": _reservoir()})
    p = write_climatology_fingerprint(cfg)
    assert p.is_file() and p == fingerprint_path(cfg)
    assert check_climatology_fingerprint(cfg)["status"] == "ok"


@pytest.mark.parametrize("바꾼설정, 값", [
    ("withdrawal_m3s", 0.0300),
    ("diversion_max_m3s", 0.40),
    ("diversion_target_ft", 22.5),
    ("diversion_from_outlet", None),
    ("obs_datum_offset_ft", -21.0),
])
def test_저수지_설정이_바뀌면_낡은_것으로_판정한다(tmp_path, 바꾼설정, 값):
    cfg = _cfg(tmp_path, _reservoirs={"ngerimel": _reservoir()})
    write_climatology_fingerprint(cfg)
    cfg2 = _cfg(tmp_path, _reservoirs={"ngerimel": _reservoir(**{바꾼설정: 값})})
    res = check_climatology_fingerprint(cfg2)
    assert res["status"] == "stale"
    assert any(바꾼설정 in d for d in res["diff"]), (
        f"무엇이 바뀌었는지 알려 주지 않는다: {res['diff']}")


def test_평년_통계를_바꿔도_낡은_것으로_판정한다(tmp_path):
    cfg = _cfg(tmp_path, _reservoirs={"ngerimel": _reservoir()})
    write_climatology_fingerprint(cfg)
    res = check_climatology_fingerprint(
        _cfg(tmp_path, climatology_stat="median",
             _reservoirs={"ngerimel": _reservoir()}))
    assert res["status"] == "stale"
    assert any("climatology_stat" in d for d in res["diff"])


def test_지문이_없으면_missing_이다(tmp_path):
    """옛 평년이거나 손으로 복사해 온 경우 — 조용히 통과시키지 않는다."""
    res = check_climatology_fingerprint(_cfg(tmp_path))
    assert res["status"] == "missing"


def test_지문이_깨졌어도_죽지_않는다(tmp_path):
    cfg = _cfg(tmp_path)
    p = fingerprint_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ 깨진 json", encoding="utf-8")
    assert check_climatology_fingerprint(cfg)["status"] == "missing"


def test_차이를_항목별로_알려준다(tmp_path):
    """여러 설정이 한꺼번에 바뀌면 전부 나열해야 한다."""
    cfg = _cfg(tmp_path, _reservoirs={"ngerimel": _reservoir()})
    write_climatology_fingerprint(cfg)
    cfg2 = _cfg(tmp_path, base_weather="era5", climatology_stat="median",
                _reservoirs={"ngerimel": _reservoir(withdrawal_m3s=0.03)})
    diff = check_climatology_fingerprint(cfg2)["diff"]
    assert any("base_weather" in d for d in diff)
    assert any("climatology_stat" in d for d in diff)
    assert any("withdrawal_m3s" in d for d in diff)


def test_기간을_바꾸면_파일명_태그가_달라져_missing_이_된다(tmp_path):
    """syear/eyear 는 파일명 태그에 들어간다 — 다른 평년 파일을 보게 되므로
    지문도 그 태그를 따라간다. 'stale' 이 아니라 'missing' 이 맞는 판정이다."""
    cfg = _cfg(tmp_path, _reservoirs={"ngerimel": _reservoir()})
    write_climatology_fingerprint(cfg)                       # ..._1985_2023.json
    cfg2 = _cfg(tmp_path, eyear=2024, _reservoirs={"ngerimel": _reservoir()})
    assert "1985_2024" in str(fingerprint_path(cfg2))
    assert check_climatology_fingerprint(cfg2)["status"] == "missing"


def test_경고는_중단하지_않고_결과를_돌려준다(tmp_path, capsys):
    """업체 요청이 '경고'였다 — 실행을 막지는 않는다. 다만 눈에 띄어야 한다."""
    cfg = _cfg(tmp_path, _reservoirs={"ngerimel": _reservoir()})
    write_climatology_fingerprint(cfg)
    cfg2 = _cfg(tmp_path, _reservoirs={"ngerimel": _reservoir(withdrawal_m3s=0.03)})
    res = warn_if_climatology_stale(cfg2)          # 예외가 나면 안 된다
    out = capsys.readouterr().out
    assert res["status"] == "stale"
    assert "평년이 낡았다" in out
    assert "withdrawal_m3s" in out, "무엇이 달라졌는지 화면에 찍어야 한다"
    assert "!!!!" in out, "지나치기 쉬운 한 줄 경고면 안 된다"


def test_정상이면_조용하다(tmp_path, capsys):
    cfg = _cfg(tmp_path, _reservoirs={"ngerimel": _reservoir()})
    write_climatology_fingerprint(cfg)
    warn_if_climatology_stale(cfg)
    assert capsys.readouterr().out == ""


def test_지문은_사람이_읽을_수_있는_json_이다(tmp_path):
    cfg = _cfg(tmp_path, _reservoirs={"ngerimel": _reservoir()})
    d = json.loads(write_climatology_fingerprint(cfg).read_text(encoding="utf-8"))
    assert d["reservoirs"]["ngerimel"]["diversion_target_ft"] == 22.0


# ── 대시보드가 실제로 대조하는지 (회귀 방지) ────────────────────────────────

def test_대시보드가_평년_지문을_대조한다():
    import inspect

    from swat_py.drought import dashboard_data

    src = inspect.getsource(dashboard_data)
    assert "warn_if_climatology_stale" in src, "평년 지문을 대조하지 않는다"
    assert "climatology_settings" in src, "결과를 dashboard.json 에 남기지 않는다"


def test_평년_생성이_지문을_남긴다():
    import inspect

    from swat_py.drought import climatology_run

    src = inspect.getsource(climatology_run.run_climatology)
    assert "write_climatology_fingerprint" in src, "평년을 만들며 지문을 남기지 않는다"


def test_저수지_평년이_두_통계를_모두_저장한다():
    import inspect

    from swat_py.drought import climatology_run

    src = inspect.getsource(climatology_run.write_reservoir_climatology)
    assert "_level_ft_mean" in src and "_level_ft_median" in src, (
        "어느 쪽을 쓸지 논의하려면 두 통계가 파일에 함께 있어야 한다")
