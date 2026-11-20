"""일단위 저장·통계 (요청 1·2·3번, 유진호 2026-11-12) 회귀 테스트.

**무엇을 지키는가**
1. 일 단위 벡터 물수지가 월 물수지(:func:`monthly_capacity_series`)와 **같은 식**인지.
   두 구현이 갈라지면 ``stage_prob.csv``(월말)와 ``stage_prob_days.csv``(일수)가
   서로 다른 물리를 말하게 되는데, 숫자는 그럴듯하게 나와 조용히 틀린다.
2. 벡터 단계 분류가 :func:`classify_stage4` 와 글자 그대로 같은 경계 처리를 하는지
   (저수지 수위의 ``top_inclusive`` 포함 — 만수 저수지가 Watch 로 떨어지던 결함).
3. 초기수위 스윕 격자가 **사수위·만수·단계 경계·설정 초기수위를 반드시 포함**하는지.
   격자가 사수위에서 더해 올라가면 만수 23.00·운영값 22.00 이 빠져, 화면 슬라이더가
   집어낼 수 있는 값이 하나도 없게 된다(2026-11-19 실제로 그랬다).
4. 일배열 NPZ 왕복과, 멤버마다 일수가 어긋날 때 **섞인 배열을 만들지 않는지**.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.drought.daily_stats import (
    CUM_COLS,
    classify_stage_index,
    cumulative_table,
    day_count_table,
    init_level_sweep,
    simulate_daily_storage,
    storage_to_level_ft,
    stream_daily_stats,
    sweep_levels_from_cfg,
    withdrawal_per_day,
    write_reservoir_outputs,
)
from swat_py.drought.daily_store import (
    common_members,
    load_daily,
    save_daily,
    stack_members,
)
from swat_py.drought.reservoir_forecast import (
    ReservoirForecastParams,
    daily_net_m3,
    monthly_capacity_series,
    surplus_m3_from_flow,
)
from swat_py.drought.stages import STAGES4, classify_stage4
from swat_py.io.reservoir import StageStorageCurve

FULL, DEAD = 100_000.0, 0.0
NW, WW, WC = 21.85, 19.55, 14.95      # 팔라우 응게리멜 실제 경계(자 눈금 ft)


def _curve() -> StageStorageCurve:
    """선형이 아닌 단조 곡선 — 직선이면 % 와 ft 를 섞어도 들키지 않는다."""
    elev = np.linspace(23.34, 45.0, 40)                 # MSL ft (사수위~만수)
    stor = FULL * ((elev - elev[0]) / (elev[-1] - elev[0])) ** 1.6
    return StageStorageCurve(elev_ft=elev, storage_m3=stor, name="test")


def _params(**kw) -> ReservoirForecastParams:
    base = dict(gis_id=4, name="res", full_m3=FULL, dead_m3=DEAD,
                init_m3=0.8 * FULL, withdrawal_m3s=0.02, curve=_curve(),
                datum_offset_ft=-22.0, diversion_from_outlet=1,
                diversion_max_m3s=0.15, diversion_min_flow_m3s=0.02,
                diversion_target_m3=0.9 * FULL)
    base.update(kw)
    return ReservoirForecastParams(**base)


def _daily_res(dates, flo_in, precip=0.0, evap=0.0, seep=0.0) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "flo_in": flo_in, "precip": precip,
                         "evap": evap, "seep": seep, "gis_id": 4})


# ── 1. 일 물수지 == 월 물수지 ───────────────────────────────────────────────────

class TestDailyMatchesMonthly:
    @pytest.mark.parametrize("seed", [0, 1, 7])
    def test_월말_저류량이_월_물수지와_같다(self, seed):
        rng = np.random.default_rng(seed)
        dates = pd.date_range("2016-04-01", "2016-06-30", freq="D")
        p = _params()
        flo_in = rng.uniform(0, 20_000, len(dates))
        q = rng.uniform(0, 0.4, len(dates))               # 수원 하천 일유량 m³/s
        res = _daily_res(dates, flo_in)
        div = pd.Series(surplus_m3_from_flow(
            q, min_flow_m3s=p.diversion_min_flow_m3s,
            max_m3s=p.diversion_max_m3s), index=dates.values)
        monthly = monthly_capacity_series(
            res, full_m3=p.full_m3, init_m3=p.init_m3,
            withdrawal_m3s=p.withdrawal_m3s, dead_m3=p.dead_m3,
            months=[4, 5, 6], curve=p.curve, datum_offset_ft=p.datum_offset_ft,
            diversion_daily_m3=div, diversion_target_m3=p.diversion_target_m3)

        sim = simulate_daily_storage(
            flo_in[None, :], div.values[None, :], init_m3=p.init_m3,
            full_m3=p.full_m3, dead_m3=p.dead_m3,
            wdr_day_m3=withdrawal_per_day(dates, withdrawal_m3s=p.withdrawal_m3s),
            target_m3=p.diversion_target_m3)
        stor = sim["storage_m3"][0]
        for m in (4, 5, 6):
            last = np.where(dates.month.values == m)[0][-1]
            assert stor[last] == pytest.approx(monthly[m]["storage_m3"], abs=1e-9), (
                f"{m}월 월말 저류량이 월 물수지와 다르다 — 식이 갈라졌다")

    def test_월별_취수가_달마다_적용된다(self):
        dates = pd.date_range("2016-04-01", "2016-06-30", freq="D")
        wmon = [0.0] * 12
        wmon[4] = 1.0                                     # 5월만 취수
        w = withdrawal_per_day(dates, withdrawal_monthly_m3s=wmon)
        assert w[dates.month == 5].min() == pytest.approx(86400.0)
        assert w[dates.month != 5].max() == 0.0

    def test_월별_취수는_12개여야_한다(self):
        with pytest.raises(ValueError, match="12개"):
            withdrawal_per_day(pd.date_range("2016-04-01", periods=3),
                               withdrawal_monthly_m3s=[0.1, 0.2])

    def test_daily_net_m3_가_손실을_뺀다(self):
        dates = pd.date_range("2016-04-01", periods=3, freq="D")
        res = _daily_res(dates, [100.0] * 3, precip=10.0, evap=4.0, seep=1.0)
        assert list(daily_net_m3(res).values) == [105.0] * 3
        assert list(daily_net_m3(res, use_losses=False).values) == [100.0] * 3

    def test_전환이_없으면_일배열도_유입만으로_푼다(self):
        sim = simulate_daily_storage(
            np.full((1, 10), 5_000.0), None, init_m3=0.0, full_m3=FULL,
            dead_m3=DEAD, wdr_day_m3=np.zeros(10))
        assert sim["take_m3"].sum() == 0.0
        assert sim["storage_m3"][0, -1] == pytest.approx(50_000.0)

    def test_만수에서_잘리고_사수위_아래로_안_내려간다(self):
        sim = simulate_daily_storage(
            np.array([[FULL * 2, -FULL * 5]]), None, init_m3=FULL / 2,
            full_m3=FULL, dead_m3=DEAD, wdr_day_m3=np.zeros(2))
        assert sim["storage_m3"][0, 0] == pytest.approx(FULL)
        assert sim["storage_m3"][0, 1] == pytest.approx(DEAD)


# ── 2. 벡터 단계 분류 ───────────────────────────────────────────────────────────

class TestClassify:
    @pytest.mark.parametrize("top", [False, True])
    def test_classify_stage4_와_원소별로_같다(self, top):
        vals = np.array([23.0, 21.86, NW, 21.0, WW, 17.0, WC, 10.0, np.nan])
        got = classify_stage_index(vals, NW, WW, WC, top_inclusive=top)
        for v, g in zip(vals, got):
            want = classify_stage4(v, NW, WW, WC, top_inclusive=top)
            assert (STAGES4[g] if g >= 0 else "NA") == want, f"{v} 에서 갈라졌다"

    def test_만수_저수지는_top_inclusive_로_Normal_이다(self):
        """수위는 만수에서 물리적으로 잘려 ``> 만수`` 가 성립하지 않는다."""
        assert classify_stage_index([NW], NW, WW, WC, top_inclusive=True)[0] == 0
        assert classify_stage_index([NW], NW, WW, WC, top_inclusive=False)[0] == 1

    def test_곡선이_없으면_수위는_NaN_이다(self):
        out = storage_to_level_ft(np.array([[1.0, 2.0]]), curve=None)
        assert np.isnan(out).all()


# ── 3. 통계 표 ─────────────────────────────────────────────────────────────────

class TestTables:
    def _idx(self):
        dates = pd.date_range("2016-04-01", "2016-05-31", freq="D")
        st = np.zeros((2, len(dates)), dtype=np.int8)
        apr = dates.month.values == 4
        st[0, apr] = [3] * 15 + [0] * 15                  # 멤버0: 4월 절반 Crisis
        st[1, apr] = 1                                    # 멤버1: 4월 전부 Watch
        return dates, st

    def test_일수_비율이_요청_정의와_같다(self):
        dates, st = self._idx()
        t = day_count_table(st, dates, [4, 5]).set_index("month")
        # 4월: Crisis 멤버0 15/30=50% · 멤버1 0% → 평균 25%
        assert t.loc[4, "Crisis"] == pytest.approx(25.0)
        assert t.loc[4, "Watch"] == pytest.approx(50.0)   # 멤버1 100% · 멤버0 0%
        assert t.loc[4, "n_days"] == 30 and t.loc[4, "n"] == 2

    def test_일수_비율_합이_100_이다(self):
        dates, st = self._idx()
        t = day_count_table(st, dates, [4, 5])
        assert t[list(STAGES4)].sum(axis=1).round(1).eq(100.0).all()

    def test_누적확률이_단계_순으로_줄어든다(self):
        dates, st = self._idx()
        me = np.array([[3, 0], [1, 0]], dtype=np.int8)     # 월말 단계(멤버×월)
        c = cumulative_table(me, st, dates, [4, 5])
        for _, r in c.iterrows():
            assert r[CUM_COLS[0]] >= r[CUM_COLS[1]] >= r[CUM_COLS[2]] - 1e-9
        mo = c[(c["basis"] == "monthend") & (c["month"] == 4)].iloc[0]
        assert mo["watch_or_worse"] == pytest.approx(100.0)   # 멤버0 Crisis·멤버1 Watch
        assert mo["crisis"] == pytest.approx(50.0)

    def test_월말과_일수_두_기준이_모두_들어간다(self):
        dates, st = self._idx()
        me = np.array([[3, 0], [1, 0]], dtype=np.int8)
        c = cumulative_table(me, st, dates, [4, 5])
        assert set(c["basis"]) == {"monthend", "daycount"}
        assert len(c) == 4

    def test_하천은_월평균_기준_이름을_쓴다(self):
        dates = pd.date_range("2016-04-01", "2016-04-30", freq="D")
        d = {"dates": dates.values.astype("datetime64[D]"),
             "q_m3s": np.full((3, 30), 0.1)}
        r = stream_daily_stats(d, thresholds={"normal_watch": 0.2,
                                              "watch_warning": 0.05,
                                              "warning_crisis": 0.01}, months=[4])
        assert set(r["cumulative"]["basis"]) == {"monthmean", "daycount"}
        assert r["day_count"].loc[0, "Watch"] == pytest.approx(100.0)


# ── 4. 초기수위 스윕 ───────────────────────────────────────────────────────────

class TestSweep:
    def _daily(self):
        dates = pd.date_range("2016-04-01", "2016-06-30", freq="D")
        rng = np.random.default_rng(3)
        return {"dates": dates.values.astype("datetime64[D]"),
                "res_net_m3": rng.uniform(0, 8_000, (12, len(dates))).astype("float32"),
                "src_q_m3s": rng.uniform(0, 0.3, (12, len(dates))).astype("float32")}

    def test_격자가_사수위_만수_경계_설정값을_모두_포함한다(self):
        p = _params()
        off = p.datum_offset_ft
        lo = float(p.curve.storage_to_stage(DEAD)) + off
        hi = float(p.curve.storage_to_stage(FULL)) + off
        init_ft = float(p.curve.storage_to_stage(p.init_m3)) + off
        sw = init_level_sweep(self._daily(), params=p,
                              thresholds={"normal_watch": NW, "watch_warning": WW,
                                          "warning_crisis": WC},
                              months=[4, 5, 6], step_ft=0.5,
                              anchors_ft=[NW, WW, WC, init_ft])
        lv = set(sw["init_ft"])
        for v in (round(lo, 2), round(hi, 2), NW, WW, WC, round(init_ft, 2)):
            assert v in lv, f"{v} ft 가 격자에 없다 — 화면이 집어낼 수 없다"

    def test_격자가_step_의_정수배에_맞는다(self):
        """사수위에서 더해 올라가면 만수·운영값이 격자에서 빠진다."""
        p = _params()
        sw = init_level_sweep(self._daily(), params=p,
                              thresholds={"normal_watch": NW, "watch_warning": WW,
                                          "warning_crisis": WC},
                              months=[4], step_ft=0.5)
        grid = np.array(sorted(sw["init_ft"].unique()))
        lo = float(p.curve.storage_to_stage(DEAD)) + p.datum_offset_ft
        hi = float(p.curve.storage_to_stage(FULL)) + p.datum_offset_ft
        inner = grid[(grid > lo + 1e-6) & (grid < hi - 1e-6)]
        assert np.allclose(np.round(inner / 0.5) * 0.5, inner, atol=1e-6)

    def test_초기수위가_높으면_일수기준_Normal_이_늘고_Crisis_가_준다(self):
        p = _params()
        sw = init_level_sweep(self._daily(), params=p,
                              thresholds={"normal_watch": NW, "watch_warning": WW,
                                          "warning_crisis": WC},
                              months=[4], step_ft=2.0).set_index("init_ft")
        assert sw["dc_Normal"].is_monotonic_increasing
        assert sw["dc_Crisis"].is_monotonic_decreasing

    def test_config_격자_해석(self):
        lv, step = sweep_levels_from_cfg([14.0, 15.0, 0.5])
        assert list(np.round(lv, 2)) == [14.0, 14.5, 15.0] and step == 0.5
        assert sweep_levels_from_cfg([]) == (None, 0.1)
        assert sweep_levels_from_cfg([1, 2, 0]) == (None, 0.1)   # 간격 0 → 자동


# ── 5. NPZ 저장소 ──────────────────────────────────────────────────────────────

class TestStore:
    def test_왕복(self, tmp_path):
        dates = pd.date_range("2016-04-01", periods=5, freq="D").values.astype(
            "datetime64[D]")
        arrs = {"res_net_m3": np.arange(10, dtype="float32").reshape(2, 5)}
        f = save_daily(tmp_path, "res", members=["m1", "m2"], dates=dates,
                       arrays=arrs)
        back = load_daily(tmp_path, "res")
        assert np.array_equal(back["res_net_m3"], arrs["res_net_m3"])
        assert list(back["members"]) == ["m1", "m2"]
        assert np.array_equal(back["dates"], dates)
        assert f.name == "res_daily.npz" and f.parent.name == "daily"

    def test_없으면_None(self, tmp_path):
        assert load_daily(tmp_path, "없는수원") is None

    def test_담을것이_없으면_파일을_만들지_않는다(self, tmp_path):
        assert save_daily(tmp_path, "res", members=[], dates=[], arrays={}) is None
        assert save_daily(tmp_path, "res", members=["m1"],
                          dates=[np.datetime64("2016-04-01")],
                          arrays={"x": None}) is None

    def test_일수가_어긋난_멤버는_버린다(self):
        """길이가 섞인 배열을 만들면 조용히 잘못 정렬된다."""
        per = {"m1": {"q": np.zeros(5)}, "m2": {"q": np.zeros(5)},
               "m3": {"q": np.zeros(4)}}
        names = ["m1", "m2", "m3"]
        a = stack_members(per, "q", names)
        assert a.shape == (2, 5)
        assert common_members(per, "q", names, 5) == ["m1", "m2"]

    def test_변수가_없으면_None(self):
        assert stack_members({"m1": {"q": np.zeros(3)}}, "없는변수", ["m1"]) is None


# ── 5-B. 설정 초기수위 앵커 ────────────────────────────────────────────────────

class TestConfiguredInitAnchor:
    """사전계산표의 설정 초기수위 앵커는 **적어 준 자 눈금 ft 그대로**여야 한다.

    저류량에서 곡선을 역조회해 앵커를 만들면 보간 왕복 오차가 섞인다(실제 팔라우:
    22.0 ft → 22.02 ft). 그러면 운영값과 0.02 ft 어긋난 중복 행이 생겨, 업체 화면이
    어느 줄이 운영 기준인지 알 수 없게 된다.
    """

    def _daily(self):
        dates = pd.date_range("2016-04-01", "2016-06-30", freq="D")
        rng = np.random.default_rng(11)
        return {"dates": dates.values.astype("datetime64[D]"),
                "res_net_m3": rng.uniform(0, 8_000, (12, len(dates))).astype("float32")}

    _THR = {"normal_watch": NW, "watch_warning": WW, "warning_crisis": WC}

    def _sweep(self, tmp_path, p):
        w = write_reservoir_outputs(tmp_path, self._daily(), params=p,
                                    thresholds=self._THR, months=[4, 5, 6],
                                    step_ft=0.5)
        assert w.get("sweep") == "init_level_sweep.csv"
        sw = pd.read_csv(tmp_path / "init_level_sweep.csv", encoding="utf-8-sig")
        return set(np.round(sw["init_ft"].unique(), 2))

    def test_앵커는_저류량이_아니라_설정_ft_에서_온다(self, tmp_path):
        """두 값을 **일부러 어긋나게** 둬서 어느 쪽을 읽는지 못 숨기게 한다.

        실제 팔라우 곡선(pchip 보간)은 ft→m³→ft 왕복에서 0.0213 ft 가 어긋난다.
        합성 곡선은 매끄러워 오차가 1e-7 이라 그 자체로는 결함을 못 드러내므로,
        여기서는 ``init_level_ft`` 와 ``init_m3`` 를 다른 수위로 맞춰 둔다.
        """
        p = _params(init_level_ft=18.07)                # 격자(0.5 ft) 밖 값
        p.init_m3 = float(p.curve.stage_to_storage(21.03 - p.datum_offset_ft))
        lv = self._sweep(tmp_path, p)
        assert 18.07 in lv, "설정 초기수위가 표에 없다 — 슬라이더 기본값을 못 찾는다"
        assert 21.03 not in lv, "저류량 역조회값이 중복 행으로 남았다"

    def test_설정값이_없으면_역조회로_물러난다(self, tmp_path):
        """옛 params(필드 없음)에서도 앵커가 사라지지 않아야 한다."""
        p = _params()                       # init_level_ft = NaN
        inv = round(float(p.curve.storage_to_stage(p.init_m3)) + p.datum_offset_ft, 2)
        lv = self._sweep(tmp_path, p)
        assert inv in lv


# ── 6. 잉여수 식 ──────────────────────────────────────────────────────────────

def test_잉여수는_하천유지유량을_남기고_펌프용량에서_잘린다():
    out = surplus_m3_from_flow([0.0, 0.01, 0.02, 0.05, 1.0],
                               min_flow_m3s=0.02, max_m3s=0.15) / 86400.0
    assert list(np.round(out, 4)) == [0.0, 0.0, 0.0, 0.03, 0.15]
