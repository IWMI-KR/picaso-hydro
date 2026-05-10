# Weather mapping 템플릿

util_py.weather_std.standardize_local() 의 매핑 YAML 예시 모음.

## 사용 방법

```bash
# 1. 본인 자료 형식과 가장 가까운 템플릿 복사
cp src/util_py/templates/weather_mapping/kma.yaml \
   0_database/weather/local/mapping.yaml

# 2. 컬럼명·단위를 실제 자료에 맞게 수정

# 3. 사용자 raw 자료 배치
0_database/weather/local/raw_daily/{station_id}.csv

# 4. 표준 변환 실행
util-weather-standardize --source local
# → 0_database/weather/local/std_daily/{station_id}.csv
```

## 제공 템플릿

| 파일 | 출처 | 비고 |
|---|---|---|
| `generic.yaml` | 영문 표준 컬럼명 (date, precip, tmax, tmin, ...) | 기본 출발점 |
| `kma.yaml` | 한국 기상청 ASOS | 한글 컬럼명, 직접 hmd 제공 |
| `bom.yaml` | 호주 Bureau of Meteorology | km/h 풍속, 9am/3pm 분리 |

## 매핑 규약

- `columns.{표준컬럼}: {raw 컬럼명}` — 매핑 정의
- `units.{pcp|temp|wind}: {단위}` — raw 단위 (없으면 SI 가정)
- `wind_height_m: 10.0` — FAO-56 2m 환산용 측정 고도
- `missing_value: -999` — raw 결측 sentinel (또는 `null` = 빈 셀)
- `date_format: "%Y-%m-%d"` — pandas to_datetime 호환 패턴

## 자동 계산되는 컬럼

매핑에 없어도 다음 조건이 충족되면 자동 산출:
- `hmd_pct` ← Magnus 식 (tavg, tdew 모두 매핑된 경우)
- `tavg_c` — 매핑 없으면 출력에 NaN (magnus_rh 가 산출 못할 수 있음)
- `ws2_ms` ← FAO-56 (ws10_ms 매핑된 경우)
