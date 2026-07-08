"""저수지 수위-내용적(stage-storage) 곡선 로딩·환산.

SWAT+ 저수지 모의 저류량(reservoir_day.txt ``flo_stor``, m³) ↔ 수위(stage) 상호 환산.
댐별 실측 수위-내용적 곡선을 CSV 로 관리하여, 모의 저류량을 관측 수위와 같은
공간에서 비교·검보정할 수 있게 한다.

CSV 포맷 (obs/reservoir/<name>_stage_storage.csv)
------------------------------------------------
필수 2열(단위는 헤더로 자기기술, 로더가 SI 정규화):
    elev_ft   또는 elev_m       — 수위(오름차순)
    storage_m3 또는 storage_acft — 저류량(단조증가)
선택 열: volume_acft, volume_mg, note(bottom/spillway/crest 표기) 등.

예)
    elev_ft,storage_m3,volume_acft,note
    23.34,0,0,bottom
    45.00,103242,83.7,spillway
    51.00,188723,153,crest
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Sequence, Union

import numpy as np
import pandas as pd

_FT_PER_M = 3.280839895013123
_M_PER_FT = 0.3048
_M3_PER_HAM = 1.0e4          # 1 ha·m = 10,000 m³ (SWAT+ hydrology.res 저류 단위)
_M3_PER_ACFT = 1233.4815589592
_M3_PER_MG = 3785.411784           # 1 US Million Gallon


@dataclass
class StageStorageCurve:
    """단조 수위-내용적 곡선 + 보간 환산.

    Attributes
    ----------
    elev_ft:     수위 (ft, 오름차순).
    storage_m3:  저류량 (m³, 단조증가).
    name:        저수지 이름.
    meta:        crest/spillway/bottom(ft), source 등 부가정보.
    """
    elev_ft:    np.ndarray
    storage_m3: np.ndarray
    name:       str = ""
    meta:       Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.elev_ft = np.asarray(self.elev_ft, dtype=float)
        self.storage_m3 = np.asarray(self.storage_m3, dtype=float)
        if self.elev_ft.ndim != 1 or self.elev_ft.shape != self.storage_m3.shape:
            raise ValueError("elev_ft 와 storage_m3 는 같은 길이의 1D 배열이어야 함")
        if len(self.elev_ft) < 2:
            raise ValueError("곡선은 최소 2점 필요")
        # 오름차순 정렬
        order = np.argsort(self.elev_ft)
        self.elev_ft = self.elev_ft[order]
        self.storage_m3 = self.storage_m3[order]
        if np.any(np.diff(self.elev_ft) <= 0):
            raise ValueError("elev_ft 는 중복 없이 단조증가해야 함")
        if np.any(np.diff(self.storage_m3) < 0):
            raise ValueError("storage_m3 는 수위 증가에 따라 감소하면 안 됨(단조)")

    # ── 환산 ──────────────────────────────────────────────────────────────────
    def storage_to_stage(
        self,
        storage_m3: Union[float, np.ndarray, pd.Series],
        *,
        interp: str = "pchip",
        clamp: bool = True,
    ) -> Union[float, np.ndarray]:
        """저류량(m³) → 수위(ft). 곡선 범위 밖은 clamp=True 시 끝값 고정."""
        return self._interp(storage_m3, self.storage_m3, self.elev_ft,
                            interp=interp, clamp=clamp)

    def stage_to_storage(
        self,
        elev_ft: Union[float, np.ndarray, pd.Series],
        *,
        interp: str = "pchip",
        clamp: bool = True,
    ) -> Union[float, np.ndarray]:
        """수위(ft) → 저류량(m³)."""
        return self._interp(elev_ft, self.elev_ft, self.storage_m3,
                            interp=interp, clamp=clamp)

    def surface_area_m2(
        self,
        elev_ft: Union[float, np.ndarray],
        *,
        interp: str = "pchip",
        delta_ft: float = 0.02,
    ) -> Union[float, np.ndarray]:
        """수위(ft)에서 수면적(m²) = dV/dz (곡선 저류-수위 도함수).

        A(m²) = (dStorage/dElev[m³/ft]) / 0.3048(m/ft).
        경계(최저·최고 수위)에서는 한쪽 차분 사용.
        """
        lo, hi = self.elev_ft[0], self.elev_ft[-1]
        ev = np.asarray(elev_ft, dtype=float)
        scalar = np.isscalar(elev_ft)
        d = delta_ft
        e = np.clip(ev, lo, hi)
        # 위치별 차분 방식 선택
        hi_side = e >= hi - d          # 상단 → 후방차분
        lo_side = e <= lo + d          # 하단 → 전방차분
        e_plus  = np.where(hi_side, e,        e + d)
        e_minus = np.where(lo_side, e,        e - d)
        e_plus  = np.where(lo_side, e + 2 * d, e_plus)
        e_minus = np.where(hi_side, e - 2 * d, e_minus)
        v_plus  = self.stage_to_storage(e_plus,  interp=interp)
        v_minus = self.stage_to_storage(e_minus, interp=interp)
        dVdz_ft = (np.asarray(v_plus) - np.asarray(v_minus)) / (2.0 * d)
        area_m2 = dVdz_ft / _M_PER_FT
        return float(area_m2) if scalar else area_m2

    @staticmethod
    def _interp(x, xp, fp, *, interp: str, clamp: bool):
        scalar = np.isscalar(x)
        xv = np.asarray(x, dtype=float)
        lo, hi = xp[0], xp[-1]
        xc = np.clip(xv, lo, hi) if clamp else xv
        if interp == "pchip":
            try:
                from scipy.interpolate import PchipInterpolator
                f = PchipInterpolator(xp, fp, extrapolate=True)
                out = f(xc)
            except Exception:
                out = np.interp(xc, xp, fp)      # scipy 부재 시 선형 fallback
        elif interp == "linear":
            out = np.interp(xc, xp, fp)
        else:
            raise ValueError(f"interp 는 'pchip' 또는 'linear' (받음: {interp})")
        # clamp 시 범위 밖은 끝값으로 강제(보간 오버슈트 방지)
        if clamp:
            out = np.where(xv <= lo, fp[0], out)
            out = np.where(xv >= hi, fp[-1], out)
        return float(out) if scalar else out


# ── 단위 정규화 로더 ────────────────────────────────────────────────────────────

def _to_storage_m3(df: pd.DataFrame) -> np.ndarray:
    cols = {c.lower(): c for c in df.columns}
    if "storage_m3" in cols:
        return pd.to_numeric(df[cols["storage_m3"]], errors="coerce").to_numpy(float)
    if "storage_acft" in cols or "volume_acft" in cols:
        c = cols.get("storage_acft", cols.get("volume_acft"))
        return pd.to_numeric(df[c], errors="coerce").to_numpy(float) * _M3_PER_ACFT
    if "storage_mg" in cols or "volume_mg" in cols:
        c = cols.get("storage_mg", cols.get("volume_mg"))
        return pd.to_numeric(df[c], errors="coerce").to_numpy(float) * _M3_PER_MG
    raise KeyError("저류량 열 없음: storage_m3 | storage_acft/volume_acft | volume_mg 필요")


def _to_elev_ft(df: pd.DataFrame) -> np.ndarray:
    cols = {c.lower(): c for c in df.columns}
    if "elev_ft" in cols:
        return pd.to_numeric(df[cols["elev_ft"]], errors="coerce").to_numpy(float)
    if "elev_m" in cols:
        return pd.to_numeric(df[cols["elev_m"]], errors="coerce").to_numpy(float) * _FT_PER_M
    raise KeyError("수위 열 없음: elev_ft | elev_m 필요")


def load_stage_storage(
    path: Union[str, Path],
    *,
    name: Optional[str] = None,
) -> StageStorageCurve:
    """수위-내용적 CSV → :class:`StageStorageCurve` (단위 자동 SI 정규화).

    ``note`` 열의 crest/spillway/bottom 표기가 있으면 meta 에 해당 elev_ft 를 기록.
    """
    path = Path(path)
    df = pd.read_csv(path)
    elev_ft = _to_elev_ft(df)
    storage_m3 = _to_storage_m3(df)

    ok = np.isfinite(elev_ft) & np.isfinite(storage_m3)
    elev_ft, storage_m3 = elev_ft[ok], storage_m3[ok]

    meta: Dict[str, float] = {}
    cols = {c.lower(): c for c in df.columns}
    if "note" in cols:
        elev_all = _to_elev_ft(df)                 # ok 필터 전 원본 정렬 기준
        notes = df[cols["note"]].astype(str).str.lower()
        for key in ("bottom", "spillway", "crest"):
            m = notes.str.contains(key, na=False).to_numpy()
            if m.any():
                meta[f"{key}_ft"] = float(elev_all[m][0])

    return StageStorageCurve(
        elev_ft=elev_ft, storage_m3=storage_m3,
        name=name or path.stem, meta=meta,
    )


# ── 취수 반영 저수지 물수지 재계산 ────────────────────────────────────────────────
#
#  SWAT+ 는 저수지 유입(flo_in)·강수·증발·침투는 계산하지만, 상수도 **취수
#  (withdrawal)** 는 모형에 없다. 관측 수위와 비교하려면 취수를 뺀 물수지로
#  저류량을 재계산해야 한다(사용자 요구: "SWAT+ 유입 − 매일 취수 = 수위").
#
#  일 물수지:
#    S[t] = S[t-1] + flo_in + precip − evap − seep − withdrawal
#    if S > cap(여수로 저류):  spill = S − cap;  S = cap        (여수로 월류)
#    if S < dead(사수위):      shortage = dead − S; S = dead    (취수 제한, 고갈)
#
#  단위: reservoir_day.txt 의 flo_in/precip/evap/seep 는 **일 부피(m³/day)**.

_SECONDS_PER_DAY = 86400.0


def simulate_managed_storage(
    df: pd.DataFrame,
    *,
    withdrawal_m3s: Union[float, Sequence[float]] = 0.0,
    cap_m3: Optional[float] = None,
    dead_m3: float = 0.0,
    init_m3: Optional[float] = None,
    use_losses: bool = True,
) -> pd.DataFrame:
    """SWAT+ 저수지 유입에서 취수를 뺀 관리 물수지로 저류량 재계산.

    Parameters
    ----------
    df:              :func:`parse_reservoir_day` 결과
                     (flo_in, precip, evap, seep, flo_stor, date 포함).
    withdrawal_m3s:  취수량(m³/s). 스칼라(상수) 또는 길이 12 배열(월별, 1~12월).
    cap_m3:          최대 저류(보통 여수로 저류). 초과분은 월류(spill). None=무제한.
    dead_m3:         사수위 저류(하한). 하회 시 취수 제한(shortage 기록).
    init_m3:         초기 저류. None → cap_m3(만수) 있으면 그 값, 없으면 첫날 flo_stor.
    use_losses:      True 면 precip/evap/seep(m³/day) 포함, False 면 유입·취수만.

    Returns
    -------
    DataFrame(date, storage_m3, spill_m3, withdrawal_m3, shortage_m3)
    """
    lc = {c.lower(): c for c in df.columns}

    def _col(name: str) -> np.ndarray:
        if name in lc:
            return pd.to_numeric(df[lc[name]], errors="coerce").fillna(0.0).to_numpy(float)
        return np.zeros(len(df), dtype=float)

    flo_in = _col("flo_in")
    precip = _col("precip") if use_losses else np.zeros(len(df))
    evap   = _col("evap")   if use_losses else np.zeros(len(df))
    seep   = _col("seep")   if use_losses else np.zeros(len(df))

    dates = pd.to_datetime(df["date"])
    months = dates.dt.month.to_numpy()

    # 취수(m³/day) — 상수 또는 월별
    if np.isscalar(withdrawal_m3s):
        W = np.full(len(df), float(withdrawal_m3s) * _SECONDS_PER_DAY)
    else:
        wm = np.asarray(withdrawal_m3s, dtype=float)
        if wm.shape[0] != 12:
            raise ValueError("withdrawal_m3s 배열은 길이 12(월별)이어야 함")
        W = wm[months - 1] * _SECONDS_PER_DAY

    # 초기 저류
    if init_m3 is None:
        init_m3 = cap_m3 if cap_m3 is not None else float(_col("flo_stor")[0])

    n = len(df)
    storage  = np.empty(n)
    spill    = np.zeros(n)
    shortage = np.zeros(n)
    S = float(init_m3)
    for t in range(n):
        S = S + flo_in[t] + precip[t] - evap[t] - seep[t] - W[t]
        if cap_m3 is not None and S > cap_m3:
            spill[t] = S - cap_m3
            S = cap_m3
        if S < dead_m3:
            shortage[t] = dead_m3 - S
            S = dead_m3
        storage[t] = S

    return pd.DataFrame({
        "date":          dates.to_numpy(),
        "storage_m3":    storage,
        "spill_m3":      spill,
        "withdrawal_m3": W,
        "shortage_m3":   shortage,
    })


def water_level_to_storage(
    curve: StageStorageCurve,
    water_level_ft: float,
    *,
    interp: str = "pchip",
) -> float:
    """초기 저수위(ft, MSL=곡선 datum) → 초기 저류량(m³).

    예측 물수지의 출발 저류량(simulate_managed_storage 의 init_m3)으로 쓴다.
    입력 수위는 수위-내용적 곡선/registry 와 동일 datum(여수로 45·댐마루 51·바닥 23.34 ft).
    """
    return float(curve.stage_to_storage(float(water_level_ft), interp=interp))


def storage_to_capacity_fraction(
    curve: StageStorageCurve,
    storage_m3,
    full_level_ft: float,
    *,
    interp: str = "pchip",
):
    """저류량(m³) → 만수위(full_level_ft) 대비 저수량 백분율(%).

    capacity_fraction 가뭄단계 분류(값↓=고갈)용. full_level_ft = 여수로(만수) 수위.
    """
    full = float(curve.stage_to_storage(float(full_level_ft), interp=interp))
    if full <= 0:
        return float("nan")
    arr = np.asarray(storage_m3, dtype=float)
    pct = arr / full * 100.0
    return float(pct) if np.isscalar(storage_m3) else pct


# ── hydrology.res 저수지 용적 갱신 (실측 수위-내용적 곡선 → SWAT+ 매개변수) ─────────
#
#  QSWAT+ 가 DEM 에서 산출한 hydrology.res 의 저수지 용적(area_ps/vol_ps/area_es/
#  vol_es)은 실제 측량과 다를 수 있다. 실측 수위-내용적 곡선으로 재산출한다.
#
#  SWAT+ hydrology.res 단위(공식): area = ha, volume = ha·m (1 ha·m=10⁴ m³).
#    principal spillway(정상 최고수위) → area_ps, vol_ps
#    emergency spillway(최대 저류=댐마루) → area_es, vol_es

def build_hydrology_res_params(
    curve: StageStorageCurve,
    *,
    principal_ft: float,
    emergency_ft: float,
    interp: str = "pchip",
) -> Dict[str, float]:
    """실측 곡선 → SWAT+ hydrology.res 매개변수(ha, ha·m).

    Parameters
    ----------
    principal_ft:  정상 최고수위(보통 여수로 마루).
    emergency_ft:  최대 저류 수위(보통 댐마루/비상여수로).

    Returns
    -------
    dict(area_ps, vol_ps, area_es, vol_es) — 각각 ha, ha·m 단위.
    """
    vol_ps_m3 = float(curve.stage_to_storage(principal_ft, interp=interp))
    vol_es_m3 = float(curve.stage_to_storage(emergency_ft, interp=interp))
    area_ps_m2 = float(curve.surface_area_m2(principal_ft, interp=interp))
    area_es_m2 = float(curve.surface_area_m2(emergency_ft, interp=interp))
    return {
        "area_ps": area_ps_m2 / 1.0e4,      # m² → ha
        "vol_ps":  vol_ps_m3 / _M3_PER_HAM,  # m³ → ha·m
        "area_es": area_es_m2 / 1.0e4,
        "vol_es":  vol_es_m3 / _M3_PER_HAM,
    }


# hydrology.res 컬럼 순서(값 행): name yr_op mon_op area_ps vol_ps area_es vol_es
#                                 k evap_co shp_co1 shp_co2
_HYDRO_RES_VALCOLS = ["area_ps", "vol_ps", "area_es", "vol_es"]


def update_hydrology_res(
    path: Union[str, Path],
    res_name: str,
    params: Dict[str, float],
    *,
    out_path: Optional[Union[str, Path]] = None,
    backup: bool = True,
) -> Dict[str, Dict[str, float]]:
    """hydrology.res 의 한 저수지 행에서 용적 4개 열만 교체(형식·타 열 보존).

    Parameters
    ----------
    path:      원본 hydrology.res.
    res_name:  대상 저수지 이름(첫 열, 예: "res4").
    params:    {area_ps, vol_ps, area_es, vol_es} (ha, ha·m).
    out_path:  출력 경로. None → path 덮어쓰기(이 경우 backup 생성).
    backup:    덮어쓸 때 ``<path>.bak`` 생성.

    Returns
    -------
    dict(before, after) — 교체 전/후 값.
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(lines) < 2:
        raise ValueError(f"hydrology.res 형식 오류: {path}")

    header = lines[1].split()
    try:
        col_idx = {c: header.index(c) for c in _HYDRO_RES_VALCOLS}
    except ValueError as e:
        raise ValueError(f"hydrology.res 헤더에서 용적 열을 찾지 못함: {e}")

    before: Dict[str, float] = {}
    found = False
    for i in range(2, len(lines)):
        parts = lines[i].split()
        if not parts or parts[0] != res_name:
            continue
        found = True
        for c in _HYDRO_RES_VALCOLS:
            before[c] = float(parts[col_idx[c]])
            parts[col_idx[c]] = f"{params[c]:.5f}"
        # 재구성: name 20 좌측정렬 + 나머지 우측정렬(폭 14, SWAT+ 자유형식이라 폭 무관)
        rebuilt = f"{parts[0]:<18s}" + "".join(f"{p:>14s}" for p in parts[1:])
        lines[i] = rebuilt + "\n"
        break

    if not found:
        raise ValueError(f"저수지 '{res_name}' 행을 찾지 못함: {path}")

    target = Path(out_path) if out_path else path
    if out_path is None and backup:
        Path(str(path) + ".bak").write_text("".join(
            path.read_text(encoding="utf-8")), encoding="utf-8")
    target.write_text("".join(lines), encoding="utf-8")

    after = {c: params[c] for c in _HYDRO_RES_VALCOLS}
    return {"before": before, "after": after}
