# config 샘플 (최종 정리된 입력 파일)

PICASO-Hydro 통합 파이프라인의 **최종 config 샘플** 3종. 실제 실행 시에는
프로젝트 루트 `config/` 폴더에 두고 사용한다(로더가 같은 폴더의 picaso-hydro.yaml 자동 병합).

| 파일 | 역할 |
|---|---|
| `picaso-hydro.yaml` | 공통(SSOT) — root/database·예측연월·앙상블수·warm-up·관측기상 경로 |
| `swat_py.yaml` | swat 서브패키지 전용 — path/보정/Tank/가뭄/기후변화 |
| `acidwg_py.yaml` | acidwg 서브패키지 전용 — 앙상블 상세화 경로·관측기간 |

현재 코드(`src/swat_py`, `src/acidwg_py`)로 로드 검증 완료.
