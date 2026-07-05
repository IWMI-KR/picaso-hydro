"""유역별 Tank 모형 forcing 구성 — 강수 매핑 + PET + 유역면적.

관측소(유역)별로 config 의 강수 매핑에 따라 강우스테이션(단일/가중다중)을 골라
표준 weather CSV(`io.load_std_daily`)에서 강수·기상을 읽고, PET 를 산정해
{obs_id: DataFrame[date, pcp_mm, pet_mm]} 및 유역면적(km²)을 반환한다.

강수 매핑 규칙 (config `tank.precip_mapping`)
  - "default": 전 유역 공통 스테이션 (예: "918430")
  - "<obs_id>": 해당 유역 전용 — 문자열(단일) 또는 [[station, weight], ...] (가중)
PET 는 대표(첫/최대가중) 스테이션의 기상으로 산정하며, 그 스테이션의 **위도**는
stations 메타 CSV(`cfg.StnFile`, 예: stations-hydro.csv)의 ID→Lat 맵핑에서 가져온다.
파일에 없는 스테이션만 `tank.default_lat` 로 폴백(이때 경고).
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from swat_py.io import load_std_daily
from swat_py.tank.pet import compute_pet


def _resolve_stations(mapping: dict, obs_id: str) -> List[Tuple[str, float]]:
    """obs_id → [(station_code, weight), ...] (정규화된 가중치)."""
    spec = mapping.get(obs_id, mapping.get("default"))
    if spec is None:
        raise ValueError(f"precip_mapping 에 '{obs_id}' 도 'default' 도 없음")
    if isinstance(spec, str):
        return [(spec, 1.0)]
    # 리스트: [[station, weight], ...] 또는 [station, ...]
    pairs: List[Tuple[str, float]] = []
    for item in spec:
        if isinstance(item, (list, tuple)):
            pairs.append((str(item[0]), float(item[1])))
        else:
            pairs.append((str(item), 1.0))
    tot = sum(w for _, w in pairs) or 1.0
    return [(s, w / tot) for s, w in pairs]


def _load_lat_lookup(meta_csv: str | Path) -> Dict[str, float]:
    """관측소 메타 CSV → {station_code: lat}.

    컬럼명을 대소문자 무관하게 인식해 SWAT+ 공용 stations CSV(ID,Lat,Lon,Elev)와
    wgn_stations.csv(id,name,lat,...) 둘 다 지원한다. 스테이션 코드 키는
    name > id > 첫 컬럼 우선(precip_mapping 코드와 매칭).
    """
    p = Path(meta_csv)
    if not p.is_file():
        return {}
    df = pd.read_csv(p)
    cols = {str(c).strip().lower(): c for c in df.columns}
    lat_col = cols.get("lat")
    if lat_col is None:
        return {}
    key_col = cols.get("name") or cols.get("id") or df.columns[0]
    out: Dict[str, float] = {}
    # 컬럼 단위로 순회 — 행(Series) 순회는 정수 코드를 float 로 승격시켜 키를
    # "918430.0" 처럼 만든다. 정수형 코드는 .0 을 제거해 precip_mapping 과 매칭.
    for code, lat in zip(df[key_col].tolist(), df[lat_col].tolist()):
        c = str(code)
        if c.endswith(".0"):
            c = c[:-2]
        try:
            out[c] = float(lat)
        except (TypeError, ValueError):
            continue
    return out


def _load_areas_from_csv(csv: str | Path, key_col: str, area_col: str) -> Dict[str, float]:
    p = Path(csv)
    if not p.is_file():
        return {}
    df = pd.read_csv(p)
    return {str(r[key_col]): float(r[area_col]) for _, r in df.iterrows()}


def build_forcing(cfg) -> Tuple[Dict[str, pd.DataFrame], Dict[str, float]]:
    """cfg.Tank + cfg.Observations → (forcing_by_obs, area_by_obs).

    Returns
    -------
    forcing : {obs_id: DataFrame[date, pcp_mm, pet_mm]}
    areas   : {obs_id: area_km2}
    """
    tk = cfg.Tank
    # 기상자료는 SWAT+와 동일 소스: 강수 CSV 폴더=cfg.ObsDayDir(공통 obs_weather_std),
    # 관측소 위도 메타=cfg.ObsDayDir/cfg.StnFile (stations 메타 CSV).
    weather_dir = Path(cfg.ObsDayDir)
    mapping = dict(tk.precip_mapping or {})
    lat_lookup = _load_lat_lookup(weather_dir / cfg.StnFile) if cfg.StnFile else {}

    # 유역면적: dict 우선, 없으면 CSV
    areas = dict(tk.basin_areas or {})
    if not areas and tk.basin_area_csv:
        areas = _load_areas_from_csv(tk.basin_area_csv, tk.basin_area_key, tk.basin_area_col)

    def _load_station(code: str) -> pd.DataFrame:
        f = weather_dir / f"{code}.csv"
        if not f.is_file():
            raise FileNotFoundError(f"weather CSV 없음: {f}")
        return load_std_daily(f)

    forcing: Dict[str, pd.DataFrame] = {}
    area_by_obs: Dict[str, float] = {}
    cache: Dict[str, pd.DataFrame] = {}

    for obs in cfg.Observations:
        pairs = _resolve_stations(mapping, obs.id)
        # 대표 스테이션(최대 가중) — PET·위도 기준
        primary = max(pairs, key=lambda sw: sw[1])[0]
        for code, _ in pairs:
            cache.setdefault(code, _load_station(code))

        # 가중 강수 (공통 날짜)
        base = cache[primary][["date"]].copy()
        pcp = None
        for code, w in pairs:
            s = cache[code][["date", "pcp_mm"]].rename(columns={"pcp_mm": code})
            base = base.merge(s, on="date", how="left")
            col = base[code].fillna(0.0) * w
            pcp = col if pcp is None else pcp + col
        base["pcp_mm"] = pcp

        # PET 위도 — stations 메타(cfg.StnFile)의 ID→Lat 맵핑에서 대표 스테이션 lat.
        # 파일에 없을 때만 default_lat 로 폴백하고 경고(무엇을 썼는지 명확히).
        if primary in lat_lookup:
            lat = lat_lookup[primary]
        else:
            lat = tk.default_lat
            warnings.warn(
                f"[tank] 스테이션 '{primary}' 위도가 '{cfg.StnFile}' 에 없어 "
                f"tank.default_lat={lat} 사용 (obs={obs.id})",
                UserWarning, stacklevel=2,
            )
        pet = compute_pet(cache[primary], tk.pet_method, lat)
        pet_df = pet.rename("pet_mm").reset_index().rename(columns={"index": "date"})
        out = base[["date", "pcp_mm"]].merge(pet_df, on="date", how="left")
        out["pet_mm"] = out["pet_mm"].fillna(0.0)

        forcing[obs.id] = out.sort_values("date").reset_index(drop=True)
        if obs.id not in areas:
            raise ValueError(f"유역면적 미지정: '{obs.id}' (tank.basin_areas 또는 CSV 확인)")
        area_by_obs[obs.id] = float(areas[obs.id])

    return forcing, area_by_obs
