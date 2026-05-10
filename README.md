# PICASO-Hydro

SWAT/SWAT-Plus 기반 수문 모델링 자동화 Python 패키지 모음.
유역통합관리연구원(IWMI) PICASO-Hydro 사업 산출물.

## 패키지 구성

| 패키지 | 역할 | 의존 라이브러리 |
|---|---|---|
| **`util_py`** | SWAT 입력 자료 자동 수집·가공 (DEM/LULC/Soil/기상/유량 + Stage 1·2 워크플로우) | rasterio, geopandas, cdsapi, netCDF4, pyyaml |
| **`swat_py`** | rSWAT(R) Python 포팅 + acidwg_py 앙상블 통합. SWAT2012/SWAT-Plus 자동 실행·보정·검증·기후변화 분석 | numpy, pandas, scipy, statsmodels |
| **`acidwg_py`** | APCC 계절예측 통계 다운스케일링 (rACID R 패키지 포팅). 1,000-멤버 앙상블 일자료 생성 | scipy, scikit-learn, statsmodels |

세 패키지는 한 PICASO-Hydro 프로젝트의 자료 → 모델 → 시나리오 파이프라인을 구성합니다:

```
util_py     →   swat_py     ←   acidwg_py
(자료수집)      (수문모델링)     (계절예측 다운스케일링)
```

## 설치

### 옵션 A — 개별 패키지 (PyPI 등록 시, 향후)
```bash
pip install util_py
pip install swat_py
pip install acidwg_py
```

### 옵션 B — 본 저장소에서 직접 (현재 권장)
```bash
pip install "git+https://github.com/IWMI-KR/picaso-hydro.git#subdirectory=util_py"
pip install "git+https://github.com/IWMI-KR/picaso-hydro.git#subdirectory=swat_py"
pip install "git+https://github.com/IWMI-KR/picaso-hydro.git#subdirectory=acidwg_py"
```

### 옵션 C — 로컬 클론 후 editable
```bash
git clone https://github.com/IWMI-KR/picaso-hydro.git
cd picaso-hydro
pip install -e ./util_py[dev]
pip install -e ./swat_py[dev]
pip install -e ./acidwg_py[dev]
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

`docs/util_py_사용자매뉴얼.docx` — 비프로그래머 사용자를 위한 11장 + 부록 2개 한글 매뉴얼:

- 설치 (Python, IDE, 패키지 3가지 옵션)
- 프로젝트 폴더 세팅
- Stage 1 / Stage 2 워크플로우
- 사용자 입력 시점 요약 (3개 + 1)
- 트러블슈팅 6가지
- Cook Islands 적용 예시 + 다른 국가 적용 체크리스트

## CLI 진입점

`util_py` 설치 시 다음 명령이 시스템 PATH 에 등록됩니다:

| 명령 | 역할 |
|---|---|
| `util-gis-download` | DEM/admin/landuse/soil/basin/river 일괄 다운로드 |
| `util-gis-clip-to-user` | Stage 2 — 사용자 영역 클립 |
| `util-era5-download` | ERA5 시간자료 NC 다운로드 (CDS API) |
| `util-era5-extract` | ERA5 NC → 격자점 hourly/daily CSV |
| `util-gsod-download` | NOAA GSOD 일자료 다운로드 |
| `util-weather-standardize` | ERA5/GSOD/local → SWAT 표준 포맷 |
| `util-weather-validate` | ERA5 vs 관측 산점 검증 (논문급 그래프) |
| `util-streamflow-download` | CARAVAN/USGS NWIS 유량 자료 |

`swat_py`, `acidwg_py` 도 `acidwg-run`, `acidwg-picaso-convert` 등의 진입점 제공.

## 라이선스

MIT License — 자유 사용·수정·재배포. 상업적 사용 가능. 출처 표기 권장.

## 인용

본 코드를 학술 논문에 사용하시는 경우 다음 형식으로 인용을 부탁드립니다:

> IWMI-KR (2026). PICASO-Hydro: SWAT/SWAT-Plus 자동화 Python 패키지. https://github.com/IWMI-KR/picaso-hydro

## 연락처

유역통합관리연구원 (IWMI-KR)
- E-mail: iwmi.kr@gmail.com
- 사업: APCC 계절예측 기반 PICASO-Hydro

## 상태

| 패키지 | 버전 | 테스트 |
|---|---|---|
| util_py   | 0.1.0 | 237 passed |
| swat_py   | 0.1.0 | 34 passed |
| acidwg_py | 1.0.0 | 79 passed |
