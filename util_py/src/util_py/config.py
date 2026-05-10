"""util_py 설정 로더 — util_py.yaml 파싱 + 교차참조 해석.

YAML 양식
---------
중첩된 섹션(project/region/era5/extract/cmip6/grid)으로 구성됩니다.
값에 ``$(섹션.키)`` 형태로 다른 키를 참조할 수 있고,
``${env:NAME}`` / ``${env:NAME:default}`` 로 환경변수도 사용 가능합니다.

우선순위 (CLI에서 적용)
-----------------------
    CLI 인자 > YAML 값 > 환경변수 > 코드상의 smart default
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml


# ── 데이터클래스 ──────────────────────────────────────────────────────────────

@dataclass
class _CdsCfg:
    url: Optional[str] = None
    key: Optional[str] = None


@dataclass
class _WeatherStdEra5Cfg:
    raw_daily_dir:  str = ""
    raw_hourly_dir: str = ""
    std_daily_dir:  str = ""
    std_hourly_dir: str = ""
    wind_height_m:  float = 10.0


@dataclass
class _WeatherStdGsodCfg:
    raw_dir:       str = ""
    std_dir:       str = ""
    wind_height_m: float = 10.0


@dataclass
class _WeatherStdLocalCfg:
    raw_daily_dir:  str = ""
    raw_hourly_dir: str = ""
    std_daily_dir:  str = ""
    std_hourly_dir: str = ""
    mapping_file:   str = ""
    wind_height_m:  float = 10.0


@dataclass
class _WeatherStdCfg:
    era5:  _WeatherStdEra5Cfg  = field(default_factory=_WeatherStdEra5Cfg)
    gsod:  _WeatherStdGsodCfg  = field(default_factory=_WeatherStdGsodCfg)
    local: _WeatherStdLocalCfg = field(default_factory=_WeatherStdLocalCfg)


@dataclass
class _WeatherValidationCfg:
    output_base:        str = ""
    variables:          List[str] = field(default_factory=lambda: [
        "pcp_mm", "tmax_c", "tmin_c", "tavg_c", "tdew_c", "hmd_pct", "ws10_ms"])
    radius_km:          float = 10.0
    show_regression:    bool = False
    write_per_variable: bool = True
    write_combined:     bool = True
    combined_ncols:     int = 4


@dataclass
class _RegionCfg:
    boundary_csv: str = ""
    utc_offset:   int = -10        # 쿡 아일랜드 표준시
    buffer_deg:   float = 0.25


@dataclass
class _Era5Cfg:
    output_dir: str = ""
    start_year: int = 2022
    end_year:   Optional[int] = None
    variables:  List[str] = field(default_factory=list)
    cds:        _CdsCfg = field(default_factory=_CdsCfg)


@dataclass
class _ExtractCfg:
    grid_file:  str = ""
    hourly_dir: str = ""
    daily_dir:  str = ""
    start_year: Optional[int] = None
    end_year:   Optional[int] = None


@dataclass
class _Cmip6Cfg:
    source_dir: str = ""
    output_dir: str = ""
    variables:  Optional[List[str]] = None


@dataclass
class _GridCfg:
    era5_resolution: float = 0.25


@dataclass
class _GadmCfg:
    url_template: str = "https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_{iso3}_shp.zip"
    level:        int = 0


@dataclass
class _HydroBasinsCfg:
    url_template: str = "https://data.hydrosheds.org/file/HydroBASINS/standard/hybas_{region}_lev{level}_v1c.zip"
    region:       Optional[str] = None
    level:        int = 12


@dataclass
class _HydroRiversCfg:
    url_template: str = "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_{region}_shp.zip"
    region:       Optional[str] = None


@dataclass
class _DemCfg:
    url_template: str = "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif"


@dataclass
class _SoilGridsCfg:
    wcs_url:    str = "https://maps.isric.org/mapserv"
    properties: List[str] = field(default_factory=lambda: ["sand", "silt", "clay"])
    depth:      str = "0-5cm"


@dataclass
class _WorldCoverCfg:
    url_template: str = "https://esa-worldcover.s3.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
    year:         int = 2021


@dataclass
class _SwatSoilCfg:
    source:    str = "local"                        # local | url
    local_dir: str = "S:/Database-INT/GISDB/Soils"


@dataclass
class _GisDownloadCfg:
    gadm:        _GadmCfg        = field(default_factory=_GadmCfg)
    hydrobasins: _HydroBasinsCfg = field(default_factory=_HydroBasinsCfg)
    hydrorivers: _HydroRiversCfg = field(default_factory=_HydroRiversCfg)
    dem:         _DemCfg         = field(default_factory=_DemCfg)
    soilgrids:   _SoilGridsCfg   = field(default_factory=_SoilGridsCfg)
    worldcover:  _WorldCoverCfg  = field(default_factory=_WorldCoverCfg)
    swat_soil:   _SwatSoilCfg    = field(default_factory=_SwatSoilCfg)


@dataclass
class _GisCfg:
    root:            str = ""
    default_epsg:    int = 4326
    swat_epsg:       Optional[int] = None    # None → boundary bbox 중심에서 자동
    swat_buffer_deg: float = 0.05            # raster 클립 buffer (도)


@dataclass
class _GisUserCfg:
    base_dir:         str = ""
    filename_pattern: str = "boundary-{area}.shp"
    raster_types:     List[str] = field(default_factory=lambda: ["dem", "landuse", "soil"])
    copy_lookups:     bool = True
    copy_mdb:         bool = True
    swat_epsg:        Optional[int] = None
    swat_buffer_deg:  float = 0.05


@dataclass
class _CaravanCfg:
    zenodo_record_id: str = "7944025"
    base_url:         str = "https://zenodo.org/records/{record_id}/files"
    sub_datasets:     List[str] = field(default_factory=list)


@dataclass
class _UsgsCfg:
    nwis_url:   str = "https://waterservices.usgs.gov/nwis/dv/"
    parameter:  str = "00060"
    start_date: str = "1990-01-01"
    end_date:   Optional[str] = None


@dataclass
class _StreamflowCfg:
    obs_dir: str = ""
    caravan: _CaravanCfg = field(default_factory=_CaravanCfg)
    usgs:    _UsgsCfg    = field(default_factory=_UsgsCfg)


@dataclass
class _GsodCfg:
    obs_dir:         str = ""
    station_csv:     str = ""
    station_shp:     str = ""
    archive_dir:     str = ""
    start_year:      int = 1929
    end_year:        Optional[int] = None
    country_code:    Optional[str] = None
    use_bbox_filter: bool = True
    isd_history_url: str = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
    gsod_access_url: str = "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access"


@dataclass
class _ProjectCfg:
    root: str = ""


@dataclass
class Config:
    """util_py 설정의 정규화 표현."""
    project: _ProjectCfg  = field(default_factory=_ProjectCfg)
    region:  _RegionCfg   = field(default_factory=_RegionCfg)
    era5:    _Era5Cfg     = field(default_factory=_Era5Cfg)
    extract: _ExtractCfg  = field(default_factory=_ExtractCfg)
    cmip6:   _Cmip6Cfg    = field(default_factory=_Cmip6Cfg)
    grid:         _GridCfg        = field(default_factory=_GridCfg)
    gis:          _GisCfg         = field(default_factory=_GisCfg)
    gis_user:     _GisUserCfg     = field(default_factory=_GisUserCfg)
    gis_download: _GisDownloadCfg = field(default_factory=_GisDownloadCfg)
    weather_std:  _WeatherStdCfg  = field(default_factory=_WeatherStdCfg)
    weather_validation: _WeatherValidationCfg = field(default_factory=_WeatherValidationCfg)
    streamflow:   _StreamflowCfg  = field(default_factory=_StreamflowCfg)
    gsod:         _GsodCfg        = field(default_factory=_GsodCfg)


# ── 교차참조 + 환경변수 치환 ─────────────────────────────────────────────────

_REF_RE = re.compile(r"\$\(([\w\.]+)\)")
_ENV_RE = re.compile(r"\$\{env:([A-Z_][A-Z0-9_]*)(?::([^}]*))?\}")


def _flat_get(data: Dict[str, Any], dotted: str) -> Any:
    """'a.b.c' 형태의 키로 중첩 dict 접근. 미존재 시 KeyError."""
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"교차참조 키 '{dotted}' 를 찾을 수 없습니다.")
        cur = cur[part]
    return cur


def _resolve_string(s: str, root: Dict[str, Any], _stack: Optional[set] = None) -> str:
    """문자열 안의 $(key) 와 ${env:VAR[:default]} 를 재귀적으로 해석."""
    if _stack is None:
        _stack = set()

    # 환경변수 먼저 (단순)
    def env_sub(m: re.Match) -> str:
        var, default = m.group(1), m.group(2)
        return os.environ.get(var, default if default is not None else "")
    s = _ENV_RE.sub(env_sub, s)

    # 교차참조: 중첩 가능 → 변화가 없을 때까지
    while True:
        m = _REF_RE.search(s)
        if not m:
            return s
        key = m.group(1)
        if key in _stack:
            raise ValueError(f"교차참조 순환: {key}")
        try:
            value = _flat_get(root, key)
        except KeyError as e:
            raise ValueError(f"교차참조 해석 실패: $({key}) — {e}") from None
        if not isinstance(value, str):
            value = str(value)
        # 참조된 값에 또 다른 참조가 있으면 먼저 풀기
        value = _resolve_string(value, root, _stack | {key})
        s = s[: m.start()] + value + s[m.end() :]


def _resolve_tree(node: Any, root: Dict[str, Any]) -> Any:
    """dict/list/str을 재귀 순회하며 모든 문자열의 참조를 해석."""
    if isinstance(node, dict):
        return {k: _resolve_tree(v, root) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_tree(v, root) for v in node]
    if isinstance(node, str):
        return _resolve_string(node, root)
    return node


# ── YAML → Config ────────────────────────────────────────────────────────────

def _build_config(raw: Dict[str, Any]) -> Config:
    """해석 완료된 dict를 Config 데이터클래스로 변환."""
    cfg = Config()

    if proj := raw.get("project"):
        cfg.project = _ProjectCfg(root=str(proj.get("root", "") or ""))

    if region := raw.get("region"):
        cfg.region = _RegionCfg(
            boundary_csv=str(region.get("boundary_csv", "") or ""),
            utc_offset=int(region.get("utc_offset", -10)),
            buffer_deg=float(region.get("buffer_deg", 0.25)),
        )

    if era5 := raw.get("era5"):
        cds_raw = era5.get("cds") or {}
        cfg.era5 = _Era5Cfg(
            output_dir=str(era5.get("output_dir", "") or ""),
            start_year=int(era5.get("start_year", 2022)),
            end_year=era5.get("end_year"),
            variables=list(era5.get("variables") or []),
            cds=_CdsCfg(
                url=cds_raw.get("url"),
                key=cds_raw.get("key"),
            ),
        )

    if ws := raw.get("weather_std"):
        ws_cfg = _WeatherStdCfg()
        if e5 := ws.get("era5"):
            ws_cfg.era5 = _WeatherStdEra5Cfg(
                raw_daily_dir=str(e5.get("raw_daily_dir", "") or ""),
                raw_hourly_dir=str(e5.get("raw_hourly_dir", "") or ""),
                std_daily_dir=str(e5.get("std_daily_dir", "") or ""),
                std_hourly_dir=str(e5.get("std_hourly_dir", "") or ""),
                wind_height_m=float(e5.get("wind_height_m", 10.0)),
            )
        if gd := ws.get("gsod"):
            ws_cfg.gsod = _WeatherStdGsodCfg(
                raw_dir=str(gd.get("raw_dir", "") or ""),
                std_dir=str(gd.get("std_dir", "") or ""),
                wind_height_m=float(gd.get("wind_height_m", 10.0)),
            )
        if lc := ws.get("local"):
            ws_cfg.local = _WeatherStdLocalCfg(
                raw_daily_dir=str(lc.get("raw_daily_dir", "") or ""),
                raw_hourly_dir=str(lc.get("raw_hourly_dir", "") or ""),
                std_daily_dir=str(lc.get("std_daily_dir", "") or ""),
                std_hourly_dir=str(lc.get("std_hourly_dir", "") or ""),
                mapping_file=str(lc.get("mapping_file", "") or ""),
                wind_height_m=float(lc.get("wind_height_m", 10.0)),
            )
        cfg.weather_std = ws_cfg

    if wv := raw.get("weather_validation"):
        cfg.weather_validation = _WeatherValidationCfg(
            output_base=str(wv.get("output_base", "") or ""),
            variables=list(wv.get("variables") or _WeatherValidationCfg().variables),
            radius_km=float(wv.get("radius_km", 10.0)),
            show_regression=bool(wv.get("show_regression", False)),
            write_per_variable=bool(wv.get("write_per_variable", True)),
            write_combined=bool(wv.get("write_combined", True)),
            combined_ncols=int(wv.get("combined_ncols", 4)),
        )

    if ex := raw.get("extract"):
        cfg.extract = _ExtractCfg(
            grid_file=str(ex.get("grid_file", "") or ""),
            hourly_dir=str(ex.get("hourly_dir", "") or ""),
            daily_dir=str(ex.get("daily_dir", "") or ""),
            start_year=ex.get("start_year"),
            end_year=ex.get("end_year"),
        )

    if c6 := raw.get("cmip6"):
        cfg.cmip6 = _Cmip6Cfg(
            source_dir=str(c6.get("source_dir", "") or ""),
            output_dir=str(c6.get("output_dir", "") or ""),
            variables=c6.get("variables"),
        )

    if g := raw.get("grid"):
        cfg.grid = _GridCfg(
            era5_resolution=float(g.get("era5_resolution", 0.25)),
        )

    if gi := raw.get("gis"):
        cfg.gis = _GisCfg(
            root=str(gi.get("root", "") or ""),
            default_epsg=int(gi.get("default_epsg", 4326)),
            swat_epsg=gi.get("swat_epsg"),
            swat_buffer_deg=float(gi.get("swat_buffer_deg", 0.05)),
        )

    if gu := raw.get("gis_user"):
        cfg.gis_user = _GisUserCfg(
            base_dir=str(gu.get("base_dir", "") or ""),
            filename_pattern=str(gu.get("filename_pattern", "boundary-{area}.shp")),
            raster_types=list(gu.get("raster_types") or ["dem", "landuse", "soil"]),
            copy_lookups=bool(gu.get("copy_lookups", True)),
            copy_mdb=bool(gu.get("copy_mdb", True)),
            swat_epsg=gu.get("swat_epsg"),
            swat_buffer_deg=float(gu.get("swat_buffer_deg", 0.05)),
        )

    if gd := raw.get("gis_download"):
        gd_cfg = _GisDownloadCfg()
        if gadm := gd.get("gadm"):
            gd_cfg.gadm = _GadmCfg(
                url_template=str(gadm.get("url_template", _GadmCfg().url_template)),
                level=int(gadm.get("level", 0)),
            )
        if hb := gd.get("hydrobasins"):
            gd_cfg.hydrobasins = _HydroBasinsCfg(
                url_template=str(hb.get("url_template", _HydroBasinsCfg().url_template)),
                region=hb.get("region"),
                level=int(hb.get("level", 12)),
            )
        if hr := gd.get("hydrorivers"):
            gd_cfg.hydrorivers = _HydroRiversCfg(
                url_template=str(hr.get("url_template", _HydroRiversCfg().url_template)),
                region=hr.get("region"),
            )
        if dm := gd.get("dem"):
            gd_cfg.dem = _DemCfg(
                url_template=str(dm.get("url_template", _DemCfg().url_template)),
            )
        if sg := gd.get("soilgrids"):
            gd_cfg.soilgrids = _SoilGridsCfg(
                wcs_url=str(sg.get("wcs_url", _SoilGridsCfg().wcs_url)),
                properties=list(sg.get("properties") or _SoilGridsCfg().properties),
                depth=str(sg.get("depth", _SoilGridsCfg().depth)),
            )
        if wc := gd.get("worldcover"):
            gd_cfg.worldcover = _WorldCoverCfg(
                url_template=str(wc.get("url_template", _WorldCoverCfg().url_template)),
                year=int(wc.get("year", 2021)),
            )
        if ss := gd.get("swat_soil"):
            gd_cfg.swat_soil = _SwatSoilCfg(
                source=str(ss.get("source", "local")),
                local_dir=str(ss.get("local_dir", _SwatSoilCfg().local_dir)),
            )
        cfg.gis_download = gd_cfg

    if sf := raw.get("streamflow"):
        sf_cfg = _StreamflowCfg(obs_dir=str(sf.get("obs_dir", "") or ""))
        if cv := sf.get("caravan"):
            sf_cfg.caravan = _CaravanCfg(
                zenodo_record_id=str(cv.get("zenodo_record_id", _CaravanCfg().zenodo_record_id)),
                base_url=str(cv.get("base_url", _CaravanCfg().base_url)),
                sub_datasets=list(cv.get("sub_datasets") or []),
            )
        if us := sf.get("usgs"):
            sf_cfg.usgs = _UsgsCfg(
                nwis_url=str(us.get("nwis_url", _UsgsCfg().nwis_url)),
                parameter=str(us.get("parameter", _UsgsCfg().parameter)),
                start_date=str(us.get("start_date", _UsgsCfg().start_date)),
                end_date=us.get("end_date"),
            )
        cfg.streamflow = sf_cfg

    if gs := raw.get("gsod"):
        cfg.gsod = _GsodCfg(
            obs_dir=str(gs.get("obs_dir", "") or ""),
            station_csv=str(gs.get("station_csv", "") or ""),
            station_shp=str(gs.get("station_shp", "") or ""),
            archive_dir=str(gs.get("archive_dir", "") or ""),
            start_year=int(gs.get("start_year", 1929)),
            end_year=gs.get("end_year"),
            country_code=gs.get("country_code"),
            use_bbox_filter=bool(gs.get("use_bbox_filter", True)),
            isd_history_url=str(gs.get("isd_history_url",
                "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv")),
            gsod_access_url=str(gs.get("gsod_access_url",
                "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access")),
        )

    return cfg


def load_config(path: Union[str, Path]) -> Config:
    """util_py.yaml을 로드하여 :class:`Config` 로 반환합니다.

    Parameters
    ----------
    path : YAML 파일 경로 (str 또는 Path).

    Returns
    -------
    Config

    Raises
    ------
    FileNotFoundError : 경로에 파일이 없을 때
    ValueError        : YAML 파싱 실패 또는 교차참조 오류
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"설정 파일이 없습니다: {p}")

    try:
        with p.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"YAML 파싱 실패: {p}\n  {e}") from e

    if not isinstance(raw, dict):
        raise ValueError(f"YAML 최상위는 매핑이어야 합니다: {p}")

    resolved = _resolve_tree(raw, raw)
    return _build_config(resolved)


def find_config(start: Optional[Path] = None) -> Optional[Path]:
    """util_py.yaml 파일을 자동 탐색합니다.

    탐색 순서
    ---------
    1. 환경변수 ``UTIL_PY_CONFIG``
    2. 현재 디렉토리 → 상위로 올라가며 ``util_py.yaml``
    3. ``$PICASO_ROOT/util_py.yaml``

    Returns
    -------
    Path or None
    """
    if env := os.environ.get("UTIL_PY_CONFIG"):
        p = Path(env)
        return p if p.is_file() else None

    cwd = (start or Path.cwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / "util_py.yaml"
        if candidate.is_file():
            return candidate

    if picaso := os.environ.get("PICASO_ROOT"):
        candidate = Path(picaso) / "util_py.yaml"
        if candidate.is_file():
            return candidate

    return None
