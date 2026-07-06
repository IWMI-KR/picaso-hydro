"""
util_py — PICASO-Hydro 유틸리티 패키지

모듈
----
era5  : ERA5 시간별 자료 다운로드 및 검증
grid  : ERA5 격자점 추출 (폴리곤 교차 분석)
cmip6 : CMIP6 글로벌 NC 파일 영역 추출
gis           : GIS 자료 좌표계/폴더 컨벤션 (UTM 자동 산출, canonical 경로)
gis_download  : SWAT 입력 GIS 자료 다운로드 (DEM/admin/soil/landuse/basin/river)
gis_user      : 사용자 정의 SWAT 영역 클립 (Stage 2)
weather_std   : 기상자료 SWAT 표준 포맷 변환 (ERA5/GSOD/local)
weather_validation : ERA5 vs 관측 산점 검증 (1:1 plot + 통계)
streamflow    : 국제 관측 유량 자료 (CARAVAN 글로벌 + USGS NWIS 미국)
gsod          : NOAA GSOD 일자료 다운로드 (국가별 통합)
"""

from util_py.era5 import (
    VARIABLES,
    compute_area,
    download_era5_year,
    download_era5_all,
    verify_era5_file,
    verify_era5_all,
)
from util_py.grid import extract_era5_grid_points
from util_py.extract import extract_era5_to_grid, HOURLY_COLS, DAILY_COLS
from util_py.cmip6 import extract_cmip6_region
from util_py.gis import (
    auto_utm_epsg,
    clip_raster,
    gis_canonical_path,
    gis_reprojected_path,
    prepare_raster_for_swat,
    reproject_raster,
    reproject_to_utm,
)
from util_py.gis_download import (
    WORLDCOVER_LOOKUP,
    bbox_to_dem_tiles,
    bbox_to_hydrosheds_region,
    bbox_to_worldcover_tiles,
    download_dem,
    download_gadm,
    download_hydrobasins,
    download_hydrorivers,
    download_soilgrids,
    download_swat_soil,
    download_worldcover,
    write_worldcover_lookup,
)
from util_py.gis_user import (
    clip_to_all_user_areas,
    clip_to_user_area,
    discover_user_areas,
)
from util_py.weather_validation import (
    DEFAULT_VARIABLES,
    compute_stats,
    find_nearest_pairs,
    haversine_km,
    plot_scatter_one_to_one,
    scatter_compare_era5_obs,
)
from util_py.weather_std import (
    STD_DAILY_COLUMNS,
    STD_HOURLY_COLUMNS,
    aggregate_dir_hourly_to_daily,
    aggregate_std_hourly_to_daily,
    fahrenheit_to_celsius,
    inches_to_mm,
    knots_to_ms,
    magnus_rh,
    standardize_dir_era5_daily,
    standardize_dir_era5_hourly,
    standardize_dir_gsod_daily,
    standardize_era5_daily,
    standardize_era5_hourly,
    standardize_gsod_daily,
    standardize_local,
    wind_to_2m_fao56,
)
from util_py.gsod import (
    ISO2_TO_FIPS,
    download_gsod_country,
    write_station_shapefile,
)
from util_py.streamflow import (
    CARAVAN_SUBSETS,
    caravan_subsets_for_bbox,
    download_streamflow_caravan,
    download_streamflow_usgs,
)
from util_py.national import download_national_database

__all__ = [
    "download_national_database",
    "VARIABLES",
    "compute_area",
    "download_era5_year",
    "download_era5_all",
    "verify_era5_file",
    "verify_era5_all",
    "extract_era5_grid_points",
    "extract_era5_to_grid",
    "HOURLY_COLS",
    "DAILY_COLS",
    "extract_cmip6_region",
    "auto_utm_epsg",
    "clip_raster",
    "gis_canonical_path",
    "gis_reprojected_path",
    "prepare_raster_for_swat",
    "reproject_raster",
    "reproject_to_utm",
    "bbox_to_dem_tiles",
    "bbox_to_hydrosheds_region",
    "bbox_to_worldcover_tiles",
    "download_dem",
    "download_gadm",
    "download_hydrobasins",
    "download_hydrorivers",
    "download_soilgrids",
    "download_swat_soil",
    "download_worldcover",
    "WORLDCOVER_LOOKUP",
    "write_worldcover_lookup",
    "clip_to_all_user_areas",
    "clip_to_user_area",
    "discover_user_areas",
    "STD_DAILY_COLUMNS",
    "STD_HOURLY_COLUMNS",
    "magnus_rh",
    "wind_to_2m_fao56",
    "standardize_era5_daily",
    "standardize_era5_hourly",
    "standardize_gsod_daily",
    "standardize_local",
    "standardize_dir_era5_daily",
    "standardize_dir_era5_hourly",
    "standardize_dir_gsod_daily",
    "aggregate_std_hourly_to_daily",
    "aggregate_dir_hourly_to_daily",
    "DEFAULT_VARIABLES",
    "compute_stats",
    "find_nearest_pairs",
    "haversine_km",
    "plot_scatter_one_to_one",
    "scatter_compare_era5_obs",
    "ISO2_TO_FIPS",
    "download_gsod_country",
    "write_station_shapefile",
    "CARAVAN_SUBSETS",
    "caravan_subsets_for_bbox",
    "download_streamflow_caravan",
    "download_streamflow_usgs",
]
