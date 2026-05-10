"""hourly→daily 집계 + 매핑 템플릿 검증."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from util_py.weather_std import (
    STD_DAILY_COLUMNS,
    STD_HOURLY_COLUMNS,
    aggregate_std_hourly_to_daily,
)


# ── hourly → daily 집계 ─────────────────────────────────────────────────────

def _make_hourly_csv(path: Path) -> Path:
    """24시간 × 2일 합성 hourly std CSV."""
    rows = []
    for d in (1, 2):
        for h in range(24):
            rows.append({
                "datetime": f"2024-01-0{d} {h:02d}:00",
                "pcp_mm":   0.5 if h == 12 else 0.0,
                "tavg_c":   20.0 + h * 0.5,            # 20~31.5 °C
                "tdew_c":   15.0,
                "hmd_pct":  72.0,
                "slr_wm2":  300.0 if 6 <= h <= 17 else 0.0,
                "ws10_ms":  3.0 + h * 0.1,
                "ws2_ms":   2.244 + h * 0.0748,
                "source":   "ERA5",
            })
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_aggregate_hourly_to_daily(tmp_path) -> None:
    h = _make_hourly_csv(tmp_path / "h.csv")
    d_path = tmp_path / "d.csv"
    aggregate_std_hourly_to_daily(h, d_path)

    df = pd.read_csv(d_path)
    assert list(df.columns) == STD_DAILY_COLUMNS
    assert len(df) == 2

    # 일 합계 강수
    assert df["pcp_mm"].iloc[0] == pytest.approx(0.5, abs=0.01)
    assert df["pcp_mm"].iloc[1] == pytest.approx(0.5, abs=0.01)
    # 일 max/min/avg 기온
    assert df["tmax_c"].iloc[0] == pytest.approx(31.5, abs=0.01)   # h=23
    assert df["tmin_c"].iloc[0] == pytest.approx(20.0, abs=0.01)   # h=0
    assert df["tavg_c"].iloc[0] == pytest.approx(25.75, abs=0.01)
    # 일 적산 일사: 12시간 × 300 W/m² × 3600 / 1e6 = 12.96 MJ/m²
    assert df["slr_mjm2"].iloc[0] == pytest.approx(12.96, abs=0.01)


# ── 매핑 템플릿 ─────────────────────────────────────────────────────────────

def _templates_dir() -> Path:
    import util_py
    return Path(util_py.__file__).parent / "templates" / "weather_mapping"


@pytest.mark.parametrize("name", ["generic.yaml", "kma.yaml", "bom.yaml"])
def test_template_yaml_loads_valid(name: str) -> None:
    p = _templates_dir() / name
    assert p.is_file(), f"템플릿 미배치: {p}"
    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "columns" in data
    assert "units" in data
    assert "wind_height_m" in data
    assert "date" in data["columns"]
    assert "pcp_mm" in data["columns"]


def test_template_bom_uses_kmh_wind() -> None:
    p = _templates_dir() / "bom.yaml"
    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["units"]["wind"] == "kmh"


def test_template_kma_korean_columns() -> None:
    p = _templates_dir() / "kma.yaml"
    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["columns"]["pcp_mm"] == "강수량(mm)"
    assert data["columns"]["tmax_c"] == "기온최고(°C)"


# ── swat_py adapter ─────────────────────────────────────────────────────────

def test_swat_py_adapter_writes_pcp(tmp_path) -> None:
    """swat_py.io.weather_std_adapter 기본 동작 확인."""
    pytest.importorskip("swat_py")
    from swat_py.io import StationMeta, write_swat_plus_station

    # 합성 std daily
    std = tmp_path / "std.csv"
    pd.DataFrame({
        "date":    pd.date_range("2024-01-01", periods=5),
        "pcp_mm":  [0.0, 1.5, 0.0, 12.3, 0.5],
        "tmax_c":  [29.0, 28.5, 30.1, 27.0, 28.8],
        "tmin_c":  [22.0, 21.5, 22.9, 21.5, 22.5],
        "tavg_c":  [25.5, 25.0, 26.5, 24.3, 25.7],
        "tdew_c":  [20.0, 19.5, 21.0, 22.5, 20.5],
        "hmd_pct": [72.0, 71.5, 73.0, 89.0, 73.5],
        "slr_mjm2":[20.0, 18.0, 22.0, 15.0, 21.0],
        "ws10_ms": [4.0, 3.5, 5.0, 4.5, 4.0],
        "ws2_ms":  [2.99, 2.62, 3.74, 3.37, 2.99],
        "source":  ["ERA5"] * 5,
    }).to_csv(std, index=False)

    out = tmp_path / "swat"
    files = write_swat_plus_station(
        std, out,
        StationMeta(id="ERA001", lat=-21.20, lon=-159.81, elev=5.0),
    )
    assert set(files.keys()) == {"pcp", "tmp", "hmd", "slr", "wnd"}

    pcp_text = (out / "ERA001.pcp").read_text(encoding="utf-8")
    assert "ERA001.pcp" in pcp_text
    assert "-21.20000" in pcp_text   # lat
    assert "year" in pcp_text         # data header


def test_swat_py_adapter_hmd_percent_to_fraction(tmp_path) -> None:
    """SWAT-Plus 는 hmd_frac (0–1) 사용 — std hmd_pct 를 /100 변환."""
    pytest.importorskip("swat_py")
    from swat_py.io import StationMeta, write_swat_plus_station

    std = tmp_path / "std.csv"
    pd.DataFrame({
        "date":    ["2024-01-01"],
        "pcp_mm":  [0.0],
        "tmax_c":  [29.0], "tmin_c": [22.0], "tavg_c": [25.0], "tdew_c": [20.0],
        "hmd_pct": [75.0],   # ★ 75% → 0.750
        "slr_mjm2":[20.0],
        "ws10_ms": [4.0], "ws2_ms": [2.99],
        "source":  ["ERA5"],
    }).to_csv(std, index=False)

    out = tmp_path / "swat"
    write_swat_plus_station(std, out,
                             StationMeta(id="X", lat=0, lon=0, elev=0),
                             variables=["hmd"])

    text = (out / "X.hmd").read_text(encoding="utf-8")
    # data 줄에 0.75 (또는 0.750) 가 있어야 함, 75 가 아니라
    assert " 0.750" in text


def test_swat_py_adapter_wnd_uses_ws2(tmp_path) -> None:
    """SWAT-Plus 풍속은 2 m → ws2_ms 사용."""
    pytest.importorskip("swat_py")
    from swat_py.io import StationMeta, write_swat_plus_station

    std = tmp_path / "std.csv"
    pd.DataFrame({
        "date":    ["2024-01-01"],
        "pcp_mm":  [0.0],
        "tmax_c":  [29.0], "tmin_c": [22.0], "tavg_c": [25.0], "tdew_c": [20.0],
        "hmd_pct": [75.0],
        "slr_mjm2":[20.0],
        "ws10_ms": [10.0],   # 10 m
        "ws2_ms":  [7.48],   # ws10 × 0.748 (FAO-56)
        "source":  ["ERA5"],
    }).to_csv(std, index=False)

    out = tmp_path / "swat"
    write_swat_plus_station(std, out,
                             StationMeta(id="X", lat=0, lon=0, elev=0),
                             variables=["wnd"])

    text = (out / "X.wnd").read_text(encoding="utf-8")
    assert " 7.480" in text   # ws2_ms 가 사용되어야 함
    assert "10.000" not in text or text.count("10.000") < 1   # ws10 아님
