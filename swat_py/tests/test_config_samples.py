"""config_samples 가 현재 코드와 어긋나지 않는지 지킨다.

배경 — 2026-10-20 제니토스 지적: GitHub 의 ``config_samples`` 가 갱신되지 않아
업체가 우리 실행 결과를 재현할 수 없었다. 샘플이 마지막으로 갱신된 커밋 이후
``drought.base_weather`` · ``drought.sources`` · ``reservoirs`` 레지스트리 등
54개 키가 추가됐는데 샘플에는 한 줄도 없었다.

이 테스트가 막는 것
-------------------
1. 샘플이 **현재 로더로 로드되지 않는** 상태  (스키마가 깨짐)
2. 로더가 읽는 설정 키가 **샘플에 문서화되지 않은** 상태  ← 재발 방지의 핵심
3. 샘플이 **폐기된 구 스키마**로 되돌아간 상태
4. 샘플에 **비밀값**이 섞여 들어간 상태 (공개 저장소다)

새 설정 키를 추가했는데 이 테스트가 실패한다면, 고쳐야 할 것은 테스트가 아니라
``config_samples`` 다. 키를 샘플에 적고 한 줄 주석으로 뜻을 밝혀라.
정말로 문서화할 필요가 없는 내부·레거시 키라면 아래 :data:`UNDOCUMENTED` 에
**사유와 함께** 추가한다.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
from pathlib import Path

import pytest
import yaml

import swat_py

SAMPLES = Path(swat_py.__file__).resolve().parents[3] / "config_samples"
ENV_PY = Path(swat_py.__file__).resolve().parent / "config" / "env.py"

#: 샘플에 적지 않아도 되는 키 — **반드시 사유를 남길 것**.
UNDOCUMENTED = {
    # 구 스키마(하위호환 전용). 새 프로젝트는 path: / calibration: 를 쓴다.
    "input":            "레거시 project.input (→ path:)",
    "observed_weather": "레거시 project.input.observed_weather (→ 공통 picaso-hydro.yaml)",
    "calibrated":       "레거시 project.output.calibrated (→ 경로 자동 산출)",
    "swat_run":         "레거시 project.output.swat_run 별칭 (→ CalibratedDir)",
    "flow":             "레거시 observed.flow (→ calibration.observations[])",
    "water_quality":    "레거시 observed.water_quality (→ calibration.observations[])",
    "baseline":         "레거시 simulation.baseline.start_year/end_year "
                        "(→ calibration.period/validation 의 날짜 형식)",
}


# ── 로더가 읽는 YAML 키 추출 ─────────────────────────────────────────────────

def _loader_yaml_keys() -> set[str]:
    """``env.py`` 의 구조화 로더가 YAML 에서 읽는 키 이름 전부.

    ``raw.get("drought")`` 같은 호출의 첫 인자를 모은다.
    ``flat.get(...)`` 은 YAML 이 아니라 내부 dict 조회라 제외한다.
    """
    fn = next(n for n in ast.parse(ENV_PY.read_text(encoding="utf-8")).body
              if isinstance(n, ast.FunctionDef) and n.name == "_normalize_nested")
    keys: set[str] = set()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and node.args):
            continue
        recv = node.func.value
        if isinstance(recv, ast.Name) and recv.id == "flat":
            continue                                  # 내부 dict — YAML 아님
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            keys.add(arg.value)
    return keys


def _sample_text() -> str:
    return "".join((SAMPLES / f).read_text(encoding="utf-8")
                   for f in ("swat_py.yaml", "picaso-hydro.yaml"))


def _mentions(key: str, text: str) -> bool:
    """샘플이 그 키를 적고 있는가 — 주석 처리된 선택 항목·인라인 매핑도 인정한다."""
    return re.search(rf"(?:^|[\s{{,#-]){re.escape(key)}\s*:", text, re.M) is not None


# ── 1. 샘플이 지금 코드로 로드되는가 ─────────────────────────────────────────

@pytest.fixture
def loaded(tmp_path, monkeypatch):
    cfgdir = tmp_path / "config"
    cfgdir.mkdir()
    for y in SAMPLES.glob("*.yaml"):
        shutil.copy(y, cfgdir / y.name)
    monkeypatch.setenv("PICASO_ROOT", str(tmp_path).replace(os.sep, "/"))
    from swat_py.config import load_config
    return load_config(str(cfgdir / "swat_py.yaml"))


@pytest.fixture
def sample_cfgdir(tmp_path, monkeypatch):
    cfgdir = tmp_path / "config"
    cfgdir.mkdir()
    for y in SAMPLES.glob("*.yaml"):
        shutil.copy(y, cfgdir / y.name)
    monkeypatch.setenv("PICASO_ROOT", str(tmp_path).replace(os.sep, "/"))
    return cfgdir


def test_샘플이_현재_로더로_로드된다(loaded):
    assert loaded.ModelType == "swat_plus"
    assert loaded.PrjDir, "project.root 가 풀리지 않았다"
    assert loaded.Observations, "calibration.observations 가 비었다"


@pytest.mark.parametrize("pkg, fname", [("acidwg_py", "acidwg_py.yaml"),
                                        ("util_py",   "util_py.yaml")])
def test_형제_패키지_샘플도_각자_로더로_로드된다(sample_cfgdir, pkg, fname):
    """swat_py 뿐 아니라 acidwg_py·util_py 샘플도 자기 로더를 통과해야 한다."""
    mod = pytest.importorskip(f"{pkg}.config")
    cfg = mod.load_config(str(sample_cfgdir / fname))
    assert cfg, f"{fname} 로드 결과가 비었다"


def test_샘플이_현행_drought_스키마를_쓴다(loaded):
    """구 flat(thresholds/outlets)이 아니라 sources 기반이어야 한다."""
    dc = loaded.Drought
    assert dc.base_weather == "single_station"
    assert dc.syear and dc.eyear, "평년 기간(syear/eyear)이 비었다"
    kinds = {s.type for s in dc.sources}
    assert kinds == {"stream", "reservoir"}, (
        f"샘플은 하천·저수지 두 유형을 모두 보여야 한다 — 현재 {kinds}")
    assert dc.outlets, "sources 의 outlets 병합 결과가 비었다"

    raw = yaml.safe_load((SAMPLES / "swat_py.yaml").read_text(encoding="utf-8"))
    assert "sources" in raw["drought"]
    for dead in ("thresholds", "outlets"):
        assert dead not in raw["drought"], (
            f"drought.{dead} 는 폐기된 구 스키마다 — sources 안으로 옮길 것")


def test_저수지_레지스트리가_모든_제원을_보여준다(loaded):
    assert loaded.Reservoirs, "reservoirs 레지스트리가 비었다"
    r = next(iter(loaded.Reservoirs.values()))
    assert r.gis_id and r.stage_storage_file
    assert r.spillway_ft == r.spillway_ft, "spillway_ft 가 NaN"
    assert r.bottom_ft == r.bottom_ft, "bottom_ft 가 NaN"
    assert r.obs_datum_offset_ft != 0.0, "기준면 차이(obs_datum_offset_ft) 예시가 필요하다"
    # 전환유입 — 주석이 아니라 실제로 파싱되는 값이어야 한다
    assert r.diversion_from_outlet, "diversion_from_outlet 이 켜져 있어야 한다"
    assert r.diversion_max_m3s > 0 and r.diversion_target_ft == r.diversion_target_ft


def test_저수지_초기조건이_문서화돼_있다(loaded):
    src = next(s for s in loaded.Drought.sources if s.type == "reservoir")
    assert src.has_initial_condition(), "initial_condition.init_water_level_ft 가 없다"
    assert loaded.Drought.forecast_suffix(), "초기조건 폴더 태그가 비었다"


# ── 2. ★ 재발 방지 — 로더 키가 샘플에 다 적혀 있는가 ─────────────────────────

def test_로더가_읽는_모든_키가_샘플에_적혀_있다():
    keys = _loader_yaml_keys()
    assert len(keys) > 80, f"키 추출이 깨졌다 — {len(keys)}개만 찾음"
    text = _sample_text()
    missing = sorted(k for k in keys
                     if k not in UNDOCUMENTED and not _mentions(k, text))
    assert not missing, (
        "config_samples 가 코드보다 뒤처졌다. 아래 키를 샘플에 적을 것"
        "(선택 항목이면 주석으로도 된다):\n  "
        + "\n  ".join(missing)
        + "\n\n문서화가 불필요한 내부·레거시 키라면 "
          "tests/test_config_samples.py 의 UNDOCUMENTED 에 사유와 함께 추가한다.")


def test_UNDOCUMENTED_에_죽은_항목이_없다():
    """로더가 더는 읽지 않는 키가 allow-list 에 남아 있으면 지운다."""
    stale = sorted(set(UNDOCUMENTED) - _loader_yaml_keys())
    assert not stale, f"UNDOCUMENTED 에서 지울 것(로더가 안 읽음): {stale}"


# ── 3. 파일 구성·위생 ────────────────────────────────────────────────────────

def test_네_가지_샘플이_모두_있다():
    expect = {"picaso-hydro.yaml", "swat_py.yaml", "acidwg_py.yaml", "util_py.yaml"}
    found = {p.name for p in SAMPLES.glob("*.yaml")}
    assert expect <= found, f"빠진 샘플: {sorted(expect - found)}"
    readme = (SAMPLES / "README.md").read_text(encoding="utf-8")
    for name in expect:
        assert name in readme, f"README.md 가 {name} 를 설명하지 않는다"


@pytest.mark.parametrize("name", ["picaso-hydro.yaml", "swat_py.yaml",
                                  "acidwg_py.yaml", "util_py.yaml"])
def test_샘플이_유효한_yaml_이다(name):
    assert yaml.safe_load((SAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["picaso-hydro.yaml", "swat_py.yaml",
                                  "acidwg_py.yaml", "util_py.yaml"])
def test_샘플에_비밀값이_없다(name):
    """공개 저장소다 — 인증 값이 채워진 채 올라가면 안 된다.

    ``key:`` 는 SWAT 보정 인자 이름(``key: "cn3_swf"``)으로도 쓰이므로
    **인증 블록 안에 있을 때만** 본다. 인증 블록은 들여쓰기로 판별한다.
    """
    AUTH_BLOCKS = ("cds", "auth", "credentials")
    SECRET = re.compile(r"^(?:-\s*)?(token|secret|password|passwd|api_key|apikey)\s*:\s*(.+)$",
                        re.I)
    EMPTY = ("null", '""', "''", "~")
    bad, auth_indent = [], None
    for i, line in enumerate((SAMPLES / name).read_text(encoding="utf-8").splitlines(), 1):
        body = line.split("#", 1)[0].rstrip()
        if not body.strip():
            continue
        indent = len(body) - len(body.lstrip())
        s = body.strip()
        # 인증 블록 진입/이탈 추적
        if auth_indent is not None and indent <= auth_indent:
            auth_indent = None
        if re.match(rf"^({'|'.join(AUTH_BLOCKS)})\s*:\s*$", s, re.I):
            auth_indent = indent
            continue
        m = SECRET.match(s)
        if m and m.group(2).strip() not in EMPTY:
            bad.append(f"{name}:{i}: {s}")
        if auth_indent is not None:
            km = re.match(r"^(key|url)\s*:\s*(.+)$", s, re.I)
            if km and km.group(2).strip() not in EMPTY:
                bad.append(f"{name}:{i}: (인증 블록) {s}")
    assert not bad, "샘플에 인증 값이 들어 있다:\n  " + "\n  ".join(bad)


@pytest.mark.parametrize("name", ["picaso-hydro.yaml", "swat_py.yaml",
                                  "acidwg_py.yaml", "util_py.yaml"])
def test_샘플에_특정_프로젝트_절대경로가_없다(name):
    """샘플은 어느 프로젝트에도 매이지 않아야 한다(PICASO_ROOT 로 바뀐다)."""
    text = (SAMPLES / name).read_text(encoding="utf-8")
    hits = re.findall(r"[A-Za-z]:[/\\]20\d\d-[\w]+", text)
    assert not hits, f"프로젝트 고정 경로가 남아 있다: {sorted(set(hits))}"


# ── 4. picaso-hydro-init 이 나눠 주는 템플릿도 같아야 한다 ──────────────────
#  ★ 2026-11-02 발견: config_samples 는 갱신했는데 picaso_hydro/templates/config
#    쪽은 구 스키마(262줄, drought.thresholds/outlets)로 남아 있었다.
#    picaso-hydro-init 을 쓴 사용자는 **폐기된 설정**을 받고 있었다.
#    사본이 둘이면 반드시 갈라진다 — 여기서 묶어 둔다.

INIT_TEMPLATES = (SAMPLES.parent / "picaso_hydro" / "src" / "picaso_hydro"
                  / "templates" / "config")

#: picaso-hydro.yaml 은 init 이 프로젝트 경로로 치환할 자리를 갖는다 — 그 한 줄만 다르다.
_ROOT_PLACEHOLDER = "__PROJECT_ROOT__"


def _norm_root(text: str) -> str:
    """root 기본값 줄을 비교 대상에서 지운다(치환 자리라 다른 것이 정상)."""
    return re.sub(r"^\s*root:.*$", "  root: <NORMALIZED>", text, flags=re.M)


@pytest.mark.parametrize("name", ["picaso-hydro.yaml", "swat_py.yaml", "acidwg_py.yaml"])
def test_init_템플릿이_config_samples_와_같다(name):
    tpl = INIT_TEMPLATES / name
    assert tpl.is_file(), f"init 템플릿이 없다: {tpl}"
    a = _norm_root((SAMPLES / name).read_text(encoding="utf-8"))
    b = _norm_root(tpl.read_text(encoding="utf-8"))
    assert a == b, (
        f"picaso-hydro-init 이 나눠 주는 {name} 이 config_samples 와 다르다.\n"
        f"  샘플 {len(a.splitlines())}줄 / 템플릿 {len(b.splitlines())}줄\n"
        f"  → config_samples 를 정본으로 {tpl} 에 복사할 것"
        f"(picaso-hydro.yaml 은 root 기본값만 {_ROOT_PLACEHOLDER} 로 둔다).")


def test_init_템플릿의_root_자리가_살아있다():
    t = (INIT_TEMPLATES / "picaso-hydro.yaml").read_text(encoding="utf-8")
    assert _ROOT_PLACEHOLDER in t, (
        "치환 자리가 사라졌다 — init 이 프로젝트 경로를 넣지 못한다")
