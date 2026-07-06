"""운영 예보 warm-up 을 최근접 ERA5 격자 일자료로 자동 구성 (단일·다중 관측소 범용).

검보정 SWAT+ 모델의 각 기상관측소(*.pcp 헤더의 위·경도)에 대해
``0_database/era5/grid_points-era5.csv`` 격자점 중 **최근접(haversine)** 을 매칭하고,
``0_database/era5/grid_daily_std/{ERAxxx}.csv`` 일자료로 warm-up 구간 .pcp/.tmp 를
재구성한다. 관측소마다 독립 매칭하므로 관측소 수(단일/다중)에 무관하다.

ERA5 는 ``util-era5-update`` 로 현재시점까지 최신화(그래야 warm-up 이 예보 직전월까지 채워짐).
예보 구간은 이후 acidwg 멤버가 덮어쓴다(ensemble_flow).

프로그램: from swat_py.drought.warmup_era5 import write_era5_warmup
          write_era5_warmup(run_dir, grid_points_csv, grid_daily_std_dir,
                            fyear=..., warmup_years=..., forecast_end=...)
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

_VAL_COLS = {"pcp": ["pcp_mm"], "tmp": ["tmax_c", "tmin_c"]}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 사이 haversine 거리(km)."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def load_grid_points(csv_path) -> pd.DataFrame:
    """격자점 좌표 CSV (Lon,Lat,Elev,ID,...) 로드."""
    return pd.read_csv(csv_path)


def stations_from_pcp(run_dir) -> List[Dict]:
    """run_dir 의 *.pcp 헤더에서 관측소 목록 [{id, lat, lon, elev}] 추출."""
    out = []
    for pcp in sorted(Path(run_dir).glob("*.pcp")):
        lines = pcp.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) < 3:
            continue
        t = lines[2].split()                       # nbyr tstep lat lon elev
        if len(t) >= 5:
            out.append({"id": pcp.stem, "lat": float(t[2]),
                        "lon": float(t[3]), "elev": float(t[4])})
    return out


def nearest_era5_grid(stations: List[Dict], grid_points: pd.DataFrame) -> Dict[str, Dict]:
    """관측소별 최근접 ERA5 격자 매칭 → {station_id: {grid_id, dist_km, lat, lon}}."""
    gid = grid_points["ID"].astype(str).tolist()
    glat = grid_points["Lat"].astype(float).tolist()
    glon = grid_points["Lon"].astype(float).tolist()
    out: Dict[str, Dict] = {}
    for s in stations:
        best_i, best_d = 0, float("inf")
        for i in range(len(gid)):
            d = _haversine_km(float(s["lat"]), float(s["lon"]), glat[i], glon[i])
            if d < best_d:
                best_i, best_d = i, d
        out[str(s["id"])] = {"grid_id": gid[best_i], "dist_km": round(best_d, 2),
                             "lat": glat[best_i], "lon": glon[best_i]}
    return out


def era5_warmup_frame(grid_id: str, grid_daily_std_dir, start, end) -> pd.DataFrame:
    """격자점 daily_std → [start, end] 일자료 (date, pcp_mm, tmax_c, tmin_c). 결측일은 -99."""
    p = Path(grid_daily_std_dir) / f"{grid_id}.csv"
    if not p.is_file():
        raise FileNotFoundError(f"ERA5 격자 daily 없음: {p}")
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"])
    full = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    keep = ["pcp_mm", "tmax_c", "tmin_c"]
    df = df.set_index("date").reindex(full)[[c for c in keep if c in df.columns]]
    df = df.fillna(-99.0)
    df.index.name = "date"
    return df.reset_index()


def _rebuild_var_file(path: Path, daily: pd.DataFrame, val_cols: List[str]) -> None:
    """*.pcp/*.tmp 본문을 daily(date+값열)로 재작성. 헤더의 lat/lon/elev·이름은 보존, nbyr 갱신."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 3:
        return
    header = lines[:3]
    hp = header[2].split()                          # nbyr tstep lat lon elev
    years = sorted(daily["date"].dt.year.unique())
    hp[0] = str(len(years))                         # nbyr
    header[2] = "  " + "     ".join(hp)
    body = []
    for _, r in daily.iterrows():
        d = r["date"]
        yr, jd = int(d.year), int(d.dayofyear)
        vals = "".join(f" {float(r[c]):9.3f}" for c in val_cols)
        body.append(f"  {yr:4d} {jd:5d}{vals}")
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def write_era5_warmup(run_dir, grid_points_csv, grid_daily_std_dir, *,
                      fyear: int, warmup_years: int, forecast_end,
                      stations: Optional[List[Dict]] = None) -> Dict:
    """run_dir 의 .pcp/.tmp 를 [fyear-warmup_years-01-01, forecast_end] 구간으로 재구성.

    관측소별 최근접 ERA5 격자 일자료로 채운다(예보 구간은 이후 acidwg 가 덮어씀).
    반환: {"mapping", "start", "end", "gap": bool, "coverage": {station: last_date}} dict.
    """
    run_dir = Path(run_dir)
    start = pd.Timestamp(fyear - warmup_years, 1, 1)
    end = pd.Timestamp(forecast_end)
    grid = load_grid_points(grid_points_csv)
    stations = stations or stations_from_pcp(run_dir)
    mapping = nearest_era5_grid(stations, grid)

    coverage: Dict[str, str] = {}
    gap = False
    for s in stations:
        sid = str(s["id"])
        gid = mapping[sid]["grid_id"]
        wf = era5_warmup_frame(gid, grid_daily_std_dir, start, end)
        # gap 판정: ERA5 격자 원자료가 예보 시작 이전까지 실제 값을 갖는지(-99 아님)
        real = wf[(wf["pcp_mm"] > -98) & (wf["date"] < end)]
        last_real = real["date"].max() if len(real) else None
        coverage[sid] = str(last_real.date()) if last_real is not None else "(없음)"
        if last_real is None or last_real < end - pd.Timedelta(days=1):
            gap = True
        pcp = run_dir / f"{sid}.pcp"
        tmp = run_dir / f"{sid}.tmp"
        if pcp.is_file():
            _rebuild_var_file(pcp, wf, _VAL_COLS["pcp"])
        if tmp.is_file():
            _rebuild_var_file(tmp, wf, _VAL_COLS["tmp"])
    return {"mapping": mapping, "start": str(start.date()), "end": str(end.date()),
            "gap": gap, "coverage": coverage}
