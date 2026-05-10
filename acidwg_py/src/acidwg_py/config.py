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

def load_config(config_file: str) -> Dict[str, Any]:
    """acidwg_py.yaml을 읽어 파싱된 설정 딕셔너리 반환.

    YAML 섹션
    ---------
    paths       : station_csv, forecast_csv, obs_dir, output_dir, model_file
    observation : syear, eyear
    forecast    : year, season(또는 months)
    ensemble    : n_members, random_seed
    model       : retrieve
    output      : overwrite, variables
    advanced    : max_retry_factor, n_cores, validate_after  (optional)

    Returns
    -------
    dict with keys
        station_csv, forecast_csv, obs_dir, output_dir, model_file,
        syear_obs, eyear_obs, forecast_year, sim_period,
        n_ensemble, random_seed, retrieve, overwrite, variables,
        max_retry_factor, n_cores, validate_after
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

    # ── 교차참조 + 환경변수 해석 ──────────────────────────────────────────────
    resolved = _resolve_tree(raw, raw)

    # ── 경로 ──────────────────────────────────────────────────────────────────
    paths = resolved.get("paths") or {}
    _required = ["station_csv", "forecast_csv", "obs_dir", "output_dir"]
    for key in _required:
        if key not in paths:
            raise ValueError(f"paths.{key} 가 설정 파일에 없음")

    # ── 관측 기간 ──────────────────────────────────────────────────────────
    obs = resolved.get("observation") or {}
    syear_obs = int(obs.get("syear", 1981))
    eyear_obs = int(obs.get("eyear", 2010))

    if syear_obs >= eyear_obs:
        raise ValueError(f"observation.syear({syear_obs}) ≥ eyear({eyear_obs})")

    # ── 예보 대상 ──────────────────────────────────────────────────────────
    fc = resolved.get("forecast") or {}
    forecast_year = int(fc.get("year", 2025))

    if "months" in fc:
        sim_period = [int(m) for m in fc["months"]]
        if not all(1 <= m <= 12 for m in sim_period):
            raise ValueError(f"forecast.months 범위 오류: {sim_period}")
    else:
        season = str(fc.get("season", "JJA")).upper()
        if season not in SEASON_MONTHS:
            raise ValueError(
                f"지원하지 않는 계절 코드: '{season}'\n"
                f"  사용 가능: {list(SEASON_MONTHS.keys())}"
            )
        sim_period = SEASON_MONTHS[season]

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

    return {
        "station_csv":       paths["station_csv"],
        "forecast_csv":      paths["forecast_csv"],
        "obs_dir":           paths["obs_dir"],
        "output_dir":        paths["output_dir"],
        "model_file":        paths.get("model_file"),
        "syear_obs":         syear_obs,
        "eyear_obs":         eyear_obs,
        "forecast_year":     forecast_year,
        "sim_period":        sim_period,
        "n_ensemble":        n_ensemble,
        "random_seed":       random_seed,
        "retrieve":          retrieve,
        "overwrite":         overwrite,
        "variables":         variables,
        "max_retry_factor":  max_retry_factor,
        "n_cores":           n_cores,
        "validate_after":    validate_after,
    }


def find_config(start: Optional[Path] = None) -> Optional[Path]:
    """acidwg_py.yaml 파일을 자동 탐색합니다.

    탐색 순서
    ---------
    1. 환경변수 ``ACIDWG_PY_CONFIG``
    2. 현재 디렉토리 → 상위로 올라가며 ``acidwg_py.yaml``
    3. ``$PICASO_ROOT/acidwg_py.yaml``
    """
    if env := os.environ.get("ACIDWG_PY_CONFIG"):
        p = Path(env)
        return p if p.is_file() else None

    cwd = (start or Path.cwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / "acidwg_py.yaml"
        if candidate.is_file():
            return candidate

    if picaso := os.environ.get("PICASO_ROOT"):
        candidate = Path(picaso) / "acidwg_py.yaml"
        if candidate.is_file():
            return candidate

    return None
