"""SWAT 실행 파일 자동 다운로드 — IWMI 사내 HTTP 저장소.

URL 매핑
--------
- swat_plus → http://shared.iwmi.kr:48080/permanent/swat_py/SWAT-Plus.exe (5 MB)
- swat2012  → http://shared.iwmi.kr:48080/permanent/swat_py/SWAT2012.exe (20 MB)
"""
from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Union


_SWAT_EXE_URLS = {
    "swat_plus":  "http://shared.iwmi.kr:48080/permanent/swat_py/SWAT-Plus.exe",
    "swat2012":   "http://shared.iwmi.kr:48080/permanent/swat_py/SWAT2012.exe",
}


def ensure_swat_exe(
    txtinout_dir: Union[str, Path],
    model_type:   str = "swat_plus",
    executable:   str = "SWAT-Plus.exe",
    *,
    timeout: int = 600,
    overwrite: bool = False,
) -> Path:
    """txtinout_dir 안 실행파일을 보장. 없으면 IWMI URL 에서 다운로드.

    Parameters
    ----------
    txtinout_dir : SWAT 입출력 폴더
    model_type   : swat_plus | swat2012
    executable   : 실행 파일명 (model.executable yaml 값)
    timeout      : 다운로드 timeout (초)
    overwrite    : 기존 파일 덮어쓰기

    Returns
    -------
    Path : 실행 파일 절대 경로

    Raises
    ------
    FileNotFoundError : URL 미제공 + 파일도 없는 경우 (swat2012 등)
    RuntimeError      : 다운로드 실패
    """
    txtinout_dir = Path(txtinout_dir)
    txtinout_dir.mkdir(parents=True, exist_ok=True)
    exe_path = txtinout_dir / executable

    if exe_path.is_file() and not overwrite:
        return exe_path

    # URL 다운로드 시도
    url = _SWAT_EXE_URLS.get(model_type)
    if not url:
        raise FileNotFoundError(
            f"{executable} 가 {txtinout_dir} 에 없고 URL 도 미제공 "
            f"(model_type='{model_type}'). 실행 파일을 직접 배치하세요."
        )

    print(f"  [DOWNLOAD] {url}")
    print(f"             → {exe_path}")
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "swat_py-exe-download/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            tmp_path = exe_path.with_suffix(exe_path.suffix + ".tmp")
            with tmp_path.open("wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
            # atomic rename
            shutil.move(str(tmp_path), str(exe_path))
        if total > 0 and downloaded != total:
            raise RuntimeError(
                f"다운로드 크기 불일치: {downloaded} vs {total}"
            )
        size_mb = exe_path.stat().st_size / 1e6
        print(f"  [OK]       {executable} ({size_mb:.2f} MB)")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP 오류 {e.code}: {url}") from e
    except Exception as e:
        # 부분 파일 정리
        for p in (exe_path, exe_path.with_suffix(exe_path.suffix + ".tmp")):
            p.unlink(missing_ok=True)
        raise RuntimeError(f"다운로드 실패: {url}\n{e}") from e

    return exe_path
