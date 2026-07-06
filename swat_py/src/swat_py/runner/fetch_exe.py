"""SWAT+ 실행파일 자동 다운로드 — OS 감지 후 공식 GitHub Releases 에서 받아 저장.

공식 배포처(고정): https://github.com/swat-model/swatplus/releases
(Linux/Windows/macOS 바이너리가 자동 컴파일·게시됨. asset 명:
 ``swatplus-{ver}-{compiler}-{os_arch}-Rel.zip``, 예 gnu-lin_x86_64, gnu-win_amd64, mac_x86_64.)

동작: OS·아키텍처 감지 → GitHub Releases API 로 맞는 Release(gnu 우선) zip 선택 →
      다운로드·압축해제 → 지정 폴더(기본 3_swatplus/calibrated·default)에 실행파일 저장
      (리눅스/macOS 는 chmod +x). 보안상 다운로드 URL 이 공식 repo 인지 확인한다.

프로그램: from swat_py.runner.fetch_exe import fetch_swat_executable
CLI:      python -m swat_py.runner.fetch_exe [--project PATH] [--version 62.0.0]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

_REPO = "swat-model/swatplus"
_API = "https://api.github.com/repos/{repo}/releases/{ref}"
_TRUSTED_PREFIX = f"https://github.com/{_REPO}/releases/download/"   # 다운로드 허용 도메인/경로


def _detect_os_arch(os_name: Optional[str] = None,
                    arch: Optional[str] = None) -> Tuple[str, str, str]:
    """(os_tag, arch, canonical_exe_name) 반환. os_tag ∈ {win, lin, mac}."""
    sysname = (os_name or platform.system()).lower()
    m = (arch or platform.machine()).lower()
    is_arm = ("arm" in m) or ("aarch64" in m)
    if sysname.startswith("win"):
        return "win", "amd64", "swatplus.exe"
    if sysname == "darwin" or "mac" in sysname:
        return "mac", ("arm64" if is_arm else "x86_64"), "swatplus"
    return "lin", ("arm64" if is_arm else "x86_64"), "swatplus"


def _github_release(ref: str = "latest") -> dict:
    ref_path = "latest" if ref in (None, "latest") else f"tags/{ref}"
    url = _API.format(repo=_REPO, ref=ref_path)
    req = urllib.request.Request(url, headers={"User-Agent": "picaso-hydro"})
    with urllib.request.urlopen(req, timeout=60) as r:      # noqa: S310 (고정 공식 API)
        return json.loads(r.read().decode())


def _select_asset(assets: List[dict], os_tag: str, arch: str) -> dict:
    """OS/arch 에 맞는 Release(gnu 우선) zip asset 선택."""
    token = f"{os_tag}_{arch}"
    cands = [a for a in assets
             if a["name"].endswith(".zip") and token in a["name"] and "Rel" in a["name"]]
    if not cands:
        raise SystemExit(
            f"OS/arch({token}) 에 맞는 SWAT+ Release asset 을 찾지 못했습니다.\n"
            f"  가용 asset: {[a['name'] for a in assets]}")
    gnu = [a for a in cands if "gnu" in a["name"]]
    return (gnu or cands)[0]


def _extract_exe(zip_path: Path, os_tag: str) -> Path:
    """zip 에서 실행파일을 임시폴더로 추출해 경로 반환."""
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if os_tag == "win":
            cands = [n for n in names if n.lower().endswith(".exe")]
        else:
            cands = [n for n in names if Path(n).name.lower().startswith("swatplus")]
        if not cands:                                       # fallback: 가장 큰 파일
            biggest = max((i for i in z.infolist() if not i.is_dir()),
                          key=lambda i: i.file_size)
            cands = [biggest.filename]
        member = cands[0]
        out = Path(tempfile.mkdtemp())
        z.extract(member, out)
        return out / member


def fetch_swat_executable(dest_dirs, *, version: str = "latest",
                          os_name: Optional[str] = None,
                          arch: Optional[str] = None) -> str:
    """OS 감지 → 공식 GitHub Releases 에서 SWAT+ 실행파일을 받아 dest_dirs 에 저장.

    반환: 저장된 실행파일 이름(예: 'swatplus' | 'swatplus.exe'). config/swat_py.yaml 의
          model.executable 에 이 이름을 지정하면 파이프라인이 사용한다.
    """
    os_tag, march, canon = _detect_os_arch(os_name, arch)
    rel = _github_release(version)
    asset = _select_asset(rel.get("assets", []), os_tag, march)
    url = asset["browser_download_url"]
    if not url.startswith(_TRUSTED_PREFIX):                 # 보안: 공식 repo 만 허용
        raise SystemExit(f"신뢰하지 않는 다운로드 URL(공식 repo 아님): {url}")

    print("=" * 64)
    print("  SWAT+ 실행파일 자동 다운로드")
    print(f"  OS/arch    : {os_tag}_{march}")
    print(f"  release    : {rel.get('tag_name')}")
    print(f"  asset      : {asset['name']}")
    print(f"  source     : {url}")
    print("=" * 64)

    tmpzip = Path(tempfile.mkdtemp()) / asset["name"]
    req = urllib.request.Request(url, headers={"User-Agent": "picaso-hydro"})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmpzip, "wb") as f:  # noqa: S310
        shutil.copyfileobj(r, f)
    print(f"  다운로드 완료: {tmpzip.stat().st_size / 1e6:.1f} MB")

    exe_src = _extract_exe(tmpzip, os_tag)
    for d in dest_dirs:
        d = Path(d)
        d.mkdir(parents=True, exist_ok=True)
        dst = d / canon
        shutil.copy2(exe_src, dst)
        if os_tag != "win":
            dst.chmod(0o755)
        print(f"  저장: {dst}")

    print("\n완료. config/swat_py.yaml 에 다음을 지정하세요:")
    print(f"    model:\n      executable: {canon}")
    return canon


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="swat_py.runner.fetch_exe",
        description="SWAT+ 실행파일 자동 다운로드(공식 GitHub Releases) → calibrated·default 저장")
    ap.add_argument("--project", default=None,
                    help="프로젝트 루트 (기본: PICASO_ROOT 또는 현재 폴더)")
    ap.add_argument("--version", default="latest", help="릴리스 태그 (기본 latest)")
    ap.add_argument("--dirs", nargs="+", default=None,
                    help="저장 폴더 (기본: 3_swatplus/calibrated·default)")
    args = ap.parse_args(argv)
    if args.dirs:
        dirs = [Path(d) for d in args.dirs]
    else:
        root = Path(args.project or os.environ.get("PICASO_ROOT") or ".")
        dirs = [root / "3_swatplus" / "calibrated", root / "3_swatplus" / "default"]
    fetch_swat_executable(dirs, version=args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
