# `swat_py.drought.climatology_run` 설명

- 작성일: 2026-08-31
- 대상: `swat_py/src/swat_py/drought/climatology_run.py` (250행)
- 실행: `swat-drought-climatology` (신규 등록) 또는 `python -m swat_py.drought.climatology_run`

## 1. 무엇을 하는가

검보정이 끝난 SWAT+ 모델을 **장기 관측 기상으로 1회 재실행**해, 가뭄위험 대시보드의
**①평년값**과 **가뭄단계 임계값(FDC)** 산정용 채널 월유량을 생산한다.

| 단계 | 내용 |
|---|---|
| 1/5 | 검보정 master(`CalibratedDir`, 지역화 파라미터 baked-in)를 **로컬 임시폴더**로 복사<br>— 프로젝트 루트가 네트워크 공유일 때 SWAT 구동이 정체되는 것을 회피 |
| 2/5 | 기상을 `stations-acidwg.csv` 의 **장기 관측소 1개**로 전 유역 재배정 |
| 3/5 | `time.sim` 을 `drought.syear ~ eyear` 로 확장 (웜업 제외 후 출력) |
| 4/5 | SWAT+ 실행. `print.prt` 를 **월단위(channel_sd_mon)** 로만 출력하도록 수정 |
| 5/5 | `channel_sd_mon.txt` 에서 `drought.outlets` 채널 유량 추출 → CSV 2종 저장 |

### 산출물 — `4_drought_risk/climatology/`

- `channel_monthly_{태그}.csv` — 월유량 시계열 (wide: date + 채널)
- `channel_monthly_avg_{태그}.csv` — 월 평년 1~12월
- 태그 = `{syear + warm_up_years}_{eyear}` (예: `1985_2023`)

가뭄단계 경계(`fdc_exceedance` Q70/Q90/Q95)는 예보와 동일한 **월유량 분포**에서
산정되므로 월단위 자료로 충분하다. 대신 일유량 유황 대표값(Q95d·Q355d 등)은 제공되지 않는다.

### 왜 월단위인가

일단위(`channel_sd_day.txt`)는 40년치가 수백 MB~1.2 GB 에 달한다. 월단위로 제한해
디스크·시간 비용을 크게 줄였다.

월단위 전환 이전에는 `channel_daily_{tag}.csv` 도 생산했으나 지금은 만들지 않으며,
쿡에 남아 있던 마지막 잔재(2026-07-05 산출)는 2026-08-31 삭제했다.
`climatology_daily_path()` 는 이름만 남은 별칭으로 실제로는 월유량 파일을 가리킨다.

## 2. 왜 `python -m` 이 필요했나 → 해소됨

`swat_py/pyproject.toml` 에 **`[project.scripts]` 섹션 자체가 없었다.**
`util_py`(10개)·`acidwg_py`(2개)는 콘솔 스크립트를 등록해 두었지만 `swat_py` 는 하나도 없어서,
모듈에 `main()` 과 `if __name__ == "__main__"` 이 갖춰져 있음에도 `python -m` 으로만 실행 가능했다.
**기술적 제약이 아니라 등록 누락이었다.**

2026-08-31 자로 13개를 등록했다(아래 §5).

> 콘솔 스크립트는 **패키지를 재설치해야** 실제 명령이 생성된다.
> `pip install -e . --no-deps` 로 반영한다.

## 3. 실질적으로 사용된 함수

| 함수 | 위치 | 기능 |
|---|---|---|
| `run_climatology(cfg, workdir, timeout)` | climatology_run | 전체 오케스트레이션(5단계). 반환 `{monthly, monthly_avg, n_outlets}` |
| `setup_acidwg_weather(cfg, work)` | climatology_run | `.cli` 인덱스와 `weather-sta.cli` 를 장기 관측소 1개로 재작성.<br>검보정용 다중 우량계(`stations-hydro.csv`)는 기록이 짧아 장기 실행 불가하므로 교체 |
| `extract_all_outlets(cha_path, outlets, out_first)` | climatology_run | `channel_sd_mon.txt` 를 **1회만** 스트리밍 파싱해 전 outlet wide 추출.<br>outlet 마다 재파싱하면 대용량 파일을 12회 읽게 됨 |
| `to_monthly(daily)` | climatology_run | 월초 날짜로 정규화한 월 시계열 (멱등) |
| `to_monthly_avg(daily)` | climatology_run | 연·월 평균 후 다년 평균 → 월 평년 1~12 |
| `climatology_tag(cfg)` | drought/climatology | 파일명 태그 `{syear+웜업}_{eyear}` 자동 산출(하드코딩 없음) |
| `resolve_swat_exe(...)` | runner/file_manager | OS별 SWAT+ 실행파일 해석, 없으면 공식 Releases 에서 자동 다운로드 |
| `_detect_colnames(path)` | output/reader_swat_plus | SWAT+ 출력 컬럼명 자동 감지 |
| `load_station_csv(path, [])` | io/station | 관측소 목록 로드 |
| `write_cli_index(var, [station], work)` | io/weather_swat_plus | `.pcp/.tmp/.slr/.hmd/.wnd` 인덱스 작성 |

### 구현상 주의점(코드 주석 근거)

- SWAT stdout 을 파이프가 아닌 **로그파일**로 리디렉션한다. 수십 년치 진행메시지가
  파이프 버퍼(~64KB)를 채우면 교착(deadlock)이 발생하기 때문.
- 실행파일 복사는 `copyfile`(메타데이터 미복사)로 — 마운트 환경의 EPERM 회피.

## 4. 기간 설정 위치

**`config/swat_py.yaml`**

```yaml
drought:
  syear: 1982
  eyear: 2023
```

여기에 **`config/picaso-hydro.yaml` 의 `warm_up_years: 3`** 이 웜업으로 적용되어
실제 출력은 `syear + 3 = 1985` 부터다. 그래서 파일명이 `..._1985_2023.csv` 가 된다.

- 우선순위: `drought.syear/eyear` → (미설정 시) `drought.climatology_years[0]/[-1]`
- 웜업은 `CioNYSKIP` 으로 로드되며 값의 출처는 공통 `warm_up_years`

### ⚠ 확인 필요한 불일치

`swat_py.yaml` 주석은 "`acidwg_py.yaml` observation(syear/eyear)과 동일 값"이라고 하지만
실제로는 어긋나 있다.

| 설정 | 값 |
|---|---|
| `acidwg_py.yaml` observation.eyear | **2024** |
| `swat_py.yaml` drought.eyear | **2023** |

의도된 차이가 아니라면 맞춰야 한다.

## 5. 매월 실행 불필요 (확인 완료)

**현업에서 매월 돌릴 필요가 없다.** 근거 3가지:

1. **파이프라인이 기본적으로 실행하지 않는다.**
   `swat_py.drought.run` 은 `--with-climatology` 를 줄 때만 실행하고, 평소엔 기존 CSV 존재만
   확인한다. 없으면 안내 후 중단한다(`run.py:44-51`).
2. **입력이 월 단위로 변하지 않는다.**
   장기 관측 기상(1982~2023)과 검보정 파라미터에만 의존하며, 매월 갱신되는
   계절예측(`forecast.period`)과 무관하다.
3. **비용이 크다.** 40년치 SWAT+ 실행으로 수 분~수십 분 소요(타임아웃 기본 7200초).

### 재실행이 필요한 경우

1. 모델 재검보정 (`CalibratedDir` 변경)
2. `drought.syear`/`eyear` 또는 `warm_up_years` 변경
3. `drought.sources` 의 outlet 구성 변경
4. 장기 관측 기상 갱신 (예: eyear 를 2024 로 연장)

→ 실무적으로 **연 1회**, 관측 기간을 한 해 연장할 때 함께 수행하면 충분하다.

## 6. 신규 등록된 swat_py 콘솔 스크립트 (13개)

| 명령 | 모듈 |
|---|---|
| `swat-drought-run` | `swat_py.drought.run` |
| `swat-drought-climatology` | `swat_py.drought.climatology_run` |
| `swat-drought-ensemble-weather` | `swat_py.drought.ensemble_weather` |
| `swat-drought-dashboard` | `swat_py.drought.dashboard_data` |
| `swat-drought-figure` | `swat_py.drought.figure` |
| `swat-drought-reclassify` | `swat_py.drought.reclassify` |
| `swat-drought-historical-worst` | `swat_py.drought.historical_worst` |
| `swat-calibration-finalize` | `swat_py.calibration.finalize` |
| `swat-promote` | `swat_py.runner.promote` |
| `swat-exe-fetch` | `swat_py.runner.fetch_exe` |
| `swat-tank-calibrate` | `swat_py.tank.calibrate` |
| `swat-tank-reservoir-calibrate` | `swat_py.tank.reservoir_calibrate` |
| `swat-tank-compare` | `swat_py.tank.compare` |

기존 `python -m swat_py.<모듈>` 방식도 그대로 동작한다(하위 호환).
