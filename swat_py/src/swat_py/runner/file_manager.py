"""File management helpers for SWAT input/output staging.

Mirrors util.R :: Swat.Copy.Input.Output.Files() and the inline
file.copy / file.rename calls throughout calibration-plus.R and
cchange_swat_plus.R.
"""

from __future__ import annotations

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


def resolve_swat_exe(executable: str, model_dir) -> Path:
    """SWAT+ 실행파일 **원본 경로** 해석 (OS·설치방식 무관).

    탐색 순서: ① 절대경로 → ② 모델폴더/{name} → ③ PATH(shutil.which).
    없으면 리눅스 바이너리 지정 방법을 안내하는 명확한 에러를 낸다.

    executable : cfg.Executable (윈도우 기본 'SWAT-Plus.exe'; 리눅스는 'swatplus' 등
                 이름 또는 절대경로 — swat_py.yaml 의 model.executable 로 지정).
    model_dir  : 실행파일이 함께 들어있을 수 있는 모델 폴더(calibrated/default).
    """
    exe = str(executable)
    p = Path(exe)
    if p.is_absolute():
        if p.is_file():
            return p
    else:
        cand = Path(model_dir) / exe
        if cand.is_file():
            return cand
        found = shutil.which(exe)
        if found:
            return Path(found)
    raise SystemExit(
        f"SWAT+ 실행파일을 찾을 수 없습니다: '{exe}' (모델폴더: {model_dir})\n"
        f"  · 리눅스: SWAT+ 리눅스 바이너리(예: swatplus)를 설치한 뒤 config/swat_py.yaml 에\n"
        f"        model:\n          executable: /절대/경로/swatplus   # 또는 PATH 에 있는 이름\n"
        f"    를 지정하거나, 모델폴더({model_dir})에 실행파일을 두고 그 이름을 지정하세요.\n"
        f"  · 윈도우 기본값은 'SWAT-Plus.exe' 입니다.")


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
