"""print.prt 객체 출력 토글(set_print_object) 등 SWAT+ config writer."""
from __future__ import annotations

import pytest

from swat_py.io.config_swat_plus import set_print_object


def _make_print_prt(tmp_path):
    p = tmp_path / "print.prt"
    p.write_text(
        "print.prt: written test\n"
        "nyskip      day_start  yrc_start  day_end   yrc_end   interval  \n"
        "3           1          2015      365       2023        1\n"
        "aa_int_cnt  \n"
        "0\n"
        "csvout        yes\n"
        "objects       daily monthly yearly avann\n"
        "channel_sd                   y             n             n             n  \n"
        "reservoir                    n             n             n             n  \n"
        "basin_wb                     n             n             n             n  \n"
    )
    return p


def test_set_print_object_enables_daily(tmp_path):
    p = _make_print_prt(tmp_path)
    assert set_print_object(tmp_path, "reservoir", daily=True) is True
    row = [l for l in p.read_text().splitlines() if l.split() and l.split()[0] == "reservoir"][0]
    flags = row.split()[1:5]
    assert flags == ["y", "n", "n", "n"]


def test_set_print_object_all_periods(tmp_path):
    p = _make_print_prt(tmp_path)
    set_print_object(tmp_path, "reservoir", daily=True, monthly=True,
                     yearly=True, avann=True)
    row = [l for l in p.read_text().splitlines() if l.split()[:1] == ["reservoir"]][0]
    assert row.split()[1:5] == ["y", "y", "y", "y"]


def test_set_print_object_does_not_touch_others(tmp_path):
    p = _make_print_prt(tmp_path)
    set_print_object(tmp_path, "reservoir", daily=True)
    txt = p.read_text().splitlines()
    ch = [l for l in txt if l.split()[:1] == ["channel_sd"]][0]
    assert ch.split()[1:5] == ["y", "n", "n", "n"]     # 변경 없음


def test_set_print_object_missing_returns_false(tmp_path):
    _make_print_prt(tmp_path)
    assert set_print_object(tmp_path, "nonexistent_obj", daily=True) is False


def test_set_print_object_no_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        set_print_object(tmp_path, "reservoir")
