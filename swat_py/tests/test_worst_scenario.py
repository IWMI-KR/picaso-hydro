"""Worst Scenario — 관측 월별 최저 ① · 예측 계절별 최악 ② 회귀 테스트.

요청(2026-11-06)과 확정 사항
    ① 관측이 있는 기간에서 **결측 제외**, 달력 월별 최저 연도의 월평균·일최저.
    ② 전체 예측 기간에서 계절별로 **비정상 개월수 우선 → 최저값** 규칙으로 1기간
       선정, 3개월 대표값·단계·확률 요약.
    ③ 다시 돌리면 갱신(멱등).
    대표통계는 ``drought.climatology_stat`` 을 따른다 — 팔라우 median / 쿡 mean.

SWAT+ 없이 도는 테스트다 — 합성 CSV 로 디렉터리 구조만 만들어 검사한다.
"""
from __future__ import annotations

import pandas as pd
import pytest

from swat_py.drought.worst_scenario import (
    SEASONS,
    build_forecast_seasonal_worst,
    build_observed_monthly_worst,
    build_worst,
    classify_stage,
    resolve_stat,
)

# 팔라우 Ngerimel 실제 경계 — 만수 23.00 ft 의 95/85/65%
PALAU_THR = (21.85, 19.55, 14.95)


# ── 설정 더미 ────────────────────────────────────────────────────────────────
class _Src:
    def __init__(self, name, outlets, type_="stream", reservoir=""):
        self.name, self.outlets, self.type, self.reservoir = name, outlets, type_, reservoir


class _Obs:
    def __init__(self, id, variable, unit, obs_file, obs_column,
                 outlet_id=None, reservoir="", min_valid=float("nan")):
        self.id, self.variable, self.unit = id, variable, unit
        self.obs_file, self.obs_column = obs_file, obs_column
        self.outlet_id, self.reservoir, self.min_valid = outlet_id, reservoir, min_valid
        self.time_step = "daily"
        self.outlet_name = ""


class _ResCfg:
    """reservoirs 레지스트리 더미 — 사수위는 bottom_ft + obs_datum_offset_ft.

    Ngerimel 실제값: 23.34 MSL + (−22.0) = 자 눈금 1.34 ft.
    """

    def __init__(self, dead_gauge=1.34):
        self.bottom_ft = 23.34
        self.obs_datum_offset_ft = dead_gauge - 23.34


class _DC:
    def __init__(self, sources, stat="median", worst_stat=""):
        self.sources, self.climatology_stat = sources, stat
        self.worst_stat = worst_stat
        self.outlets = {g: n for s in sources for g, n in s.outlets.items()}

    def source_for(self, outlet):
        for s in self.sources:
            try:
                if int(outlet) in s.outlets:
                    return s
            except (ValueError, TypeError):
                pass
            if str(outlet) in {str(v) for v in s.outlets.values()}:
                return s
        return None


class _Cfg:
    def __init__(self, root, sources, obs, stat="median", worst_stat=""):
        self.PrjDir = str(root)
        self.ObservedDataDir = str(root / "0_database" / "obs")
        self.Drought = _DC(sources, stat, worst_stat)
        self.Observations = obs


# ── 합성 자료 ────────────────────────────────────────────────────────────────
def _write_obs(root, name, col, rows):
    d = root / "0_database" / "obs" / "flow"
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["date", col]).to_csv(d / f"{name}.csv", index=False)


def _daily_month(year, month, value, days=28):
    return [(f"{year}-{month:02d}-{d:02d}", value) for d in range(1, days + 1)]


def _write_period(root, label, outlet, ym_vals, thr=PALAU_THR,
                  probs=None, variable="water_level_ft"):
    """한 기간·한 수원 폴더에 series/stage_prob/thresholds 를 만든다."""
    d = root / "4_drought_risk" / "forecast" / label / outlet
    d.mkdir(parents=True, exist_ok=True)
    ser = [{"ym": ym, "month": int(ym[5:7]), "hist_mean": 23.0, "observed": "",
            "forecast_mean": v, "p5": v, "p25": v, "p50": v, "p75": v, "p95": v}
           for ym, v in ym_vals]
    pd.DataFrame(ser).to_csv(d / "series.csv", index=False)
    pr = []
    for i, (ym, v) in enumerate(ym_vals):
        p = (probs or {}).get(ym, (70.0, 20.0, 7.0, 3.0))
        st = classify_stage(v, *thr)
        pr.append({"month": int(ym[5:7]), "ym": ym, "Normal": p[0], "Watch": p[1],
                   "Warning": p[2], "Crisis": p[3], "most_likely": st, "n": 1000})
    pd.DataFrame(pr).to_csv(d / "stage_prob.csv", index=False)
    pd.DataFrame([{"method": "level_fraction", "variable": variable,
                   "n_ensemble": 1000, "normal_watch": thr[0],
                   "watch_warning": thr[1], "warning_crisis": thr[2]}]
                 ).to_csv(d / "thresholds.csv", index=False)


# ── classify_stage ──────────────────────────────────────────────────────────
class TestClassifyStage:
    @pytest.mark.parametrize("v,exp", [
        (23.0, "Normal"), (21.85, "Normal"), (21.84, "Watch"), (19.55, "Watch"),
        (19.54, "Warning"), (14.95, "Warning"), (14.94, "Crisis"), (0.0, "Crisis"),
    ])
    def test_경계값은_상위단계에_포함된다(self, v, exp):
        assert classify_stage(v, *PALAU_THR) == exp

    def test_NaN_은_빈칸(self):
        assert classify_stage(float("nan"), *PALAU_THR) == ""

    def test_낮을수록_나쁘다_하천유량도_같다(self):
        """유량(m³/s)도 낮을수록 나쁘다 — 수위와 방향이 같다."""
        assert classify_stage(0.0005, 0.000514, 1.92e-05, 1.12e-05) == "Watch"
        assert classify_stage(1e-06, 0.000514, 1.92e-05, 1.12e-05) == "Crisis"


# ── 대표통계 선택 ────────────────────────────────────────────────────────────
class TestResolveStat:
    def test_팔라우는_median_쿡은_mean_을_설정에서_가져온다(self, tmp_path):
        for stat in ("median", "mean"):
            cfg = _Cfg(tmp_path, [_Src("a", {1: "a"})], [], stat=stat)
            assert resolve_stat(cfg) == stat

    def test_인자가_설정을_덮어쓴다(self, tmp_path):
        cfg = _Cfg(tmp_path, [_Src("a", {1: "a"})], [], stat="median")
        assert resolve_stat(cfg, "mean") == "mean"

    def test_잘못된_값은_거부(self, tmp_path):
        cfg = _Cfg(tmp_path, [_Src("a", {1: "a"})], [], stat="median")
        with pytest.raises(ValueError):
            resolve_stat(cfg, "p90")

    def test_worst_stat_이_climatology_stat_을_덮는다(self, tmp_path):
        """평년선은 median, Worst Scenario 는 mean — 팔라우가 쓰는 조합(2026-11-06).

        저수지 median 은 만수에 고정돼 최악이 가려지지 않으므로 분리했다.
        """
        cfg = _Cfg(tmp_path, [_Src("a", {1: "a"})], [], stat="median", worst_stat="mean")
        assert cfg.Drought.climatology_stat == "median"
        assert resolve_stat(cfg) == "mean"

    def test_worst_stat_이_비면_climatology_stat_을_따른다(self, tmp_path):
        cfg = _Cfg(tmp_path, [_Src("a", {1: "a"})], [], stat="median", worst_stat="")
        assert resolve_stat(cfg) == "median"

    def test_설정_dataclass_가_worst_stat_을_실제로_읽는다(self):
        """필드가 없으면 YAML 키가 **조용히 무시**된다 — 실제 있었던 버그."""
        from swat_py.config.env import _DroughtCfg
        assert "worst_stat" in _DroughtCfg.__dataclass_fields__
        assert _DroughtCfg.__dataclass_fields__["worst_stat"].default == ""


# ── ① 관측 월별 최저 ────────────────────────────────────────────────────────
class TestObservedMonthlyWorst:
    def _cfg(self, tmp_path, rows, min_valid=float("nan")):
        _write_obs(tmp_path, "ngerimel", "wlevel_ft", rows)
        obs = [_Obs("ngerimel", "wlevel", "ft", "flow/ngerimel.csv", "wlevel_ft",
                    reservoir="ngerimel", min_valid=min_valid)]
        src = [_Src("ngerimel", {4: "ngerimel"}, "reservoir", "ngerimel")]
        return _Cfg(tmp_path, src, obs)

    def test_가장_낮은_연도를_고르고_월평균과_일최저를_낸다(self, tmp_path):
        rows = (_daily_month(2019, 3, 22.0) + _daily_month(2020, 3, 18.0)
                + _daily_month(2021, 3, 20.0))
        rows[len(_daily_month(2019, 3, 22.0)) + 5] = ("2020-03-06", 15.0)  # 일최저
        df, _ = build_observed_monthly_worst(self._cfg(tmp_path, rows))
        r = df[df["month"] == 3].iloc[0]
        assert r["worst_year"] == 2020
        assert r["daily_min"] == pytest.approx(15.0)
        assert r["monthly_mean"] < 18.0          # 15.0 이 섞여 평균이 내려간다
        assert r["daily_min_date"] == "2020-03-06"

    def test_결측은_제외하고_평균을_낸다(self, tmp_path):
        """빈 칸(결측)이 0 으로 취급되면 평균이 왜곡된다 — 제외해야 한다."""
        rows = _daily_month(2020, 5, 20.0)
        rows[0] = ("2020-05-01", "")             # 결측
        cfg = self._cfg(tmp_path, rows)
        df, _ = build_observed_monthly_worst(cfg, min_coverage=0.5)
        r = df[df["month"] == 5].iloc[0]
        assert r["monthly_mean"] == pytest.approx(20.0)
        assert r["n_days_valid"] == 27

    def test_min_valid_미만은_결측_처리(self, tmp_path):
        """팔라우 2019-03 의 0.0 ft 같은 물리적 불가 값을 평균에 넣지 않는다."""
        rows = _daily_month(2020, 5, 7.0)
        rows[0] = ("2020-05-01", 0.0)
        cfg = self._cfg(tmp_path, rows, min_valid=1.0)
        df, _ = build_observed_monthly_worst(cfg, min_coverage=0.5)
        r = df[df["month"] == 5].iloc[0]
        assert r["daily_min"] == pytest.approx(7.0), "0.0 이 일최저로 잡히면 안 된다"
        assert r["n_days_valid"] == 27

    def test_유효일_부족한_연도는_후보에서_빠진다(self, tmp_path):
        """더 낮지만 3일만 있는 해보다, 온전한 해를 고른다."""
        rows = (_daily_month(2020, 7, 21.0, days=31)
                + [("2021-07-01", 5.0), ("2021-07-02", 5.0), ("2021-07-03", 5.0)])
        cfg = self._cfg(tmp_path, rows)
        df, log = build_observed_monthly_worst(cfg, min_coverage=0.90)
        r = df[df["month"] == 7].iloc[0]
        assert r["worst_year"] == 2020
        assert r["selection"] == "ok"
        assert r["n_years_candidate"] == 1 and r["n_years_observed"] == 2

    def test_후보가_없으면_차선으로_대체하고_로그에_남긴다(self, tmp_path):
        rows = [("2021-08-01", 5.0), ("2021-08-02", 5.0)]
        cfg = self._cfg(tmp_path, rows)
        df, log = build_observed_monthly_worst(cfg, min_coverage=0.90)
        r = df[df["month"] == 8].iloc[0]
        assert r["selection"] == "relaxed"
        assert any("차선" in ln for ln in log)

    def test_관측_없는_달은_행을_만들지_않는다(self, tmp_path):
        cfg = self._cfg(tmp_path, _daily_month(2020, 2, 20.0))
        df, _ = build_observed_monthly_worst(cfg, min_coverage=0.5)
        assert sorted(df["month"].tolist()) == [2]

    def test_저수지는_사수위_미만을_자동으로_결측_처리한다(self, tmp_path):
        """min_valid 가 없어도 레지스트리 사수위로 0.0 같은 기록을 막는다
        (2019-03 결측 0.0 사례 재발 방지 — 자료수정이력 2026-11-02)."""
        rows = _daily_month(2020, 6, 20.0, days=30)
        rows[0] = ("2020-06-01", 0.0)
        cfg = self._cfg(tmp_path, rows)          # min_valid 미지정
        cfg.Reservoirs = {"ngerimel": _ResCfg(dead_gauge=1.34)}
        df, _ = build_observed_monthly_worst(cfg, min_coverage=0.5)
        r = df[df["month"] == 6].iloc[0]
        assert r["daily_min"] == pytest.approx(20.0), "0.0 이 일최저로 잡히면 안 된다"
        assert r["n_days_valid"] == 29

    def test_수원에_속하지_않는_관측은_제외(self, tmp_path):
        _write_obs(tmp_path, "other", "flow_m3s", _daily_month(2020, 2, 1.0))
        obs = [_Obs("other", "flow", "m3/s", "flow/other.csv", "flow_m3s", outlet_id=99)]
        cfg = _Cfg(tmp_path, [_Src("ngerimel", {4: "ngerimel"})], obs)
        df, log = build_observed_monthly_worst(cfg)
        assert df.empty and any("건너뛰" in ln or "없어" in ln for ln in log)


# ── ② 예측 계절별 최악 ──────────────────────────────────────────────────────
class TestForecastSeasonalWorst:
    def _three(self, year, mons, vals):
        return [(f"{year}-{m:02d}", v) for m, v in zip(mons, vals)]

    def test_비정상_개월수가_많은_기간을_먼저_고른다(self, tmp_path):
        """확정 규칙 — 더 깊게 떨어진 기간보다 **오래** 낮았던 기간."""
        # 2020: 3개월 모두 Watch 이하(비정상 3) / 2024: 한 달만 Crisis(비정상 1)
        _write_period(tmp_path, "2020_FMA", "ngerimel",
                      self._three(2020, [2, 3, 4], [21.0, 20.1, 19.8]))
        _write_period(tmp_path, "2024_FMA", "ngerimel",
                      self._three(2024, [2, 3, 4], [23.0, 14.9, 23.0]))
        cfg = _Cfg(tmp_path, [_Src("ngerimel", {4: "ngerimel"}, "reservoir", "ngerimel")], [])
        det, sel, st = build_forecast_seasonal_worst(cfg)
        row = sel[sel["season"] == "FMA"].iloc[0]
        assert row["selected_period"] == "2020_FMA"
        assert row["n_months_below_watch"] == 3
        assert row["n_candidates"] == 2

    def test_개월수가_같으면_최저값이_낮은_기간(self, tmp_path):
        _write_period(tmp_path, "2015_JFM", "ngerimel",
                      self._three(2015, [1, 2, 3], [23.0, 23.0, 20.0]))
        _write_period(tmp_path, "2016_JFM", "ngerimel",
                      self._three(2016, [1, 2, 3], [23.0, 23.0, 16.0]))
        cfg = _Cfg(tmp_path, [_Src("ngerimel", {4: "ngerimel"})], [])
        _, sel, _ = build_forecast_seasonal_worst(cfg)
        row = sel[sel["season"] == "JFM"].iloc[0]
        assert row["selected_period"] == "2016_JFM"
        assert row["min_value"] == pytest.approx(16.0)

    def test_median_과_mean_이_다른_기간을_고를_수_있다(self, tmp_path):
        """쿡은 mean, 팔라우는 median — 통계 선택이 결과를 바꾼다."""
        d = tmp_path / "4_drought_risk" / "forecast" / "2017_MAM" / "ch"
        d.mkdir(parents=True)
        pd.DataFrame([
            {"ym": "2017-03", "month": 3, "forecast_mean": 23.0, "p50": 20.0},
            {"ym": "2017-04", "month": 4, "forecast_mean": 23.0, "p50": 23.0},
            {"ym": "2017-05", "month": 5, "forecast_mean": 23.0, "p50": 23.0},
        ]).to_csv(d / "series.csv", index=False)
        pd.DataFrame([{"month": m, "ym": f"2017-{m:02d}", "Normal": 50.0, "Watch": 30.0,
                       "Warning": 15.0, "Crisis": 5.0, "most_likely": "Normal", "n": 1000}
                      for m in (3, 4, 5)]).to_csv(d / "stage_prob.csv", index=False)
        pd.DataFrame([{"method": "level_fraction", "variable": "water_level_ft",
                       "normal_watch": PALAU_THR[0], "watch_warning": PALAU_THR[1],
                       "warning_crisis": PALAU_THR[2], "n_ensemble": 1000}]
                     ).to_csv(d / "thresholds.csv", index=False)
        cfg = _Cfg(tmp_path, [_Src("ch", {1: "ch"})], [])
        _, sel_med, _ = build_forecast_seasonal_worst(cfg, stat="median")
        _, sel_mean, _ = build_forecast_seasonal_worst(cfg, stat="mean")
        assert sel_med.iloc[0]["n_months_below_watch"] == 1
        assert sel_mean.iloc[0]["n_months_below_watch"] == 0

    def test_두_값이_동점이면_비정상확률로_가른다(self, tmp_path):
        """팔라우 Ngerimel 처럼 중앙값이 만수에 고정돼 동점일 때 — 연도순이 아니라
        위험확률이 큰 기간을 고르고, 동점 사실을 표에 남긴다."""
        for yr, p in ((2013, (95.0, 4.0, 1.0, 0.0)), (2019, (60.0, 20.0, 15.0, 5.0))):
            _write_period(tmp_path, f"{yr}_MJJ", "ngerimel",
                          [(f"{yr}-05", 23.0), (f"{yr}-06", 23.0), (f"{yr}-07", 23.0)],
                          probs={f"{yr}-{m:02d}": p for m in (5, 6, 7)})
        cfg = _Cfg(tmp_path, [_Src("ngerimel", {4: "ngerimel"})], [])
        _, sel, _ = build_forecast_seasonal_worst(cfg)
        row = sel[sel["season"] == "MJJ"].iloc[0]
        assert row["selected_period"] == "2019_MJJ", "연도순 첫 후보가 뽑히면 안 된다"
        assert row["n_tied_by_rule"] == 2
        assert row["tiebreak"] == "비정상확률"
        assert row["risk_nonnormal_pct"] == pytest.approx(40.0)

    def test_동점이_아니면_타이브레이크를_쓰지_않는다(self, tmp_path):
        """확정 규칙이 먼저다 — 위험확률이 낮아도 비정상 개월수가 많으면 그쪽."""
        _write_period(tmp_path, "2013_JJA", "ngerimel",
                      [("2013-06", 23.0), ("2013-07", 23.0), ("2013-08", 23.0)],
                      probs={f"2013-{m:02d}": (10.0, 30.0, 30.0, 30.0) for m in (6, 7, 8)})
        _write_period(tmp_path, "2019_JJA", "ngerimel",
                      [("2019-06", 20.0), ("2019-07", 20.0), ("2019-08", 20.0)],
                      probs={f"2019-{m:02d}": (99.0, 1.0, 0.0, 0.0) for m in (6, 7, 8)})
        cfg = _Cfg(tmp_path, [_Src("ngerimel", {4: "ngerimel"})], [])
        _, sel, _ = build_forecast_seasonal_worst(cfg)
        row = sel[sel["season"] == "JJA"].iloc[0]
        assert row["selected_period"] == "2019_JJA"
        assert row["n_months_below_watch"] == 3 and row["tiebreak"] == ""

    def test_3개월_상세에_단계와_확률이_함께_나온다(self, tmp_path):
        probs = {"2020-02": (10.0, 60.0, 20.0, 10.0)}
        _write_period(tmp_path, "2020_FMA", "ngerimel",
                      self._three(2020, [2, 3, 4], [21.0, 20.1, 19.8]), probs=probs)
        cfg = _Cfg(tmp_path, [_Src("ngerimel", {4: "ngerimel"})], [])
        det, _, _ = build_forecast_seasonal_worst(cfg)
        r = det[det["ym"] == "2020-02"].iloc[0]
        assert r["stage"] == "Watch"
        assert r["prob_of_stage_pct"] == pytest.approx(60.0)
        assert r["prob_watch_pct"] == pytest.approx(60.0)
        assert r["prob_crisis_pct"] == pytest.approx(10.0)
        assert r["unit"] == "ft" and r["n_members"] == 1000
        assert sorted(det["month_index"].tolist()) == [1, 2, 3]

    def test_하천은_단위가_유량으로_나온다(self, tmp_path):
        _write_period(tmp_path, "2018_JJA", "avatiu",
                      [("2018-06", 1e-5), ("2018-07", 1e-5), ("2018-08", 1e-5)],
                      thr=(5.1e-4, 1.9e-5, 1.1e-5), variable="flow_m3s")
        cfg = _Cfg(tmp_path, [_Src("avatiu", {13: "avatiu"})], [], stat="mean")
        det, _, _ = build_forecast_seasonal_worst(cfg)
        assert set(det["unit"]) == {"m3/s"}

    def test_계절_꼬리표가_붙은_폴더도_읽는다(self, tmp_path):
        _write_period(tmp_path, "2021_SON__ic22.0ft-scn", "ngerimel",
                      self._three(2021, [9, 10, 11], [20.0, 20.0, 20.0]))
        cfg = _Cfg(tmp_path, [_Src("ngerimel", {4: "ngerimel"})], [])
        _, sel, _ = build_forecast_seasonal_worst(cfg)
        assert sel.iloc[0]["selected_period"] == "2021_SON__ic22.0ft-scn"

    def test_불완전한_기간은_후보에서_빠진다(self, tmp_path):
        """stage_prob 만 있고 series 가 없으면 센다 — 빈 결과가 최악으로 뽑히면 안 된다."""
        _write_period(tmp_path, "2019_OND", "ngerimel",
                      self._three(2019, [10, 11, 12], [20.0, 20.0, 20.0]))
        bad = tmp_path / "4_drought_risk" / "forecast" / "2022_OND" / "ngerimel"
        bad.mkdir(parents=True)
        (bad / "stage_prob.csv").write_text("month,ym,Normal\n10,2022-10,100\n")
        cfg = _Cfg(tmp_path, [_Src("ngerimel", {4: "ngerimel"})], [])
        _, sel, _ = build_forecast_seasonal_worst(cfg)
        row = sel[sel["season"] == "OND"].iloc[0]
        assert row["selected_period"] == "2019_OND" and row["n_candidates"] == 1

    def test_예측이_없으면_빈_표(self, tmp_path):
        cfg = _Cfg(tmp_path, [_Src("ngerimel", {4: "ngerimel"})], [])
        det, sel, _ = build_forecast_seasonal_worst(cfg)
        assert det.empty and sel.empty

    def test_12계절_라벨이_모두_정의돼_있다(self):
        assert len(SEASONS) == 12 and SEASONS[0] == "JFM" and SEASONS[-1] == "DJF"


# ── ③ 갱신(멱등) ────────────────────────────────────────────────────────────
class TestBuildWorstUpdates:
    def _cfg(self, tmp_path):
        _write_obs(tmp_path, "ngerimel", "wlevel_ft", _daily_month(2020, 3, 20.0, days=31))
        obs = [_Obs("ngerimel", "wlevel", "ft", "flow/ngerimel.csv", "wlevel_ft",
                    reservoir="ngerimel")]
        return _Cfg(tmp_path, [_Src("ngerimel", {4: "ngerimel"}, "reservoir", "ngerimel")], obs)

    def test_네_파일이_worst_폴더에_생긴다(self, tmp_path):
        cfg = self._cfg(tmp_path)
        _write_period(tmp_path, "2020_FMA", "ngerimel",
                      [("2020-02", 21.0), ("2020-03", 20.1), ("2020-04", 19.8)])
        build_worst(cfg, quiet=True)
        d = tmp_path / "4_drought_risk" / "worst"
        for fn in ("worst_observed_monthly.csv", "worst_observed_reliability.txt",
                   "worst_forecast_seasonal.csv", "worst_forecast_selection.csv"):
            assert (d / fn).is_file(), fn

    def test_새_예측이_추가되면_다시_돌려_갱신된다(self, tmp_path):
        """③ 요건 — 매월 재실행으로 최신 상태가 된다."""
        cfg = self._cfg(tmp_path)
        _write_period(tmp_path, "2020_FMA", "ngerimel",
                      [("2020-02", 23.0), ("2020-03", 22.0), ("2020-04", 23.0)])
        build_worst(cfg, quiet=True)
        f = tmp_path / "4_drought_risk" / "worst" / "worst_forecast_selection.csv"
        assert pd.read_csv(f).iloc[0]["selected_period"] == "2020_FMA"
        # 더 나쁜 새 예측 추가 → 재실행하면 선정이 바뀐다
        _write_period(tmp_path, "2026_FMA", "ngerimel",
                      [("2026-02", 20.0), ("2026-03", 19.0), ("2026-04", 18.0)])
        build_worst(cfg, quiet=True)
        after = pd.read_csv(f).iloc[0]
        assert after["selected_period"] == "2026_FMA"
        assert after["n_months_below_watch"] == 3

    def test_관측이_바뀌면_다시_돌려_갱신된다(self, tmp_path):
        cfg = self._cfg(tmp_path)
        build_worst(cfg, quiet=True, forecast=False)
        f = tmp_path / "4_drought_risk" / "worst" / "worst_observed_monthly.csv"
        assert pd.read_csv(f).iloc[0]["worst_year"] == 2020
        _write_obs(tmp_path, "ngerimel", "wlevel_ft",
                   _daily_month(2020, 3, 20.0, days=31) + _daily_month(2022, 3, 12.0, days=31))
        build_worst(cfg, quiet=True, forecast=False)
        r = pd.read_csv(f).iloc[0]
        assert r["worst_year"] == 2022 and r["monthly_mean"] == pytest.approx(12.0)

    def test_같은_입력을_두_번_돌리면_결과가_같다(self, tmp_path):
        cfg = self._cfg(tmp_path)
        _write_period(tmp_path, "2020_FMA", "ngerimel",
                      [("2020-02", 21.0), ("2020-03", 20.1), ("2020-04", 19.8)])
        build_worst(cfg, quiet=True)
        f = tmp_path / "4_drought_risk" / "worst" / "worst_forecast_seasonal.csv"
        first = f.read_text(encoding="utf-8-sig")
        build_worst(cfg, quiet=True)
        assert f.read_text(encoding="utf-8-sig") == first


class TestWiredIntoPipeline:
    def test_run_파이프라인이_worst_를_부른다(self):
        """매월 운영(swat_py.drought.run)에서 자동 갱신되는지 — 소스로 확인."""
        import inspect

        from swat_py.drought import run
        src = inspect.getsource(run.run_pipeline)
        assert "build_worst" in src
        assert "with_worst" in inspect.signature(run.run_pipeline).parameters
