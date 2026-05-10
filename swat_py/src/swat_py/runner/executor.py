"""SWAT model executor — platform-aware subprocess launcher.

Mirrors the system("cmd.exe /c SWAT-Plus.exe") calls in R's calibration-plus.R
and cchange_swat_plus.R.
"""

from __future__ import annotations

import concurrent.futures
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


class SwatRunError(RuntimeError):
    """Raised when a SWAT executable exits with a non-zero return code."""

    def __init__(self, exe: str, returncode: int, stdout: str, stderr: str) -> None:
        super().__init__(
            f"{exe} exited with code {returncode}.\n"
            f"STDOUT: {stdout[-2000:]}\nSTDERR: {stderr[-2000:]}"
        )
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class SwatExecutor:
    """Run a SWAT executable inside a given directory.

    Parameters
    ----------
    run_dir:
        Directory that contains the SWAT input files and executable.
    exe_name:
        Executable filename (e.g. ``"SWAT-Plus.exe"`` or ``"swat_rev622"``).
    timeout:
        Maximum seconds to wait for the run (default 3 600 s / 1 h).
    """

    def __init__(
        self,
        run_dir: Path,
        exe_name: str = "SWAT-Plus.exe",
        timeout: int = 3600,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.exe_name = exe_name
        self.timeout = timeout

    # ------------------------------------------------------------------
    def _exe_cmd(self) -> List[str]:
        # On Windows, subprocess does NOT search cwd for executables,
        # so we must supply the absolute path to the exe.
        # On POSIX, "./<exe>" is the conventional CWD-relative form.
        if sys.platform == "win32":
            return [str(self.run_dir / self.exe_name)]
        return [f"./{self.exe_name}"]

    # ------------------------------------------------------------------
    def run(self, capture_output: bool = True) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
        """Execute SWAT and return the completed-process object.

        Raises :class:`SwatRunError` if the process exits non-zero.
        """
        result = subprocess.run(
            self._exe_cmd(),
            cwd=self.run_dir,
            capture_output=capture_output,
            text=True,
            timeout=self.timeout,
        )
        if result.returncode != 0:
            raise SwatRunError(
                self.exe_name,
                result.returncode,
                result.stdout or "",
                result.stderr or "",
            )
        return result

    # ------------------------------------------------------------------
    def run_batch(
        self,
        member_dirs: List[Path],
        parallel: bool = True,
        n_workers: int = 4,
    ) -> List[subprocess.CompletedProcess]:  # type: ignore[type-arg]
        """Run SWAT in multiple directories (ensemble members).

        Parameters
        ----------
        member_dirs:
            Each directory must already contain a full SWAT setup and the exe.
        parallel:
            If True, use a process pool.  If False, run sequentially.
        n_workers:
            Number of parallel worker processes.
        """
        if not parallel:
            return [
                SwatExecutor(d, self.exe_name, self.timeout).run()
                for d in member_dirs
            ]

        def _run_one(d: Path) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
            return SwatExecutor(d, self.exe_name, self.timeout).run()

        with concurrent.futures.ProcessPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_run_one, d): d for d in member_dirs}
            results: List[subprocess.CompletedProcess] = []  # type: ignore[type-arg]
            for fut in concurrent.futures.as_completed(futures):
                results.append(fut.result())
        return results
