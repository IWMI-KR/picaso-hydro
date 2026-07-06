# picaso_hydro

PICASO-Hydro 프로젝트 **초기화(스캐폴딩)** 패키지. GitHub 에서 설치한 뒤 빈 프로젝트
폴더에 파이프라인 구동에 필요한 **고정 폴더 구조**와 초기 파일(샘플 config 3종 +
샘플 `country_boundary.csv`)을 생성한다. 런타임 의존성 없음(순수 stdlib).

## 설치

```bash
pip install "git+https://github.com/IWMI-KR/picaso-hydro.git#subdirectory=picaso_hydro"
```

## 사용

```bash
# CLI — 프로젝트 루트를 만들고 초기화
picaso-hydro-init /data/MyProject
python -m picaso_hydro.init /data/MyProject --force   # 기존 파일 덮어쓰기
```
```python
# 프로그램
from picaso_hydro import initialize
initialize("/data/MyProject")
```

## 생성 결과

```
MyProject/
  config/
    picaso-hydro.yaml   swat_py.yaml   acidwg_py.yaml     # 샘플 config 3종
  0_database/
    gis/admin/country_boundary.csv                        # 샘플 국가 경계(교체 필요)
    gis/{dem,soil,landuse,basin,river,user,era5,gsod}/
    era5/…  gsod/…  obs/{weather,flow,tn,tp}/  picaso/{prec,t2m}/  cmip6/…  analysis/
  1_acidwg/{picaso,forecast,cache}/
  2_qswat/
  3_swatplus/{default,calibrated,forecast}/
  4_drought_risk/{climatology,forecast}/
  reports/
```

- `picaso-hydro.yaml` 의 `project.root` 는 초기화 경로로 자동 설정되며, 환경변수
  `PICASO_ROOT` 가 있으면 그 값이 우선한다.
- `config/`·`country_boundary.csv` 가 이미 있으면 보존한다(`--force` 로 덮어쓰기).

## 다음 단계

1. `export PICASO_ROOT=/data/MyProject` (Windows: `set PICASO_ROOT=...`)
2. `0_database/gis/admin/country_boundary.csv` 를 대상 국가(NAME/ISO3/ISO2/bbox)로 편집
3. `util-gis-download` → `util-era5-download` … 로 `0_database` 채우기
4. 이후 `acidwg-run` → `python -m swat_py.drought.run` 파이프라인 실행
