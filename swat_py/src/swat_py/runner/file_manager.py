"""File management helpers for SWAT input/output staging.

Mirrors util.R :: Swat.Copy.Input.Output.Files() and the inline
file.copy / file.rename calls throughout calibration-plus.R and
cchange_swat_plus.R.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import List, Optional

# SWAT 2012 standard output filenames
_SWAT2012_OUTPUTS = [
    "output.hru",
    "output.sub",
    "output.rch",
    "output.wtr",
    "output.std",
    "output.sed",
    "output.rsv",
]

# SWAT 2012 standard weather input filenames
_SWAT2012_WEATHER = ["pcp1.pcp", "tmp1.tmp", "hmd.hmd", "wnd.wnd", "slr.slr"]


def setup_run_dir(run_dir: Path) -> None:
    """Create *run_dir* and all parents if they do not exist."""
    Path(run_dir).mkdir(parents=True, exist_ok=True)


def _swat_exe_candidates(executable: str) -> List[str]:
    """실행파일 후보 이름 — 설정값 + OS 기본(swatplus[.exe]). 중복 제거·순서 보존."""
    names = [str(executable)] if executable else []
    if platform.system().lower().startswith("win"):
        names += ["swatplus.exe", "SWAT-Plus.exe", "swatplus"]
    else:
        names += ["swatplus", "SWAT-Plus", "swatplus.exe"]
    seen, out = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def resolve_swat_exe(executable: str, model_dir, *, auto_fetch: bool = True,
                     fetch_dirs=None, version: Optional[str] = None) -> Path:
    """SWAT+ 실행파일 **원본 경로** 해석 — OS 자동대응 + 모델 버전 일치 + 자동 다운로드.

    모델 TxtInOut(file.cio)에서 요구 버전(예 61.0.2)을 감지해, 모델폴더의 실행파일이
    그 버전과 다르면(입력파일 형식 불일치로 SIGSEGV 위험) **맞는 버전을 재다운로드**한다.

    탐색: ① cfg.Executable/OS 기본 이름의 **절대경로** → ② **모델폴더**(버전 마커 일치 시)
    → ③ **PATH** → ④ 미확보 시 공식 GitHub Releases 에서 요구 버전 다운로드(fetch_dirs).
    version 미지정 시 모델에서 자동 감지. auto_fetch 는 PICASO_NO_AUTOFETCH 로 끌 수 있다.
    """
    from swat_py.runner.fetch_exe import (
        detect_swat_version,
        fetch_swat_executable,
        read_version_marker,
    )
    want = version or detect_swat_version(model_dir)      # 모델이 요구하는 rev
    cands = _swat_exe_candidates(executable)

    # ① 절대경로 지정(사용자 신뢰)
    for name in cands:
        p = Path(name)
        if p.is_absolute() and p.is_file():
            return p

    # ② 모델폴더 내 바이너리 — 버전 마커가 모델 요구와 일치할 때만 사용
    marker = read_version_marker(model_dir)
    stale = False
    for name in cands:
        cand = Path(model_dir) / name
        if cand.is_file():
            if want is None or marker == want:
                return cand
            stale = True
            print(f"[SWAT+] 실행파일 버전 불일치(보유: rev {marker or '미상'}, "
                  f"모델 요구: rev {want}) → 올바른 버전 재다운로드")
            break

    # ③ PATH (모델폴더에 없고, 버전 불일치가 아닐 때만 — PATH 바이너리 버전은 신뢰)
    if not stale:
        for name in cands:
            if not Path(name).is_absolute():
                found = shutil.which(name)
                if found:
                    return Path(found)

    # ④ 자동 다운로드(모델 요구 버전, OS 감지)
    if auto_fetch and not os.environ.get("PICASO_NO_AUTOFETCH"):
        try:
            dirs = [Path(d) for d in (fetch_dirs or [model_dir]) if d]
            ver = want or "latest"
            print(f"[SWAT+] 실행파일 확보 → 공식 GitHub Releases 에서 다운로드(rev {ver}) …")
            name = fetch_swat_executable(dirs, version=ver)
            for d in [Path(model_dir), *dirs]:
                if (d / name).is_file():
                    return d / name
        except Exception as e:                       # 네트워크·다운로드 실패
            print(f"[SWAT+] 자동 다운로드 실패: {e}")

    raise SystemExit(
        f"SWAT+ 실행파일을 확보할 수 없습니다 "
        f"(모델폴더: {model_dir}, 요구 rev: {want or '미상'}).\n"
        f"  · 자동 다운로드 실패 시(인터넷 없음 등) 수동 설치:\n"
        f"        python -m swat_py.runner.fetch_exe --version {want or '61.0.2'} "
        f"--project <프로젝트루트>\n"
        f"    또는 해당 버전 바이너리를 모델폴더에 두고 config/swat_py.yaml model.executable 지정.")


def copy_input_files(
    common_dir: Path,
    input_dir: Path,
    scenario_dir: Path,
    swat_dir: Path,
) -> None:
    """Copy common, model-input, and weather input files into *swat_dir*.

    Mirrors Swat.Copy.Input.Output.Files(..., type="Input").
    """
    swat_dir = Path(swat_dir)

    # Copy all files from input_dir
    for src in Path(input_dir).iterdir():
        if src.is_file():
            shutil.copy2(src, swat_dir / src.name)

    # Copy weather input files from scenario_dir
    for fname in _SWAT2012_WEATHER:
        src = Path(scenario_dir) / fname
        if src.exists():
            shutil.copy2(src, swat_dir / fname)


def rename_outputs(
    run_dir: Path,
    out_dir: Path,
    output_types: List[str],
    scenario_name: str,
    model: str = "swat_plus",
) -> None:
    """Move/rename SWAT output files after a run.

    For SWAT-Plus:
        channel_sd_day.txt  →  <out_dir>/channel_sd_day-{scenario_name}.txt

    For SWAT 2012:
        output.rch          →  <out_dir>/output-{scenario_name}.rch

    Parameters
    ----------
    run_dir:
        Directory where SWAT was run.
    out_dir:
        Destination directory for renamed output files.
    output_types:
        SWAT-Plus: list of channel type identifiers, e.g. ``["sd"]``.
        SWAT 2012: list of extension identifiers, e.g. ``["rch", "sub"]``.
    scenario_name:
        Tag appended to the output filename (e.g. ``"Calibration"``).
    model:
        ``"swat_plus"`` or ``"swat2012"``.
    """
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if model == "swat_plus":
        for otype in output_types:
            src = run_dir / f"channel_{otype}_day.txt"
            dst = out_dir / f"channel_{otype}_day-{scenario_name}.txt"
            if src.exists():
                shutil.move(str(src), dst)
    else:  # swat2012
        for otype in output_types:
            src = run_dir / f"output.{otype}"
            dst = out_dir / f"output-{scenario_name}.{otype}"
            if src.exists():
                shutil.move(str(src), dst)

# ── SWAT+ 출력물 판별 — TxtInOut 복사량 줄이기 ────────────────────────────────
#  검보정 master(calibrated/)에는 이전 실행의 출력 파일이 남아 있다. 쿡 기준
#  194개 1.19GB 중 **출력물 64개가 1.18GB**(99%)이고, 실제 입력은 130개 19.5MB 뿐이다.
#  예측 앙상블은 멤버마다 TxtInOut 을 통째로 복사하므로, 거르지 않으면
#  1,000멤버 한 기간에 1.17TB 를 복사한다(디스크 포화 → SWAT+ 가 2개만 동시 실행).
#  출력물은 SWAT+ 가 실행하며 다시 만들므로 복사할 이유가 없다.

#: SWAT+ 출력 파일 접미어 (objects 출력: {object}_{day|mon|yr|aa}.txt)
SWAT_OUTPUT_SUFFIXES = ("_day.txt", "_mon.txt", "_yr.txt", "_aa.txt")

#: 접미어 규칙에 안 걸리는 출력·부산물 파일 이름
SWAT_OUTPUT_NAMES = frozenset({
    "simulation.out", "diagnostics.out", "area_calc.out", "files_out.out",
    "erosion.out", "checker.out", "co2.out", "hru_dom.out", "success.fin",
    "fort.7777", "promotion_info.csv",
})


def is_swat_output(name: str) -> bool:
    """파일명이 SWAT+ **출력물**인가 (입력세트와 대조해 검증한 규칙).

    쿡 default/(입력 127개) 전수에 대해 오판 0건, calibrated/ 의 출력 67개를
    모두 걸러내는 것을 확인했다.
    """
    return name.endswith(SWAT_OUTPUT_SUFFIXES) or name in SWAT_OUTPUT_NAMES


def ignore_swat_outputs(_dir, names):
    """``shutil.copytree(..., ignore=ignore_swat_outputs)`` 용 필터."""
    return {n for n in names if is_swat_output(n)}


def copy_txtinout(src, dst) -> dict:
    """TxtInOut 을 **입력물만** 복사. 반환 {"files", "bytes", "skipped", "skipped_bytes"}.

    출력물은 SWAT+ 가 실행 중 새로 만든다. 거르면 복사량이 1/60 로 준다.
    """
    import shutil
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    n = b = sn = sb = 0
    for f in src.iterdir():
        if not f.is_file():
            continue
        if is_swat_output(f.name):
            sn += 1
            sb += f.stat().st_size
            continue
        shutil.copyfile(f, dst / f.name)
        n += 1
        b += f.stat().st_size
    return {"files": n, "bytes": b, "skipped": sn, "skipped_bytes": sb}
