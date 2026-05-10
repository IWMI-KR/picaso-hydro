"""
swat_py - Python interface for SWAT and SWAT-Plus hydrological models.

Provides automated weather input generation, model execution, output parsing,
performance metrics, climate change analysis, and probabilistic ensemble forecasting.
"""

__version__ = "0.1.0"
__author__ = "IWMI-KR"

from swat_py.config.env import EnvConfig, load_config
from swat_py.metrics.performance import calc_all as calc_metrics

__all__ = [
    "EnvConfig",
    "load_config",
    "calc_metrics",
]
