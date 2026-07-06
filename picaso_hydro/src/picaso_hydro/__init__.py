"""picaso_hydro — PICASO-Hydro 프로젝트 초기화(스캐폴딩) 패키지.

GitHub 설치 후 빈 프로젝트 폴더에 고정 폴더 구조 + 샘플 config 를 생성한다.

    from picaso_hydro import initialize
    initialize("/data/MyProject")            # 또는 CLI: picaso-hydro-init /data/MyProject
"""
from picaso_hydro.init import FIXED_DIRS, initialize

__version__ = "0.1.0"
__all__ = ["initialize", "FIXED_DIRS", "__version__"]
