"""swat_py.tank — 3단 직렬 Sugawara Tank 모형 (집중형 강우-유출) + DDS 검보정.

SWAT+와 동일한 관측소·기상·유량·검보정기간을 공유하며, 관측소별로 독립 검보정하고
SWAT+ 결과와 비교한다. 설정은 yaml `tank:` 블록(config.env._TankCfg).

주요 진입점
- run_tank_calibration(cfg) : 관측소별 Tank 검보정 → 3_swatplus/calibration-tank/
- compare_swat_tank(cfg)    : SWAT vs Tank 비교 → reports/05_모형간_유량비교/
- simulate_tank(...)        : 단일 Tank 시뮬레이션
- compute_pet(df, method, lat) : PET(Hamon/Hargreaves/Priestley-Taylor)
"""
from swat_py.tank.model import (
    DEFAULT_BOUNDS, PARAM_ORDER, TankParams, bounds_from_config, simulate_tank,
)
from swat_py.tank.pet import METHODS as PET_METHODS, compute_pet
from swat_py.tank.forcing import build_forcing
from swat_py.tank.calibrate import run_tank_calibration
from swat_py.tank.compare import compare_swat_tank

__all__ = [
    "TankParams", "simulate_tank", "bounds_from_config",
    "PARAM_ORDER", "DEFAULT_BOUNDS",
    "compute_pet", "PET_METHODS",
    "build_forcing", "run_tank_calibration", "compare_swat_tank",
]
