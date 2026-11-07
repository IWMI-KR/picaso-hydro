"""장기 채널 **월유량** → outlet별 ① 월평년 + ④ FDC 임계선.

`4_drought_risk/climatology/channel_monthly_{syear+warmup}_{eyear}.csv`
(wide: date + outlet열)를 읽어 각 outlet의 월별 평년유량(1~12월)과
유황 대표유량(Q95d~Q355d, 참조값)을 산정한다. 대시보드 단계 경계는 이것이 아니라
:func:`swat_py.drought.fdc.stage_thresholds` 가 설정대로(기본 Q70/Q90/Q95) 따로 뽑는다.

climatology_run 이 시간 절약을 위해 **월단위만** 생산하므로 일유량 파일은 없다.
과거 이름인 :func:`climatology_daily_path` 는 :func:`climatology_flow_path` 의
별칭으로 남아 있으며 실제로는 위 월유량 파일 경로를 돌려준다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from swat_py.drought.fdc import fdc_thresholds


def climatology_tag(cfg) -> str:
    """장기 기후 결과 파일명 태그 ``{출력시작}_{eyear}`` (하드코딩 대신 자동 산출).

    출력 시작연도 = ``drought.syear + warm_up_years``(웜업 기간 제외 후 출력).
    drought.syear 미설정 시 climatology_years[0] 로 하위호환.
    예) syear=1982·웜업3·eyear=2024 → ``"1985_2024"``.
    """
    dc = cfg.Drought
    warmup = int(getattr(cfg, "CioNYSKIP", 0) or 0)
    syear = dc.syear or (dc.climatology_years[0] if dc.climatology_years else 2003)
    eyear = dc.eyear or (dc.climatology_years[-1] if dc.climatology_years else 2024)
    return f"{int(syear) + warmup}_{int(eyear)}"


def climatology_flow_path(cfg):
    """장기 기후 유량 CSV 경로 — **월유량 시계열**(channel_monthly_{tag}.csv).

    climatology_run 이 시간 절약을 위해 월단위만 생산하므로 일유량 파일은 없다. 가뭄단계
    경계(fdc_exceedance)는 이 월유량 분포에서 산정된다. drought.climatology_csv 명시 시 그 값 우선.
    """
    dc = cfg.Drought
    if dc.climatology_csv:
        return Path(dc.climatology_csv)
    return (Path(cfg.PrjDir) / "4_drought_risk" / "climatology"
            / f"channel_monthly_{climatology_tag(cfg)}.csv")


# 하위호환 별칭 — 기존 호출부(dashboard_data·reclassify·run)는 이제 월유량 파일을 받는다.
climatology_daily_path = climatology_flow_path


def load_daily_flow(csv_path) -> pd.DataFrame:
    """wide 유량 CSV 로드 (date 파싱). 컬럼 = outlet 이름. (월단위 시계열)."""
    return pd.read_csv(csv_path, parse_dates=["date"])


def monthly_climatology(daily: pd.DataFrame, outlet: str) -> pd.DataFrame:
    """outlet의 월별 평년(1~12): mean·p25·p50·p75 (일유량의 월평균 후 연간 통계)."""
    s = daily[["date", outlet]].dropna().copy()
    s["year"] = s["date"].dt.year
    s["month"] = s["date"].dt.month
    # 연·월 평균 → 월별 다년 통계
    ym = s.groupby(["year", "month"])[outlet].mean().reset_index()
    g = ym.groupby("month")[outlet]
    out = pd.DataFrame({
        "month": range(1, 13),
    }).merge(
        pd.DataFrame({
            "month": g.mean().index,
            "mean": g.mean().values,
            "p25": g.quantile(0.25).values,
            "p50": g.median().values,
            "p75": g.quantile(0.75).values,
        }), on="month", how="left")
    return out


def outlet_climatology_and_thresholds(daily: pd.DataFrame, outlet: str) -> Dict:
    """outlet의 ① 월평년 + ④ FDC 임계선(dict) 반환."""
    clim = monthly_climatology(daily, outlet)
    thr = fdc_thresholds(daily[outlet].dropna().values)
    return {"outlet": outlet, "monthly": clim, "thresholds": thr}


def compute_all(daily_csv, outlets) -> Dict[str, Dict]:
    """모든 outlet에 대해 평년+임계선 산정. outlets = outlet 이름 리스트."""
    daily = load_daily_flow(daily_csv)
    return {o: outlet_climatology_and_thresholds(daily, o)
            for o in outlets if o in daily.columns}


# ── 평년 통계 선택 · 설정 지문 ──────────────────────────────────────────────
#  ★ 2026-10-20 업체 지적(최기섭 §4-라):
#    ① "평균인 평년선이 3월에 Watch 구간으로 그려지는 것이 의도한 결과인가,
#       중앙값을 쓰는 편이 나은가"
#    ② "보충수·취수 설정을 바꾸면 평년도 다시 계산해야 하는데, 지금은 예전 설정으로
#       만든 평년 파일이 남아 있어도 대시보드가 그대로 읽고 경고하지 않는다"
#  ①은 drought.climatology_stat 로 고를 수 있게 했고(기본 mean — 기존 거동 보존),
#  ②는 평년 산출물 옆에 설정 지문 JSON 을 남기고 읽을 때 대조하도록 했다.

CLIM_STATS = ("mean", "median")


def climatology_stat(cfg) -> str:
    """평년선에 쓸 통계 — ``mean``(기본) | ``median``.

    저수지 수위처럼 위가 만수로 막혀 있고 아래로 긴 꼬리를 갖는 분포에서는
    소수의 가뭄 해가 평균을 끌어내려, "보통 해"를 나타내야 할 평년선이 Watch
    구간에 그려진다(팔라우 Ngerimel 3월). 그런 경우 median 이 낫다.
    """
    dc = getattr(cfg, "Drought", None)
    v = str(getattr(dc, "climatology_stat", "") or "mean").lower()
    if v not in CLIM_STATS:
        raise ValueError(f"drought.climatology_stat 는 {CLIM_STATS} 중 하나여야 함: {v!r}")
    return v


def _reservoir_fingerprint(cfg) -> Dict:
    """평년 저수지 물수지에 영향을 주는 레지스트리 값만 추린다."""
    keys = ("stage_storage_file", "obs_datum_offset_ft", "interp", "spillway_ft",
            "bottom_ft", "crest_ft", "withdrawal_m3s", "withdrawal_monthly_m3s",
            "diversion_from_outlet", "diversion_max_m3s", "diversion_min_flow_m3s",
            "diversion_target_ft")
    out: Dict[str, Dict] = {}
    for name, r in (getattr(cfg, "Reservoirs", {}) or {}).items():
        out[str(name)] = {k: _plain(getattr(r, k, None)) for k in keys}
    return out


def _plain(v):
    """JSON 으로 안정적으로 비교되도록 정규화 (NaN → None, 수치 → 반올림)."""
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, float):
        return None if v != v else round(v, 6)
    if isinstance(v, int):
        return int(v)
    return str(v)


def climatology_fingerprint(cfg) -> Dict:
    """평년 산출물을 좌우하는 설정값 모음 — 저장·대조용.

    기간(syear/eyear)은 파일명 태그에 이미 들어가지만, 바뀌면 파일이 아예 달라지는
    것이 맞는지 확인할 수 있도록 함께 남긴다.
    """
    dc = getattr(cfg, "Drought", None)
    return {
        "syear": int(getattr(dc, "syear", 0) or 0),
        "eyear": int(getattr(dc, "eyear", 0) or 0),
        "warm_up_years": int(getattr(cfg, "CioNYSKIP", 0) or 0),
        "base_weather": str(getattr(dc, "base_weather", "") or ""),
        "climatology_stat": climatology_stat(cfg),
        "sources": {
            s.name: {"type": s.type, "reservoir": s.reservoir,
                     "threshold_method": s.threshold_method,
                     "threshold_values": _plain(list(s.threshold_values or [])),
                     "outlets": {str(k): v for k, v in sorted((s.outlets or {}).items())}}
            for s in (getattr(dc, "sources", []) or [])
        },
        "reservoirs": _reservoir_fingerprint(cfg),
    }


def fingerprint_path(cfg, out_dir=None) -> Path:
    """설정 지문 JSON 경로 — 평년 산출물과 같은 폴더, 같은 태그."""
    d = Path(out_dir) if out_dir else (
        Path(cfg.PrjDir) / "4_drought_risk" / "climatology")
    return d / f"climatology_settings_{climatology_tag(cfg)}.json"


def write_climatology_fingerprint(cfg, out_dir=None) -> Path:
    """현재 설정 지문을 평년 산출물 옆에 남긴다."""
    import json
    p = fingerprint_path(cfg, out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(climatology_fingerprint(cfg), ensure_ascii=False,
                            indent=2, sort_keys=True), encoding="utf-8")
    return p


def check_climatology_fingerprint(cfg, out_dir=None) -> Dict:
    """평년 산출물이 **지금 설정으로 만든 것인지** 확인한다.

    Returns
    -------
    {"status": ok | missing | stale, "diff": [사람이 읽는 차이 설명…], "path": str}

    ``missing`` 은 지문이 없는 경우다 — 이 기능이 생기기 전에 만든 평년이거나,
    평년을 손으로 복사해 온 경우. 설정이 맞는지 확인할 방법이 없다는 뜻이므로
    조용히 통과시키지 않는다.
    """
    import json
    p = fingerprint_path(cfg, out_dir)
    now = climatology_fingerprint(cfg)
    if not p.is_file():
        return {"status": "missing", "diff": [], "path": str(p)}
    try:
        old = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"status": "missing", "diff": [f"지문을 읽지 못함: {e}"], "path": str(p)}
    diff = _diff_fingerprint(old, now)
    return {"status": "stale" if diff else "ok", "diff": diff, "path": str(p)}


def _diff_fingerprint(old, new, prefix: str = "") -> list:
    """두 지문의 차이를 '경로: 옛값 → 새값' 목록으로."""
    out = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            out += _diff_fingerprint(old.get(k), new.get(k),
                                     f"{prefix}.{k}" if prefix else str(k))
    elif old != new:
        out.append(f"{prefix or '값'}: {old!r} → {new!r}")
    return out


def warn_if_climatology_stale(cfg, out_dir=None) -> Dict:
    """평년이 현재 설정과 어긋나면 **눈에 띄게** 경고한다(중단하지는 않는다).

    업체 요청이 "경고"였다. 다만 조용한 한 줄로는 지나치기 쉬워, 어떤 설정이
    어떻게 달라졌는지 항목별로 찍고 결과 dict 를 돌려준다 — 호출부는 이것을
    dashboard.json 에 남겨 화면에서도 보이게 한다.
    """
    res = check_climatology_fingerprint(cfg, out_dir)
    if res["status"] == "ok":
        return res
    bar = "!" * 72
    print(bar)
    if res["status"] == "missing":
        print("[평년 설정 확인 불가] 평년 산출물 옆에 설정 지문이 없다.")
        print(f"  기대 위치: {res['path']}")
        print("  → 지금 설정으로 만든 평년인지 확인할 수 없다. "
              "climatology_run 을 다시 돌리면 지문이 생긴다.")
    else:
        print("[평년이 낡았다] 평년 산출물이 **지금 설정과 다른 설정**으로 만들어졌다.")
        for d in res["diff"]:
            print(f"    · {d}")
        print("  → 평년선·FDC 임계가 예측과 다른 물리를 쓴다. "
              "climatology_run 을 다시 돌릴 것.")
    print(bar)
    return res
