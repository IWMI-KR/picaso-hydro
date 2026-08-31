# `swat_py.drought.dashboard_data` 설명

- 작성일: 2026-08-31
- 대상: `swat_py/src/swat_py/drought/dashboard_data.py` (445행)
- 실행: `swat-drought-dashboard` 또는 `python -m swat_py.drought.dashboard_data`

## 1. 무엇을 하는가

**가뭄위험 대시보드 데이터를 만드는 오케스트레이터.**
장기 평년·임계값(climatology 산출물)과 acidwg 앙상블(N멤버 상세화 기상)을 결합해
**수원(outlet)별 예측 유량 분포와 가뭄단계 확률**을 산출한다.

파이프라인상 위치:

```
[climatology_run] 평년·임계값  ┐
                              ├→ [dashboard_data] outlet × ①~⑤ → 대시보드
[acidwg-run] 앙상블 상세화     ┘
```

`swat_py.drought.run`(= `swat-drought-run`)이 이 모듈을 3단계 중 마지막으로 호출한다.
단독 실행도 가능하다.

## 2. CLI

```bash
swat-drought-dashboard                       # config 의 forecast.period · ensemble.n_members 사용
swat-drought-dashboard --forecast 2026_FMA --members 1000 --workers 6
swat-drought-dashboard --demo 5              # 5멤버만 (검증용 빠른 실행)
```

| 인자 | 의미 | 기본값 |
|---|---|---|
| `--config` | swat_py 설정 (`picaso-hydro.yaml` 공통값 자동 병합) | `config/swat_py.yaml` |
| `--forecast` | 예측연월 `{year}_{season}` | config `forecast.period` |
| `--members` | 앙상블 수 | config `ensemble.n_members` |
| `--workers` | SWAT+ 병렬 실행 워커 수 | 6 |
| `--demo N` | N멤버만 실행(검증) | 0(미사용) |

실행 마지막에 `swat_py.drought.figure.make_all_figures()` 를 호출해 그림까지 생성한다.

## 3. 처리 흐름 — `build()`

| 단계 | 내용 |
|---|---|
| 0 | `prepare_base()` — 검보정 master 를 **로컬 임시폴더**로 복사, `time.sim` 을 예측기간(웜업 선행 ~ 예측끝월)으로 설정 |
| 1 | **① 평년 + ④ FDC** — climatology CSV 로드 → outlet별 월평년·임계선 |
| 2 | **② 관측/모의** — 예측 직전월(예: FMA 예측이면 1월)의 관측기상 모의 유량 |
| 3 | **③⑤ 예측 앙상블** — `run_ensemble()` 로 N멤버 SWAT+ 병렬 실행 |
| 4 | outlet별 결과 저장 + `summary.csv` |

분위수는 `QLEVELS = [0.05, 0.25, 0.50, 0.75, 0.95]` 를 쓴다.

## 4. 실질적으로 사용된 함수

### 모듈 내부 (7개)

| 함수 | 기능 |
|---|---|
| `build(cfg, forecast, *, n_members, n_workers)` | 전체 오케스트레이션(0~4단계). 결과 경로 dict 반환 |
| `prepare_base(cfg, base_dir, fyear, months)` | calibrated master 복사 + `time.sim` 설정. Windows 삭제지연·읽기전용 대응 재시도 포함. 반환값은 해석된 실행파일 이름 |
| `_member_dir(cfg, fyear, season)` | acidwg 멤버 폴더 자동 탐색. `1_acidwg/forecast/{year}_{season}` 우선, 구 `hindcast/`·`operational/` 은 하위호환 폴백 |
| `_forecast_station(cfg)` | `stations-acidwg.csv` 의 주 관측소 ID(예측 상세화 기준) |
| `_observed_monthly(daily, outlet, fyear, obs_months)` | 예측 직전월의 관측기상 모의 월평균 유량 |
| `_seasonal_stage_row(mem, months, q185, q275, q355, season)` | 멤버별 **3개월 평균**을 먼저 구한 뒤 단계 분류 → 계절 단계확률 1행. 월별 확률의 평균이 아니라 "계절 평균 상태"의 분포를 준다 |
| `main(argv)` | CLI 진입점. config 폴백 처리 후 `build()` → `make_all_figures()` |

### 외부 모듈 (7개)

| 함수 | 출처 | 기능 |
|---|---|---|
| `climatology_daily_path(cfg)` | `drought.climatology` | 평년 CSV 경로 자동 산출. **이름과 달리 월유량 파일**(`channel_monthly_{tag}.csv`)을 가리킨다(`climatology_flow_path` 의 별칭) |
| `load_daily_flow(csv)` | `drought.climatology` | wide 유량 CSV 로드(date 파싱) |
| `outlet_climatology_and_thresholds(daily, outlet)` | `drought.climatology` | ① 월평년(mean·p25·p50·p75) + ④ FDC 임계선 |
| `stage_thresholds(daily_q, method, values, capacity)` | `drought.fdc` | 4단계 경계 산정. 하천=유량(m³/s), 저수지=저수량(m³) 또는 만수대비%. 항상 `normal_watch ≥ watch_warning ≥ warning_crisis` |
| `stage_probabilities4(values, q185, q275, q355)` | `drought.stages` | 앙상블 → Normal/Watch/Warning/Crisis 확률(%) + 최빈 단계 |
| `run_ensemble(base_dir, ensemble_dir, …)` | `drought.ensemble_flow` | N멤버 SWAT+ 병렬 실행 → `(values, aux)`. aux 에 앙상블 강수·기온·저수지 수위 포함 |
| `dumps_json(obj)` | `dashboard.json_writers` | NaN → null 표준 JSON 직렬화 |

## 5. 산출물

### `3_swatplus/forecast/{period}/{outlet}.csv` — long format (member × month)

- 하천 : `member, month, precip_mm, tmax_c, tmin_c, flo_m3s`
- 저수지: 위 + `water_level_ft, storage_pct`

### `4_drought_risk/forecast/{period}/{outlet}/`

| 파일 | 내용 |
|---|---|
| `series.csv` | 평년·관측·예측 분위(QLEVELS) 시계열 |
| `thresholds.csv` | 4단계 경계값 |
| `stage_prob.csv` | 월별 단계확률 |
| `stage_prob_season.csv` | 계절 전체 단계확률(1행) |
| `ensemble_members.csv` | 멤버별 원자료 |
| `dashboard.json` | 대시보드용 통합 JSON(NaN→null) |

상위 폴더에 `summary.csv` 를 함께 저장한다.

## 6. 설계상 주목할 점

### 로컬 실행 강제

base 준비와 멤버 실행은 시스템 임시폴더(`C:`)에서 수행한다.
프로젝트 루트가 네트워크 공유(`I:` = `\10.9.0.200`)이므로 N개 멤버가 각자 base 를
네트워크에서 복사하면 극도로 느려지기 때문이다. 결과 CSV(소용량)만 프로젝트에 저장한다.

### 초기조건 시나리오 분리

저수지 초기수위 등 시나리오는 `Drought.forecast_suffix()` 로 **출력 폴더에만** 태그를 붙인다
(예: `2016_AMJ__ic44.0ft-scn`). 입력·멤버·평년 경로는 실제 연월 기준을 그대로 써서,
같은 기간의 초기조건별 결과를 구분해 보관한다.

### 수원 유형별 분기

`drought.sources` 에서 수원마다 `type`(stream|reservoir)·`thresholds`·`outlets` 를 독립 지정한다.
저수지 수원은 채널 유량 대신 `reservoir_day` 물수지의 만수대비%로 단계를 판정하며,
레지스트리·수위-내용적 곡선이 없으면 경고 후 건너뛴다.

## 7. 실행 전 전제

1. **climatology 산출물** — `4_drought_risk/climatology/channel_monthly_{tag}.csv`
   (없으면 `swat-drought-climatology` 먼저 실행)
2. **acidwg 앙상블** — `1_acidwg/forecast/{year}_{season}/member_XXXX/`
   (없으면 `acidwg-run` 먼저 실행)

2026-08-31 기준 쿡·팔라우 모두 두 전제가 준비되어 있어 `2026_FMA` 로 바로 구동 가능하다.

## 8. 참고 — `climatology_daily_path` 명명

`climatology_daily_path` 는 **월유량 파일**을 반환하는 별칭이다
(`climatology_flow_path` 와 동일 함수. 일유량은 더 이상 생산하지 않는다).

이름 때문에 일유량 파일을 읽는 것으로 오해하기 쉬워, 이를 언급하던 주석·docstring
4곳을 2026-08-31 정리했다.

- `swat_py/src/swat_py/drought/climatology.py`
- `swat_py/src/swat_py/drought/dashboard_data.py`
- `config_samples/swat_py.yaml`
- `picaso_hydro/src/picaso_hydro/templates/config/swat_py.yaml`

함수 이름 자체는 외부 호출부(`drought/run.py`, `drought/reclassify.py`)와의 호환을 위해
별칭으로 유지한다.
