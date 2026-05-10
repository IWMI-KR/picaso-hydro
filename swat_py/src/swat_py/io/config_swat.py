"""SWAT 2012 file.cio patcher.

Mirrors input_swat.R :: Write.Cio.Input().
"""

from __future__ import annotations

from pathlib import Path

from swat_py.utils.dates import is_leap_year


def patch_file_cio(wdir: Path, nbyr: int, iyr: int, nyskip: int) -> None:
    """Overwrite NBYR, IYR, IDAL, NYSKIP in file.cio.

    Parameters
    ----------
    wdir:   SWAT 2012 run directory containing file.cio.
    nbyr:   Total number of simulation years.
    iyr:    Start year.
    nyskip: Warm-up years to skip.
    """
    path = Path(wdir) / "file.cio"
    if not path.exists():
        raise FileNotFoundError(f"file.cio not found in {wdir}")

    idal = 366 if is_leap_year(iyr) else 365

    # Detect encoding: ARCGIS-SWAT generated file.cio may use cp949 on Korean Windows
    for _enc in ("utf-8", "cp949", "latin-1"):
        try:
            lines = path.read_text(encoding=_enc).splitlines(keepends=True)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Cannot decode {path} with utf-8 / cp949 / latin-1")
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if "NBYR" in stripped:
            new_lines.append(f"{nbyr:16d}    | NBYR : Number of years simulated\n")
        elif "IYR" in stripped and "IYRB" not in stripped:
            new_lines.append(f"{iyr:16d}    | IYR : Beginning year of simulation\n")
        elif "IDAL" in stripped and "IDAL2" not in stripped:
            new_lines.append(
                f"{idal:16d}    | IDAL : Beginning julian day of simulation\n"
            )
        elif "NYSKIP" in stripped:
            new_lines.append(
                f"{nyskip:16d}    | NYSKIP : Number of years to skip output\n"
            )
        else:
            new_lines.append(line)

    path.write_text("".join(new_lines), encoding=_enc)
