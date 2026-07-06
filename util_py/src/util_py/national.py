"""대상 국가 국가단위 DB 일괄 구축 (Stage 1) + 사용자 영역 UTM 클립 (Stage 2, 조건부).

개별 ``util-*`` 명령을 순서대로 한 번에 실행한다.

사전 준비 (둘 중 하나 이상)
  1) ``0_database/gis/admin/country_boundary.csv`` 를 **대상 국가 한 행만** 남기고 편집
  2) (선택) ``0_database/gis/user/boundary-{area}.shp`` 배치
     → 이 shape 가 있으면 다운로드 후 대상 영역을 **UTM 좌표로 변환·클립**(Stage 2)까지 자동 실행

실행 순서 (Stage 1)
  gis-download → era5-download → era5-extract → gsod-download →
  weather-standardize → weather-validate → streamflow-download
그 다음 (Stage 2, 사용자 shape 있을 때만) gis-clip-to-user --all

프로그램:  from util_py import download_national_database
           download_national_database(start_year=2010)
CLI:       util-download-national [--start-year 2010] [--config ...] [옵션]
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


def _picaso_root() -> Path:
    if env := os.environ.get("PICASO_ROOT"):
        return Path(env)
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / "0_database").is_dir():
            return parent
    return cwd


def _user_base_and_pattern(config: Optional[str]) -> Tuple[str, str]:
    """gis/user 루트와 shape 파일명 패턴 — config 있으면 우선, 없으면 PICASO_ROOT 기본."""
    from util_py.config import find_config, load_config
    cfg = None
    if config:
        cfg = load_config(config)
    else:
        found = find_config()
        if found:
            cfg = load_config(found)
    if cfg and getattr(cfg, "gis_user", None) and cfg.gis_user.base_dir:
        return cfg.gis_user.base_dir, cfg.gis_user.filename_pattern
    return str(_picaso_root() / "0_database" / "gis" / "user"), "boundary-{area}.shp"


def _banner(msg: str) -> None:
    print("\n" + "═" * 64)
    print(f"  {msg}")
    print("═" * 64)


def download_national_database(
    config: Optional[str] = None,
    *,
    start_year: int = 2010,
    validate: bool = True,
    streamflow: bool = True,
    clip: bool = True,
    skip: Sequence[str] = (),
    continue_on_error: bool = False,
) -> List[Dict[str, str]]:
    """대상 국가 국가단위 DB 를 일괄 다운로드하고, 사용자 shape 가 있으면 UTM 클립까지 실행.

    Parameters
    ----------
    config           : util_py.yaml 경로 (생략 시 자동 탐색 / 기본값 사용)
    start_year       : ERA5 다운로드 시작 연도 (기본 2010)
    validate         : weather-validate(ERA5 vs 관측 검증) 실행 여부
    streamflow       : streamflow-download(유량 자료) 실행 여부
    clip             : 사용자 shape 존재 시 Stage 2 UTM 클립 실행 여부
    skip             : 건너뛸 단계 이름 목록 (예: ["weather-validate"])
    continue_on_error: True 면 실패해도 다음 단계 진행 (기본 False: 첫 실패 시 중단)

    Returns
    -------
    list of {"step": 단계명, "status": "ok"|"skip"|"rc=N"|"ERROR: ..."} — 실행 요약.
    """
    # 하위 CLI 를 지연 임포트 (패키지 import 사이클·비용 방지). 각 main 은 argv 리스트를 받음.
    from util_py.cli import (
        era5_download,
        era5_extract,
        gis_clip_to_user,
        gis_download,
        gsod_download,
        streamflow_download,
        weather_standardize,
        weather_validate,
    )
    from util_py.gis_user import discover_user_areas

    cbase = ["--config", config] if config else []
    sy = ["--start-year", str(start_year)]
    steps = [
        ("gis-download",        gis_download.main,        cbase),
        ("era5-download",       era5_download.main,       cbase + sy),
        ("era5-extract",        era5_extract.main,        cbase),
        ("gsod-download",       gsod_download.main,       cbase),
        ("weather-standardize", weather_standardize.main, cbase),
    ]
    if validate:
        steps.append(("weather-validate", weather_validate.main, cbase))
    if streamflow:
        steps.append(("streamflow-download", streamflow_download.main, cbase))

    skip = set(skip)
    results: List[Dict[str, str]] = []

    for name, fn, argv in steps:
        if name in skip:
            print(f"[건너뜀] {name}")
            results.append({"step": name, "status": "skip"})
            continue
        _banner(f"[{len(results) + 1}] {name}")
        try:
            rc = fn(argv)
            status = "ok" if rc in (0, None) else f"rc={rc}"
            results.append({"step": name, "status": status})
            if status != "ok" and not continue_on_error:
                print(f"\n✗ {name} 실패({status}) → 중단 (--continue-on-error 로 계속 가능)")
                return results
        except SystemExit as e:                       # argparse 등
            code = e.code if isinstance(e.code, int) else 1
            results.append({"step": name, "status": f"exit={code}"})
            if code != 0 and not continue_on_error:
                print(f"\n✗ {name} 종료코드 {code} → 중단")
                return results
        except Exception as e:                         # 네트워크·인증 등
            results.append({"step": name, "status": f"ERROR: {e}"})
            print(f"\n✗ {name} 예외: {e}")
            if not continue_on_error:
                print("  → 중단 (--continue-on-error 로 계속 가능)")
                return results

    # ── Stage 2 — 사용자 shape 있으면 UTM 클립 ────────────────────────────────
    if clip and "gis-clip-to-user" not in skip:
        user_base, pattern = _user_base_and_pattern(config)
        areas = discover_user_areas(user_base, pattern)
        if areas:
            names = ", ".join(str(a["area"]) for a in areas)
            _banner(f"[Stage 2] gis-clip-to-user — UTM 클립 ({len(areas)} area: {names})")
            try:
                gis_clip_to_user.main(cbase + ["--all"])
                results.append({"step": "gis-clip-to-user", "status": f"ok ({len(areas)} area)"})
            except Exception as e:
                results.append({"step": "gis-clip-to-user", "status": f"ERROR: {e}"})
                print(f"\n✗ gis-clip-to-user 예외: {e}")
        else:
            print(f"\n[Stage 2] 사용자 shape 없음({user_base}) → UTM 클립 건너뜀")
            print("  (대상 영역 클립이 필요하면 gis/user/boundary-{area}.shp 배치 후 재실행)")
            results.append({"step": "gis-clip-to-user", "status": "skip (no user shape)"})

    # ── 요약 ──────────────────────────────────────────────────────────────────
    _banner("일괄 실행 요약")
    for r in results:
        mark = "✓" if r["status"].startswith("ok") else ("—" if "skip" in r["status"] else "✗")
        print(f"  {mark} {r['step']:<22s} {r['status']}")
    print("═" * 64)
    return results
