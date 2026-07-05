"""reservoir_day.txt 리더 + stage-storage 환산 테스트."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swat_py.output.reader_swat_plus import (
    parse_reservoir_day,
    extract_res_outtype,
    reservoir_storage_to_stage,
    read_hydrology_res,
)

_M_TO_FT = 3.280839895013123


def _make_res_file(tmp_path: Path, gis_id: int = 4, name: str = "res4",
                   n: int = 3) -> Path:
    """최소 reservoir_day.txt (제목·컬럼명·단위 3행 + n 데이터행).

    컬럼: jday mon day yr unit gis_id name area flo_stor flo_out
    (실제 파일은 65열이나, 리더는 gis_id/이름 기반 위치 매핑이라 부분집합으로 검증)
    """
    title = "ngeri  SWAT+ test\n"
    header = "jday mon day yr unit gis_id name area flo_stor flo_out\n"
    units = "                        ha  m^3  m^3\n"
    rows = ""
    for i in range(n):
        # area=0.8 ha=8000 m², flo_stor=80000 m³ → V/A=10 m ; flo_out=8640 m³/day=0.1 cms
        rows += f"{i+1} 1 {i+1} 2020 1 {gis_id} {name} 0.8000 0.8000E+05 0.8640E+04\n"
    p = tmp_path / "reservoir_day.txt"
    p.write_text(title + header + units + rows)
    return p


def test_parse_reservoir_day_rows(tmp_path):
    p = _make_res_file(tmp_path, gis_id=4)
    df = parse_reservoir_day(p, outlet=4, sdate="2020-01-01")
    assert df is not None
    assert len(df) == 3
    assert "flo_stor" in df.columns and "date" in df.columns


def test_parse_reservoir_wrong_outlet(tmp_path):
    p = _make_res_file(tmp_path, gis_id=4)
    assert parse_reservoir_day(p, outlet=99, sdate="2020-01-01") is None


def test_parse_reservoir_missing_file(tmp_path):
    assert parse_reservoir_day(tmp_path / "nope.txt", 4, "2020-01-01") is None


def test_filter_by_unit(tmp_path):
    p = _make_res_file(tmp_path, gis_id=4, name="res4")
    df = parse_reservoir_day(p, outlet=1, sdate="2020-01-01", filter_col="unit")
    assert df is not None and len(df) == 3


def test_stage_prismatic_is_mean_depth():
    # V=80000 m³, A=0.8 ha=8000 m² → 10 m (shape_factor=1)
    s = reservoir_storage_to_stage(80000.0, 0.8, shape_factor=1.0)
    assert s == pytest.approx(10.0, abs=1e-6)


def test_stage_wedge_double():
    s = reservoir_storage_to_stage(80000.0, 0.8, shape_factor=2.0)
    assert s == pytest.approx(20.0, abs=1e-6)


def test_stage_datum_offset():
    s = reservoir_storage_to_stage(80000.0, 0.8, shape_factor=1.0, datum_m=5.0)
    assert s == pytest.approx(15.0, abs=1e-6)


def test_stage_zero_area_is_nan():
    assert np.isnan(reservoir_storage_to_stage(80000.0, 0.0))


def test_stage_series_zero_area_nan():
    stor = pd.Series([80000.0, 80000.0])
    area = pd.Series([0.8, 0.0])
    out = reservoir_storage_to_stage(stor, area, shape_factor=1.0)
    assert out.iloc[0] == pytest.approx(10.0)
    assert np.isnan(out.iloc[1])


def test_extract_wlevel(tmp_path):
    p = _make_res_file(tmp_path, gis_id=4)
    df = parse_reservoir_day(p, outlet=4, sdate="2020-01-01")
    wl = extract_res_outtype(df, "wlevel", shape_factor=1.0)
    assert list(wl.columns) == ["date", "wlevel_m", "wlevel_ft"]
    assert wl["wlevel_m"].iloc[0] == pytest.approx(10.0, abs=1e-6)
    assert wl["wlevel_ft"].iloc[0] == pytest.approx(10.0 * _M_TO_FT, abs=1e-4)


def test_extract_resflow_m3day_to_cms(tmp_path):
    p = _make_res_file(tmp_path, gis_id=4)
    df = parse_reservoir_day(p, outlet=4, sdate="2020-01-01")
    rf = extract_res_outtype(df, "resflow")
    # 8640 m³/day ÷ 86400 = 0.1 m³/s
    assert rf["flow_cms"].iloc[0] == pytest.approx(0.1, abs=1e-9)


def test_extract_resstor(tmp_path):
    p = _make_res_file(tmp_path, gis_id=4)
    df = parse_reservoir_day(p, outlet=4, sdate="2020-01-01")
    rs = extract_res_outtype(df, "resstor")
    assert rs["stor_m3"].iloc[0] == pytest.approx(80000.0)
    assert rs["stor_1e4m3"].iloc[0] == pytest.approx(8.0)


def test_extract_unknown_outtype_raises(tmp_path):
    p = _make_res_file(tmp_path, gis_id=4)
    df = parse_reservoir_day(p, outlet=4, sdate="2020-01-01")
    with pytest.raises(ValueError):
        extract_res_outtype(df, "bogus")


# ── 실제 Palau ngeri 자료 (있을 때만) ─────────────────────────────────────────

_NGERI = Path(r"I:/2025-APCC_Palau/PICASO-Hydro/2_qswat/ngeri/Scenarios/Default/TxtInOut")


@pytest.mark.skipif(not (_NGERI / "reservoir_day.txt").is_file(),
                    reason="Palau ngeri reservoir_day.txt 없음")
def test_real_ngeri_res4():
    df = parse_reservoir_day(_NGERI / "reservoir_day.txt", outlet=4, sdate="1980-01-01")
    assert df is not None and len(df) > 1000
    wl = extract_res_outtype(df, "wlevel", shape_factor=1.0)
    # 평균수심(V/A) 은 양수·수 m 범위
    assert (wl["wlevel_m"] > 0).all()
    assert 1 < wl["wlevel_m"].mean() < 50
    params = read_hydrology_res(_NGERI / "hydrology.res", name="res4")
    assert "res4" in params and params["res4"]["vol_ps"] > 0
