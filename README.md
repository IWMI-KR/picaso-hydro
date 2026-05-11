# PICASO-Hydro

SWAT/SWAT-Plus 기반 수문 모델링 자동화를 위한 Python 패키지 모음.
유역통합관리연구원(IWMI) PICASO-Hydro 사업 산출물.

## 역할

| 패키지 | 역할 | 주요 의존 |
|---|---|---|
| **`util_py`** | SWAT 입력 자료 자동 수집·가공 (DEM/LULC/Soil/기상/유량 + Stage 1·2 워크플로우) + ERA5 vs 관측 검증 | rasterio, geopandas, cdsapi, netCDF4, pyyaml |
| **`acidwg_py`** | APCC 계절예측 통계 다운스케일링 (rACID R 패키지 포팅). 1,000-멤버 일자료 앙상블 | numpy, pandas, scipy, scikit-learn, statsmodels, pyyaml |
| **`swat_py`** | SWAT/SWAT-Plus 자동 실행·보정·검증·기후변화·앙상블 예보 (rSWAT R 포팅 + acidwg_py 1000 멤버 통합) | numpy, pandas, scipy, matplotlib, seaborn, pyyaml |

`acidwg_py` 는 `util_py` 의 표준 daily 관측 포맷 (`util-weather-standardize` 출력) 을 직접 입력으로 사용합니다.
`swat_py` 는 `acidwg_py` 의 1000-멤버 앙상블 출력을 직접 입력으로 사용합니다 (operational + hindcast 모두).

## 설치

### 옵션 A — 본 저장소에서 직접 (현재 권장)
```bash
pip install "git+https://github.com/IWMI-KR/picaso-hydro.git#subdirectory=util_py"
pip install "git+https://github.com/IWMI-KR/picaso-hydro.git#subdirectory=acidwg_py"
pip install "git+https://github.com/IWMI-KR/picaso-hydro.git#subdirectory=swat_py"
```

### 옵션 B — 로컬 클론 후 editable
```bash
git clone https://github.com/IWMI-KR/picaso-hydro.git
cd picaso-hydro
pip install -e ./util_py[dev]
pip install -e ./acidwg_py
pip install -e ./swat_py
```

## 빠른 시작

```bash
# 환경 설정 (1회)
set PICASO_ROOT=D:\MyProject

# Stage 1 — 국가 전체 자료 수집
util-gis-download
util-era5-download --start-year 2010
util-era5-extract
util-gsod-download
util-weather-standardize
util-weather-validate

# Stage 2 — SWAT 모델링 영역 클립 (예: 라로통가)
util-gis-clip-to-user --area rarotonga
```

상세 사용법은 `docs/util_py_사용자매뉴얼.docx` 참조.

## 사용자 매뉴얼

- `docs/util_py_사용자매뉴얼.docx` — util_py 자료 수집·표준화·검증 (비프로그래머용 11장 + 부록 2)
- `docs/acidwg_py_사용자매뉴얼.docx` — acidwg_py 계절예측 다운스케일링 (10장 + 부록 5)

## CLI 진입점

설치 시 다음 명령이 시스템 PATH 에 등록됩니다:

| 명령 | 패키지 | 역할 |
|---|---|---|
| `util-gis-download` | util_py | DEM/admin/landuse/soil/basin/river 일괄 다운로드 |
| `util-gis-clip-to-user` | util_py | Stage 2 — 사용자 영역 클립 |
| `util-era5-download` | util_py | ERA5 시간자료 NC 다운로드 (CDS API) |
| `util-era5-extract` | util_py | ERA5 NC → 격자점 hourly/daily CSV |
| `util-gsod-download` | util_py | NOAA GSOD 일자료 다운로드 |
| `util-weather-standardize` | util_py | ERA5/GSOD/local → SWAT 표준 포맷 |
| `util-weather-validate` | util_py | ERA5 vs 관측 산점 검증 (논문급 그래프) |
| `util-streamflow-download` | util_py | CARAVAN/USGS NWIS 유량 자료 |
| `acidwg-picaso-convert` | acidwg_py | PICASO 원본 → forecast CSV 변환 |
| `acidwg-run` | acidwg_py | 1000-멤버 일자료 앙상블 시나리오 생성 |

## 라이선스

MIT License — 자유 사용·수정·재배포. 상업적 사용 가능. 출처 표기 권장.

## 인용

본 코드를 학술 논문에 사용하시는 경우 다음 형식으로 인용을 부탁드립니다:

> IWMI-KR (2026). PICASO-Hydro: SWAT 자료 수집·다운스케일링 Python 패키지 모음 (util_py, acidwg_py). https://github.com/IWMI-KR/picaso-hydro

## 연락처

유역통합관리연구원 (IWMI-KR)
- E-mail: iwmi.kr@gmail.com
- 사업: APCC 계절예측 기반 PICASO-Hydro

## 상태

| 패키지 | 버전 | 테스트 |
|---|---|---|
| util_py   | 0.1.0 | 243 passed |
| acidwg_py | 1.0.0 | 108 passed |
| swat_py   | 0.1.0 | 45 passed |
