"""Station metadata dataclass and CSV loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import pandas as pd


@dataclass
class StationInfo:
    """Metadata for a single weather station."""

    id: str
    lat: float
    lon: float
    elev: float


def load_station_csv(path: Path, ids: List[str]) -> List[StationInfo]:
    """Read station metadata CSV and filter to *ids*.

    Expected CSV columns: ID, Lat, Lon, Elev
    (mirrors R's StnFile format).
    """
    df = pd.read_csv(path)
    # Normalise column names to title-case
    df.columns = [c.strip() for c in df.columns]

    col_map = {c.lower(): c for c in df.columns}
    id_col = col_map.get("id", "ID")
    lat_col = col_map.get("lat", "Lat")
    lon_col = col_map.get("lon", "Lon")
    elev_col = col_map.get("elev", "Elev")

    stations: List[StationInfo] = []
    for stn_id in ids:
        row = df[df[id_col].astype(str) == str(stn_id)]
        if row.empty:
            raise ValueError(f"Station '{stn_id}' not found in {path}")
        r = row.iloc[0]
        stations.append(
            StationInfo(
                id=str(r[id_col]),
                lat=float(r[lat_col]),
                lon=float(r[lon_col]),
                elev=float(r[elev_col]),
            )
        )
    return stations
