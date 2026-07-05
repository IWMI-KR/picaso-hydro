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


def set_print_object(
    wdir: Path,
    obj: str,
    *,
    daily: bool = True,
    monthly: bool = False,
    yearly: bool = False,
    avann: bool = False,
) -> bool:
    """print.prt 의 객체별 출력 플래그(daily/monthly/yearly/avann) 설정.

    print.prt 하단 객체 출력 섹션의 각 줄은
    ``{object}  {daily} {monthly} {yearly} {avann}`` (y/n) 형식이다.
    예: 저수지 일 출력 활성화 → ``set_print_object(wdir, "reservoir", daily=True)``
    → ``reservoir_day.txt`` 생성.

    Parameters
    ----------
    wdir:  print.prt 가 있는 폴더.
    obj:   객체 이름(첫 열, 예: ``"reservoir"``, ``"channel_sd"``, ``"basin_wb"``).
    daily/monthly/yearly/avann:  각 출력 주기 on/off.

    Returns
    -------
    True 면 해당 객체 줄을 찾아 갱신, False 면 미발견.
    """
    path = Path(wdir) / "print.prt"
    if not path.exists():
        raise FileNotFoundError(f"print.prt not found in {wdir}")

    def yn(b: bool) -> str:
        return "y" if b else "n"

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    found = False
    for idx, line in enumerate(lines):
        parts = line.split()
        # 객체 출력 줄: 첫 토큰이 obj, 뒤 4개가 y/n
        if len(parts) >= 5 and parts[0] == obj and all(
            p.lower() in ("y", "n") for p in parts[1:5]
        ):
            newline = (
                f"{parts[0]:<28s} {yn(daily):<13s} {yn(monthly):<13s} "
                f"{yn(yearly):<13s} {yn(avann):<13s}\n"
            )
            lines[idx] = newline
            found = True
            break

    if found:
        path.write_text("".join(lines), encoding="utf-8")
    return found
