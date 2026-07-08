"""dashboard JSON NaN→null 정제 — 표준 JSON(Rust/JS) 파서 호환 검증."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from swat_py.dashboard.json_writers import sanitize_json, dumps_json, dump_json


def _strict_parse(s: str):
    """비표준 토큰(NaN/Infinity)을 거부하는 엄격 파서(Rust serde_json/JS 모사)."""
    def _reject(x):
        raise ValueError(f"비표준 JSON 토큰: {x}")
    return json.loads(s, parse_constant=_reject)


def test_sanitize_nan_inf_to_none():
    out = sanitize_json({"a": float("nan"), "b": float("inf"), "c": -float("inf"),
                         "d": 1.5, "e": [np.nan, 2.0, np.float64("nan")]})
    assert out["a"] is None and out["b"] is None and out["c"] is None
    assert out["d"] == 1.5
    assert out["e"] == [None, 2.0, None]


def test_sanitize_numpy_and_timestamp():
    out = sanitize_json({"i": np.int64(3), "f": np.float64(2.5),
                         "arr": np.array([1.0, np.nan]), "t": pd.Timestamp("2016-04-01"),
                         "nat": pd.NaT})
    assert out["i"] == 3 and isinstance(out["i"], int)
    assert out["f"] == 2.5
    assert out["arr"] == [1.0, None]
    assert out["t"] == "2016-04-01"
    assert out["nat"] is None


def test_dumps_json_no_nan_token():
    # dashboard.json series 유사 구조(관측/예측 결측 혼재)
    series = {"month": list(range(1, 13)),
              "observed": [0.37, 0.14, 0.09] + [float("nan")] * 9,
              "forecast_mean": [float("nan")] * 3 + [0.02, 0.12, 0.18] + [float("nan")] * 6}
    s = dumps_json({"outlet": "ngerikiil", "series": series}, indent=1)
    assert "NaN" not in s and "Infinity" not in s          # 비표준 토큰 없음
    parsed = _strict_parse(s)                              # 엄격 파서 통과
    assert parsed["series"]["observed"][3] is None
    assert parsed["series"]["forecast_mean"][0] is None
    assert parsed["series"]["forecast_mean"][3] == 0.02


def test_dataframe_where_none_still_sanitized():
    # DataFrame.where(...,None) 은 float 컬럼에서 None→NaN 재변환 → dumps_json 이 최종 방어
    df = pd.DataFrame({"month": [1, 2, 3], "obs": [1.0, np.nan, 3.0]})
    d = df.where(pd.notna(df), None).to_dict(orient="list")   # obs 에 NaN 잔존
    s = dumps_json({"series": d})
    assert "NaN" not in s
    assert _strict_parse(s)["series"]["obs"] == [1.0, None, 3.0]


def test_dump_json_file_roundtrip(tmp_path):
    p = dump_json(tmp_path / "sub" / "dash.json", {"x": float("nan"), "y": 2})
    txt = p.read_text(encoding="utf-8")
    assert "NaN" not in txt
    assert _strict_parse(txt) == {"x": None, "y": 2}
