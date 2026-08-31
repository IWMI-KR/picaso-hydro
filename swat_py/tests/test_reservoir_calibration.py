"""저수지 수위(wlevel) 보정 루프 통합 테스트.

analyze_one_observation_plus / run_observation_analysis_plus 가
reservoir_day-{Sim}.txt + 관측(wlevel_ft) → 일·월 비교 + 성능지표를
end-to-end 로 산출하는지 검증한다.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from swat_py.config.env import _Observation
from ._paths import palau_path
from swat_py.calibration.analysis_swat_plus import (
    analyze_one_observation_plus,
    run_observation_analysis_plus,
    _resolve_obs_path,
)

_NGERI = palau_path("2_qswat/ngeri/Scenarios/Default/TxtInOut")
_OBS   = palau_path("0_database/obs/flow/ngerimel.csv")
_YAML  = palau_path("swat_py_apcc.yaml")


# ── 합성 데이터 기반(항상 실행) ───────────────────────────────────────────────

def _make_res_day(path: Path, gis_id=4, dates=None):
    """최소 reservoir_day-{Sim}.txt (제목·헤더·단위 + 데이터)."""
    if dates is None:
        dates = pd.date_range("2018-01-01", periods=10, freq="D")
    hdr = "jday mon day yr unit gis_id name area flo_stor flo_out\n"
    lines = ["ngeri test\n", hdr, "  ha m^3 m^3\n"]
    for d in dates:
        # area=0.8ha, flo_stor=80000 → V/A=10 m
        lines.append(f"{d.dayofyear} {d.month} {d.day} {d.year} 1 {gis_id} res4 "
                     f"0.8000 0.8000E+05 0.8640E+04\n")
    path.write_text("".join(lines))


def _obs(**kw):
    base = dict(id="ngerimel", outlet_id=4, variable="wlevel", unit="ft",
                obs_file="", obs_column="wlevel_ft", outlet_name="res4",
                time_step="daily", weight=1.0, objective="NSE",
                shape_factor=1.0, datum_m=0.0)
    base.update(kw)
    return _Observation(**base)


def test_analyze_one_wlevel_synthetic(tmp_path):
    out_dir = tmp_path / "Output"; out_dir.mkdir()
    ana_dir = tmp_path / "Analysis"
    dates = pd.date_range("2018-01-01", periods=10, freq="D")
    _make_res_day(out_dir / "reservoir_day-Calibration.txt", dates=dates)

    # 관측: 모의 wlevel_ft(=10 m→32.808 ft)와 동일하게 두면 NSE≈1
    obs_csv = tmp_path / "ngerimel.csv"
    wl_ft = 10.0 * 3.280839895013123
    pd.DataFrame({"date": dates, "wlevel_ft": [wl_ft] * len(dates)}).to_csv(obs_csv, index=False)

    obs = _obs(obs_file=str(obs_csv))
    s = analyze_one_observation_plus(
        obs, "Calibration", syear=2018, nyskip=0,
        out_dir=out_dir, analysis_dir=ana_dir, make_plot=False,
    )
    assert s is not None
    assert s["source"] == "reservoir" and s["variable"] == "wlevel"
    assert s["n_daily"] == 10
    # 관측=모의(상수) → 분산 0 이라 NSE 정의상 문제 가능 → 값 존재만 확인
    assert "daily_pbias" in s
    assert abs(s["daily_pbias"]) < 1e-6            # 완전일치 → bias 0
    assert (ana_dir / "Calibration_ngerimel_wlevel_4-daily.csv").is_file()


def test_analyze_one_wlevel_datum_shift(tmp_path):
    """datum_m 오프셋이 모의 수위에 그대로 반영되는지."""
    out_dir = tmp_path / "Output"; out_dir.mkdir()
    dates = pd.date_range("2018-01-01", periods=5, freq="D")
    _make_res_day(out_dir / "reservoir_day-Calibration.txt", dates=dates)
    obs_csv = tmp_path / "o.csv"
    pd.DataFrame({"date": dates, "wlevel_ft": [40.0]*5}).to_csv(obs_csv, index=False)

    s0 = analyze_one_observation_plus(_obs(obs_file=str(obs_csv), datum_m=0.0),
        "Calibration", 2018, 0, out_dir, tmp_path/"A0", make_plot=False)
    s2 = analyze_one_observation_plus(_obs(obs_file=str(obs_csv), datum_m=2.0),
        "Calibration", 2018, 0, out_dir, tmp_path/"A2", make_plot=False)
    # datum +2 m → 모의 수위 +2 m(=6.56 ft) 상승 → PBIAS 변화
    assert s0["daily_pbias"] != s2["daily_pbias"]


def test_run_observation_analysis_namespace(tmp_path):
    out_dir = tmp_path / "Output"; out_dir.mkdir()
    dates = pd.date_range("2018-01-01", periods=8, freq="D")
    _make_res_day(out_dir / "reservoir_day-Calibration.txt", dates=dates)
    obs_csv = tmp_path / "ngerimel.csv"
    pd.DataFrame({"date": dates, "wlevel_ft": np.linspace(30, 34, 8)}).to_csv(obs_csv, index=False)

    cfg = SimpleNamespace(
        CioNYSKIP=0, SwatObsDir=str(tmp_path),
        ObservedDataDir=str(tmp_path), SwatDbDir=str(tmp_path),
        Observations=[_obs(obs_file=str(obs_csv))],
    )
    df = run_observation_analysis_plus(
        cfg, "Calibration", syear=2018,
        out_dir=out_dir, analysis_dir=tmp_path / "Analysis", make_plot=False,
    )
    assert not df.empty
    assert df.iloc[0]["variable"] == "wlevel"
    assert (tmp_path / "Analysis" / "Calibration_observation_metrics.csv").is_file()


def test_resolve_obs_path_relative(tmp_path):
    root = tmp_path / "obs"; (root / "flow").mkdir(parents=True)
    f = root / "flow" / "x.csv"; f.write_text("date,wlevel_ft\n")
    assert _resolve_obs_path("flow/x.csv", str(root)) == f


def test_missing_reservoir_file_returns_none(tmp_path):
    obs = _obs(obs_file=str(tmp_path / "o.csv"))
    (tmp_path / "o.csv").write_text("date,wlevel_ft\n2018-01-01,20\n")
    s = analyze_one_observation_plus(obs, "Calibration", 2018, 0,
        tmp_path / "Output", tmp_path / "A", make_plot=False)
    assert s is None


# ── 실제 Palau ngeri 자료(있을 때만) ─────────────────────────────────────────

@pytest.mark.skipif(not (_NGERI / "reservoir_day.txt").is_file() or not _OBS.is_file(),
                    reason="Palau ngeri 저수지 출력 또는 관측 없음")
def test_real_ngeri_wlevel_endtoend(tmp_path):
    out_dir = tmp_path / "Output"; out_dir.mkdir()
    # 실제 reservoir_day.txt → rename 규칙에 맞게 복사
    shutil.copy(_NGERI / "reservoir_day.txt", out_dir / "reservoir_day-Calibration.txt")

    obs = _obs(obs_file=str(_OBS), shape_factor=1.0, datum_m=0.0)
    s = analyze_one_observation_plus(
        obs, "Calibration", syear=1980, nyskip=0,
        out_dir=out_dir, analysis_dir=tmp_path / "Analysis", make_plot=False,
    )
    assert s is not None
    # 관측 2018–2023 과 모의 1980–2024 의 겹침 → 수백~수천 일
    assert s["n_daily"] > 500
    # 지표가 유한값으로 산출
    assert np.isfinite(s["daily_pbias"])
    assert "daily_nse" in s and "monthly_nse" in s
    assert (tmp_path / "Analysis" / "Calibration_ngerimel_wlevel_4-daily.csv").is_file()
    print("REAL ngeri wlevel metrics:", {k: round(v, 3) for k, v in s.items()
                                          if isinstance(v, float)})


@pytest.mark.skipif(not _YAML.is_file(), reason="Palau config 없음")
def test_palau_yaml_parses_wlevel_observation():
    from swat_py.config.env import load_config
    cfg = load_config(_YAML)
    obs = [o for o in cfg.Observations if o.id == "ngerimel"]
    assert len(obs) == 1
    o = obs[0]
    assert o.variable == "wlevel" and o.outlet_id == 4      # gis_id 상속(reservoir 링크)
    assert o.obs_column == "wlevel_ft"
    assert o.reservoir == "ngerimel"
    r = cfg.Reservoirs["ngerimel"]
    assert r.gis_id == 4 and r.withdrawal_m3s == pytest.approx(0.0438)
    assert r.spillway_ft == 45.0 and r.bottom_ft == pytest.approx(23.34)


# ── 곡선 + 취수 + datum 배선 (합성) ───────────────────────────────────────────

def _make_curve_csv(path):
    path.write_text("elev_ft,storage_m3,note\n"
                    "0,0,bottom\n45,90000,spillway\n50,100000,crest\n")


def test_curve_withdrawal_datum_wiring(tmp_path):
    from swat_py.config.env import _Reservoir
    out_dir = tmp_path / "Output"; out_dir.mkdir()
    dates = pd.date_range("2020-01-01", periods=6, freq="D")
    # 유입 큰 날 → 만수/월류, 유입 0 날 → 취수로 저하
    hdr = "jday mon day yr unit gis_id name area flo_in precip evap seep flo_stor flo_out\n"
    lines = ["t\n", hdr, "  ha m3 m3 m3 m3 m3 m3\n"]
    flo_ins = [200000, 0, 0, 0, 0, 0]
    for d, fi in zip(dates, flo_ins):
        lines.append(f"{d.dayofyear} {d.month} {d.day} {d.year} 1 4 res4 "
                     f"1.0 {fi} 0 0 0 95000 0\n")
    (out_dir / "reservoir_day-Calibration.txt").write_text("".join(lines))

    curve_csv = tmp_path / "curve.csv"; _make_curve_csv(curve_csv)
    obs_csv = tmp_path / "o.csv"
    pd.DataFrame({"date": dates, "wlevel_ft": [23.0]*6}).to_csv(obs_csv, index=False)

    res = _Reservoir(name="r", gis_id=4, stage_storage_file=str(curve_csv),
                     spillway_ft=45.0, bottom_ft=0.0, obs_datum_offset_ft=-22.0,
                     withdrawal_m3s=0.05)   # 0.05*86400=4320 m³/day
    obs = _obs(obs_file=str(obs_csv), obs_column="wlevel_ft")
    obs.reservoir = "r"

    s = analyze_one_observation_plus(
        obs, "Calibration", 2020, 0, out_dir, tmp_path / "A",
        make_plot=False, reservoirs={"r": res},
    )
    assert s is not None and s["n_daily"] == 6
    # 곡선 사용 → daily csv 의 sim(수위) 이 존재하고, 취수로 저하 후 datum(-22) 적용
    daily = pd.read_csv(tmp_path / "A" / "Calibration_ngerimel_wlevel_4-daily.csv")
    assert "sim" in daily.columns
    # 1일차: 유입 큰 뒤 만수(45ft)+datum(-22)=23ft 부근
    assert daily["sim"].iloc[0] == pytest.approx(23.0, abs=1.0)
    # 이후 취수로 하강(단조 감소 경향) → 마지막날 < 첫날
    assert daily["sim"].iloc[-1] < daily["sim"].iloc[0]


def test_auto_calibration_reservoir_routing(tmp_path, monkeypatch):
    """auto._extract_obs_from_swat_output 가 wlevel obs 를 reservoir_day 로 라우팅."""
    from types import SimpleNamespace
    from swat_py.config.env import _Reservoir
    import swat_py.calibration.auto as auto

    run_dir = tmp_path / "run"; run_dir.mkdir()
    dates = pd.date_range("2020-01-01", periods=4, freq="D")
    hdr = "jday mon day yr unit gis_id name area flo_in precip evap seep flo_stor flo_out\n"
    lines = ["t\n", hdr, "  ha\n"]
    for d in dates:
        lines.append(f"{d.dayofyear} {d.month} {d.day} {d.year} 1 4 res4 "
                     f"1.0 0 0 0 0 45000 0\n")
    (run_dir / "reservoir_day.txt").write_text("".join(lines))

    curve_csv = tmp_path / "curve.csv"; _make_curve_csv(curve_csv)
    (run_dir / "SWAT-Plus.exe").write_text("dummy")     # exe 존재만
    dummy_exe = tmp_path / "SWAT-Plus.exe"; dummy_exe.write_text("dummy")

    # SWAT 실행을 no-op 로 대체
    monkeypatch.setattr(auto.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stderr=b""))

    res = _Reservoir(name="r", gis_id=4, stage_storage_file=str(curve_csv),
                     spillway_ft=45.0, bottom_ft=0.0, obs_datum_offset_ft=-22.0)
    obs = _obs(); obs.reservoir = "r"
    ctx = SimpleNamespace(
        exe_path=dummy_exe,
        cfg=SimpleNamespace(Executable="SWAT-Plus.exe", ModelType="swat_plus",
                            Reservoirs={"r": res}, SimStartDate="2020-01-01"),
        observations=[obs],
    )
    out = auto._extract_obs_from_swat_output(run_dir, ctx)
    assert obs.id in out
    d, v = out[obs.id]
    assert len(v) == 4
    # flo_stor=45000 → 곡선 22.5ft + datum(-22) = 0.5ft
    assert v[0] == pytest.approx(0.5, abs=0.01)


def test_no_withdrawal_uses_flo_stor(tmp_path):
    """취수 미설정 시 SWAT+ flo_stor 를 그대로 곡선 환산."""
    from swat_py.config.env import _Reservoir
    out_dir = tmp_path / "Output"; out_dir.mkdir()
    dates = pd.date_range("2020-01-01", periods=3, freq="D")
    hdr = "jday mon day yr unit gis_id name area flo_in precip evap seep flo_stor flo_out\n"
    lines = ["t\n", hdr, "  ha\n"]
    for d in dates:
        lines.append(f"{d.dayofyear} {d.month} {d.day} {d.year} 1 4 res4 "
                     f"1.0 0 0 0 0 45000 0\n")   # flo_stor=45000 → 곡선상 22.5ft
    (out_dir / "reservoir_day-Calibration.txt").write_text("".join(lines))
    curve_csv = tmp_path / "curve.csv"; _make_curve_csv(curve_csv)
    obs_csv = tmp_path / "o.csv"
    pd.DataFrame({"date": dates, "wlevel_ft": [22.5]*3}).to_csv(obs_csv, index=False)

    res = _Reservoir(name="r", gis_id=4, stage_storage_file=str(curve_csv),
                     spillway_ft=45.0, bottom_ft=0.0)   # withdrawal_m3s=0(기본)
    obs = _obs(obs_file=str(obs_csv)); obs.reservoir = "r"
    s = analyze_one_observation_plus(obs, "Calibration", 2020, 0, out_dir,
        tmp_path / "A", make_plot=False, reservoirs={"r": res})
    daily = pd.read_csv(tmp_path / "A" / "Calibration_ngerimel_wlevel_4-daily.csv")
    # flo_stor=45000 → 곡선(0@0, 90000@45) → 22.5 ft
    assert daily["sim"].iloc[0] == pytest.approx(22.5, abs=0.01)
