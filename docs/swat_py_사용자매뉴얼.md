# swat_py 사용자 매뉴얼

> PICASO-Hydro 서브패키지 · SWAT+ 자동 검보정 · 가뭄예측 · 저수지·Tank 모델링
> 최신 코드 기준 (2026-07)

## 1. 개요

`swat_py`는 PICASO-Hydro의 SWAT+ 모델 자동화 서브패키지다. QSWAT+로 구축한 SWAT+ 모델을 대상으로 **DDS 자동 검보정**, **장기 기후(평년·유황곡선) 재실행**, **앙상블 가뭄예측**, **저수지 물수지 모델링**, **집중형 3단 Tank 모형 검보정**, 그리고 이를 종합한 **가뭄위험 대시보드 산출물** 생성을 담당한다.

모든 CLI는 콘솔 스크립트가 없으며 **`python -m swat_py.<module>`** 형태로 실행하고, 대부분 설정 파일 `config/swat_py.yaml`(공통값 `config/picaso-hydro.yaml` 자동 병합)만으로 구동된다.

### 파이프라인 내 위치
```
[util_py] 국가 DB  →  [acidwg_py] 앙상블 상세화  →  ★[swat_py] SWAT+ 검보정·가뭄예측·대시보드
```

## 2. 설치

```bash
pip install "git+https://github.com/IWMI-KR/picaso-hydro.git#subdirectory=swat_py"
# 최신 강제 업데이트
pip install --upgrade --force-reinstall --no-cache-dir --no-deps \
  "git+https://github.com/IWMI-KR/picaso-hydro.git@main#subdirectory=swat_py"
```

> 별도 표기가 없으면 `--config` 기본값은 `config/swat_py.yaml`이며, 같은 폴더의 `picaso-hydro.yaml`(공통 SSOT: 예측연월·앙상블수·warm-up·경로)을 자동 병합한다.

## 3. CLI 모듈

### 3.1 검보정 (calibration)

#### `swat_py.calibration.auto` — 자동 검보정(DDS) · ★라이브러리(무 CLI)
- **주의**: `main()`/`__main__`이 **없어** `python -m`로 직접 실행하지 않는다. `from swat_py.calibration.auto import run_auto_calibration; run_auto_calibration(cfg)`로 **프로그램에서 호출**.
- **용도**: `yaml.calibration` 설정에 따라 DDS로 다중 관측소 SWAT+ 자동 검보정.
- **동작**: 인자범위 추출 → SWAT+.exe 확보 → N회 반복(인자 샘플링 → `default/`→`runs/run_NNNN/` 복제 → 인자 적용(지역보정 rows 포함) → SWAT+ 실행 → 관측·모의 매칭 후 목적함수 평가).
- **목적함수**: 관측소별 지표(NSE/KGE/R²/PBIAS/RMSE) 정규화 후 `weight` 가중합(최대화), **보정기간(cal_period)** 관측치만 평가.
- **출력**(`3_swatplus/calibration/results/`): `all_runs.csv`, `top5_runs.csv`, `parameter_changes.csv`(default vs best), `cal_val_summary.csv`(관측소별 보정/검증 성능), `figures/`.

#### `swat_py.calibration.finalize` — 검보정 후처리(발행)
```bash
python -m swat_py.calibration.finalize [--config ...] [--steps sim,figs,history,promote|all]
```
- 자동 검보정 결과로 최종 산출물 생성. 지역보정(rows)을 **위치(순서) 결합**으로 정확 복원해 Top1 재현.
- 단계: `sim`(Top1 파라미터로 SWAT+ 1회 → `results/top1_sim_daily.csv`) · `figs`(5-패널 그림 + `pub_report_index.csv`) · `history`(`final_parameters.csv`(rows 포함 정본), `calibration_stage_history.csv`) · `promote`(그림·요약 → `reports/04_검보정결과/`).

### 3.2 가뭄 (drought)

#### `swat_py.drought.climatology_run` — 장기 기후 재실행 (평년·FDC)
```bash
python -m swat_py.drought.climatology_run [--config ...] [--workdir DIR] [--timeout SEC]
```
- 검보정 master를 복사, 기상을 장기 관측소(`stations-acidwg.csv`) 단일로 전 유역 재배정, `time.sim`을 `drought.syear~eyear`로 확장해 1회 실행 → 대시보드 ①평년·④FDC용 채널 **월유량**.
- **출력**(`4_drought_risk/climatology/`): `channel_monthly_{tag}.csv`, `channel_monthly_avg_{tag}.csv`. tag=`{syear+warmup}_{eyear}`.

#### `swat_py.drought.dashboard_data` — 예측 앙상블 → 대시보드
```bash
python -m swat_py.drought.dashboard_data [--forecast 2016_AMJ] [--members 100] [--workers 6] [--demo N]
```
- base(calibrated + 예측기간 time.sim) 준비 → 앙상블 SWAT+ 실행 → 수원별 series/thresholds/stage_prob/dashboard.json + summary.
- 인자: `--forecast`(기본 config forecast.period), `--members`(기본 config n_members), `--workers`(6), `--demo N`(>0이면 N멤버만, 검증용).
- **입력**: climatology CSV, 앙상블 멤버(`1_acidwg/forecast/{year}_{season}/member_*`), `calibrated/`.
- **출력**: `3_swatplus/forecast/{period}/{outlet}.csv`(하천: `member,month,precip_mm,tmax_c,tmin_c,flo_m3s` / 저수지: `…,water_level_ft,storage_pct`). `4_drought_risk/forecast/{period}/{outlet}/`(series·thresholds·stage_prob·ensemble_members·dashboard.json) + `summary.csv`·`summary_season.csv` + 그림. (dashboard.json은 결측을 표준 JSON `null`로 출력.)

#### `swat_py.drought.historical_worst` — 계절/월 최저강수 worst 모의
```bash
python -m swat_py.drought.historical_worst [--monthly] [--reservoir-hindcast] [--gen-reservoir-daily]
```
- 장기 관측강수(.pcp)로 12개 계절(JFM…DJF) 연도별 강수총량 → 각 계절 **최저강수 연도** 선택(결측 과다 raw 최저는 로그 기록 후 차선 신뢰연도로 대체), 같은 장기모의에서 그 연도 계절 결과를 수원별 정리.
- 옵션: `--monthly`(달력 월 1~12), `--reservoir-hindcast`(관측기간 저수지 재모델링 flo_in+취수+관측초기화 vs 관측), `--gen-reservoir-daily`(장기 저수지 일유입 flo_in SWAT 생성, 수 분 선행).
- **출력**(`3_swatplus/forecast/historical_worst/`): `driest_year_by_season|by_month.csv`, `modeling_results_by_season|by_month.csv`, `reliability_log_*.txt`, (옵션) `reservoir_hindcast_daily.csv`, `reservoir_day_{s}_{e}.csv`.

#### `swat_py.drought.reclassify` — 단계 재분류 (SWAT 재실행 불필요)
```bash
python -m swat_py.drought.reclassify [--forecast 2016_AMJ] [--n-ensemble N] [--dashboard-root DIR]
```
- 저장된 분위(series.csv p5~p95)에서 경험적 CDF로 4단계 확률 재구성. 임계 변경 후 단계경계만 재적용.
- **출력**: 대상 outlet별 `stage_prob.csv`·`thresholds.csv`·`dashboard.json` 갱신 + 그림 + `summary.csv`.

#### `swat_py.drought.run` — 가뭄예측 end-to-end
```bash
python -m swat_py.drought.run --forecast 2016_AMJ [--members N] [--workers W] [--with-climatology] [--skip-acidwg]
```
- 예측연월 하나로 ①장기 기후(전제) → ②acidwg 앙상블 상세화 → ③SWAT+ 앙상블+대시보드 자동 연결.
- 옵션: `--with-climatology`(장기 기후 선행), `--skip-acidwg`(기존 멤버 사용), `--acidwg-config`(기본 `config/acidwg_py.yaml`).

#### `swat_py.drought.ensemble_weather` — acidwg 상세화 진입점
```bash
python -m swat_py.drought.ensemble_weather [--forecast 2016_AMJ] [--members N] [--acidwg-config config/acidwg_py.yaml]
```
- 공통 config의 예측대상·앙상블수 + `acidwg_py.yaml`의 관측기간·WGEN으로 일단위 N멤버 weather 상세화. `fyear≤eyear_obs`면 hindcast, 이후면 operational.

#### `swat_py.drought.figure` — outlet별 대시보드 그림
```bash
python -m swat_py.drought.figure [--forecast 2016_AMJ] [--out-root DIR]
```
- `series/thresholds/stage_prob.csv` → `dashboard_{outlet}.png`(시계열+표), `_gauge.png`, `_pie.png`(월별+3개월평균), `_season_pie.png`. 저수지 outlet은 만수대비 저수량% 축으로 자동 전환.

### 3.3 Tank 모형 (tank)

#### `swat_py.tank.calibrate` — Tank 유량 검보정
```bash
python -m swat_py.tank.calibrate [--iters N]
```
- 관측소별 3단 Tank(9개 파라미터)를 SWAT+와 동일 관측·기간·목적함수(NSE, 보정기간)로 DDS 검보정.
- **출력**(`3_swatplus/calibration-tank/`): `params/{station}_tank_params.csv`, `results/tank_sim_daily.csv`·`cal_val_summary.csv`, `figures/{station}_cal|val_flow.png`.

#### `swat_py.tank.reservoir_calibrate` — Tank 저수지 수위 검보정
```bash
python -m swat_py.tank.reservoir_calibrate [--iters N] [--objective kge|nse|r2|pbias] [--transfer-to ngerikiil]
```
- 저수지(예 Ngerimel)를 **수위**로 검보정: Tank 유입 q → 물수지(유입−취수, 여수로 월류·사수위 하한) → 수위내용적 곡선 → 수위(MSL) → 관측수위(datum offset 정합) 비교. 결정 파라미터를 변경 없이 다른 유역(면적·강수만 교체)에 적용해 유량 vs 관측수위 산점도 생성.
- `--objective` 기본 `kge`(관리형 저수지는 변동 작아 NSE 착시 방지).
- **출력**(`3_swatplus/calibration-tank/`): `params/ngerimel_tank_reservoir_params.csv`, `results/tank_reservoir_sim_daily.csv`·`cal_val_summary.csv`·`figures/ngerimel_wlevel_calib.png`, `transfer/{target}_flow_vs_wlevel.csv`+`.png`.

#### `swat_py.tank.compare` — SWAT+ vs Tank 유량 비교
```bash
python -m swat_py.tank.compare
```
- SWAT+ `top1_sim_daily.csv` vs Tank `tank_sim_daily.csv`를 관측치와 비교.
- **출력**(`reports/05_모형간_유량비교/`): `{station}_flow_compare.png`, `model_comparison_summary.csv`, `README.md`.

### 3.4 실행파일 관리 (runner)

#### `swat_py.runner.fetch_exe` — SWAT+ 실행파일 자동 다운로드
```bash
python -m swat_py.runner.fetch_exe [--project PATH] [--version latest] [--dirs DIR...]
```
- OS/아키텍처 감지 후 공식 GitHub Releases(`swat-model/swatplus`, gnu 우선)에서 실행파일 받아 저장(비-Windows는 chmod +x). 기본 저장 `3_swatplus/calibrated`·`default`.

#### `swat_py.runner.promote` — QSWAT+ Default → 검보정 마스터 승격
```bash
python -m swat_py.runner.promote [--source TxtInOut] [--dest 마스터] [--keep-outputs] [--dry-run] [--yes]
```
- QSWAT+ `Scenarios/Default/TxtInOut`을 검보정 마스터(`3_swatplus/default`)로 복사·동결. 기본은 SWAT+ 출력(`*_day/_mon/_yr/_aa.txt` 등) 제외한 lean 마스터.

## 4. 주요 개념

### (a) 자동 검보정 (DDS · 분할표본)
- **DDS**(`calibration.optimizer.dds_optimize`): `perturbation r=0.20`·`seed` 재현. 각 반복=SWAT+ 1회 실행. 목적함수=관측소별 지표 정규화 후 `weight` 가중합(최대화).
- **분할표본**: `calibration.period`(보정)로만 평가, 완료 후 `calibration.validation`(검증)로 독립 검증. period 비우면 전체 sim∩obs로 복귀(하위호환).
- **지역보정(rows)**: 파라미터에 `rows`(SWAT+ 파일 특정 행) 주면 전역 적용 후 그 행만 덮어씀. `parameter_changes.csv`는 rows 없어 `finalize`가 config와 위치결합으로 복원 → `final_parameters.csv` 정본화.

### (b) 저수지 수원 (type=reservoir · capacity_fraction · flo_in 물수지)
- `drought.sources.<name>.type: reservoir` → 채널 유량 대신 **만수 대비 저수량%(capacity_fraction)**로 가뭄단계. 임계 예 `[100,85,65]`% (만수 이상=Normal, ~85 Watch, 85~65 Warning, 65↓ Crisis).
- **물수지**: `S = clip(S + flo_in(+precip−evap−seep) − 취수, dead, full)`. 예측 앙상블은 `reservoir_day.txt`의 실제 유입 `flo_in`을 써 만수대비%·수위(ft) 산출. 채널유량 근사는 저수지 용량이 채널 월유량보다 작을 때 만수 고정 문제 → `--gen-reservoir-daily` 장기 flo_in 연속 물수지가 정확.
- **곡선/registry**(`reservoirs.<name>`): `stage_storage_file`(수위내용적), `spillway_ft`(만수/여수로), `bottom_ft`(사수위), `withdrawal_m3s`(취수), `obs_datum_offset_ft`(관측 staff-gauge↔곡선 datum 정합), `interp`(pchip/linear).

### (c) 3단 Tank 모형 (직렬 Sugawara)
- Tank1(표층: a1@ha1·a2@ha2, 침투 b1, 증발) → Tank2(a3@hb1, 침투 b2) → Tank3(기저 a4@0). Q(mm)=qa+qb+qc.
- 파라미터 9개: `a1,a2,ha1,ha2,b1 / a3,hb1,b2 / a4`. `q_m3s = q_mm·area_km2/86.4`. 물수지 폐합 `ΣP=ΣQ+ΣE+ΔS`. `tank.pet_method`: hargreaves/hamon/priestley_taylor.

### (d) config `swat_py.yaml` 주요 블록
- **`path`**: `qswat_txtinout`, `swatplus_txtinout`(=DefaultDir), `observed`, `cc_weather`. (root·warm-up 등 공통은 `picaso-hydro.yaml`)
- **`simulation`**: `start_date`·`end_date`·`time_step`.
- **`calibration`**: `period`/`validation`(분할표본), `observations[]`(id·outlet_id(채널 gis_id)·variable(flow/tn/tp/wlevel)·unit·obs_file·weight·objective), `parameters[]`(file·key·range·change_type(absval/relchg/abschg)·rows), `method`(name·n_iterations·seed).
- **`tank`**: `pet_method`·`default_lat`·`precip_mapping`·`basin_areas`·`parameters{a1..a4}`·`method`.
- **`drought`**: `syear`/`eyear`, `sources.<name>`(type stream|reservoir·thresholds{method,values}·outlets{gis_id:이름}·(저수지) reservoir·init_water_level_ft·measured). flat 하위호환도 지원.
- **`reservoirs.<name>`**(저수지 프로젝트 전용): `gis_id`·`stage_storage_file`·`spillway_ft`·`bottom_ft`·`withdrawal_m3s`·`obs_datum_offset_ft`·`interp`.
- **`climate_change`**(선택): enabled·metadata_file.

## 5. 전형적 실행 순서
```bash
# 0. 실행파일·마스터 준비
python -m swat_py.runner.fetch_exe --project <root>
python -m swat_py.runner.promote                      # QSWAT+ Default → 3_swatplus/default

# 1. 자동 검보정(DDS) — run_auto_calibration(cfg) 프로그램 호출 후
python -m swat_py.calibration.finalize --steps all    # → 3_swatplus/calibration/results, reports/04_검보정결과

# 2. 장기 기후(평년·FDC)
python -m swat_py.drought.climatology_run             # → 4_drought_risk/climatology

# 3. 예측 앙상블 → 대시보드
python -m swat_py.drought.dashboard_data --forecast 2016_AMJ --members 1000
#   또는 end-to-end: python -m swat_py.drought.run --forecast 2016_AMJ --with-climatology

# 4. (보조) 계절/월 최저강수 worst 모의
python -m swat_py.drought.historical_worst            # 계절
python -m swat_py.drought.historical_worst --monthly  # 월
#   (저수지: --gen-reservoir-daily 선행 → --reservoir-hindcast 검증)
```
보조/선택: Tank(`tank.calibrate`, `tank.reservoir_calibrate`) → `tank.compare`, 임계 변경 후 `drought.reclassify`, 그림만 `drought.figure`.

## 6. 산출물 폴더 요약
```
3_swatplus/
├── calibration/results/     top1_sim_daily·cal_val_summary·parameter_changes·final_parameters·figures
├── calibration-tank/        params·results·transfer  (Tank 검보정)
└── forecast/{period}/{outlet}.csv  ·  forecast/historical_worst/
4_drought_risk/
├── climatology/             channel_monthly(_avg)_{tag}.csv
└── forecast/{period}/{outlet}/  series·thresholds·stage_prob·dashboard.json + 그림
reports/04_검보정결과 · 05_모형간_유량비교
```
