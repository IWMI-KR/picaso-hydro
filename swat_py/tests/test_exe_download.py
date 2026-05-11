"""exe_download — IWMI URL 매핑·다운로드 함수 검증."""
from __future__ import annotations

from pathlib import Path

import pytest

from swat_py.calibration.exe_download import _SWAT_EXE_URLS, ensure_swat_exe


def test_urls_cover_both_versions() -> None:
    """swat_plus + swat2012 양쪽 URL 등록."""
    assert "swat_plus" in _SWAT_EXE_URLS
    assert "swat2012"  in _SWAT_EXE_URLS
    for v, url in _SWAT_EXE_URLS.items():
        assert url.startswith("http://shared.iwmi.kr:48080/permanent/swat_py/")
        assert url.endswith(".exe")


def test_ensure_existing_returns_path(tmp_path) -> None:
    """파일이 이미 있으면 다운로드 없이 그 경로 반환."""
    fake_exe = tmp_path / "SWAT-Plus.exe"
    fake_exe.write_bytes(b"FAKE")
    p = ensure_swat_exe(tmp_path, "swat_plus", "SWAT-Plus.exe")
    assert p == fake_exe
    assert p.read_bytes() == b"FAKE"   # 다운로드로 덮어쓰기 X


def test_ensure_unknown_model_raises(tmp_path) -> None:
    """URL 미등록 model_type + 파일 없음 → FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="URL.*미제공"):
        ensure_swat_exe(tmp_path, "swat_3000", "SWAT-X.exe")
