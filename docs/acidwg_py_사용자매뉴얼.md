# acidwg_py 사용자 매뉴얼

> PICASO-Hydro 서브패키지 · APCC 계절예측 통계적 상세화 (일단위 기상 앙상블)
> 최신 코드 기준 (2026-07)

## 1. 개요

`acidwg_py`는 APCC 계절예측(3개월 tercile 확률: AN/NN/BN)을 관측소별 **일단위 기상 앙상블 시나리오**로 통계적 상세화(downscaling)하는 도구다. R 패키지 `rACID`(APCC Climate Information Downscaling Weather Generator)의 Python 포팅이며, 관측 기상 자료로 강수·기온 모델을 적합한 뒤 예측 확률에 따라 다수(기본 1000개)의 일단위 앙상블 멤버를 생성해 PICASO-Hydro 수문 파이프라인(swat_py)이 직접 읽는 CSV로 저장한다.

입력은 NetCDF 대신 관측소×월×변수별 AN/NN/BN 확률 CSV(`forecast_csv`)를 사용한다.

### 파이프라인 내 위치
```
[util_py] 국가 DB·기상 구축  →  ★[acidwg_py] 계절예측 앙상블 상세화  →  [swat_py] SWAT+ 앙상블 가뭄예측
```
acidwg_py의 출력(`1_acidwg/forecast/.../member_XXXX/{station}.csv`)이 swat_py `drought.dashboard_data`의 앙상블 입력이 된다.

## 2. 설치

```bash
pip install "git+https://github.com/IWMI-KR/picaso-hydro.git#subdirectory=acidwg_py"
# 최신 강제 업데이트
pip install --upgrade --force-reinstall --no-cache-dir --no-deps \
  "git+https://github.com/IWMI-KR/picaso-hydro.git@main#subdirectory=acidwg_py"
```

## 3. CLI 명령 (2개)

### 3.1 `acidwg-picaso-convert` — PICASO 예보확률 → 입력 CSV

PICASO 힌드캐스트 예보 확률 원본을 acidwg_py 입력 CSV(`{year}_{season}_picaso.csv`)로 일괄 변환.

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--picaso-dir` | PICASO 원본 루트 | `{ROOT}/0_database/picaso` |
| `--stations-csv` | 대상 관측소 목록(ID 컬럼) | `.../obs/weather/stations-acidwg.csv` |
| `--output-dir` | 출력 폴더 | `{ROOT}/1_acidwg/picaso` |
| `--seasons` | 계절 코드(12개 중) | 전체 12개 |
| `--years` | 연도 리스트 | 자동 감지 |

- **입력**: `0_database/picaso/prec/{MON}/{YEAR}/TP_{MON}_{YEAR}_LT{lt}.csv`(강수), `t2m/.../TT_...csv`(기온). 컬럼 `stnid, an, nn, bn`(an+nn+bn=100). 3개월 시즌의 각 월에 Lead Time 1·2·3 순차 할당(연도 경계 넘는 월은 파일연도+1). `stn_loc_unep.csv`(선택)로 id 체계 다를 때 위경도 최근접 매핑.
- **출력**: `1_acidwg/picaso/{year}_{season}_picaso.csv` (컬럼 `station_id, month, variable(prcp|t2m), AN, NN, BN`). 원본 누락 시 해당 `{year}_{season}` 건너뜀.

### 3.2 `acidwg-run` — 상세화 실행 (앙상블 생성)

관측 자료로 모델 적합 후 1000-멤버 일단위 앙상블 생성. operational(단일 year×season)·hindcast(다년 일괄)·forecast.period(공통 예측연월) 세 경로 분기.

| 인자 | 의미 | 기본값 |
|---|---|---|
| `config_file`/`--config` | 설정 YAML | 자동 탐색 |
| `--forecast YYYY_SSS` | 예측연월 단일(≤관측eyear→hindcast, 이후→operational 자동) | picaso-hydro.yaml `forecast.period` |
| `--hindcast` | hindcast 모드(yaml `hindcast` 일괄) | off |
| `--years YEAR…` | hindcast 처리 연도 일부 | yaml `hindcast.years` |
| `--seasons SEASON…` | 계절(`all` 또는 리스트) | yaml |
| `--dry-run` | 처리 대상만 출력 | off |

- 무인자 우선순위: `--forecast` > 공통 `forecast.period`(단 `--seasons` 미지정) > operational 단일. 환경변수 `ACIDWG_PY_CONFIG`, `PICASO_ROOT`.
- **입력**: 설정 YAML, 관측소 메타 `station_csv`(`Lon,Lat,Elev,ID,Ename,SYear`), 관측 일자료 `obs_dir`(util_py 표준 daily), 예측확률 `picaso_dir/{year}_{season}_picaso.csv`(convert 산출물), 모델 캐시 `model_file`(.pkl).
- **출력**: `1_acidwg/forecast/{year}_{season}/member_{NNNN}/{station_id}.csv`. 각 멤버 컬럼 `[year,] mon, day, prcp, tmax, tmin`(소수 1자리) — swat_py가 직접 읽는 포맷(누락 요소는 SWAT+ 기상발생기 `-99` 대체).

## 4. 핵심 개념 — 상세화 방법

- **tercile → 일단위 앙상블**: 입력은 월별·관측소별 tercile 확률(AN=정상초과, NN=정상, BN=하위). `get_basin_prob`로 유역평균 확률행렬 `(3, n_months)`을 만들고, 멤버마다 `determine_monthly_ch`가 강수·기온 결합분포(`np.outer` 9조합)에서 월별 습윤·온도 범주를 동시 샘플링해 두 변수 간 상관 보존.
- **모델링(`acid_modeling`)**: 관측으로 강수 모델(Gamma 강수량, 음이항 건조기간, 마르코프 패턴 전이, Gaussian copula 공간상관)과 기온 모델(LOESS detrending, EOF/PCA, pooled AR(2) Yule-Walker, skew-normal) 추정. `model_file` pickle 캐싱(`retrieve=True` 재사용).
- **시뮬레이션(`main_simulation`)**: 멤버별 강수 시나리오 → ISO(저주파 기온진동) → 기온(tmax/tmin 분리).
- **사후 보정(`calibrate_monthly_categories`)**: 강수 월합은 목표 범주 역사값으로 비례조정(multiplicative), 기온 월평균은 평행이동(additive) → 관측소별 재현확률 오차 < 5%p.
- **앙상블 크기**: 기본 1000(`ensemble.n_members`), 실패 시 재시도(최대 ×5).
- **hindcast leakage 방지**: `observation_eyear_cap=True`면 각 연도 관측 종료를 `min(eyear_obs, year-1)`로 제한하고 매 연도 재적합(캐시 미사용).

## 5. 전형적 실행 순서
1. `acidwg-picaso-convert` — PICASO 원본(prec/t2m tercile) → `1_acidwg/picaso/{year}_{season}_picaso.csv`
2. `acidwg-run` (또는 `--hindcast` / `--forecast YYYY_SSS`) — 관측 모델 적합 + 앙상블 → `1_acidwg/forecast/{year}_{season}/member_XXXX/{station}.csv`

(convert가 acidwg-run의 입력 `picaso_dir` CSV를 만든다.)

## 6. 설정 파일 `acidwg_py.yaml`

- **탐색**: `ACIDWG_PY_CONFIG` → `$PICASO_ROOT/config/acidwg_py.yaml`(권장) → cwd 상위 → 구 위치. 같은 폴더 `picaso-hydro.yaml` 병합(공통 root·obs·`ensemble.n_members`·`forecast.period`; acidwg 값 우선).
- **주요 섹션**:
  - `paths`: `base_dir`, `station_csv`, `obs_dir`(util_py 표준 daily), `picaso_dir`(forecast CSV), `output_root`(=acidwg_root), `model_file`. 필수: `station_csv, obs_dir, picaso_dir, acidwg_root`.
  - `observation`: `syear`(1981)·`eyear`(2010) — 모델 적합 관측범위.
  - `operational`: `year`·`season`("JFM") 또는 `months:[1,2,3]`.
  - `hindcast`: `years:[start,end]` 또는 리스트, `seasons`("all"/리스트), `observation_eyear_cap`(true).
  - `ensemble`: `n_members`(1000), `random_seed`(1; null=매번 다름).
  - `model`: `retrieve`(true; hindcast+cap이면 자동 false).
  - `output`: `overwrite`(false), `variables`([prcp,tmax,tmin]).
  - `advanced`(선택): `max_retry_factor`(5), `n_cores`(1), `validate_after`(false).
- YAML은 `$(섹션.키)`·`${env:VAR:default}` 문법 지원.

## 7. 계절 코드 (12개 3개월 rolling 계절)
`JFM, FMA, MAM, AMJ, MJJ, JJA, JAS, ASO, SON, OND, NDJ, DJF`
