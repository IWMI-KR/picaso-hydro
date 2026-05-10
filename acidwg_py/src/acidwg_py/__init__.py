"""
acidWG — APCC Climate Information Downscaling Weather Generator (Python port)

R 원본 패키지를 Python으로 변환한 버전.
입력 변경 사항:
  - NetCDF 예측 파일 대신 forecast_new.csv의 관측소×월×변수별 AN/NN/BN 확률을 사용
  - 관측소별 일단위 기상 CSV 파일 직접 읽기
  - Output 폴더에 사용자 지정 앙상블 수만큼 일단위 시나리오 CSV 생성
"""

__version__ = "1.0.0"
__author__ = "IWMI-KR"

from acidwg_py.run import acid_run, acid_modeling
from acidwg_py.picaso import build_picaso_forecast_csv, build_all_picaso_forecasts

__all__ = [
    "acid_run",
    "acid_modeling",
    "build_picaso_forecast_csv",
    "build_all_picaso_forecasts",
]
