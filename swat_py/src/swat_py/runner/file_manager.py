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
from typing import List

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
                     fetch_dirs=None) -> Path:
    """SWAT+ 실행파일 **원본 경로** 해석 — OS 자동 대응 + 미발견 시 자동 다운로드.

    ① cfg.Executable → ② OS 기본 이름(swatplus / swatplus.exe) 순으로, 각 후보를
    절대경로/모델폴더/PATH 에서 탐색한다(모델폴더에 리눅스 바이너리가 있으면
    model.executable 을 지정하지 않아도 자동 인식). 못 찾고 auto_fetch=True 이면
    공식 GitHub Releases 에서 받아 fetch_dirs(기본 [model_dir])에 저장 후 사용한다.

    auto_fetch 는 환경변수 PICASO_NO_AUTOFETCH 로 끌 수 있다.
    """
    for name in _swat_exe_candidates(executable):
        p = Path(name)
        if p.is_absolute():
            if p.is_file():
                return p
            continue
        cand = Path(model_dir) / name
        if cand.is_file():
            return cand
        found = shutil.which(name)
        if found:
            return Path(found)

    # 미발견 → 공식 Releases 에서 자동 다운로드(OS 감지)
    if auto_fetch and not os.environ.get("PICASO_NO_AUTOFETCH"):
        try:
            from swat_py.runner.fetch_exe import fetch_swat_executable
            dirs = [Path(d) for d in (fetch_dirs or [model_dir]) if d]
            print("[SWAT+] 실행파일 미발견 → 공식 GitHub Releases 에서 자동 다운로드 …")
            name = fetch_swat_executable(dirs)
            for d in [Path(model_dir), *dirs]:
                if (d / name).is_file():
                    return d / name
        except Exception as e:                       # 네트워크·다운로드 실패
            print(f"[SWAT+] 자동 다운로드 실패: {e}")

    raise SystemExit(
        f"SWAT+ 실행파일을 찾을 수 없습니다 (모델폴더: {model_dir}).\n"
        f"  · 자동 다운로드가 실패했다면(인터넷 없음 등) 수동 설치:\n"
        f"        python -m swat_py.runner.fetch_exe --project <프로젝트루트>\n"
        f"    또는 리눅스 바이너리를 모델폴더에 두고 config/swat_py.yaml 에\n"
        f"        model:\n          executable: swatplus   # 또는 절대경로/PATH 이름\n"
        f"    를 지정하세요. (윈도우 기본값: SWAT-Plus.exe)")


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
