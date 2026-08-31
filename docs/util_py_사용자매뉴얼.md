# util_py 사용자 매뉴얼

> PICASO-Hydro 서브패키지 · 국가단위 입력 데이터베이스(0_database) 구축 유틸리티
> 최신 코드 기준 (2026-07)

## 1. 개요

`util_py`는 PICASO-Hydro 파이프라인의 **국가단위 입력 데이터베이스(`0_database`) 구축 유틸리티**다. 대상 국가의 경계(`country_boundary.csv`) 하나만 지정하면 SWAT 모형에 필요한 GIS 자료(행정구역·유역·하천·DEM·토양·토지피복), 기상 자료(ERA5 재분석·NOAA GSOD 관측), 관측 유량(CARAVAN·USGS), 그리고 이들을 SWAT 표준 포맷으로 변환·검증하는 작업을 전(全) 자동으로 수행한다.

개별 `util-*` 콘솔 명령으로 단계별 실행이 가능하며, `util-download-national` 오케스트레이터가 이 명령들을 정해진 순서로 일괄 실행한다(Stage 1 = 국가단위 다운로드, Stage 2 = 사용자 영역 UTM 클립).

### 파이프라인 내 위치
```
[util_py] 국가 DB·기상·GIS 구축  →  [acidwg_py] 계절예측 앙상블 상세화  →  [swat_py] SWAT+ 검보정·가뭄예측
```

## 2. 설치

```bash
# 최초 설치 (GitHub 에서)
pip install "git+https://github.com/IWMI-KR/picaso-hydro.git#subdirectory=util_py"

# 최신 코드로 강제 업데이트 (버전 고정 캐시 우회)
pip install --upgrade --force-reinstall --no-cache-dir --no-deps \
  "git+https://github.com/IWMI-KR/picaso-hydro.git@main#subdirectory=util_py"
```

프로젝트 설정은 `{프로젝트 루트}/config/util_py.yaml` 에 둔다. 루트는 `PICASO_ROOT` 환경변수 →
YAML `project.root` → 설정 파일 위치 → `0_database/` 를 가진 상위 폴더 자동 탐지 순으로 결정된다.

## 3. CLI 명령

`pyproject.toml [project.scripts]`에 정의된 10개 콘솔 스크립트. 설정 우선순위는 **CLI 인자 > 프로젝트 `config/util_py.yaml` > 패키지 기본 템플릿**이며, 코드에 사이트 종속 기본값은 없다.

### 3.1 `util-download-national` — 오케스트레이터

국가단위 DB 일괄 다운로드(Stage 1) + 사용자 영역 UTM 클립(Stage 2)을 개별 `util-*` 명령으로 순차 실행.

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--config` | util_py.yaml 경로 (생략 시 자동 탐색) | 자동 |
| `--start-year` | ERA5 다운로드 시작 연도 | YAML `era5.start_year` |
| `--no-validate` | weather-validate 단계 생략 | off |
| `--no-streamflow` | streamflow-download 단계 생략 | off |
| `--no-clip` | 사용자 shape 있어도 Stage 2 생략 | off |
| `--skip STEP…` | 건너뛸 단계명 | `[]` |
| `--continue-on-error` | 단계 실패해도 다음 진행 (기본: 첫 실패 시 중단) | off |

- **입력**: `0_database/gis/admin/country_boundary.csv`(대상 국가 한 행), 선택 `0_database/gis/user/boundary-{area}.shp`
- **출력**: 하위 명령 산출물 전체 + 실행 요약. 실패 단계가 있으면 종료코드 1.
- **사전 준비**: `country_boundary.csv`를 대상 국가 한 행만 남기고 편집. `gis/user/boundary-{area}.shp`가 있으면 Stage 2 자동 실행.

### 3.2 `util-gis-download` — SWAT 입력 GIS 자동 다운로드

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--boundary-csv` | 경계 CSV (`region.boundary_csv`) | YAML |
| `--gis-root` | GIS 루트 (`gis.root`) | YAML |
| `--datasets …` | `admin basin river dem soil swat_soil landuse all` | `all` |
| `--keep-continental` | HydroSHEDS 대륙 원본 보관 | off |

- **데이터셋**: admin(GADM v4.1 lev0), basin(HydroBASINS lev12), river(HydroRIVERS v10), dem(Copernicus GLO-30 1°타일), soil(ISRIC SoilGrids 250m sand/silt/clay 0-5cm), swat_soil(한국=RDA/그 외=FAO 자동 분기), landuse(ESA WorldCover 2021 3°타일)
- **swat_soil 출처**: `gis_download.swat_soil.base_url`(기본 `http://shared.iwmi.kr:48080/permanent/swat_py/`)
  에서 HTTP 다운로드. ISO3 가 `KOR` 이면 `soil_korea.tif`, 그 외 국가는 `soil_global.tif`
  (mdb·sqlite·lookup 도 같은 위치). 로컬 공유드라이브(`S:` 등)는 사용하지 않는다.
- **입력**: `country_boundary.csv`(bbox·ISO 추출) · **출력**: `0_database/gis/`(admin/basin/river/dem/soil/landuse)

### 3.3 `util-era5-download` — ERA5 시간별 재분석 (CDS API)

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--start-year`/`--end-year` | 연도 범위 | YAML(2022)/현재연도 |
| `--vars VAR…` | 변수(8개 중) | 전체 |
| `--output-dir` | NC 저장 폴더 | YAML |
| `--overwrite` / `--verify-only` | 덮어쓰기 / 검증만 | off |
| `--dry-run` | 받을 파일·건너뛸 파일 계획만 출력 | off |
| `--no-extract` | 신규 파일이 있어도 era5-extract 자동실행 안 함 | off |
| `--url`/`--key` | CDS API URL/키 | YAML/.cdsapirc/env |

- **입력**: `country_boundary.csv`(영역=bbox+`region.buffer_deg`) · **출력**: `0_database/era5/nc_hourly/`
- **파일 단위 (중요)**
  - 지난 연도: 연 단위 1파일 — `ERA5_{var}_hourly_{YYYY}.nc` (예: `ERA5_v10m_hourly_2025.nc`)
  - 현재 연도: **월 단위 N파일** — `ERA5_{var}_hourly_{YYYYMM}.nc` (예: `ERA5_v10m_hourly_202604.nc`)
  - 이유: 진행 중인 연도를 연 단위로 저장하면 "파일이 이미 있음"으로 매번 skip 되어
    **연도 중반에 받은 파일이 영원히 갱신되지 않는다.** 월 단위로 쪼개면 없는 달만 채운다.
  - 지난 연도가 월 단위 파일로 채워져 있으면(= 현재 연도였을 때 받은 것) 그대로 인정하고
    연 단위로 다시 받지 않는다. 월이 빠져 있으면 그 달만 보충한다.
- **자동 연계**: 신규 파일을 받고 검증까지 통과하면 곧바로 `util-era5-extract --overwrite` 를
  실행해 `grid_hourly/`·`grid_daily/` 를 최신화한다(`--no-extract` 로 해제).
  격자점 CSV 는 전 기간을 다시 쓰므로 `--overwrite` 가 반드시 필요하다.
- **인증**: `util_py.yaml era5.cds.url/key` 또는 `.cdsapirc` 또는 `CDSAPI_URL`/`CDSAPI_KEY`

### 3.4 `util-era5-extract` — 격자점별 기상 추출

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--grid` | 격자점 .csv/.shp | YAML |
| `--utc-offset` | UTC→로컬 시차 | YAML `region.utc_offset` |
| `--start-year`/`--end-year` | 추출 연도 | 자동 |
| `--boundary` | 격자점 자동생성용 shapefile | YAML `gis.root`/admin/admin.shp |

- **입력**: `era5/grid_points-era5.csv`(없으면 boundary+NC로 자동생성), `era5/nc_hourly/`
- **출력**: `era5/grid_hourly/`, `era5/grid_daily/` (+ 자동생성 시 `grid_points-era5.shp/.csv`)
- **연·월 혼재 처리**: NC 폴더에 연 단위·월 단위 파일이 섞여 있어도 자동 인식한다.
  같은 연도에 월 단위 파일이 있으면 **그 연도의 연 단위 파일은 무시**하여 시간 중복을 막는다.
- `--overwrite` 없이 실행하면 이미 있는 격자점 CSV 는 건너뛰므로 **기간이 늘어나도 갱신되지 않는다.**
  새 자료를 반영할 때는 반드시 `--overwrite` 를 붙인다.

### 3.5 `util-gsod-download` — NOAA GSOD 일자료

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--start-year`/`--end-year` | 연도 범위 | YAML(1929) |
| `--country-code` | ISO2/FIPS 직접 지정 | 자동 |
| `--no-bbox` | 국가코드만(bbox 필터 off) | off |
| `--overwrite` | 증분 대신 전 연도 재수집 | off |

- **입력**: `country_boundary.csv`, NOAA ISD-history/GSOD
- **출력**: `0_database/gsod/daily/`(관측소별 CSV), `gsod/station-gsod.csv`(메타), `gis/gsod/station-gsod.shp`
- **수집 방식**: NOAA `access/{year}/{USAF}{WBAN}.csv` 를 **관측소·연도 단위로 직접 다운로드**한다.
  전세계 `{year}.tar.gz` 아카이브는 사용하지 않으므로 로컬 아카이브 준비가 필요 없다.
- **증분 갱신**: NOAA 는 진행 중인 연도의 관측소 CSV 를 계속 덧붙인다. 재실행하면
  **가장 최근 보유 연도부터 앞으로만** 받아 기존 파일에 병합한다(`DATE` 기준 중복 제거, 최신본 우선).
  - 과거의 빈 연도는 자료가 없어서 비어 있는 것이라 재요청하지 않는다. 전부 다시 받으려면 `--overwrite`.
  - 요청 연도는 isd-history 의 관측소별 `BEGIN`/`END` 로 좁혀 불필요한 404 를 줄인다.
  - 이전 버전은 통합 CSV 가 있으면 관측소 전체를 건너뛰어 **새 자료가 영영 반영되지 않았다.**

### 3.6 `util-weather-standardize` — SWAT 표준 포맷 변환

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--source` | `era5 gsod local all` | `all` |
| `--resolution` | `daily hourly both` | `both` |
| `--mapping` | local 매핑 YAML | YAML |

- **표준 daily 컬럼**: `date, pcp_mm, tmax_c, tmin_c, tavg_c, tdew_c, hmd_pct, slr_mjm2, ws10_ms, ws2_ms, source` (hmd=Magnus/FAO-56, ws2=FAO-56 로그풍속, GSOD 일사=NaN)
- **입출력**: ERA5 `grid_daily/`→`grid_daily_std/`, `grid_hourly/`→`grid_hourly_std/` · GSOD(일만) `gsod/daily/`→`gsod/daily_std/` · local `obs/weather/daily/`→`daily_std/`(`mapping.yaml` 필요)

### 3.7 `util-weather-validate` — ERA5 vs 관측 검증

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--source` | `gsod` 또는 `local` | `gsod` |
| `--variables VAR…` | 비교 변수 | YAML/SWAT 7종 |
| `--regression` | 회귀선 추가 | off |
| `--radius-km` | 매칭 반경(이내 station 모두, 없으면 nearest) | YAML(10) |
| `--output-dir` | 출력 폴더 | `reports/` |

- 각 ERA5 격자점 ↔ 최근접 관측소를 같은 날짜로 1:1 산점도 + 통계
- **출력**: `reports/era5_vs_{source}/` (`nearest_pairs.csv`, `statistics.csv`, `plots/{var}/`, `plots/combined/`)

### 3.8 `util-streamflow-download` — 국제 관측 유량 (CARAVAN/USGS)

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--bbox XMIN YMIN XMAX YMAX` | bbox 직접 지정 | None |
| `--source` | `caravan usgs auto` | `auto` |
| `--sub-datasets …` | CARAVAN 서브셋 명시 | 자동 |
| `--start-date`/`--end-date` | USGS 기간 | YAML(1990-01-01) |

- `auto`: bbox가 USGS 권역이면 usgs, 아니면 매칭 CARAVAN, 둘 다 없으면 종료코드 1(GRDC 직접 문의 안내)
- **출력**: `0_database/obs/streamflow/`

### 3.9 `util-gis-clip-to-user` — Stage 2 (사용자 영역 UTM 클립)

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--area` / `--all` | 단일 area / 전체 처리 | `--all` |
| `--types …` | `dem landuse soil` | YAML(3종) |
| `--buffer-deg` | boundary 외측 버퍼 | YAML(0.05) |
| `--epsg` | UTM EPSG 강제 | 자동 |
| `--list` | area 나열 후 종료 | off |

- **입력**: `gis/user/boundary-{area}.shp`(사용자 배치) + `gis/` 국가자료
- **출력**: `gis/user/{area}/` (boundary·dem+UTM·landuse+lookup·soil+mdb)

### 3.10 `util-era5-update` — ERA5 증분 최신화 (운영 warm-up)

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--start-year` | 시작 연도(종료=오늘) | config |
| `--no-standardize` | 다운로드·추출만 | off |

- 내부적으로 era5-download(증분, `--no-extract`) → era5-extract(`--overwrite`) → weather-standardize(era5) 순차.
  현재 연도는 월 단위 파일이라 빠진 달만 받고, 추출은 전 기간을 다시 써서 `grid_daily_std` 를 최신화한다.

## 4. 전형적 실행 순서

`util-download-national`이 강제하는 표준 순서:

**Stage 1 — 국가단위 다운로드**
1. `util-gis-download` (**가장 먼저** — 이후 단계가 `admin.shp` 사용)
2. `util-era5-download --start-year YYYY`
3. `util-era5-extract` (격자점 없으면 admin.shp로 자동생성)
4. `util-gsod-download`
5. `util-weather-standardize` (2·4 출력 필요)
6. `util-weather-validate` (5 출력 필요; `--no-validate` 생략 가능)
7. `util-streamflow-download` (`--no-streamflow` 생략 가능)

**Stage 2 — 사용자 영역 클립 (조건부)**
8. `util-gis-clip-to-user --all` (`gis/user/boundary-{area}.shp` 있을 때만)

의존성: extract←gis-download+era5-download / standardize←era5-extract+gsod / validate←standardize / clip←gis-download. 기본은 첫 실패 시 중단(`--continue-on-error`로 계속).

## 5. 설정 파일 `util_py.yaml`

- **표준 위치**: `{프로젝트 루트}/config/util_py.yaml`
  — `picaso-hydro-init` 이 `picaso-hydro.yaml`·`swat_py.yaml`·`acidwg_py.yaml` 과 함께 자동 생성한다.
  생성 시 `project.root` 가 초기화 경로로 확정되므로 **사용자가 손댈 내용이 없다**
  (교체가 필요한 것은 `0_database/gis/admin/country_boundary.csv` 뿐).
- **탐색 순서**: ① `UTIL_PY_CONFIG` 환경변수 → ② cwd에서 상위로 올라가며 `config/util_py.yaml` → `util_py.yaml` → ③ `$PICASO_ROOT/config/util_py.yaml` → `$PICASO_ROOT/util_py.yaml`
- **폴백**: 프로젝트 설정이 없으면 패키지 동봉 기본 템플릿(`util_py/templates/util_py.yaml`)을 사용한다.
- **병합**: 프로젝트 YAML 은 템플릿 위에 **깊은 병합**된다. 바꾸고 싶은 키만 적으면 되고, 나머지는 템플릿 값이 채워진다.
- **하드코딩 없음**: 경로·시차·연도 등 모든 값의 출처는 YAML 이다. 파이썬 코드에는 사이트 종속 기본값을 두지 않는다.
- **`project.root` 결정 순서**: `PICASO_ROOT` 환경변수 → YAML `project.root` 명시값 → 설정 파일 위치(`config/` 의 상위) → cwd 에서 `0_database` 를 가진 상위 폴더 자동 탐지
- **`region.utc_offset`**: 값을 적으면 그대로 쓰고, `null` 이면 GIS 경계(admin.shp → 없으면
  `country_boundary.csv` bbox)의 **대표 경도에서 `round(경도/15)` 로 자동 추정**한다.
  경도 기반 근사라 **법정 표준시와 다를 수 있다**(쿡 아일랜드: 경도 −11 / 법정 −10).
  정확한 값이 필요하면 직접 지정한다. 쿡=-10, 팔라우=+9.
- **YAML 문법 확장**: `$(섹션.키)` 교차참조, `${env:NAME:default}` 환경변수 치환(재귀·순환감지).
- **주요 섹션**: `project.root`, `region`(boundary_csv, utc_offset, buffer_deg 0.25), `era5`(output_dir, start_year 2022, variables, cds.url/key), `extract`, `gis`(root, swat_epsg, swat_buffer_deg 0.05), `gis_user`(base_dir, filename_pattern `boundary-{area}.shp`, raster_types), `gis_download`(각 소스 URL·파라미터), `weather_std`(era5/gsod/local 경로), `weather_validation`(radius_km 10), `streamflow`(caravan/usgs), `gsod`(start_year 1929, isd_history_url, gsod_access_url).
- **local 소스**는 별도 `mapping.yaml`(`weather_std.local.mapping_file`)을 추가로 읽는다.

## 6. 산출물 폴더 요약 (`0_database/`)
```
0_database/
├── gis/  admin·basin·river·dem·soil·landuse·gsod·user/{area}/
├── era5/ nc_hourly · grid_hourly(_std) · grid_daily(_std) · grid_points-era5.csv
├── gsod/ daily · daily_std · station-gsod.csv
└── obs/  streamflow · weather/{daily,hourly}(_std)
reports/ era5_vs_{gsod|local}/   # weather-validate 산점도·통계
```
