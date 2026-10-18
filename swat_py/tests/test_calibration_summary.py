"""보정 요약·그림 유틸 — 순수함수 검증."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_plot_scatter_top_n_empty_overlap(tmp_path):
    """관측·모의 공통 자료가 없어도 예외 없이 그림을 남긴다.

    보정 설정상 라우팅이 어긋난 관측점(n=0)이 하나라도 있으면 여기서 ValueError 가
    나 보정 전체가 요약표 저장 직후 중단됐다(팔라우 ngerikiil, 2026-10-18).
    """
    import numpy as np
    from swat_py.calibration.summary import plot_scatter_top_n
    dates = np.array(["2018-01-01", "2018-01-02"], dtype="datetime64[ns]")
    obs = np.array([np.nan, np.nan])            # 유효 관측 0건
    sims = {1: np.array([1.0, 2.0])}
    out = tmp_path / "scatter.png"
    p = plot_scatter_top_n(dates, obs, sims, out, title="empty")
    assert Path(p).is_file()
