"""swat_py 테스트용 실데이터 경로 해석 헬퍼.

대부분의 테스트는 합성 데이터로 동작하지만, 일부는 실제 프로젝트 자료
(쿡 관측기상, 팔라우 Ngerimel 저수지)가 있을 때만 돌아가는 통합 테스트다.
그 경로를 소스에 절대경로로 박아두면 다른 PC 에서 무의미해지므로,
**환경변수 → 형제 프로젝트 폴더 자동 탐색 → (없으면) skip** 순으로 해석한다.

환경변수
--------
``PICASO_COOK_ROOT``   쿡 프로젝트 루트 (예: .../2025-APCC_Cook/PICASO-Hydro)
``PICASO_PALAU_ROOT``  팔라우 프로젝트 루트
``PICASO_ROOT``        위 둘이 없을 때 현재 프로젝트 루트로 사용

자동 탐색
---------
이 파일에서 위로 올라가며 ``0_database`` 를 가진 폴더를 현재 프로젝트 루트로 보고,
그 부모 폴더에서 ``*Cook*``/``*Palau*`` 이름의 형제 프로젝트를 찾는다.
찾지 못하면 존재하지 않는 경로를 돌려주므로 각 테스트의 ``skipif`` 가 알아서 건너뛴다.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_MARKER = "0_database"


def _current_project_root() -> Optional[Path]:
    """이 파일 기준 위로 올라가며 0_database 를 가진 폴더."""
    if env := os.environ.get("PICASO_ROOT"):
        p = Path(env)
        if (p / _MARKER).is_dir():
            return p
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / _MARKER).is_dir():
            return parent
    return None


def _sibling_project(keyword: str) -> Optional[Path]:
    """형제 폴더 중 이름에 keyword 가 든 PICASO-Hydro 프로젝트."""
    root = _current_project_root()
    if root is None:
        return None
    if keyword.lower() in root.parent.name.lower() and (root / _MARKER).is_dir():
        return root                      # 현재 프로젝트가 바로 그 대상
    grandparent = root.parent.parent     # 예: .../2025-APCC_Cook/PICASO-Hydro → 그 위
    if not grandparent.is_dir():
        return None
    for cand in sorted(grandparent.iterdir()):
        if not cand.is_dir() or keyword.lower() not in cand.name.lower():
            continue
        proj = cand / root.name          # 같은 이름의 프로젝트 폴더 (PICASO-Hydro)
        if (proj / _MARKER).is_dir():
            return proj
    return None


def project_root(keyword: str, env_var: str) -> Optional[Path]:
    """``env_var`` → 형제 폴더 탐색 순으로 프로젝트 루트를 찾는다."""
    if env := os.environ.get(env_var):
        p = Path(env)
        return p if p.is_dir() else None
    return _sibling_project(keyword)


def data_path(keyword: str, env_var: str, rel: str) -> Path:
    """프로젝트 루트 하위 ``rel`` 경로. 루트를 못 찾으면 존재하지 않는 경로를 돌려준다.

    호출 측의 ``@pytest.mark.skipif(not path.is_file(), ...)`` 가 그대로 동작하도록
    예외를 던지지 않는다.
    """
    root = project_root(keyword, env_var)
    if root is None:
        return Path("__no_project_root__") / rel
    return root / rel


def cook_path(rel: str) -> Path:
    """쿡 프로젝트 자료 경로 (``PICASO_COOK_ROOT``)."""
    return data_path("cook", "PICASO_COOK_ROOT", rel)


def palau_path(rel: str) -> Path:
    """팔라우 프로젝트 자료 경로 (``PICASO_PALAU_ROOT``)."""
    return data_path("palau", "PICASO_PALAU_ROOT", rel)
