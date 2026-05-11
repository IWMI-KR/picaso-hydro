"""SWAT-Plus simulation config writers.

Mirrors input_swat.R :: Write.Time.Sim.Input.Plus() and
Write.Print.Prt.Input.Plus().
"""

from __future__ import annotations

from pathlib import Path

from swat_py.utils.dates import is_leap_year


def write_time_sim(wdir: Path, nbyr: int, iyr: int) -> None:
    """Overwrite time.sim with simulation period.

    Mirrors R's ``Write.Time.Sim.Input.Plus(wdir, NBYR, IYR)`` which
    replaces the entire file with three lines:

    .. code-block:: text

        time.sim: written by rSWAT
        day_start  yrc_start   day_end   yrc_end      step
                0      IYR         0      EYR         0

    Parameters
    ----------
    wdir:   SWAT-Plus run directory containing time.sim.
    nbyr:   Total number of years to simulate (including warm-up).
    iyr:    Start year (before warm-up).
    """
    path = Path(wdir) / "time.sim"
    if not path.exists():
        raise FileNotFoundError(f"time.sim not found in {wdir}")

    end_year = iyr + nbyr - 1

    # Replace the entire file (R also does a full rewrite)
    lines = [
        "time.sim: written by swat_py\n",
        "day_start  yrc_start   day_end   yrc_end      step\n",
        f"{0:9d} {iyr:9d} {0:9d} {end_year:9d} {0:9d}\n",
    ]
    path.write_text("".join(lines), encoding="utf-8")


def patch_print_prt(wdir: Path, nbyr: int, iyr: int, nyskip: int) -> None:
    """Patch print.prt to set warm-up years and output date range.

    Mirrors R's ``Write.Print.Prt.Input.Plus(wdir, NBYR, IYR, NYSKIP)``.

    R replaces line 1 (title) and line 3 (data row after the header):

    .. code-block:: text

        print.prt: written by rSWAT
        nyskip  day_start  yrc_start  day_end   yrc_end   interval
        NYSKIP  1          IYR        365/366   EYR        1

    Note: yrc_start = IYR (full simulation start, **before** warm-up).
    SWAT-Plus uses nyskip internally to determine how many years to skip
    before writing output.

    Parameters
    ----------
    wdir:   SWAT-Plus run directory containing print.prt.
    nbyr:   Total simulation years.
    iyr:    Simulation start year (before warm-up).
    nyskip: Warm-up years to skip.
    """
    path = Path(wdir) / "print.prt"
    if not path.exists():
        raise FileNotFoundError(f"print.prt not found in {wdir}")

    end_year = iyr + nbyr - 1
    end_day = 366 if is_leap_year(end_year) else 365

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines: list[str] = []
    data_line_idx = None  # index of the data row after "nyskip day_start..." header

    for idx, line in enumerate(lines):
        stripped = line.strip().lower()
        if idx == 0:
            # Replace title line
            new_lines.append("print.prt: written by swat_py\n")
        elif "nyskip" in stripped and "day_start" in stripped:
            # Keep the column header line, mark next line for replacement
            new_lines.append(line)
            data_line_idx = idx + 1
        elif data_line_idx is not None and idx == data_line_idx:
            # Replace data row: nyskip day_start yrc_start day_end yrc_end interval
            # R format: "%d %11d %13d %8d %10d %8d" % (NYSKIP, 1, IYR, end_day, EYR, 1)
            new_lines.append(
                f"{nyskip:d} {1:11d} {iyr:13d} {end_day:8d} {end_year:10d} {1:8d}\n"
            )
        else:
            new_lines.append(line)

    path.write_text("".join(new_lines), encoding="utf-8")
