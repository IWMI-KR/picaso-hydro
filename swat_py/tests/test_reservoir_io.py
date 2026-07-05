"""수위-내용적 곡선(StageStorageCurve) + 취수 물수지(simulate_managed_storage)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swat_py.io.reservoir import (
    StageStorageCurve,
    load_stage_storage,
    simulate_managed_storage,
    build_hydrology_res_params,
    update_hydrology_res,
)

_M_PER_FT = 0.3048

_M3_PER_ACFT = 1233.4815589592
_NGERI = Path(r"I:/2025-APCC_Palau/PICASO-Hydro/0_database/obs/reservoir/ngerimel_stage_storage.csv")


# ── StageStorageCurve ─────────────────────────────────────────────────────────

def _simple_curve() -> StageStorageCurve:
    # 선형: 0 m³ @0 ft, 1000 m³ @10 ft
    return StageStorageCurve(elev_ft=np.array([0.0, 10.0]),
                             storage_m3=np.array([0.0, 1000.0]), name="lin")


def test_curve_monotone_roundtrip():
    c = _simple_curve()
    assert c.storage_to_stage(500.0, interp="linear") == pytest.approx(5.0)
    assert c.stage_to_storage(5.0, interp="linear") == pytest.approx(500.0)


def test_curve_clamp_outside_range():
    c = _simple_curve()
    assert c.storage_to_stage(-100.0) == pytest.approx(0.0)   # 하한
    assert c.storage_to_stage(9999.0) == pytest.approx(10.0)  # 상한(clamp)


def test_curve_rejects_nonmonotone():
    with pytest.raises(ValueError):
        StageStorageCurve(elev_ft=np.array([0, 5, 10]),
                          storage_m3=np.array([0, 100, 50]))  # 감소


def test_curve_needs_two_points():
    with pytest.raises(ValueError):
        StageStorageCurve(elev_ft=np.array([1.0]), storage_m3=np.array([1.0]))


def test_curve_array_input():
    c = _simple_curve()
    out = c.storage_to_stage(np.array([0.0, 500.0, 1000.0]), interp="linear")
    np.testing.assert_allclose(out, [0.0, 5.0, 10.0])


def test_load_units_acft(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("elev_ft,volume_acft,note\n0,0,bottom\n10,1,\n")
    c = load_stage_storage(p)
    assert c.storage_m3[-1] == pytest.approx(_M3_PER_ACFT, rel=1e-6)
    assert c.meta.get("bottom_ft") == pytest.approx(0.0)


def test_load_units_elev_m(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("elev_m,storage_m3\n0,0\n3.048,1000\n")   # 3.048 m = 10 ft
    c = load_stage_storage(p)
    assert c.elev_ft[-1] == pytest.approx(10.0, abs=1e-3)


# ── simulate_managed_storage ──────────────────────────────────────────────────

def _res_df(n=10, flo_in=1000.0, precip=0.0, evap=0.0, seep=0.0, start="2020-01-01"):
    dates = pd.date_range(start, periods=n, freq="D")
    return pd.DataFrame({
        "date": dates,
        "flo_in": [flo_in] * n, "precip": [precip] * n,
        "evap": [evap] * n, "seep": [seep] * n,
        "flo_stor": [5000.0] * n,
    })


def test_balance_withdrawal_reduces_storage():
    df = _res_df(n=5, flo_in=0.0)          # 유입 0
    # 취수 0.01 m³/s = 864 m³/day, init 5000, dead 0
    bal = simulate_managed_storage(df, withdrawal_m3s=0.01, dead_m3=0.0,
                                   init_m3=5000.0, use_losses=False)
    # 매일 864 감소
    assert bal["storage_m3"].iloc[0] == pytest.approx(5000 - 864)
    assert bal["storage_m3"].iloc[4] == pytest.approx(5000 - 5 * 864)


def test_balance_spill_cap():
    df = _res_df(n=3, flo_in=2000.0)       # 유입 2000/day
    bal = simulate_managed_storage(df, withdrawal_m3s=0.0, cap_m3=1000.0,
                                   init_m3=1000.0, use_losses=False)
    # 만수 유지 + 유입 전량 월류
    assert (bal["storage_m3"] == 1000.0).all()
    assert bal["spill_m3"].iloc[0] == pytest.approx(2000.0)


def test_balance_dead_floor_and_shortage():
    df = _res_df(n=3, flo_in=0.0)
    bal = simulate_managed_storage(df, withdrawal_m3s=0.02, dead_m3=0.0,
                                   init_m3=500.0, use_losses=False)
    # 0.02*86400=1728/day > init → 첫날 바닥, 이후 shortage 계속
    assert (bal["storage_m3"] >= 0).all()
    assert bal["shortage_m3"].iloc[0] > 0


def test_balance_losses_included():
    df = _res_df(n=1, flo_in=1000.0, precip=200.0, evap=300.0, seep=100.0)
    bal = simulate_managed_storage(df, withdrawal_m3s=0.0, init_m3=0.0)
    # 1000+200-300-100 = 800
    assert bal["storage_m3"].iloc[0] == pytest.approx(800.0)


def test_balance_monthly_withdrawal():
    df = _res_df(n=1, flo_in=0.0, start="2020-07-01")   # 7월
    w = [0.0] * 12; w[6] = 0.01                          # 7월만 취수
    bal = simulate_managed_storage(df, withdrawal_m3s=w, init_m3=5000.0,
                                   use_losses=False)
    assert bal["withdrawal_m3"].iloc[0] == pytest.approx(0.01 * 86400)


def test_balance_monthly_wrong_length_raises():
    df = _res_df(n=1)
    with pytest.raises(ValueError):
        simulate_managed_storage(df, withdrawal_m3s=[0.0, 0.1])


# ── surface_area / hydrology.res 갱신 ─────────────────────────────────────────

def test_surface_area_linear():
    c = _simple_curve()   # 0 m³@0ft, 1000 m³@10ft → dV/dz=100 m³/ft
    a = c.surface_area_m2(5.0, interp="linear")
    assert a == pytest.approx(100.0 / _M_PER_FT, rel=1e-4)   # ≈328.08 m²


def test_surface_area_boundary_backward():
    c = _simple_curve()
    # 상단(10ft)에서도 유한·양수(후방차분)
    a = c.surface_area_m2(10.0, interp="linear")
    assert a == pytest.approx(100.0 / _M_PER_FT, rel=1e-4)


def test_build_hydrology_res_params():
    c = _simple_curve()
    p = build_hydrology_res_params(c, principal_ft=5.0, emergency_ft=10.0,
                                   interp="linear")
    # vol@5ft=500 m³=0.05 ha·m ; vol@10ft=1000=0.1 ha·m
    assert p["vol_ps"] == pytest.approx(0.05, rel=1e-4)
    assert p["vol_es"] == pytest.approx(0.10, rel=1e-4)
    # area=328.08 m²=0.0328 ha
    assert p["area_ps"] == pytest.approx(0.0328084, rel=1e-3)
    assert p["vol_es"] > p["vol_ps"]


def _fake_hydro_res(tmp_path):
    p = tmp_path / "hydrology.res"
    p.write_text(
        "hydrology.res: test\n"
        "name                 yr_op    mon_op       area_ps        vol_ps"
        "       area_es        vol_es             k       evap_co"
        "       shp_co1       shp_co2  \n"
        "res4                     1         1       0.18841       1.88409"
        "       0.21667       2.16670       0.00000       0.60000"
        "       0.00000       0.00000  \n"
    )
    return p


def test_update_hydrology_res_replaces_and_preserves(tmp_path):
    p = _fake_hydro_res(tmp_path)
    params = {"area_ps": 4.07, "vol_ps": 10.32, "area_es": 5.24, "vol_es": 18.87}
    res = update_hydrology_res(p, "res4", params, backup=True)
    assert res["before"]["vol_ps"] == pytest.approx(1.88409)
    # 재읽기 검증
    row = p.read_text().splitlines()[2].split()
    hdr = p.read_text().splitlines()[1].split()
    assert float(row[hdr.index("vol_ps")]) == pytest.approx(10.32)
    assert float(row[hdr.index("area_es")]) == pytest.approx(5.24)
    # 타 열 보존
    assert float(row[hdr.index("evap_co")]) == pytest.approx(0.60)
    assert float(row[hdr.index("k")]) == pytest.approx(0.0)
    # 백업 생성
    assert (tmp_path / "hydrology.res.bak").is_file()


def test_update_hydrology_res_out_path_no_overwrite(tmp_path):
    p = _fake_hydro_res(tmp_path)
    orig = p.read_text()
    out = tmp_path / "hydrology.res.updated"
    update_hydrology_res(p, "res4", {"area_ps": 1, "vol_ps": 2, "area_es": 3,
                                     "vol_es": 4}, out_path=out)
    assert p.read_text() == orig          # 원본 불변
    assert out.is_file()


def test_update_hydrology_res_missing_reservoir(tmp_path):
    p = _fake_hydro_res(tmp_path)
    with pytest.raises(ValueError):
        update_hydrology_res(p, "resXX", {"area_ps": 1, "vol_ps": 2,
                                          "area_es": 3, "vol_es": 4})


# ── 실제 Ngerimel 곡선 (있을 때만) ─────────────────────────────────────────────

@pytest.mark.skipif(not _NGERI.is_file(), reason="Ngerimel stage-storage CSV 없음")
def test_real_ngerimel_curve():
    c = load_stage_storage(_NGERI, name="ngerimel")
    assert c.meta["bottom_ft"] == pytest.approx(23.34)
    assert c.meta["spillway_ft"] == pytest.approx(45.0)
    assert c.meta["crest_ft"] == pytest.approx(51.0)
    # 여수로(45ft) 저류 ≈ 83.7 ac-ft
    assert float(c.stage_to_storage(45.0)) == pytest.approx(83.7 * _M3_PER_ACFT, rel=1e-3)
    # 단조·clamp
    assert float(c.storage_to_stage(1e9)) == pytest.approx(51.0)
