"""실패하면 0이 아닌 종료코드로 끝내기 (P2-B, 회귀 방지).

요청(최기섭 2026-10-02): "기간이 뒤집히거나 예측월 결과가 비면 0 이 아닌
종료 코드로 실패하게 해 주세요. **지금은 exit 0 으로 끝나서 틀린 결과를
감지할 수 없습니다.**"

예전에는 2015_DJF 가 12월 `n=0, most_likely="NA"` 인데도 파일이 정상 생성되고
`main()` 이 무조건 `return 0` 이었다.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import swat_py.config as config_mod
import swat_py.drought.dashboard_data as dd
import swat_py.drought.figure as figure_mod
from swat_py.drought.season import SEASON_MONTHS, assert_period_sane

# ── ① 기간이 뒤집히거나 성립하지 않으면 즉시 중단 ─────────────────────────────

@pytest.mark.parametrize("season,months", list(SEASON_MONTHS.items()))
def test_every_season_is_sane(season, months) -> None:
    """정상 계절 12개는 모두 통과하고 (연,월) 3쌍을 돌려준다."""
    yms = assert_period_sane(2025, months)
    assert len(yms) == 3 and [m for _, m in yms] == list(months), season


@pytest.mark.parametrize("months,why", [
    ([],             "비어 있다"),
    ([11, 13, 1],    "1~12 밖"),
    ([11, 11, 12],   "같은 달이 두 번"),
    ([11, 1, 12],    "연속한 달이 아니다"),
    ([2, 5, 8],      "연속한 달이 아니다"),
])
def test_insane_period_raises(months, why) -> None:
    with pytest.raises(ValueError):
        assert_period_sane(2025, months)


def test_sane_period_is_never_reversed() -> None:
    """옛 코드는 NDJ·DJF 에서 끝이 시작보다 앞선 구간을 만들고도 조용히 끝났다."""
    import pandas as pd
    for season, months in SEASON_MONTHS.items():
        yms = assert_period_sane(2025, months)
        first, last = yms[0], yms[-1]
        assert pd.Timestamp(*last, 1) > pd.Timestamp(*first, 1), season


# ── ② 예측월 결과가 비면 실패 메시지 ─────────────────────────────────────────

def test_forecast_incomplete_message() -> None:
    e = dd.ForecastIncomplete([("avana", "2025-12", "유효 멤버 0"),
                               ("ngerimel", "2026-01", "결과 없음")], "X:/out")
    msg = str(e)
    assert "2건" in msg and "2025-12" in msg and "2026-01" in msg
    assert "--allow-incomplete" in msg           # 벗어나는 방법을 알려 준다
    assert e.out_root == "X:/out" and len(e.problems) == 2


def test_forecast_incomplete_truncates_long_list() -> None:
    e = dd.ForecastIncomplete([("o", f"2025-{i:02d}", "유효 멤버 0")
                               for i in range(1, 13)] * 2, "X:/out")
    assert "24건" in str(e) and "외 12건" in str(e)


# ── ③ 예측월 공백 판정 ───────────────────────────────────────────────────────

MON_YM = {11: "2025-11", 12: "2025-12", 1: "2026-01"}
MONTHS = [11, 12, 1]


def test_no_problem_when_all_months_have_members() -> None:
    rows = [{"month": m, "n": 1000} for m in MONTHS]
    assert dd.empty_forecast_months("avana", rows, MONTHS, MON_YM) == []


def test_detects_zero_member_month() -> None:
    """2015_DJF 의 12월이 이 상태였다 — n=0, most_likely="NA" 인데 성공으로 끝났다."""
    rows = [{"month": 11, "n": 1000}, {"month": 12, "n": 0}, {"month": 1, "n": 1000}]
    assert dd.empty_forecast_months("avana", rows, MONTHS, MON_YM) == [
        ("avana", "2025-12", "유효 멤버 0")]


def test_detects_missing_month_row() -> None:
    """해를 넘는 달이 통째로 빠진 경우(옛 NDJ·DJF 증상)."""
    rows = [{"month": 11, "n": 1000}, {"month": 12, "n": 1000}]
    assert dd.empty_forecast_months("avana", rows, MONTHS, MON_YM) == [
        ("avana", "2026-01", "결과 없음")]


def test_detects_everything_when_no_ensemble() -> None:
    assert len(dd.empty_forecast_months("avana", [], MONTHS, MON_YM)) == 3


# ── ④ main() 의 종료코드 ─────────────────────────────────────────────────────

@pytest.fixture
def stub_cli(monkeypatch, tmp_path):
    """config 로드·그림 생성을 치우고 build 만 바꿔 끼울 수 있게 한다."""
    monkeypatch.setattr(config_mod, "load_config",
                        lambda path: SimpleNamespace(Drought=None))
    monkeypatch.setattr(figure_mod, "make_all_figures", lambda p: None)
    return tmp_path


def test_main_returns_1_when_forecast_month_empty(stub_cli, monkeypatch) -> None:
    def boom(*a, **k):
        raise dd.ForecastIncomplete([("avana", "2025-12", "유효 멤버 0")], stub_cli)
    monkeypatch.setattr(dd, "build", boom)
    assert dd.main(["--forecast", "2025_NDJ", "--demo", "5"]) == 1


def test_main_returns_0_when_complete(stub_cli, monkeypatch) -> None:
    monkeypatch.setattr(dd, "build", lambda *a, **k: {"out_root": str(stub_cli)})
    assert dd.main(["--forecast", "2025_NDJ", "--demo", "5"]) == 0


def test_main_draws_figures_even_on_failure(stub_cli, monkeypatch) -> None:
    """실패해도 진단용 그림은 남긴다 — 어디가 비었는지 보려면 필요하다."""
    drawn = []
    monkeypatch.setattr(figure_mod, "make_all_figures", lambda p: drawn.append(p))
    monkeypatch.setattr(dd, "build", lambda *a, **k: (_ for _ in ()).throw(
        dd.ForecastIncomplete([("avana", "2025-12", "유효 멤버 0")], stub_cli)))
    assert dd.main(["--forecast", "2025_NDJ", "--demo", "5"]) == 1
    assert len(drawn) == 1


def test_allow_incomplete_turns_strict_off(stub_cli, monkeypatch) -> None:
    seen = {}

    def fake_build(cfg, forecast, **kw):
        seen.update(kw)
        return {"out_root": str(stub_cli)}

    monkeypatch.setattr(dd, "build", fake_build)
    assert dd.main(["--forecast", "2025_NDJ", "--demo", "5"]) == 0
    assert seen["strict"] is True                     # 기본은 엄격
    assert dd.main(["--forecast", "2025_NDJ", "--demo", "5", "--allow-incomplete"]) == 0
    assert seen["strict"] is False


# ── ⑤ 파이프라인(run.py) 도 같은 종료코드 ────────────────────────────────────

def test_pipeline_main_returns_1(monkeypatch, tmp_path) -> None:
    import swat_py.drought.run as run_mod
    monkeypatch.setattr(config_mod, "load_config",
                        lambda path: SimpleNamespace(Drought=None))

    def boom(cfg, **kw):
        assert kw["strict"] is True
        raise dd.ForecastIncomplete([("avana", "2025-12", "유효 멤버 0")], tmp_path)

    monkeypatch.setattr(run_mod, "run_pipeline", boom)
    assert run_mod.main(["--forecast", "2025_NDJ"]) == 1


# ── ⑥ acidwg — 멤버가 모자라면 실패 ──────────────────────────────────────────

def test_acidwg_raises_when_members_short() -> None:
    """예전에는 '경고: 최대 시도 횟수 초과' 만 찍고 정상 종료(exit 0)했다."""
    from acidwg_py.run import assert_full_ensemble
    assert_full_ensemble(1000, 1000, 1200, "X:/out")      # 다 채웠으면 조용히 통과
    with pytest.raises(RuntimeError, match="998개만 생성"):
        assert_full_ensemble(998, 1000, 5001, "X:/out/2013_NDJ")
