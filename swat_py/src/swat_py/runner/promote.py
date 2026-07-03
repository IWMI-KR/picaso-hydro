"""QSWAT+ Default → 검보정 마스터(3_swatplus/default) 승격(promote) 헬퍼.

반자동 워크플로우
-----------------
QSWAT+/SWAT+ Editor 로 모델을 확정한 뒤, 그 ``Scenarios/Default/TxtInOut`` 을
검보정 마스터(``project.output.default`` = 보통 ``$(root)/3_swatplus/default``)로
**한 번 복사·동결**한다.  이후 자동 검보정은 이 동결 마스터를 반복 복제해 구동하므로
QSWAT+ 작업 폴더와 분리되고(재실행에 영향 없음), 복제가 가볍고 재현 가능해진다.

- 복사 자체는 자동(한 명령), 시점은 사용자가 통제 → "반자동".
- 기본적으로 **SWAT+ 출력 산출물**(*_day/_mon/_yr/_aa.txt, *.out, fort.*, 실행 플래그)은
  제외해 입력 위주의 lean 마스터를 만든다. 작동 ``SWAT-Plus.exe`` 는 보존한다.

CLI
---
    python -m swat_py.runner.promote            # config/swat_py.yaml 기준 자동
    python -m swat_py.runner.promote --source <QSWAT+ TxtInOut> --dest <마스터>
    python -m swat_py.runner.promote --dry-run  # 복사/제외 목록만 출력

연관: :func:`swat_py.calibration.auto.run_auto_calibration` (마스터=cfg.DefaultDir).
"""

from __future__ import annotations

import argparse
import fnmatch
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

# ── SWAT+ 출력 산출물 패턴 (마스터에서 제외) ──────────────────────────────────
#  입력 파일과 겹치지 않는, 잘 알려진 SWAT+ 출력·로그·스크래치만 보수적으로 제외.
SWAT_PLUS_OUTPUT_GLOBS: Sequence[str] = (
    "*_day.txt",  # 일 시계열 출력 (channel_sd_day, basin_wb_day, ...)
    "*_mon.txt",  # 월 출력
    "*_yr.txt",  # 연 출력
    "*_aa.txt",  # 다년 평균 출력
    "*.out",  # 로그/IPEAT/checker/diagnostics/simulation.out ...
    "fort.*",  # Fortran 스크래치
    "*.fin",  # 실행 완료 플래그 (success.fin ...)
    "*.rdy",  # pslave 플래그
    "*.bak_*",  # 백업본 (예: SWAT-Plus.exe.bak_rev60.5.4)
    "p###.##",  # SWAT+ 스크래치
)


def _is_output(name: str, globs: Sequence[str]) -> bool:
    lname = name.lower()
    return any(fnmatch.fnmatch(lname, g.lower()) for g in globs)


def promote_default(
    source: Path,
    dest: Path,
    *,
    strip_outputs: bool = True,
    output_globs: Sequence[str] = SWAT_PLUS_OUTPUT_GLOBS,
    dry_run: bool = False,
) -> Dict[str, object]:
    """*source* (QSWAT+ TxtInOut) 를 *dest* (검보정 마스터) 로 승격 복사.

    Parameters
    ----------
    source        : QSWAT+ ``Scenarios/Default/TxtInOut`` 폴더.
    dest          : 검보정 마스터 폴더 (예: ``3_swatplus/default``). 존재하면 **덮어씀**.
    strip_outputs : True 면 SWAT+ 출력 산출물(*_day.txt 등)을 제외하고 입력만 복사.
    output_globs  : 제외 패턴 (기본 :data:`SWAT_PLUS_OUTPUT_GLOBS`).
    dry_run       : True 면 실제 복사 없이 복사/제외 목록만 산출.

    Returns
    -------
    dict — {copied, skipped, removed, dest, dry_run} (copied/skipped 는 파일명 리스트).

    Raises
    ------
    FileNotFoundError : source 가 없거나 폴더가 아님.
    ValueError        : dest 가 source 와 같거나 그 하위 경로 (자기복사 방지).
    """
    source = Path(source).resolve()
    dest = Path(dest).resolve()

    if not source.is_dir():
        raise FileNotFoundError(f"source TxtInOut 가 없음: {source}")
    if not any(source.iterdir()):
        raise FileNotFoundError(f"source TxtInOut 가 비어 있음: {source}")
    if dest == source or source in dest.parents or dest in source.parents:
        raise ValueError(
            f"dest 가 source 와 겹칩니다 (자기복사 방지).\n  source={source}\n  dest={dest}"
        )

    copied: List[str] = []
    skipped: List[str] = []
    for src in sorted(source.iterdir()):
        if not src.is_file():
            skipped.append(src.name + "/ (하위폴더 제외)")
            continue
        if strip_outputs and _is_output(src.name, output_globs):
            skipped.append(src.name)
            continue
        copied.append(src.name)

    # 기존 dest 정리 (사용자가 승격을 명시적으로 요청 → 덮어쓰기)
    removed = 0
    if dest.exists():
        removed = sum(1 for _ in dest.rglob("*") if _.is_file())

    if not dry_run:
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        for name in copied:
            shutil.copy2(source / name, dest / name)

    return {
        "copied": copied,
        "skipped": skipped,
        "removed": removed,
        "dest": str(dest),
        "source": str(source),
        "dry_run": dry_run,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="swat-promote-default",
        description="QSWAT+ Default TxtInOut → 검보정 마스터(3_swatplus/default) 승격",
    )
    p.add_argument(
        "--config",
        default="config/swat_py.yaml",
        help="swat_py.yaml 경로 (source/dest 미지정 시 참조)",
    )
    p.add_argument(
        "--source", default=None, help="QSWAT+ TxtInOut (미지정 시 yaml project.qswat_txtinout)"
    )
    p.add_argument(
        "--dest",
        default=None,
        help="검보정 마스터 (미지정 시 yaml project.output.default = cfg.DefaultDir)",
    )
    p.add_argument(
        "--keep-outputs", action="store_true", help="SWAT+ 출력 산출물도 함께 복사 (기본: 제외)"
    )
    p.add_argument("--dry-run", action="store_true", help="실제 복사 없이 복사/제외 목록만 출력")
    p.add_argument("--yes", "-y", action="store_true", help="dest 덮어쓰기 확인 프롬프트 생략")
    args = p.parse_args(argv)

    source = args.source
    dest = args.dest
    if source is None or dest is None:
        from swat_py.config import load_config

        cfg = load_config(args.config)
        if source is None:
            source = cfg.QswatTxtInOut
            if not source:
                p.error("source 미지정 & yaml 에 project.qswat_txtinout 없음 → --source 지정 필요")
        if dest is None:
            dest = cfg.DefaultDir
            if not dest:
                p.error("dest 미지정 & yaml 에서 DefaultDir 산출 불가 → --dest 지정 필요")

    src_path, dst_path = Path(source), Path(dest)
    print("=" * 64)
    print("  Promote — QSWAT+ Default → 검보정 마스터")
    print("=" * 64)
    print(f"  source : {src_path}")
    print(f"  dest   : {dst_path}")
    print(f"  outputs: {'포함' if args.keep_outputs else '제외 (입력 위주 lean 마스터)'}")

    # 미리보기 (항상 dry-run 계산)
    try:
        preview = promote_default(
            src_path, dst_path, strip_outputs=not args.keep_outputs, dry_run=True
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"\n[오류] {e}", file=sys.stderr)
        return 2

    print(f"  복사 예정 : {len(preview['copied'])} 파일")
    print(f"  제외 예정 : {len(preview['skipped'])} 파일 (출력·스크래치·하위폴더)")
    if preview["removed"]:
        print(f"  ⚠ dest 기존 {preview['removed']} 파일은 덮어쓰기로 삭제됩니다.")

    if args.dry_run:
        print("\n[dry-run] 실제 복사 없음. 제외 목록 일부:")
        for n in preview["skipped"][:15]:
            print(f"    - {n}")
        return 0

    if not args.yes and preview["removed"]:
        try:
            ans = input("\n  dest 를 덮어쓰고 진행할까요? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("  취소됨.")
            return 1

    result = promote_default(src_path, dst_path, strip_outputs=not args.keep_outputs, dry_run=False)
    print(f"\n  ✔ 완료: {len(result['copied'])} 파일 복사 → {result['dest']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
