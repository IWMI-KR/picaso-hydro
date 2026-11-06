"""historical_worst — 저수지 단계 기준(단위)과 그림 생성.

두 결함을 막는다.

① **단위 불일치** — 설정이 `level_fraction [95, 85, 65]`(만수 **수위**의 %)인데,
   그 값을 그대로 받아 **저수량%**에 대고 분류했다. 만수 수위의 95%와 만수 저수량의
   95%는 다른 양이다. 응게리멜 12계절 중 **9계절이 실제보다 심각한 쪽으로** 오분류됐다
   (예: MJJ 2015 → Watch, 자 눈금 22.24 ft 로는 Normal). 예측 경로와 기준을 맞춘다.

② **고아 그림** — 이 대시보드 PNG 는 생성 코드가 없어 파일로만 존재했다. 결과가 바뀌어도
   그림은 그대로 남아 보고서가 옛 수치를 인용했다. 이제 산출과 함께 항상 만든다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.drought.fdc import stage_thresholds
from swat_py.drought.historical_worst import (
    _reservoir_stage,
    _stage_thresholds_by_outlet,
    make_historical_worst_figure,
)

FULL_FT = 23.0
NW, WW, WC = 21.85, 19.55, 14.95        # [95, 85, 65] % × 23.0 ft


class TestLevelFractionUnits:
    def test_level_fraction_은_ft_로_환산해야_한다(self):
        st = stage_thresholds([], "level_fraction", [95, 85, 65], full_level_ft=FULL_FT)
        assert st["normal_watch"] == pytest.approx(NW)
        assert st["watch_warning"] == pytest.approx(WW)
        assert st["warning_crisis"] == pytest.approx(WC)

    def test_환산하지_않으면_백분율이_그대로_나온다(self):
        """환산 누락 시의 값 — 이 값이 저수량%에 쓰이면서 오분류가 났다."""
        st = stage_thresholds([], "level_fraction", [95, 85, 65])
        assert (st["normal_watch"], st["watch_warning"],
                st["warning_crisis"]) == (95.0, 85.0, 65.0)

    @pytest.mark.parametrize("storage_pct,gauge_ft,wrong,right", [
        (90.7, 22.24, "Watch", "Normal"),      # MJJ 2015 — 보고서가 Crisis 로 적었던 계절
        (94.1, 22.50, "Watch", "Normal"),      # JJA 1997
        (80.7, 21.24, "Warning", "Watch"),     # SON 1994
        (59.0, 18.63, "Crisis", "Warning"),    # DJF 2015
        (70.8, 19.53, "Warning", "Warning"),   # JFM 1998 — 우연히 같은 계절
        (39.3, 12.46, "Crisis", "Crisis"),     # FMA 1998 — 실제 최악
    ])
    def test_저수량퍼센트_분류와_수위_분류가_다르다(self, storage_pct, gauge_ft, wrong, right):
        assert _reservoir_stage(storage_pct, 95.0, 85.0, 65.0) == wrong
        assert _reservoir_stage(gauge_ft, NW, WW, WC) == right

    def test_만수_이상은_Normal(self):
        assert _reservoir_stage(23.0, NW, WW, WC) == "Normal"
        assert _reservoir_stage(float("nan"), NW, WW, WC) == "NA"


class TestThresholdHelper:
    def test_그림이_쓰는_헬퍼도_ft_로_준다(self, monkeypatch):
        """그림의 임계선과 축의 단위가 같아야 한다 — 축은 ft, 선은 % 이던 결함."""
        import swat_py.drought.historical_worst as H

        class _Src:
            type = "reservoir"
            outlets = {4: "ngerimel"}

        class _DC:
            sources = [_Src()]
            syear, eyear, climatology_years = 1982, 2023, []

            @staticmethod
            def threshold_for(gid):
                return "level_fraction", [95.0, 85.0, 65.0]

        class _Cfg:
            PrjDir = "."
            CioNYSKIP = 3
            Drought = _DC()

        monkeypatch.setattr(H, "load_monthly_flow",
                            lambda p: ({(1985, 1): {"ngerimel": 0.3}}, ["ngerimel"]))
        monkeypatch.setattr(H, "_reservoir_source",
                            lambda cfg: (None, _Params(), None))
        thr = _stage_thresholds_by_outlet(_Cfg())
        assert thr["ngerimel"][:3] == pytest.approx((NW, WW, WC))
        assert thr["ngerimel"][3] == "reservoir"


class _Params:
    """full_level_ft(params) 가 자 눈금 만수 23.0 을 주도록 하는 최소 스텁.

    실제와 같은 경로를 타게 한다 — 곡선(MSL 45.0) + datum_offset(-22.0) = 23.0 ft.
    """
    class _Curve:
        @staticmethod
        def storage_to_stage(_m3):
            return 45.0
    curve = _Curve()
    full_m3 = 1.0
    datum_offset_ft = -22.0


class TestFigure:
    def _project(self, tmp_path, *, gauge=True):
        d = tmp_path / "3_swatplus" / "forecast" / "historical_worst"
        d.mkdir(parents=True)
        seasons = ["JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA",
                   "JAS", "ASO", "SON", "OND", "NDJ", "DJF"]
        res = pd.DataFrame({
            "season": seasons, "driest_year": [1998] * 12,
            "precip_mm": np.linspace(130, 860, 12), "substituted": [True] * 12,
            "ngerikiil_flow_m3s": np.linspace(0.02, 0.36, 12),
            "ngerikiil_stage": ["Crisis"] * 3 + ["Watch"] * 6 + ["Normal"] * 3,
            "ngerimel_storage_pct": np.linspace(21, 94, 12),
            "ngerimel_stage": ["Crisis"] * 3 + ["Watch"] * 6 + ["Normal"] * 3,
        })
        if gauge:
            res["ngerimel_water_level_gauge_ft"] = np.linspace(8.3, 22.5, 12)
            res["ngerimel_water_level_gauge_ft_min"] = np.linspace(1.34, 21.1, 12)
        else:
            res["ngerimel_storage_pct_min"] = np.linspace(0.0, 77.0, 12)
        res.to_csv(d / "modeling_results_by_season.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame({"season": seasons, "median_mm": np.linspace(730, 1210, 12)}
                     ).to_csv(d / "driest_year_by_season.csv", index=False,
                              encoding="utf-8-sig")
        return d

    def _cfg(self, tmp_path):
        import swat_py.drought.historical_worst as H

        class _Src:
            type = "reservoir"
            outlets = {4: "ngerimel"}

        class _Str:
            type = "stream"
            outlets = {1: "ngerikiil"}

        class _DC:
            sources = [_Str(), _Src()]
            syear, eyear = 1982, 2023

            @staticmethod
            def threshold_for(gid):
                return (("level_fraction", [95.0, 85.0, 65.0]) if gid == 4
                        else ("fdc_exceedance", [70.0, 90.0, 95.0]))

        class _Cfg:
            PrjDir = str(tmp_path)
            CioNYSKIP = 3
            Drought = _DC()

        H._PATCHED = True
        return _Cfg()

    @pytest.fixture(autouse=True)
    def _stub_flow(self, monkeypatch):
        import swat_py.drought.historical_worst as H
        monkeypatch.setattr(H, "load_monthly_flow", lambda p: (
            {(1985, m): {"ngerikiil": 0.1 * m, "ngerimel": 0.1 * m} for m in range(1, 13)},
            ["ngerikiil", "ngerimel"]))
        monkeypatch.setattr(H, "_reservoir_source", lambda cfg: (None, _Params(), None))

    def test_그림이_생성된다(self, tmp_path):
        self._project(tmp_path)
        out = make_historical_worst_figure(self._cfg(tmp_path))
        assert out is not None and out.is_file() and out.stat().st_size > 0
        assert out.name == "historical_worst_dashboard.png"

    def test_영문판은_별도_파일(self, tmp_path):
        self._project(tmp_path)
        out = make_historical_worst_figure(self._cfg(tmp_path), lang="en")
        assert out.name == "historical_worst_dashboard_en.png"
        assert out.is_file() and out.stat().st_size > 0

    def test_저수량퍼센트만_있어도_그려진다(self, tmp_path):
        """capacity_fraction 사업(수위 열 없음) 하위호환."""
        self._project(tmp_path, gauge=False)
        out = make_historical_worst_figure(self._cfg(tmp_path))
        assert out is not None and out.is_file()

    def test_산출_CSV_가_없으면_None(self, tmp_path):
        (tmp_path / "3_swatplus" / "forecast" / "historical_worst").mkdir(parents=True)
        assert make_historical_worst_figure(self._cfg(tmp_path)) is None

    def test_산출_함수가_그림을_함께_만든다(self):
        """고아 PNG 재발 방지 — build 끝에서 호출되어야 한다."""
        import inspect

        from swat_py.drought.historical_worst import build_historical_worst
        src = inspect.getsource(build_historical_worst)
        assert "make_historical_worst_figure" in src
