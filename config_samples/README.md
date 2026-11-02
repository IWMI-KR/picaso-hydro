# config 샘플 (최종 정리된 입력 파일)

PICASO-Hydro 통합 파이프라인의 **config 샘플 4종**. 실제 실행 시에는 프로젝트 루트
`config/` 폴더에 두고 사용한다(로더가 같은 폴더의 `picaso-hydro.yaml` 을 자동 병합).

| 파일 | 역할 |
|---|---|
| `picaso-hydro.yaml` | 공통(SSOT) — root/database·예측연월·앙상블수·warm-up·관측기상 경로 |
| `swat_py.yaml` | swat 서브패키지 전용 — 모델/경로·검보정·Tank·가뭄 대시보드·기후변화·저수지 레지스트리 |
| `acidwg_py.yaml` | acidwg 서브패키지 전용 — 앙상블 상세화 경로·관측기간 |
| `util_py.yaml` | util 서브패키지 전용 — ERA5·GSOD 내려받기, 표준화, GIS 자료 준비 |

## 쓰는 법

1. 네 파일을 프로젝트의 `config/` 로 복사한다.
2. `picaso-hydro.yaml` 의 `project.root` 를 실제 경로로 바꾸거나,
   환경변수 `PICASO_ROOT` 를 지정한다(환경변수가 우선).
3. 대상 지역에 맞게 고친다 — 관측소·유역 outlet·검보정 기간·평년 기간.
4. 저수지(댐)가 없는 프로젝트라면 `swat_py.yaml` 의
   `drought.sources.example_dam` 과 `reservoirs:` 블록을 통째로 지운다.

## 샘플이 보여주는 것

`swat_py.yaml` 은 **하천수와 저수지 두 수원이 함께 있는** 프로젝트를 예로 든다.
쿡(하천만)·팔라우(하천+댐) 어느 쪽으로도 줄여 쓸 수 있게 하기 위해서다.
자주 틀리는 자리에는 주석으로 경고를 달아 두었다 —
기준면(datum) 차이, `%` 의 정의(저수량 vs 수위), 만수 경계를 100%로 두면 안 되는 이유.

## 코드와의 일관성

`swat_py/tests/test_config_samples.py` 가 매 테스트 실행마다 확인한다.

- 샘플이 **현재 로더로 로드**되는가
- 로더가 읽는 설정 키가 **전부 샘플에 적혀** 있는가 (주석 처리된 선택 항목도 인정)
- 폐기된 구 스키마(`drought.thresholds` / `drought.outlets`)로 되돌아가지 않았는가
- 비밀값·특정 프로젝트 절대경로가 섞이지 않았는가

**설정 키를 새로 추가하면 이 테스트가 실패한다.** 그때 고칠 것은 테스트가 아니라
이 폴더의 샘플이다. 키를 적고 한 줄 주석으로 뜻을 밝히면 된다.
문서화가 불필요한 내부·레거시 키라면 테스트 파일의 `UNDOCUMENTED` 에
**사유와 함께** 추가한다.
