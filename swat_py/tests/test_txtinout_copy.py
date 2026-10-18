"""TxtInOut 복사에서 SWAT+ 출력물 제외 (성능 회귀 방지).

검보정 master 에는 이전 실행의 출력 파일이 남는다. 쿡 기준 194개 1.19GB 중
**출력물 64개가 1.18GB(99%)** 이고 실제 입력은 130개 19.5MB 뿐이다.
예측 앙상블은 멤버마다 TxtInOut 을 통째로 복사하므로, 거르지 않으면
1,000멤버 한 기간에 1.17TB 를 복사한다 — 디스크가 포화돼 24워커를 걸어도
SWAT+ 가 2개만 동시에 돈다(실측: CPU 78.8%, 디스크 190%).
"""
from __future__ import annotations

import pytest

from swat_py.runner.file_manager import (
    copy_txtinout,
    ignore_swat_outputs,
    is_swat_output,
)

# default/(입력 127개) 전수 검증으로 확인한 실제 파일명들
INPUTS = ["time.sim", "print.prt", "file.cio", "hydrology.hyd", "aquifer.aqu",
          "soils.sol", "918430.pcp", "918430.tmp", "918430.wgn", "pcp.cli",
          "weather-sta.cli", "chandeg.con", "hru.con", "parameters.bsn",
          "SWAT-Plus.exe", "object.cnt", "rout_unit.con", "topography.hyd"]
OUTPUTS = ["channel_sd_day.txt", "channel_sd_mon.txt", "basin_wb_aa.txt",
           "hru_wb_yr.txt", "hydin_day.txt", "hydout_day.txt",
           "simulation.out", "diagnostics.out", "area_calc.out",
           "files_out.out", "erosion.out", "checker.out", "co2.out",
           "fort.7777", "promotion_info.csv"]


@pytest.mark.parametrize("name", INPUTS)
def test_inputs_are_kept(name) -> None:
    assert is_swat_output(name) is False, name


@pytest.mark.parametrize("name", OUTPUTS)
def test_outputs_are_skipped(name) -> None:
    assert is_swat_output(name) is True, name


def test_ignore_filter_for_copytree() -> None:
    names = ["time.sim", "channel_sd_day.txt", "918430.pcp", "simulation.out"]
    assert ignore_swat_outputs("/x", names) == {"channel_sd_day.txt", "simulation.out"}


def test_copy_txtinout_skips_outputs(tmp_path) -> None:
    src = tmp_path / "master"
    src.mkdir()
    (src / "time.sim").write_text("in")
    (src / "918430.pcp").write_text("in")
    (src / "channel_sd_day.txt").write_text("x" * 5000)   # 출력물(큼)
    (src / "hydin_day.txt").write_text("x" * 5000)
    dst = tmp_path / "base"
    st = copy_txtinout(src, dst)
    assert sorted(p.name for p in dst.iterdir()) == ["918430.pcp", "time.sim"]
    assert st["files"] == 2 and st["skipped"] == 2
    assert st["skipped_bytes"] == 10000


def test_copy_txtinout_creates_dst(tmp_path) -> None:
    src = tmp_path / "m"
    src.mkdir()
    (src / "time.sim").write_text("x")
    st = copy_txtinout(src, tmp_path / "deep" / "base")
    assert (tmp_path / "deep" / "base" / "time.sim").is_file() and st["files"] == 1


def test_copy_txtinout_ignores_subdirs(tmp_path) -> None:
    """TxtInOut 은 평면 구조 — 하위 폴더가 있어도 파일만 복사한다."""
    src = tmp_path / "m"
    src.mkdir()
    (src / "sub").mkdir()
    (src / "time.sim").write_text("x")
    (src / "sub" / "junk.txt").write_text("y")
    st = copy_txtinout(src, tmp_path / "b")
    assert st["files"] == 1 and not (tmp_path / "b" / "sub").exists()


# ── 활성 강수파일 판정 (pcp.cli 기준) ────────────────────────────────────────

def _mk_base(tmp_path, cli_names, files):
    b = tmp_path / "base"
    b.mkdir()
    for n in files:
        (b / n).write_text("x")
    if cli_names is not None:
        (b / "pcp.cli").write_text(
            "pcp.cli: test\nfilename\n" + "\n".join(cli_names) + "\n")
    return b


def test_active_pcp_uses_cli_index(tmp_path) -> None:
    """단일소 재배정 후 쓰지 않는 관측소 파일은 검사 대상에서 빠져야 한다.

    쿡 461417 은 2014-09 부터라, 폴더 전체를 검사하면 2013년 기간 실행이 막혔다.
    """
    from swat_py.drought.dashboard_data import active_pcp_files
    b = _mk_base(tmp_path, ["918430.pcp"],
                 ["918430.pcp", "461417.pcp", "427608.pcp"])
    assert [p.name for p in active_pcp_files(b)] == ["918430.pcp"]


def test_active_pcp_multi_station(tmp_path) -> None:
    from swat_py.drought.dashboard_data import active_pcp_files
    b = _mk_base(tmp_path, ["918430.pcp", "427608.pcp"],
                 ["918430.pcp", "461417.pcp", "427608.pcp"])
    assert [p.name for p in active_pcp_files(b)] == ["427608.pcp", "918430.pcp"]


def test_active_pcp_falls_back_without_cli(tmp_path) -> None:
    """pcp.cli 가 없으면 폴더 전체 — 기존 동작 유지."""
    from swat_py.drought.dashboard_data import active_pcp_files
    b = _mk_base(tmp_path, None, ["918430.pcp", "461417.pcp"])
    assert len(active_pcp_files(b)) == 2
