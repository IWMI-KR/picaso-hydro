"""작업폴더 안전 비우기 — 상위 폴더 삭제 사고(2026-10-20) 재발 방지.

``--workdir X`` 를 주면 X 가 아니라 X 의 **상위 폴더**가 통째로 지워지던 문제를
막는 :func:`swat_py.runner.file_manager.reset_work_dir` 의 계약을 고정한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from swat_py.runner.file_manager import (
    WORKDIR_MARKER,
    mark_work_dir,
    reset_work_dir,
)

# ── 핵심: 상위 폴더를 건드리지 않는다 ────────────────────────────────────────

def test_상위폴더와_형제폴더를_지우지_않는다(tmp_path):
    """옛 동작(rmtree(work.parent))이었다면 sibling 과 소중한파일이 사라진다."""
    parent = tmp_path / "사용자작업"
    work = parent / "TxtInOut"
    work.mkdir(parents=True)
    mark_work_dir(work)
    (work / "old.txt").write_text("이전 실행 산출물")
    sibling = parent / "소중한자료"
    sibling.mkdir()
    (sibling / "결과.csv").write_text("지우면 안 됨")
    keep = parent / "메모.txt"
    keep.write_text("지우면 안 됨")

    reset_work_dir(work, label="시험")

    assert not work.exists()            # 대상만 사라짐
    assert parent.is_dir()              # 상위는 그대로
    assert (sibling / "결과.csv").read_text() == "지우면 안 됨"
    assert keep.read_text() == "지우면 안 됨"


def test_대상이_없으면_상위만_만들고_끝낸다(tmp_path):
    work = tmp_path / "새폴더" / "TxtInOut"
    out = reset_work_dir(work, label="시험")
    assert out == work
    assert work.parent.is_dir()
    assert not work.exists()            # copytree 가 만들 자리 — 미리 만들지 않는다


# ── 사용자가 준 경로: 남의 폴더는 지우지 않는다 ──────────────────────────────

def test_표식없는_사용자폴더는_중단한다(tmp_path):
    work = tmp_path / "내자료"
    work.mkdir()
    (work / "중요.csv").write_text("실측 자료")

    with pytest.raises(RuntimeError, match="PICASO 가 만든 것이 아니다"):
        reset_work_dir(work, label="시험", trusted=False)

    assert (work / "중요.csv").read_text() == "실측 자료"   # 그대로 남아 있다


def test_표식이_있으면_지운다(tmp_path):
    work = tmp_path / "내자료"
    work.mkdir()
    (work / "중요.csv").write_text("이전 실행 산출물")
    mark_work_dir(work)
    assert (work / WORKDIR_MARKER).is_file()

    reset_work_dir(work, label="시험", trusted=False)
    assert not work.exists()


def test_빈_폴더는_지운다(tmp_path):
    work = tmp_path / "빈폴더"
    work.mkdir()
    reset_work_dir(work, label="시험", trusted=False)
    assert not work.exists()


def test_내부경로는_표식없이도_지운다(tmp_path):
    """trusted=True — 호출부가 경로를 직접 만든 경우(앙상블 base 등)."""
    work = tmp_path / "picaso_ens_base" / "TxtInOut"
    work.mkdir(parents=True)
    (work / "file.cio").write_text("이전 실행")
    reset_work_dir(work, label="시험", trusted=True)
    assert not work.exists()


# ── 보호 경로 ────────────────────────────────────────────────────────────────

def test_드라이브_루트는_거부한다(tmp_path):
    root = Path(tmp_path.anchor)
    with pytest.raises(RuntimeError, match="쓸 수 없는 경로"):
        reset_work_dir(root, label="시험", trusted=True)


def test_사용자_홈은_거부한다():
    with pytest.raises(RuntimeError, match="쓸 수 없는 경로"):
        reset_work_dir(Path.home(), label="시험", trusted=True)


def test_파일이_자리를_차지하면_중단한다(tmp_path):
    f = tmp_path / "작업"
    f.write_text("폴더가 아니라 파일")
    with pytest.raises(RuntimeError, match="자리에 파일이 있다"):
        reset_work_dir(f, label="시험", trusted=True)
    assert f.is_file()


# ── 호출부가 실제로 헬퍼를 쓰는지 (회귀 방지) ────────────────────────────────

def test_rmtree_parent_패턴이_남아있지_않다():
    """`shutil.rmtree(...parent)` 가 다시 들어오면 실패한다."""
    import swat_py
    src = Path(swat_py.__file__).parent
    offenders = []
    for py in src.rglob("*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            if "rmtree(" in s and ".parent" in s:
                offenders.append(f"{py.relative_to(src)}:{i}: {s}")
    assert not offenders, "상위 폴더 삭제 패턴 재발:\n" + "\n".join(offenders)
