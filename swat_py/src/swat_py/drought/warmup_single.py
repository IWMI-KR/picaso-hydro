"""예측 base 의 warm-up 기상을 **평년과 같은 단일 관측소 기준**으로 맞춘다.

왜 필요한가
-----------
평년(Historical) 실행은 ``stations-acidwg.csv`` 의 장기 관측소 **하나**로 전 유역을
재배정해 돌리고, 그 산출물에서 평년선(hist_mean)과 FDC 임계(Q70/Q90/Q95)를 만든다.
예측 상세화(acidwg)도 같은 관측소 하나를 쓴다. 그러므로 예측 base 의 warm-up 도
같은 관측소여야 비교가 성립한다.

그런데 예측 base 는 검보정용 다지점 우량계 연결을 그대로 쓰고 있었다. 쿡 실측
3.4년 합계로 보면 918430 2,754mm 인데 461303 6,232 · 427608 9,393 · 461412 6,898mm 라,
다지점 warm-up 은 기준보다 **1.8~2.3배 젖은 상태**에서 예측을 시작한다. 유출은
강수에 비선형이라(같은 범주 멤버에서 13~140배 차이 관측) 이 차이가 크게 증폭된다.

운영 예보의 공백
----------------
단일 관측소 실측은 예보 시작까지 닿지 않는다(쿡 918430 은 2024-12-31 까지).
그 공백은 **같은 관측소 최근접 ERA5 격자**를 **월별 편의보정**해 채운다.
평년 날씨(wgn·대표연도)로 채우면 진행 중인 가뭄을 모형이 모르게 되는데,
선행조건이 유량을 좌우하므로 가뭄예측에서는 치명적이다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from swat_py.drought.warmup_era5 import (
    _haversine_km,
    _rebuild_var_file,
    era5_warmup_frame,
    load_grid_points,
)

_MISSING = -98.0          # 이 값 이하를 결측으로 본다(SWAT+ 관례 -99)


def read_station_daily(path: Path, cols: List[str]) -> Tuple[pd.DataFrame, Dict]:
    """``*.pcp``/``*.tmp`` → (일자료 DataFrame, 헤더정보{lat, lon}).

    결측(-99)은 NaN 으로 돌려준다 — 보정·대체 판단을 호출부에서 하게 한다.
    """
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    t = lines[2].split()
    meta = {"lat": float(t[2]), "lon": float(t[3])}
    rows = []
    for ln in lines[3:]:
        p = ln.split()
        if len(p) < 2 + len(cols):
            continue
        yr, jd = int(float(p[0])), int(float(p[1]))
        d = pd.Timestamp(yr, 1, 1) + pd.Timedelta(days=jd - 1)
        vals = [float(x) for x in p[2:2 + len(cols)]]
        rows.append([d] + [float("nan") if v <= _MISSING else v for v in vals])
    return pd.DataFrame(rows, columns=["date"] + cols), meta


def monthly_pcp_factor(obs: pd.Series, era: pd.Series,
                       month: pd.Series) -> Dict[int, float]:
    """월별 강수 편의보정 **계수**(관측합/ERA5합). 자료가 없으면 1.0.

    비율 보정이라 0mm 는 0mm 로 남는다(강수일수는 ERA5 를 따른다).
    """
    out = {}
    for m in range(1, 13):
        k = (month == m) & obs.notna() & era.notna()
        o, e = obs[k].sum(), era[k].sum()
        out[m] = float(o / e) if e > 0 else 1.0
    return out


def monthly_temp_offset(obs: pd.Series, era: pd.Series,
                        month: pd.Series) -> Dict[int, float]:
    """월별 기온 편의보정 **가산값**(관측평균−ERA5평균). 자료가 없으면 0.0."""
    out = {}
    for m in range(1, 13):
        k = (month == m) & obs.notna() & era.notna()
        out[m] = float(obs[k].mean() - era[k].mean()) if k.any() else 0.0
    return out


def nearest_grid_id(lat: float, lon: float, grid_points_csv) -> Tuple[str, float]:
    """관측소 최근접 ERA5 격자 → (격자 ID, 거리 km)."""
    g = load_grid_points(grid_points_csv)
    best, bd = None, float("inf")
    for r in g.itertuples():
        d = _haversine_km(lat, lon, float(r.Lat), float(r.Lon))
        if d < bd:
            best, bd = str(r.ID), d
    return best, bd


def fill_single_station_warmup(base_dir: Path, station: str, *,
                               start: pd.Timestamp, end: pd.Timestamp,
                               grid_points_csv: Optional[str] = None,
                               grid_daily_std_dir: Optional[str] = None) -> Dict:
    """``{station}.pcp/.tmp`` 를 [start, end] 로 재구성 — 실측 우선, 공백은 보정 ERA5.

    Returns
    -------
    dict : {"station", "grid", "dist_km", "obs_last", "filled_days", "factors"}
    """
    base_dir = Path(base_dir)
    info: Dict = {"station": station, "grid": None, "dist_km": None,
                  "obs_last": None, "filled_days": 0, "factors": {}}
    spec = [("pcp", ["pcp_mm"]), ("tmp", ["tmax_c", "tmin_c"])]
    full = pd.date_range(start, end, freq="D")

    # 관측소 실측 적재 + 최근접 격자
    obs_data, meta = {}, None
    for ext, cols in spec:
        p = base_dir / f"{station}.{ext}"
        if not p.is_file():
            raise FileNotFoundError(f"단일소 기상파일 없음: {p}")
        df, m = read_station_daily(p, cols)
        obs_data[ext] = df
        meta = meta or m
    last = max((d["date"][d[c[0]].notna()].max() for (e, c), d in
                zip(spec, obs_data.values())), default=pd.NaT)
    info["obs_last"] = None if pd.isna(last) else str(last.date())

    era = None
    if grid_points_csv and grid_daily_std_dir and Path(grid_daily_std_dir).is_dir():
        gid, dist = nearest_grid_id(meta["lat"], meta["lon"], grid_points_csv)
        info["grid"], info["dist_km"] = gid, round(dist, 1)
        era = era5_warmup_frame(gid, grid_daily_std_dir, start, end)
        era = era.replace(-99.0, float("nan"))

    for ext, cols in spec:
        obs = obs_data[ext].set_index("date").reindex(full)
        out = obs[cols].copy()
        if era is not None:
            e = era.set_index("date").reindex(full)
            mon = pd.Series(full.month, index=full)
            if ext == "pcp":
                f = monthly_pcp_factor(obs["pcp_mm"], e["pcp_mm"], mon)
                info["factors"]["pcp"] = {k: round(v, 3) for k, v in f.items()}
                cor = e["pcp_mm"] * mon.map(f)
            else:
                cor = pd.DataFrame(index=full)
                for c, ec in (("tmax_c", "tmax_c"), ("tmin_c", "tmin_c")):
                    o = monthly_temp_offset(obs[c], e[ec], mon)
                    info["factors"][c] = {k: round(v, 2) for k, v in o.items()}
                    cor[c] = e[ec] + mon.map(o)
            for c in cols:
                src = cor if ext == "pcp" else cor[c]
                gap = out[c].isna()
                out.loc[gap, c] = (src[gap] if ext == "pcp" else src[gap])
                info["filled_days"] = max(info["filled_days"],
                                          int((gap & out[c].notna()).sum()))
        out = out.fillna(-99.0).reset_index().rename(columns={"index": "date"})
        _rebuild_var_file(base_dir / f"{station}.{ext}", out, cols)
    return info
