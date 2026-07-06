"""acidwg_py.yaml 설정 파일 로더.

기능
----
- YAML 파싱
- 교차참조 ``$(섹션.키)`` (점-경로) — swat_py·util_py와 통일된 양식
- 환경변수 ``${env:VAR}`` / ``${env:VAR:default}``
- season → sim_period 변환 (12개 3개월 계절)
- 필수 키 유효성 검증

반환
----
:func:`load_config` 는 dict를 반환합니다 (run.py의 ``cfg["sim_period"]`` 등 호출과 호환).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


# 계절 코드 → 월 리스트 (APCC 계절예측 12개 3개월 계절)
SEASON_MONTHS: Dict[str, list[int]] = {
    "JFM": [1, 2, 3],
    "FMA": [2, 3, 4],
    "MAM": [3, 4, 5],
    "AMJ": [4, 5, 6],
    "MJJ": [5, 6, 7],
    "JJA": [6, 7, 8],
    "JAS": [7, 8, 9],
    "ASO": [8, 9, 10],
    "SON": [9, 10, 11],
    "OND": [10, 11, 12],
    "NDJ": [11, 12, 1],
    "DJF": [12, 1, 2],
}


# ── 교차참조 + 환경변수 치환 ─────────────────────────────────────────────────

_REF_RE = re.compile(r"\$\(([\w\.]+)\)")
_ENV_RE = re.compile(r"\$\{env:([A-Z_][A-Z0-9_]*)(?::([^}]*))?\}")


def _flat_get(data: Dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"교차참조 키 '{dotted}' 를 찾을 수 없습니다.")
        cur = cur[part]
    return cur


def _resolve_string(s: str, root: Dict[str, Any], _stack: Optional[set] = None) -> str:
    if _stack is None:
        _stack = set()

    def env_sub(m: re.Match) -> str:
        var, default = m.group(1), m.group(2)
        return os.environ.get(var, default if default is not None else "")
    s = _ENV_RE.sub(env_sub, s)

    while True:
        m = _REF_RE.search(s)
        if not m:
            return s
        key = m.group(1)
        if key in _stack:
            raise ValueError(f"교차참조 순환: {key}")
        try:
            value = _flat_get(root, key)
        except KeyError as e:
            raise ValueError(f"교차참조 해석 실패: $({key}) — {e}") from None
        if not isinstance(value, str):
            value = str(value)
        value = _resolve_string(value, root, _stack | {key})
        s = s[: m.start()] + value + s[m.end() :]


def _resolve_tree(node: Any, root: Dict[str, Any]) -> Any:
    if isinstance(node, dict):
        return {k: _resolve_tree(v, root) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_tree(v, root) for v in node]
    if isinstance(node, str):
        return _resolve_string(node, root)
    return node


# ── 메인 로더 ────────────────────────────────────────────────────────────────

def _expand_years(spec: Any) -> List[int]:
    """``hindcast.years`` 를 정수 리스트로 전개.

    - [start, end] (정확히 2 항목, start <= end) → 연속 범위
    - [a, b, c, ...] (3 이상) → 명시 리스트 그대로
    """
    if not isinstance(spec, list) or len(spec) < 2:
        raise ValueError(
            f"hindcast.years 는 [start, end] 또는 [y1, y2, ...] 형식: {spec!r}"
        )
    items = [int(x) for x in spec]
    if len(items) == 2 and items[0] <= items[1]:
        return list(range(items[0], items[1] + 1))
    return items


def _expand_seasons(spec: Any) -> List[str]:
    """``hindcast.seasons`` 를 계절 코드 리스트로 전개."""
    if isinstance(spec, str) and spec.lower() == "all":
        return list(SEASON_MONTHS.keys())
    if not isinstance(spec, list):
        raise ValueError(
            f"hindcast.seasons 는 'all' 또는 ['JFM', ...] 리스트: {spec!r}"
        )
    out = []
    for s in spec:
        s = str(s).upper()
        if s not in SEASON_MONTHS:
            raise ValueError(
                f"지원하지 않는 계절 코드: '{s}'\n"
                f"  사용 가능: {list(SEASON_MONTHS.keys())}"
            )
        out.append(s)
    return out


def _load_shared_yaml(config_file: str) -> Dict[str, Any]:
    """같은 config 폴더의 공통 picaso-hydro.yaml 로드(없으면 {})."""
    p = Path(config_file).parent / "picaso-hydro.yaml"
    if not p.is_file():
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _merge_shared_acidwg(shared: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    """공통(중립) 키를 acidwg 설정 구조로 주입. acidwg_py.yaml 값이 있으면 우선."""
    if not shared:
        return raw
    proj = shared.get("project") or {}
    # 참조 해석용 project 주입
    raw.setdefault("project", {})
    for k, v in proj.items():
        raw["project"].setdefault(k, v)
    paths = raw.setdefault("paths", {})
    paths.setdefault("base_dir", proj.get("root"))
    paths.setdefault("obs_dir", proj.get("obs_weather_std"))    # 공통 관측기상
    # station_csv 는 obs_dir(=obs_weather_std)/stations-acidwg.csv 로 자동 해석
    paths.setdefault("station_csv", "$(paths.obs_dir)/stations-acidwg.csv")
    # picaso_dir·output_root 는 acidwg_py.yaml 에서 관리(공통 주입 안 함)
    nm = (shared.get("ensemble") or {}).get("n_members")
    if nm is not None:
        raw.setdefault("ensemble", {}).setdefault("n_members", nm)
    # 공통 예측연월(forecast.period) — acidwg-run 무인자 실행의 기본 대상(SSOT).
    #   acidwg_py.yaml 에 두지 않고, picaso-hydro.yaml 에 있으면 그 값을 전달만 한다.
    period = (shared.get("forecast") or {}).get("period")
    if period is not None:
        raw.setdefault("forecast_period", period)
    return raw


def load_config(config_file: str) -> Dict[str, Any]:
    """acidwg_py.yaml을 읽어 파싱된 설정 딕셔너리 반환.

    YAML 섹션
    ---------
    paths        : station_csv, obs_dir, picaso_dir, acidwg_root, ensemble_root, model_file
    observation  : syear, eyear
    operational  : year, season(또는 months)            # 단일 — acidwg-run 기본
    hindcast     : years, seasons, observation_eyear_cap  # 일괄 — acidwg-run --hindcast
    ensemble     : n_members, random_seed
    model        : retrieve
    output       : overwrite, variables
    advanced     : max_retry_factor, n_cores, validate_after  (optional)

    Returns
    -------
    dict — operational 키들 (forecast_year, sim_period, output_dir 등) 은
    operational 블록에서 채우고, hindcast 블록은 ``hindcast`` 하위 딕셔너리로
    유지. CLI 가 mode 별로 분기.
    """
    config_path = Path(config_file)
    if not config_path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없음: {config_file}")

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ValueError(f"설정 파일이 비어 있음: {config_file}")
    if not isinstance(raw, dict):
        raise ValueError(f"YAML 최상위는 매핑이어야 합니다: {config_file}")

    # ── 공통 picaso-hydro.yaml 병합 (경로·앙상블수 등 공통값 주입) ────────────
    raw = _merge_shared_acidwg(_load_shared_yaml(config_file), raw)

    # ── 교차참조 + 환경변수 해석 ──────────────────────────────────────────────
    resolved = _resolve_tree(raw, raw)

    # ── 경로 ──────────────────────────────────────────────────────────────────
    paths = resolved.get("paths") or {}
    # acidwg_root(신) ↔ output_root(구) 호환
    if "acidwg_root" not in paths and "output_root" in paths:
        paths["acidwg_root"] = paths["output_root"]
    _required = ["station_csv", "obs_dir", "picaso_dir", "acidwg_root"]
    for key in _required:
        if key not in paths:
            raise ValueError(
                f"paths.{key} 가 설정 파일에 없음 "
                f"(operational/hindcast 공용)"
            )

    # ── 관측 기간 ──────────────────────────────────────────────────────────
    obs = resolved.get("observation") or {}
    syear_obs = int(obs.get("syear", 1981))
    eyear_obs = int(obs.get("eyear", 2010))

    if syear_obs >= eyear_obs:
        raise ValueError(f"observation.syear({syear_obs}) ≥ eyear({eyear_obs})")

    # ── operational 블록 (단일 연도/시즌) ─────────────────────────────────
    op = resolved.get("operational") or {}
    if not op:
        # 친절한 안내 — 옛 'forecast:' 키 사용 시 명시적 에러
        if "forecast" in resolved:
            raise ValueError(
                "yaml 의 'forecast:' 키는 'operational:' 으로 변경되었습니다.\n"
                "  yaml 을 다음과 같이 수정하세요:\n"
                "    operational:\n"
                "      year:   2024\n"
                "      season: 'JFM'"
            )
        raise ValueError("operational 섹션이 없습니다 (year/season 필요)")

    forecast_year = int(op.get("year", 2025))
    if "months" in op:
        sim_period = [int(m) for m in op["months"]]
        if not all(1 <= m <= 12 for m in sim_period):
            raise ValueError(f"operational.months 범위 오류: {sim_period}")
    else:
        season = str(op.get("season", "JJA")).upper()
        if season not in SEASON_MONTHS:
            raise ValueError(
                f"지원하지 않는 계절 코드: '{season}'\n"
                f"  사용 가능: {list(SEASON_MONTHS.keys())}"
            )
        sim_period = SEASON_MONTHS[season]

    # ── hindcast 블록 (선택) ─────────────────────────────────────────────
    hc_raw = resolved.get("hindcast")
    if hc_raw:
        hc_years = _expand_years(hc_raw.get("years"))
        hc_seasons = _expand_seasons(hc_raw.get("seasons", "all"))
        hc_eyear_cap = bool(hc_raw.get("observation_eyear_cap", True))
        hindcast_cfg: Optional[Dict[str, Any]] = {
            "years":   hc_years,
            "seasons": hc_seasons,
            "observation_eyear_cap": hc_eyear_cap,
        }
    else:
        hindcast_cfg = None

    # ── 앙상블 ────────────────────────────────────────────────────────────
    ens = resolved.get("ensemble") or {}
    n_ensemble  = int(ens.get("n_members", 1000))
    seed_raw    = ens.get("random_seed", 1)
    random_seed = None if seed_raw is None else int(seed_raw)

    if n_ensemble < 1:
        raise ValueError(f"ensemble.n_members 는 1 이상이어야 함: {n_ensemble}")

    # ── 모델 ──────────────────────────────────────────────────────────────
    mdl      = resolved.get("model") or {}
    retrieve = bool(mdl.get("retrieve", True))

    # ── 출력 ──────────────────────────────────────────────────────────────
    out_sec   = resolved.get("output") or {}
    overwrite = bool(out_sec.get("overwrite", False))
    variables = list(out_sec.get("variables") or ["prcp", "tmax", "tmin"])

    # ── 고급 설정 ──────────────────────────────────────────────────────────
    adv              = resolved.get("advanced") or {}
    max_retry_factor = int(adv.get("max_retry_factor", 5))
    n_cores          = int(adv.get("n_cores", 1))
    validate_after   = bool(adv.get("validate_after", False))

    # 단일 forecast_csv / output_dir 자동 산출
    # output_dir 은 forecast base — acid_run 이 forecast_year 로 {year}_{season} 폴더 부여
    forecast_csv_op = (
        Path(paths["picaso_dir"])
        / f"{forecast_year}_{_season_label(sim_period)}_picaso.csv"
    )
    output_dir_op = Path(paths["acidwg_root"]) / "forecast"

    return {
        # 경로 (공용)
        "station_csv":       paths["station_csv"],
        "obs_dir":           paths["obs_dir"],
        "picaso_dir":        paths["picaso_dir"],
        "acidwg_root":       paths["acidwg_root"],
        "output_root":       paths["acidwg_root"],   # 호환 별칭(구 이름)
        "ensemble_root":             paths.get("ensemble_root"),   # 통합 forecast 루트
        "model_file":        paths.get("model_file"),
        # 관측 기간
        "syear_obs":         syear_obs,
        "eyear_obs":         eyear_obs,
        # operational (단일) 자동 산출 — acidwg-run 기본 모드에서 사용
        "forecast_year":     forecast_year,
        "sim_period":        sim_period,
        "forecast_csv":      str(forecast_csv_op),
        "output_dir":        str(output_dir_op),
        # hindcast (일괄) — acidwg-run --hindcast 사용
        "hindcast":          hindcast_cfg,
        # 공통 예측연월(picaso-hydro.yaml forecast.period) — 무인자 실행의 기본 대상. 없으면 None.
        "forecast_period":   resolved.get("forecast_period"),
        # 공통 옵션
        "n_ensemble":        n_ensemble,
        "random_seed":       random_seed,
        "retrieve":          retrieve,
        "overwrite":         overwrite,
        "variables":         variables,
        "max_retry_factor":  max_retry_factor,
        "n_cores":           n_cores,
        "validate_after":    validate_after,
    }


def _season_label(sim_period: List[int]) -> str:
    """월 리스트 → 계절 코드 (예: [1,2,3] → 'JFM'). 매칭 없으면 'M{months}' 형식."""
    for code, months in SEASON_MONTHS.items():
        if months == sim_period:
            return code
    return "M" + "_".join(str(m) for m in sim_period)


def find_config(start: Optional[Path] = None) -> Optional[Path]:
    """acidwg_py.yaml 파일을 자동 탐색합니다.

    탐색 순서
    ---------
    1. 환경변수 ``ACIDWG_PY_CONFIG``
    2. ``$PICASO_ROOT/config/acidwg_py.yaml`` (★ 권장 — 공통 picaso-hydro.yaml 과 동거)
    3. 현재 디렉토리 → 상위로 올라가며 ``acidwg_py.yaml``
    4. ``$PICASO_ROOT/1_acidwg/config/acidwg_py.yaml`` (구 위치 — 하위호환)
    5. ``$PICASO_ROOT/acidwg_py.yaml`` (대안 — 루트 직속)
    """
    if env := os.environ.get("ACIDWG_PY_CONFIG"):
        p = Path(env)
        return p if p.is_file() else None

    if picaso := os.environ.get("PICASO_ROOT"):
        preferred = Path(picaso) / "config" / "acidwg_py.yaml"
        if preferred.is_file():
            return preferred

    cwd = (start or Path.cwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / "config" / "acidwg_py.yaml"
        if candidate.is_file():
            return candidate
        candidate = parent / "acidwg_py.yaml"
        if candidate.is_file():
            return candidate

    if picaso := os.environ.get("PICASO_ROOT"):
        for sub in (Path("1_acidwg") / "config" / "acidwg_py.yaml",
                    Path("acidwg_py.yaml")):
            candidate = Path(picaso) / sub
            if candidate.is_file():
                return candidate

    return None
