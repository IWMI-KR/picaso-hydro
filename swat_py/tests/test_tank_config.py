"""config.env — yaml `tank:` 블록 파싱 검증."""
from __future__ import annotations

from textwrap import dedent

from swat_py.config import load_config


def _write_yaml(tmp_path, body: str):
    p = tmp_path / "cfg.yaml"
    p.write_text(dedent(body), encoding="utf-8")
    return p


_BASE = """
    project:
      root: "{root}"
      database: "{root}/db"
    model:
      type: "swat_plus"
    simulation:
      start_date: "2012-01-01"
      end_date: "2020-12-31"
"""


def test_tank_defaults_when_absent(tmp_path):
    cfg = load_config(_write_yaml(tmp_path, _BASE.format(root=str(tmp_path).replace("\\", "/"))))
    t = cfg.Tank
    assert t.pet_method == "hargreaves"
    assert t.precip_mapping == {"default": "918430"}
    assert t.n_iterations == 300
    # weather_dir/station_meta_csv 는 제거됨 — 기상은 cfg.ObsDayDir/cfg.StnFile 공용
    assert not hasattr(t, "weather_dir")
    assert not hasattr(t, "station_meta_csv")


def test_tank_full_parse(tmp_path):
    root = str(tmp_path).replace("\\", "/")
    body = _BASE.format(root=root) + """
    tank:
      pet_method: "priestley_taylor"
      precip_mapping:
        default: "918430"
        avatiu: "471301"
        avana: [["427608", 0.7], ["918430", 0.3]]
      basin_areas:
        avatiu: 1.235
        avana: 2.283
      default_lat: -21.2
      parameters:
        a1: [0.1, 0.5]
        a4: [0.001, 0.05]
      method:
        n_iterations: 50
        seed: 7
    """
    cfg = load_config(_write_yaml(tmp_path, body))
    t = cfg.Tank
    assert t.pet_method == "priestley_taylor"
    assert t.precip_mapping["avatiu"] == "471301"
    assert t.precip_mapping["avana"] == [["427608", 0.7], ["918430", 0.3]]
    assert t.basin_areas == {"avatiu": 1.235, "avana": 2.283}
    assert t.parameters["a1"] == [0.1, 0.5]
    assert t.default_lat == -21.2
    assert t.n_iterations == 50 and t.seed == 7
