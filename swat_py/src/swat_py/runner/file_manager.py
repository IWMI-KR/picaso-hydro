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
