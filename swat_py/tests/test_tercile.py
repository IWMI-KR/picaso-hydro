"""⑥ 3분위(BN·NN·AN) 확률 — 경계 산정·분류·CSV·파이."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swat_py.drought.figure import make_tercile_pie
from swat_py.drought.tercile import (
    MIN_CLIM_SAMPLE, TERCILES, build_terciles, classify_tercile,
    is_reservoir_outlet, load_members, month_samples,
    monthly_values, season_sample, tercile_bounds, tercile_probabilities,
    tercile_rows, tercile_season_row, write_tercile_csvs,
)


# ── 경계·분류 ────────────────────────────────────────────────────────────────

def test_bounds_split_sample_in_thirds():
    t33, t67 = tercile_bounds(range(1, 100))      # 1..99
    assert t33 == pytest.approx(33.66, abs=0.1)
    assert t67 == pytest.approx(66.33, abs=0.1)


def test_bounds_nan_when_sample_too_small():
    t33, t67 = tercile_bounds(range(MIN_CLIM_SAMPLE - 1))
    assert np.isnan(t33) and np.isnan(t67)


def test_classify_boundary_goes_to_drier_side():
    assert classify_tercile(0.5, 1.0, 2.0) == "BN"
    assert classify_tercile(1.0, 1.0, 2.0) == "BN"      # 경계값 = 아래쪽
    assert classify_tercile(1.5, 1.0, 2.0) == "NN"
    assert classify_tercile(2.0, 1.0, 2.0) == "NN"
    assert classify_tercile(2.5, 1.0, 2.0) == "AN"
    assert classify_tercile(float("nan"), 1.0, 2.0) == "NA"


def test_probabilities_sum_to_100():
    vals = [0.5] * 20 + [1.5] * 50 + [3.0] * 30
    tp = tercile_probabilities(vals, 1.0, 2.0)
    assert tp["BN"] == pytest.approx(20.0)
    assert tp["NN"] == pytest.approx(50.0)
    assert tp["AN"] == pytest.approx(30.0)
    assert tp["most_likely"] == "NN"
    assert tp["n"] == 100


def test_probabilities_nan_when_bounds_unknown():
    """평년 표본이 모자라면 0% 가 아니라 NaN·NA — '평년 이하 없음'처럼 보이면 안 된다."""
    tp = tercile_probabilities([1, 2, 3], float("nan"), float("nan"))
    assert all(np.isnan(tp[k]) for k in TERCILES)
    assert tp["most_likely"] == "NA"


def test_probabilities_skip_nan_members():
    tp = tercile_probabilities([0.5, np.nan, 3.0], 1.0, 2.0)
    assert tp["n"] == 2
    assert tp["BN"] == pytest.approx(50.0) and tp["AN"] == pytest.approx(50.0)


# ── 평년 표본 ────────────────────────────────────────────────────────────────

def _clim_frame(years=range(1985, 2024)):
    """월 시계열 wide CSV 모사 — 값 = 연도 순번(경계가 예측 가능해짐)."""
    rows = []
    for i, y in enumerate(years):
        for m in range(1, 13):
            rows.append({"date": f"{y}-{m:02d}-01", "avana": float(i) + m / 100.0})
    return pd.DataFrame(rows)


def test_month_samples_one_value_per_year():
    mv = monthly_values(_clim_frame(), "avana")
    ms = month_samples(mv)
    assert set(ms) == set(range(1, 13))
    assert len(ms[9]) == 39                      # 1985~2023


def test_season_sample_crosses_year_boundary():
    """NDJ 는 11·12월과 **다음 해** 1월 평균이라, 마지막 해는 표본에서 빠진다."""
    mv = monthly_values(_clim_frame(), "avana")
    son = season_sample(mv, [9, 10, 11])         # 해를 넘지 않음 → 39개
    ndj = season_sample(mv, [11, 12, 1])         # 2023-11 ~ 2024-01 은 미완 → 38개
    assert len(son) == 39
    assert len(ndj) == 38


def test_season_sample_is_mean_of_three_months():
    mv = monthly_values(_clim_frame(years=[2000]), "avana")
    assert season_sample(mv, [9, 10, 11])[0] == pytest.approx((0.09 + 0.10 + 0.11) / 3)


# ── 행·CSV ───────────────────────────────────────────────────────────────────

def _mem():
    """3멤버 × 3개월 — 9월 전부 건조, 11월 전부 습윤."""
    return pd.DataFrame([[0.0, 5.0, 100.0]] * 3, columns=[9, 10, 11])


def test_tercile_rows_carry_bounds_and_ym():
    mv = monthly_values(_clim_frame(), "avana")
    rows = tercile_rows(_mem(), [9, 10, 11],
                        {9: "2026-09", 10: "2026-10", 11: "2026-11"},
                        month_samples(mv), clim_years="1985_2023")
    assert [r["ym"] for r in rows] == ["2026-09", "2026-10", "2026-11"]
    assert rows[0]["most_likely"] == "BN"        # 0.0 < t33
    assert rows[2]["most_likely"] == "AN"        # 100.0 > t67
    r = rows[0]
    assert r["clim_n"] == 39 and r["clim_years"] == "1985_2023"
    assert r["t33"] < r["t67"]


def test_tercile_season_row_uses_member_3month_mean():
    mv = monthly_values(_clim_frame(), "avana")
    row = tercile_season_row(_mem(), [9, 10, 11], "SON",
                             season_sample(mv, [9, 10, 11]), clim_years="1985_2023")
    # 멤버별 3개월 평균 = 35.0 → 계절 평년 분포(0~38)의 상위 1/3보다 큼
    assert row["season"] == "SON" and row["most_likely"] == "AN"
    assert row["AN"] == pytest.approx(100.0)


def test_tercile_season_row_none_without_members():
    assert tercile_season_row(None, [9, 10, 11], "SON", [1.0] * 39) is None


def test_write_csvs_round_trip(tmp_path):
    rows = [{"month": 9, "ym": "2026-09", "BN": 70.0, "NN": 20.0, "AN": 10.0,
             "most_likely": "BN", "n": 1000, "t33": 0.01, "t67": 0.02,
             "clim_n": 39, "clim_years": "1985_2023"}]
    srow = dict(rows[0]); srow.pop("month"); srow.pop("ym"); srow["season"] = "SON"
    written = write_tercile_csvs(tmp_path, rows, srow)
    assert [p.name for p in written] == ["tercile_prob.csv", "tercile_prob_season.csv"]
    back = pd.read_csv(tmp_path / "tercile_prob.csv")
    assert list(back.columns)[:5] == ["month", "ym", "BN", "NN", "AN"]
    assert back.iloc[0]["BN"] == pytest.approx(70.0)


def test_load_members_restores_month_numbers(tmp_path):
    pd.DataFrame({"member": ["m1", "m2"], "2026-09": [1.0, 2.0],
                  "2026-10": [3.0, 4.0]}).set_index("member").to_csv(
        tmp_path / "ensemble_members.csv")
    mem, mon_ym = load_members(tmp_path)
    assert list(mem.columns) == [9, 10]
    assert mon_ym == {9: "2026-09", 10: "2026-10"}


def test_load_members_missing(tmp_path):
    mem, mon_ym = load_members(tmp_path)
    assert mem is None and mon_ym == {}


# ── 그림 ─────────────────────────────────────────────────────────────────────

def _outlet_dir(tmp_path, with_season=True, bounds_ok=True):
    d = tmp_path / "avana"; d.mkdir()
    nan = float("nan")
    rows = [{"month": 9, "ym": "2026-09", "BN": 10.0 if bounds_ok else nan,
             "NN": 30.0 if bounds_ok else nan, "AN": 60.0 if bounds_ok else nan,
             "most_likely": "AN" if bounds_ok else "NA", "n": 1000,
             "t33": 0.01 if bounds_ok else nan, "t67": 0.02 if bounds_ok else nan,
             "clim_n": 39, "clim_years": "1985_2023"},
            {"month": 10, "ym": "2026-10", "BN": 55.0, "NN": 35.0, "AN": 10.0,
             "most_likely": "BN", "n": 1000, "t33": 0.005, "t67": 0.008,
             "clim_n": 39, "clim_years": "1985_2023"}]
    pd.DataFrame(rows).to_csv(d / "tercile_prob.csv", index=False)
    if with_season:
        pd.DataFrame([{"season": "SON", "BN": 40.0, "NN": 40.0, "AN": 20.0,
                       "most_likely": "BN", "n": 1000, "t33": 0.01, "t67": 0.03,
                       "clim_n": 39, "clim_years": "1985_2023"}]).to_csv(
            d / "tercile_prob_season.csv", index=False)
    return d


def test_tercile_pie_filename_distinct_from_stage_pie(tmp_path):
    out = make_tercile_pie(_outlet_dir(tmp_path))
    assert out is not None and out.is_file() and out.stat().st_size > 0
    assert out.name == "dashboard_avana_tercile_pie.png"
    assert out.name != "dashboard_avana_pie.png"


def test_tercile_pie_without_season(tmp_path):
    assert make_tercile_pie(_outlet_dir(tmp_path, with_season=False)).is_file()


def test_tercile_pie_draws_when_bounds_unknown(tmp_path):
    """경계 미산정(NaN) 칸도 '자료 없음'으로 그려지고 예외를 내지 않는다."""
    assert make_tercile_pie(_outlet_dir(tmp_path, bounds_ok=False)).is_file()


def test_tercile_pie_none_without_csv(tmp_path):
    d = tmp_path / "x"; d.mkdir()
    assert make_tercile_pie(d) is None


# ── 저수지는 3분위 미적용 ────────────────────────────────────────────────────

def _thr(d, **kw):
    """수원 폴더의 thresholds.csv 모사 — 기본은 하천(FDC 유량)."""
    row = {"outlet": d.name, "method": "fdc_exceedance", "variable": "flow_cms",
           "normal_watch": 0.02, "watch_warning": 0.01, "warning_crisis": 0.005,
           "n_ensemble": 3}
    row.update(kw)
    pd.DataFrame([row]).to_csv(d / "thresholds.csv", index=False)


def test_is_reservoir_outlet_reads_thresholds(tmp_path):
    stream = tmp_path / "avana"; stream.mkdir(); _thr(stream)
    pct = tmp_path / "res_pct"; pct.mkdir()
    _thr(pct, variable="capacity_pct", method="capacity_fraction")
    lvl = tmp_path / "res_ft"; lvl.mkdir()
    _thr(lvl, variable="water_level_ft", method="level_fraction")
    assert not is_reservoir_outlet(stream)
    assert is_reservoir_outlet(pct) and is_reservoir_outlet(lvl)
    assert not is_reservoir_outlet(tmp_path / "없는폴더")   # 판별 불가 → False


def test_tercile_pie_skips_reservoir(tmp_path):
    """저수지 폴더에 옛 CSV 가 남아 있어도 3분위 파이는 내보내지 않는다."""
    d = _outlet_dir(tmp_path)
    _thr(d, variable="water_level_ft", method="level_fraction")
    assert make_tercile_pie(d) is None
    assert not list(d.glob("*_tercile_pie.png"))


def test_build_terciles_skips_reservoir_outlet(tmp_path):
    """하천만 산출하고 저수지는 사유를 남겨 건너뛴다 — CSV·그림을 만들지 않는다."""
    from types import SimpleNamespace
    prj = tmp_path / "prj"
    clim = prj / "4_drought_risk" / "climatology"; clim.mkdir(parents=True)
    _clim_frame().to_csv(clim / "channel_monthly_1985_2023.csv", index=False)
    root = prj / "4_drought_risk" / "forecast" / "2026_SON"; root.mkdir(parents=True)
    for name in ("avana", "ngerimel"):
        d = root / name; d.mkdir()
        pd.DataFrame({"member": ["m1", "m2", "m3"],
                      "2026-09": [0.0, 0.0, 0.0],
                      "2026-10": [5.0, 5.0, 5.0],
                      "2026-11": [100.0, 100.0, 100.0]}
                     ).set_index("member").to_csv(d / "ensemble_members.csv")
    _thr(root / "avana")
    _thr(root / "ngerimel", variable="water_level_ft", method="level_fraction")
    cfg = SimpleNamespace(
        PrjDir=str(prj), CioNYSKIP=0,
        Drought=SimpleNamespace(syear=1985, eyear=2023,
                                climatology_years=[1985, 2023],
                                climatology_csv=None))
    res = build_terciles(cfg, "2026_SON", make_figure=True, verbose=False)
    assert res["n_outlets"] == 1
    assert [o for o, _ in res["skipped"]] == ["ngerimel"]
    assert "저수지" in res["skipped"][0][1]
    assert (root / "avana" / "tercile_prob.csv").is_file()
    assert (root / "avana" / "dashboard_avana_tercile_pie.png").is_file()
    assert not (root / "ngerimel" / "tercile_prob.csv").exists()
    assert not list((root / "ngerimel").glob("*.png"))
