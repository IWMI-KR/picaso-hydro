"""calibration — 카탈로그·인자 변경·합성 관측 자료 검증."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from swat_py.calibration import (
    CATALOG,
    CHANGE_TYPES,
    FLOW_PARAMETERS,
    ParameterChange,
    ParameterDef,
    SS_PARAMETERS,
    TN_PARAMETERS,
    TP_PARAMETERS,
    apply_change,
    apply_parameter_set,
    backup_txtinout,
    find_parameter,
    generate_synthetic_flow,
    generate_synthetic_water_quality,
    get_parameters,
    list_all_parameters,
    modify_swat_plus_file,
    summary_dataframe,
)


# ── 카탈로그 ────────────────────────────────────────────────────────────────

def test_catalog_has_4_variables() -> None:
    assert set(CATALOG.keys()) == {"flow", "ss", "tn", "tp"}


def test_flow_parameters_include_standard_set() -> None:
    """SWAT-CUP 표준 보정 인자 (CN2, ALPHA_BF, GW_DELAY 등) 모두 포함."""
    names_2012 = {p.name_swat2012 for p in FLOW_PARAMETERS}
    for std in ("CN2", "ALPHA_BF", "GW_DELAY", "GWQMN", "ESCO", "EPCO",
                "SURLAG", "SOL_AWC", "SOL_K", "CH_N2"):
        assert std in names_2012, f"표준 인자 누락: {std}"


def test_ss_parameters_include_usle_and_sediment_routing() -> None:
    names = {p.name_swat2012 for p in SS_PARAMETERS}
    for std in ("USLE_P", "USLE_K", "USLE_C", "PRF", "SPCON", "SPEXP"):
        assert std in names


def test_tn_parameters_include_nitrogen_cycling() -> None:
    names = {p.name_swat2012 for p in TN_PARAMETERS}
    for std in ("NPERCO", "CMN", "CDN", "HLIFE_NGW"):
        assert std in names


def test_tp_parameters_include_phosphorus_cycling() -> None:
    names = {p.name_swat2012 for p in TP_PARAMETERS}
    for std in ("PPERCO", "PHOSKD", "PSP"):
        assert std in names


def test_get_parameters_by_variable() -> None:
    flow = get_parameters("flow")
    assert len(flow) >= 10
    assert all(isinstance(p, ParameterDef) for p in flow)


def test_get_parameters_invalid_raises() -> None:
    with pytest.raises(ValueError, match="미지원 variable"):
        get_parameters("temperature")


def test_find_parameter_by_name() -> None:
    p = find_parameter("CN2", model_type="swat2012")
    assert p.variable == "flow"
    assert p.name_swat_plus == "cn2"
    p2 = find_parameter("alpha", model_type="swat_plus")
    assert p2.name_swat2012 == "ALPHA_BF"


def test_find_parameter_unknown_raises() -> None:
    with pytest.raises(KeyError):
        find_parameter("NO_SUCH_PARAM")


def test_list_all_parameters() -> None:
    all_p = list_all_parameters()
    assert len(all_p) >= 30   # flow 15 + ss 11 + tn 14 + tp 10 = 50


def test_summary_dataframe() -> None:
    df = summary_dataframe()
    assert "variable" in df.columns
    assert "swat2012" in df.columns
    assert "swat_plus" in df.columns
    assert "range" in df.columns
    assert "change_type" in df.columns


def test_all_change_types_in_catalog_are_valid() -> None:
    for p in list_all_parameters():
        assert p.change_type in CHANGE_TYPES, p.name_swat2012


def test_default_range_min_lt_max() -> None:
    for p in list_all_parameters():
        lo, hi = p.default_range
        assert lo < hi, f"{p.name_swat2012}: range 잘못됨"


# ── apply_change ────────────────────────────────────────────────────────────

def test_apply_absval() -> None:
    assert apply_change(5.0, "absval", 2.5) == 2.5


def test_apply_abschg() -> None:
    assert apply_change(5.0, "abschg", 0.3) == pytest.approx(5.3)
    assert apply_change(5.0, "abschg", -1.0) == pytest.approx(4.0)


def test_apply_relchg() -> None:
    assert apply_change(10.0, "relchg", 0.2) == pytest.approx(12.0)
    assert apply_change(10.0, "relchg", -0.3) == pytest.approx(7.0)


def test_apply_pctchg() -> None:
    assert apply_change(10.0, "pctchg", 25.0) == pytest.approx(12.5)


def test_apply_invalid_change_type_raises() -> None:
    with pytest.raises(ValueError, match="미지원 change_type"):
        apply_change(1.0, "unknown_method", 1.0)


# ── SWAT-Plus 파일 수정 ────────────────────────────────────────────────────

def _write_plus_file(path: Path, header: list, rows: list) -> Path:
    """SWAT-Plus 형식 (1행 주석, 2행 컬럼, 3행+ 데이터)."""
    lines = ["# title comment"]
    lines.append(" ".join(header))
    for r in rows:
        lines.append(" ".join(str(v) for v in r))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_modify_swat_plus_absval(tmp_path) -> None:
    p = _write_plus_file(tmp_path / "basin.bsn",
                         ["surlag", "cn3_swf"], [[4.0, 0.85]])
    changes = modify_swat_plus_file(p, "surlag", 2.5, "absval")
    assert len(changes) == 1
    assert changes[0] == (0, 4.0, 2.5)
    df = pd.read_csv(p, sep=r"\s+", skiprows=1, engine="python")
    assert df["surlag"].iloc[0] == 2.5


def test_modify_swat_plus_relchg(tmp_path) -> None:
    p = _write_plus_file(tmp_path / "hyd.hyd",
                         ["cn2", "esco"],
                         [[75.0, 0.95], [60.0, 0.85]])
    changes = modify_swat_plus_file(p, "cn2", 0.2, "relchg")
    assert len(changes) == 2
    # 75 × 1.2 = 90, 60 × 1.2 = 72
    df = pd.read_csv(p, sep=r"\s+", skiprows=1, engine="python")
    assert df["cn2"].iloc[0] == pytest.approx(90.0)
    assert df["cn2"].iloc[1] == pytest.approx(72.0)


def test_modify_swat_plus_rows_subset(tmp_path) -> None:
    p = _write_plus_file(tmp_path / "soils.sol",
                         ["sol_awc"], [[0.15], [0.20], [0.18]])
    # 인덱스 0, 2 만 변경
    changes = modify_swat_plus_file(p, "sol_awc", 0.05, "abschg", rows=[0, 2])
    assert len(changes) == 2
    df = pd.read_csv(p, sep=r"\s+", skiprows=1, engine="python")
    assert df["sol_awc"].iloc[0] == pytest.approx(0.20)
    assert df["sol_awc"].iloc[1] == pytest.approx(0.20)   # 변경 X
    assert df["sol_awc"].iloc[2] == pytest.approx(0.23)


def test_modify_swat_plus_unknown_param_raises(tmp_path) -> None:
    p = _write_plus_file(tmp_path / "basin.bsn", ["surlag"], [[4.0]])
    with pytest.raises(KeyError, match="파라미터"):
        modify_swat_plus_file(p, "no_such_param", 1.0)


# ── apply_parameter_set 통합 ───────────────────────────────────────────────

def test_apply_parameter_set_swat_plus(tmp_path) -> None:
    """다수 파일 × 다수 인자 일괄 적용."""
    txt = tmp_path / "TxtInOut"; txt.mkdir()
    _write_plus_file(txt / "basin.bsn",      ["surlag"], [[4.0]])
    _write_plus_file(txt / "hydrology.hyd",  ["cn2", "esco"], [[75.0, 0.95]])

    changes = [
        ParameterChange("basin.bsn",     "surlag", 2.0, "absval"),
        ParameterChange("hydrology.hyd", "cn2",    0.10, "relchg"),
        ParameterChange("hydrology.hyd", "esco",   0.80, "absval"),
    ]
    log = apply_parameter_set(txt, changes, model_type="swat_plus")
    assert len(log) == 3

    # 결과 확인
    bsn = pd.read_csv(txt / "basin.bsn", sep=r"\s+", skiprows=1, engine="python")
    assert bsn["surlag"].iloc[0] == 2.0
    hyd = pd.read_csv(txt / "hydrology.hyd", sep=r"\s+", skiprows=1, engine="python")
    assert hyd["cn2"].iloc[0]  == pytest.approx(82.5)   # 75 × 1.1
    assert hyd["esco"].iloc[0] == 0.80


def test_apply_parameter_set_glob_pattern(tmp_path) -> None:
    """*.bsn 같은 글롭 패턴 — 매칭되는 모든 파일에 적용."""
    txt = tmp_path / "TxtInOut"; txt.mkdir()
    _write_plus_file(txt / "basin.bsn",   ["surlag"], [[4.0]])
    _write_plus_file(txt / "another.bsn", ["surlag"], [[10.0]])
    changes = [ParameterChange("*.bsn", "surlag", 1.0, "absval")]
    log = apply_parameter_set(txt, changes)
    assert len(log) == 2   # 두 파일 모두 처리


# ── backup ──────────────────────────────────────────────────────────────────

def test_backup_txtinout(tmp_path) -> None:
    src = tmp_path / "TxtInOut"; src.mkdir()
    _write_plus_file(src / "basin.bsn", ["surlag"], [[4.0]])
    bk = tmp_path / "backup"
    saved = backup_txtinout(src, bk)
    assert saved == bk
    assert (bk / "basin.bsn").is_file()


# ── 합성 관측 자료 ──────────────────────────────────────────────────────────

def test_synthetic_flow_basic() -> None:
    df = generate_synthetic_flow("2020-01-01", "2020-12-31", seed=0)
    assert len(df) == 366  # 윤년
    assert (df["flow_m3s"] > 0).all()   # 모두 양수
    assert "date" in df.columns


def test_synthetic_flow_reproducible() -> None:
    """같은 seed → 같은 결과."""
    df1 = generate_synthetic_flow("2020-01-01", "2020-03-31", seed=42)
    df2 = generate_synthetic_flow("2020-01-01", "2020-03-31", seed=42)
    pd.testing.assert_frame_equal(df1, df2)


def test_synthetic_wq_monthly() -> None:
    df = generate_synthetic_water_quality(
        "2020-01-01", "2020-12-31", time_step="monthly", seed=0
    )
    assert len(df) == 12
    assert set(df.columns) == {"date", "ss_mgl", "tn_mgl", "tp_mgl"}
    assert (df["ss_mgl"] > 0).all()
    assert (df["tp_mgl"] > 0).all()


def test_synthetic_wq_daily() -> None:
    df = generate_synthetic_water_quality(
        "2020-01-01", "2020-01-31", time_step="daily", seed=0
    )
    assert len(df) == 31
