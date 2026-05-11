"""Dashboard 자료 생성 — 1000 멤버 SWAT 출력 → forecast.json + timeseries.json.

서브 모듈
---------
- aggregate    : 멤버 출력 집계 (월평균 + 분위수)
- json_writers : forecast.json / timeseries.json 작성
- stitch       : warm-up (ERA5) + ensemble 기상 자동 결합
- build        : high-level — 한 함수가 모든 단계 자동
"""
from swat_py.dashboard.aggregate import (
    aggregate_ensemble_monthly,
    compute_terciles,
    load_ensemble_outputs,
)
from swat_py.dashboard.build import build_dashboard_data
from swat_py.dashboard.json_writers import (
    write_forecast_json,
    write_timeseries_json,
)
from swat_py.dashboard.stitch import stitch_weather_files

__all__ = [
    "aggregate_ensemble_monthly",
    "compute_terciles",
    "load_ensemble_outputs",
    "build_dashboard_data",
    "write_forecast_json",
    "write_timeseries_json",
    "stitch_weather_files",
]
