"""평년선 범례(통계명·기간)와 평년 평균 보조선.

두 결함을 막는다.

① 범례가 평년선의 통계를 **잘못 말했다** — `drought.climatology_stat` 을 설정 가능하게
   만든 뒤에도 범례는 `"Historical Mean (2006–2024)"` 가 하드코딩돼 있어, 팔라우는
   **median 을 그리면서 Mean 이라 적었다.** 기간도 실제(1985–2023)와 달랐다 —
   양 사업 모두 틀린 값이었다.

② 예측선은 **항상 앙상블 평균**이다. 평년선이 median 이면 두 선이 서로 다른 통계가
   되어, 저수지는 median > mean 이라 예측이 **늘** 평년 아래로 그려진다(팔라우
   응게리멜 501개월 100%, 평균 −0.252 ft). 같은 통계의 기준선(hist_alt)을 함께
   그려 그 인공물을 없앤다. median 을 고른 경우에만 만들므로 쿡 그림은 바뀌지 않는다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from swat_py.drought.figure import make_outlet_figure


def _outlet(tmp_path, *, clim_stat=None, clim_years=None, hist_alt=False):
    d = tmp_path / "ngerimel"
    d.mkdir()
    cols = {"month": range(1, 13),
            "hist_mean": np.linspace(22.0, 23.0, 12),
            "observed": [np.nan] * 12,
            "forecast_mean": [np.nan] * 3 + [22.0, 21.0, 20.0] + [np.nan] * 6,
            "p5": [np.nan] * 3 + [15.0, 14.0, 13.0] + [np.nan] * 6,
            "p25": [np.nan] * 3 + [20.0, 19.0, 18.0] + [np.nan] * 6,
            "p50": [np.nan] * 3 + [23.0, 23.0, 23.0] + [np.nan] * 6,
            "p75": [np.nan] * 3 + [23.0, 23.0, 23.0] + [np.nan] * 6,
            "p95": [np.nan] * 3 + [23.0, 23.0, 23.0] + [np.nan] * 6}
    if hist_alt:                       # 평년 평균은 중앙값보다 낮다(저수지)
        cols["hist_alt"] = np.linspace(21.0, 22.5, 12)
    pd.DataFrame(cols).to_csv(d / "series.csv", index=False)
    thr = {"method": "level_fraction", "variable": "water_level_ft",
           "nw_input": 95, "ww_input": 85, "wc_input": 65,
           "full_level_ft": 23.0, "n_ensemble": 1000,
           "normal_watch": 21.85, "watch_warning": 19.55, "warning_crisis": 14.95}
    if clim_stat is not None:
        thr["clim_stat"] = clim_stat
    if clim_years is not None:
        thr["clim_years"] = clim_years
    pd.DataFrame([thr]).to_csv(d / "thresholds.csv", index=False)
    pd.DataFrame([{"month": m, "Normal": 40, "Watch": 30, "Warning": 20,
                   "Crisis": 10, "most_likely": "Normal"} for m in (4, 5, 6)]
                 ).to_csv(d / "stage_prob.csv", index=False)
    return d


# ── ① 범례 ──────────────────────────────────────────────────────────────────
class TestLegendLabel:
    def test_median_이면_Median_이라_적는다(self, tmp_path):
        d = _outlet(tmp_path, clim_stat="median", clim_years="1985_2023")
        out = make_outlet_figure(d)
        assert out.is_file() and out.stat().st_size > 0
        from swat_py.drought import figure as F
        lbl = F._climatology_legend("median", "1985_2023")
        assert lbl == "Historical Median (1985–2023)"

    def test_mean_이면_Mean_이라_적는다(self):
        from swat_py.drought import figure as F
        assert F._climatology_legend("mean", "1985_2023") == "Historical Mean (1985–2023)"

    def test_기간은_설정에서_오고_하드코딩이_아니다(self):
        from swat_py.drought import figure as F
        assert "2006" not in F._climatology_legend("mean", "1982_2020")
        assert F._climatology_legend("mean", "1982_2020") == "Historical Mean (1982–2020)"

    def test_통계_미상이면_중립_표기(self):
        """옛 산출물(clim_stat 열 없음)도 그려야 한다 — 틀린 이름을 적지는 않는다."""
        from swat_py.drought import figure as F
        assert F._climatology_legend("", "") == "Historical"
        assert F._climatology_legend("", "1985_2023") == "Historical (1985–2023)"

    def test_옛_산출물도_그려진다(self, tmp_path):
        d = _outlet(tmp_path)                      # clim_stat·clim_years 없음
        out = make_outlet_figure(d)
        assert out.is_file() and out.stat().st_size > 0

    def test_하드코딩된_옛_문구가_코드에_남아있지_않다(self):
        from pathlib import Path

        import swat_py.drought.figure as F
        src = Path(F.__file__).read_text(encoding="utf-8")
        assert "Historical Mean (2006–2024)" not in src


# ── ② 평년 평균 보조선 ───────────────────────────────────────────────────────
class TestClimatologyAltLine:
    def test_hist_alt_있으면_그려진다(self, tmp_path):
        d = _outlet(tmp_path, clim_stat="median", clim_years="1985_2023", hist_alt=True)
        out = make_outlet_figure(d)
        assert out.is_file() and out.stat().st_size > 0

    def test_hist_alt_없어도_그려진다(self, tmp_path):
        d = _outlet(tmp_path, clim_stat="mean", clim_years="1985_2023", hist_alt=False)
        out = make_outlet_figure(d)
        assert out.is_file() and out.stat().st_size > 0

    def test_hist_alt_가_전부_결측이면_선을_추가하지_않는다(self, tmp_path):
        d = _outlet(tmp_path, clim_stat="median", clim_years="1985_2023")
        s = pd.read_csv(d / "series.csv")
        s["hist_alt"] = np.nan
        s.to_csv(d / "series.csv", index=False)
        out = make_outlet_figure(d)        # 빈 열로 죽지 않아야 한다
        assert out.is_file() and out.stat().st_size > 0


# ── ③ 산출 단계: hist_alt 생성 조건 · thresholds 메타데이터 ──────────────────
class TestDashboardWiring:
    """`dashboard_data` 가 범례·보조선에 필요한 값을 **실제로 기록하는지**."""

    def test_두_분기_모두_clim_stat_과_clim_years_를_기록한다(self):
        from pathlib import Path

        import swat_py.drought.dashboard_data as D
        src = Path(D.__file__).read_text(encoding="utf-8")
        # 저수지 분기 + 채널 분기 = thresholds.csv 를 쓰는 지점 2곳
        assert src.count('"clim_stat": climatology_stat(cfg)') == 2
        assert src.count('"clim_years": climatology_tag(cfg)') == 2
        assert src.count('thresholds.csv"') >= 2

    def test_hist_alt_는_median_을_고른_경우에만_만든다(self):
        """mean 을 고른 사업(쿡)의 그림을 말없이 바꾸지 않기 위한 조건."""
        from pathlib import Path

        import swat_py.drought.dashboard_data as D
        src = Path(D.__file__).read_text(encoding="utf-8")
        assert 'if _stat_col != "mean":' in src            # 채널 분기
        assert 'climatology_stat(cfg) != "mean"' in src     # 저수지 분기
        assert src.count('series["hist_alt"]') == 2

    def test_저수지_보조선은_수위_기준일_때만(self):
        """저수량%(capacity) 기준에는 _level_ft_mean 열이 없다 — 조건에 level_based 포함."""
        from pathlib import Path

        import swat_py.drought.dashboard_data as D
        src = Path(D.__file__).read_text(encoding="utf-8")
        assert 'if level_based and climatology_stat(cfg) != "mean":' in src
        assert '_level_ft_mean' in src
