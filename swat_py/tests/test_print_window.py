"""print.prt 출력창(yrc) 동기화 — 일단위 출력이 비는 결함의 회귀 테스트.

**무엇이 잘못되었던가** (2026-11-03)
    예측·평년 실행은 ``time.sim`` 을 대상 기간으로 옮기면서 ``print.prt`` 의
    ``nyskip`` 만 고치고 **출력창(day_start/yrc_start/day_end/yrc_end)** 은
    master(검보정 기간)의 값을 그대로 두었다.

    SWAT+ 는 ``yrc_start`` 보다 이른 해의 **일단위** 출력을 쓰지 않는다. 팔라우
    master 는 창이 2015~2023 이어서 2013·2014년 예측에서 ``reservoir_day.txt`` 가
    머리글만 남은 빈 파일이 되었고, 저수지 수원이 통째로 빠져 24기간이 실패했다.
    평년 실행도 같은 이유로 저수지 평년을 1985~2023 이 아니라 2015~2023 의
    9년만으로 계산했다(조용한 오류 — 숫자는 나왔다).

    월단위 출력은 이 창을 무시하므로(실측 확인) 하천 월유량만 보던 경로에서는
    드러나지 않았다. 쿡 master 는 창이 ``0 0 0 0``(제한 없음)이라 영향이 없었다.

실측 근거 (SWAT+ 61.0.2, 팔라우 calibrated, 같은 모델·같은 time.sim 2010~2013)
    창 2015~2023 → reservoir_day.txt 0행 / 창 2010~2013 → 180행.
    창 2015~2023 + time.sim 2023~2026 → 334행(끝연도는 강제되지 않음).
"""
from __future__ import annotations

import pytest

from swat_py.io.config_swat_plus import print_window_line

# 팔라우 calibrated master 의 실제 자료행
PALAU_MASTER = "3           1          2015      365       2023        1"


def _f(line: str) -> list[str]:
    return line.split()


class TestPrintWindowLine:
    def test_옛_동작은_창을_그대로_남긴다(self):
        """고치기 전 코드와 동일한 조작 — 창이 검보정 기간에 머문다(결함 재현)."""
        toks = _f(PALAU_MASTER)
        toks[0] = "3"
        assert toks[2] == "2015", "결함 재현: 출력창 시작이 예측연도로 옮겨지지 않는다"

    def test_출력창이_모의기간으로_옮겨진다(self):
        out = _f(print_window_line(PALAU_MASTER, nyskip=3,
                                   yrc_start=2010, yrc_end=2013))
        assert out == ["3", "1", "2010", "366", "2013", "1"]

    def test_2013년_예측에서_창시작이_예측연도보다_뒤가_아니다(self):
        """핵심 — 창 시작연도 ≤ 출력연도. 아니면 일단위 출력이 빈다."""
        fyear, nyskip = 2013, 3
        out = _f(print_window_line(PALAU_MASTER, nyskip=nyskip,
                                   yrc_start=fyear - nyskip, yrc_end=fyear))
        assert int(out[2]) <= fyear

    def test_nyskip_이_반영된다(self):
        out = _f(print_window_line(PALAU_MASTER, nyskip=5,
                                   yrc_start=2000, yrc_end=2005))
        assert out[0] == "5"

    def test_interval_은_보존된다(self):
        out = _f(print_window_line(PALAU_MASTER, nyskip=3,
                                   yrc_start=2010, yrc_end=2013))
        assert out[5] == "1", "interval(마지막 토큰)은 건드리지 않는다"

    def test_day_end_은_366_이라_윤년_마지막날이_빠지지_않는다(self):
        """창 끝을 365 로 두면 윤년 12/31(366일)이 잘린다 — OND·NDJ 예측에 영향."""
        out = _f(print_window_line(PALAU_MASTER, nyskip=3,
                                   yrc_start=2010, yrc_end=2012))
        assert int(out[3]) >= 366

    def test_day_start_과_day_end_를_지정할_수_있다(self):
        out = _f(print_window_line(PALAU_MASTER, nyskip=3, yrc_start=2010,
                                   yrc_end=2013, day_start=1, day_end=180))
        assert out[1] == "1" and out[3] == "180"

    def test_창_없는_짧은_행은_nyskip_만_고친다(self):
        """토큰이 5개 미만인 비정형 행에서 IndexError 로 죽지 않는다."""
        out = _f(print_window_line("3  1", nyskip=7, yrc_start=2010, yrc_end=2013))
        assert out[0] == "7"

    def test_빈_줄은_그대로_돌려준다(self):
        assert print_window_line("   ", nyskip=3, yrc_start=2010, yrc_end=2013) == "   "

    def test_쿡처럼_제한없는_창도_모의기간으로_채워진다(self):
        """창이 0 0 0 0 이면 원래 제한이 없지만, 명시해도 동작은 같다."""
        out = _f(print_window_line("3  0  0  0  0  1", nyskip=3,
                                   yrc_start=1982, yrc_end=2023))
        assert out[2] == "1982" and out[4] == "2023"


class TestCallSitesUseIt:
    """세 실행 경로(예측 base·평년·역사최악)가 모두 창을 동기화하는지."""

    @pytest.mark.parametrize("module,func", [
        ("swat_py.drought.dashboard_data", "prepare_base"),
        ("swat_py.drought.climatology_run", None),
        ("swat_py.drought.historical_worst", None),
    ])
    def test_헬퍼를_불러쓴다(self, module, func):
        import importlib
        m = importlib.import_module(module)
        assert hasattr(m, "print_window_line"), (
            f"{module} 이 print_window_line 을 import 하지 않는다 — "
            "출력창을 고치지 않으면 일단위 출력이 빈다")
        if func:
            assert callable(getattr(m, func))

    def test_예측_base_가_창_헬퍼를_쓴다(self):
        """prepare_base 가 창 계산을 forecast_print_window_line 에 맡기는지.

        2026-11-19 변경: 창을 웜업 시작이 아니라 **예측 첫 달 1일**로 맞춘다
        (일단위 출력을 예측월로 좁혀 용량·시간을 줄이기 위해). 옛 테스트는
        소스에 ``yrc_start=start_yr`` 문자열이 있는지 봤는데, 그 방식은 창이
        예측월을 덮는지를 전혀 보증하지 못했다 — 아래 TestForecastWindow 가
        **동작으로** 검증한다.
        """
        import inspect

        from swat_py.drought import dashboard_data
        src = inspect.getsource(dashboard_data.prepare_base).replace(" ", "")
        assert "forecast_print_window_line(" in src

    def test_평년이_창을_평년_전기간으로_넘긴다(self):
        import inspect

        from swat_py.drought import climatology_run
        src = inspect.getsource(climatology_run)
        flat = src.replace(" ", "").replace("\n", "")
        assert "print_window_line(" in flat
        assert "yrc_start=syear" in flat and "yrc_end=eyear" in flat


class TestForecastWindow:
    """예측 출력창이 **예측 전 기간을 덮는지** — 일단위 출력이 비면 저수지가 빠진다.

    창을 좁히는 최적화(2026-11-19)가 어느 계절에서도 하루라도 잘라먹지 않음을
    보증한다. 특히 해를 넘는 계절(NDJ·DJF)과 윤년 2월이 위험 구간이다.
    """

    @pytest.mark.parametrize("fyear,months", [
        (2016, [4, 5, 6]),        # 같은 해
        (2016, [11, 12, 1]),      # 해를 넘는다
        (2019, [12, 1, 2]),       # 해를 넘고 끝월이 윤년 2월(2020-02-29)
        (2016, [1, 2, 3]),        # 연초 — 창 시작이 1월 1일
        (2015, [10, 11, 12]),     # 연말 — 창 끝이 12월 31일
    ])
    def test_창이_예측_첫날과_끝날을_정확히_덮는다(self, fyear, months):
        import pandas as pd

        from swat_py.drought.dashboard_data import forecast_print_window_line
        from swat_py.drought.season import period_end, period_ym

        out = _f(forecast_print_window_line(PALAU_MASTER, nyskip=3,
                                            fyear=fyear, months=months))
        d0 = pd.Timestamp(*period_ym(fyear, months)[0], 1)
        d1 = period_end(fyear, months)
        assert int(out[1]) == d0.dayofyear, "창 시작일이 예측 첫날이 아니다"
        assert int(out[2]) == d0.year, "창 시작연도가 예측 첫 달의 해가 아니다"
        assert int(out[3]) == d1.dayofyear, "창 끝일이 예측 끝날이 아니다"
        assert int(out[4]) == d1.year, "창 끝연도가 예측 끝 달의 해가 아니다"

    @pytest.mark.parametrize("fyear,months", [
        (2013, [4, 5, 6]), (2013, [11, 12, 1]), (2026, [1, 2, 3]),
    ])
    def test_창시작이_예측시작보다_뒤가_아니다(self, fyear, months):
        """2026-11-03 결함의 핵심 조건 — 뒤로 가면 일단위 출력이 통째로 빈다."""
        import pandas as pd

        from swat_py.drought.dashboard_data import forecast_print_window_line
        from swat_py.drought.season import period_ym

        out = _f(forecast_print_window_line(PALAU_MASTER, nyskip=3,
                                            fyear=fyear, months=months))
        d0 = pd.Timestamp(*period_ym(fyear, months)[0], 1)
        assert (int(out[2]), int(out[1])) <= (d0.year, d0.dayofyear)

    def test_윤년_2월29일이_창에_들어온다(self):
        """옛 창은 day_end=366 로 넉넉히 뒀다. 좁힌 창이 윤달을 자르면 안 된다."""
        from swat_py.drought.dashboard_data import forecast_print_window_line

        out = _f(forecast_print_window_line(PALAU_MASTER, nyskip=3,
                                            fyear=2019, months=[12, 1, 2]))
        assert (int(out[4]), int(out[3])) == (2020, 60), "2020-02-29 = 연중 60일"
