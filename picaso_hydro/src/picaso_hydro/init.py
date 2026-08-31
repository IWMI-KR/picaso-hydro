"""PICASO-Hydro 프로젝트 초기화 — 고정 폴더 구조 + 샘플 config 생성.

GitHub 에서 패키지를 설치한 뒤, 빈 프로젝트 폴더에 대해 이 함수를 호출하면
picaso-hydro 파이프라인(util_py→acidwg_py→swat_py) 구동에 필요한 **고정 폴더 구조**와
초기 파일(샘플 config 3종 + 샘플 country_boundary.csv)을 생성한다.

프로그램:  from picaso_hydro import initialize; initialize("/data/MyProject")
CLI:       picaso-hydro-init /data/MyProject
           python -m picaso_hydro.init /data/MyProject [--force]

생성물
------
    config/
      picaso-hydro.yaml  swat_py.yaml  acidwg_py.yaml     ← 샘플 config 3종
      util_py.yaml                                       ← util_py 패키지 템플릿에서 생성
    0_database/gis/admin/country_boundary.csv             ← 샘플 국가 경계(대상 국가로 교체)
    0_database/ …  1_acidwg/ …  2_qswat/  3_swatplus/ …  4_drought_risk/ …  reports/
"""
from __future__ import annotations

import argparse
import shutil
from importlib import resources
from pathlib import Path
from typing import List

# ── 고정 폴더 구조 ────────────────────────────────────────────────────────────
#  파이프라인이 읽고/쓰는 표준 디렉터리. 초기화 시 모두 생성(입력 폴더는 비어 있음).
FIXED_DIRS: List[str] = [
    "config",
    # 0_database — 원자료·표준화 입력 (util_py 수집 대상)
    "0_database/gis/admin", "0_database/gis/dem", "0_database/gis/soil",
    "0_database/gis/landuse", "0_database/gis/basin", "0_database/gis/river",
    "0_database/gis/user", "0_database/gis/era5", "0_database/gis/gsod",
    "0_database/era5/nc_hourly", "0_database/era5/grid_hourly",
    "0_database/era5/grid_daily", "0_database/era5/grid_hourly_std",
    "0_database/era5/grid_daily_std",
    "0_database/gsod/daily", "0_database/gsod/daily_std",
    "0_database/obs/weather", "0_database/obs/flow", "0_database/obs/tn", "0_database/obs/tp",
    "0_database/picaso/prec", "0_database/picaso/t2m",
    "0_database/cmip6/nc_daily", "0_database/cmip6/downscaled",
    "0_database/analysis",
    # 1_acidwg — 앙상블 상세화 (acidwg_py). forecast/{year}_{season} 통합 레이아웃
    "1_acidwg/picaso", "1_acidwg/forecast", "1_acidwg/cache",
    # 2_qswat — QSWAT+ 모델 DB (QGIS 산출)
    "2_qswat",
    # 3_swatplus — SWAT+ 모델 (swat_py)
    "3_swatplus/default", "3_swatplus/calibrated", "3_swatplus/forecast",
    # 4_drought_risk — 가뭄위험 대시보드 (swat_py.drought)
    "4_drought_risk/climatology", "4_drought_risk/forecast",
    # reports — 보고서·산출물
    "reports",
]

_CONFIG_FILES = ["picaso-hydro.yaml", "swat_py.yaml", "acidwg_py.yaml"]

#: util_py.yaml 은 util_py 패키지가 정본 템플릿을 갖고 있으므로 복사본을 두지 않고
#: 설치된 util_py 에서 직접 읽어 생성한다(사본이 갈라지는 것을 막는다).
_UTIL_PY_CONFIG = "util_py.yaml"
_BOUNDARY_REL = "0_database/gis/admin/country_boundary.csv"
_ROOT_PLACEHOLDER = "__PROJECT_ROOT__"


def _templates():
    """번들된 templates 디렉터리 (설치 위치 무관, importlib.resources)."""
    return resources.files("picaso_hydro") / "templates"


def _write_config(name: str, dest: Path, project_root: Path, *, force: bool) -> str:
    """샘플 config 1개를 dest 로 복사. picaso-hydro.yaml 은 root 플레이스홀더 치환."""
    if dest.exists() and not force:
        return f"config/{name}  (건너뜀: 이미 존재)"
    text = (_templates() / "config" / name).read_text(encoding="utf-8")
    if _ROOT_PLACEHOLDER in text:
        text = text.replace(_ROOT_PLACEHOLDER, project_root.as_posix())
    dest.write_text(text, encoding="utf-8")
    return f"config/{name}  ✓"


def _write_util_py_config(dest: Path, project_root: Path, *, force: bool) -> str:
    """``config/util_py.yaml`` 을 util_py 패키지의 정본 템플릿에서 생성한다.

    ``project.root`` 를 초기화 경로로 확정해 두어, 사용자가 손대지 않아도
    모든 경로가 곧바로 맞도록 한다. util_py 가 아직 설치돼 있지 않으면 건너뛴다
    (그 경우에도 util_py 는 자신의 패키지 템플릿으로 동작한다).
    """
    if dest.exists() and not force:
        return f"config/{_UTIL_PY_CONFIG}  (건너뜀: 이미 존재)"
    try:
        from util_py.config import PACKAGE_TEMPLATE
    except Exception:
        return (f"config/{_UTIL_PY_CONFIG}  (건너뜀: util_py 미설치 — "
                f"설치 후 picaso-hydro-init 재실행 시 생성)")
    text = Path(PACKAGE_TEMPLATE).read_text(encoding="utf-8")
    text = text.replace('  root: "${env:PICASO_ROOT}"',
                        f'  root: "${{env:PICASO_ROOT:{project_root.as_posix()}}}"')
    dest.write_text(text, encoding="utf-8")
    return f"config/{_UTIL_PY_CONFIG}  ✓"


def initialize(project_root, *, force: bool = False) -> Path:
    """빈 프로젝트 폴더에 picaso-hydro 고정 폴더 구조 + 초기 파일을 생성한다.

    Parameters
    ----------
    project_root : str | Path
        프로젝트 루트(없으면 생성). 이 경로가 곧 PICASO_ROOT 가 된다.
    force : bool
        True 면 기존 config/country_boundary.csv 를 덮어씀(기본 False: 보존).

    Returns
    -------
    Path  생성/확인된 프로젝트 루트(절대경로).
    """
    root = Path(project_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  PICASO-Hydro 프로젝트 초기화")
    print("=" * 64)
    print(f"  프로젝트 루트 : {root}")
    print("=" * 64)

    # ① 고정 폴더 구조
    for rel in FIXED_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    print(f"  [폴더] {len(FIXED_DIRS)}개 고정 디렉터리 생성/확인")

    # ② 샘플 config 3종
    cfg_dir = root / "config"
    for name in _CONFIG_FILES:
        print("  [config] " + _write_config(name, cfg_dir / name, root, force=force))
    print("  [config] " + _write_util_py_config(
        cfg_dir / _UTIL_PY_CONFIG, root, force=force))

    # ③ 샘플 country_boundary.csv
    bnd = root / _BOUNDARY_REL
    if bnd.exists() and not force:
        print(f"  [경계] {_BOUNDARY_REL}  (건너뜀: 이미 존재)")
    else:
        shutil.copyfile(str(_templates() / "country_boundary.csv"), bnd)
        print(f"  [경계] {_BOUNDARY_REL}  ✓ (샘플: 대상 국가로 교체 필요)")

    print("=" * 64)
    print("  완료. 다음 단계:")
    print(f"    1) {_BOUNDARY_REL} 를 대상 국가 경계(NAME/ISO3/ISO2/bbox)로 교체")
    print("       — config/*.yaml 은 그대로 두어도 동작합니다(경로는 이미 이 폴더 기준).")
    print("    2) util-gis-download → util-era5-download … 로 0_database 채우기")
    print()
    print("  참고")
    print(f"    · PICASO_ROOT 를 지정하지 않아도 이 폴더가 자동 인식됩니다"
          f" (다른 위치에서 실행하려면 set PICASO_ROOT={root}).")
    print("    · config/util_py.yaml 의 region.utc_offset 은 null(경도 기반 자동 추정)입니다.")
    print("      법정 표준시가 경도 시간대와 다른 지역(예: 쿡 아일랜드 −10)은 직접 지정하세요.")
    print("=" * 64)
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="picaso-hydro-init",
        description="PICASO-Hydro 프로젝트 고정 폴더 구조 + 샘플 config 초기화")
    ap.add_argument("path", nargs="?", default=".",
                    help="프로젝트 루트 경로 (기본: 현재 폴더)")
    ap.add_argument("--force", action="store_true",
                    help="기존 config/country_boundary.csv 덮어쓰기 (기본: 보존)")
    args = ap.parse_args(argv)
    initialize(args.path, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
