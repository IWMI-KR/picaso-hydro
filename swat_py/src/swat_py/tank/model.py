"""3단 직렬 Sugawara Tank 모형 — 집중형 개념 강우-유출.

구조 (직렬 3탱크)
-----------------
  Tank1 (표층)   입력 P, 증발 E.  측면유출 2구(a1@ha1 상단, a2@ha2 하단) + 하단 침투 b1
  Tank2 (중간)   입력 = Tank1 침투.  측면유출 1구(a3@hb1) + 하단 침투 b2
  Tank3 (기저)   입력 = Tank2 침투.  측면유출 1구(a4@0)  (하단 손실 없음)
  총 유출 Q(mm) = qa + qb + qc

매개변수 9개 — a1,a2,ha1,ha2,b1 / a3,hb1,b2 / a4  (검보정 대상).
물수지: ΣP = ΣQ + ΣE + ΔS  (b1,b2 는 내부 이송이라 손실 아님 → 폐합).
단위변환: q_m3s = q_mm · area_km2 / 86.4  (1 mm/km²/day = 1000 m³/day).
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Sequence

import numpy as np
import pandas as pd

# 표준 파라미터 순서 (DDS 벡터 ↔ TankParams 매핑에 사용)
PARAM_ORDER = ("a1", "a2", "ha1", "ha2", "b1", "a3", "hb1", "b2", "a4")

# 기본 검보정 범위 (yaml 미지정 시 사용) — Sugawara 문헌 관용값
DEFAULT_BOUNDS = {
    "a1":  (0.05, 0.6),    # 1단 상단 유출계수 (빠른 표면유출)
    "a2":  (0.02, 0.4),    # 1단 하단 유출계수
    "ha1": (10.0, 80.0),   # 1단 상단 유출높이 (mm)
    "ha2": (0.0, 40.0),    # 1단 하단 유출높이 (mm)  (ha2<ha1 권장)
    "b1":  (0.05, 0.6),    # 1단 침투계수
    "a3":  (0.01, 0.2),    # 2단 유출계수 (중간유출)
    "hb1": (0.0, 30.0),    # 2단 유출높이 (mm)
    "b2":  (0.01, 0.3),    # 2단 침투계수
    "a4":  (0.001, 0.1),   # 3단 유출계수 (기저유출)
}


@dataclass
class TankParams:
    a1: float; a2: float; ha1: float; ha2: float; b1: float
    a3: float; hb1: float; b2: float; a4: float

    @classmethod
    def from_vector(cls, x: Sequence[float]) -> "TankParams":
        return cls(**{k: float(v) for k, v in zip(PARAM_ORDER, x)})

    def to_vector(self) -> np.ndarray:
        return np.array([getattr(self, k) for k in PARAM_ORDER], dtype=float)


def simulate_tank(
    dates: Sequence,
    pcp_mm: Sequence[float],
    pet_mm: Sequence[float],
    params: TankParams,
    area_km2: float,
    *,
    s_init: Sequence[float] = (0.0, 0.0, 0.0),
) -> pd.DataFrame:
    """일 강수·PET → 3단 Tank 유출 시계열.

    Returns
    -------
    DataFrame[date, q_mm, q_m3s, e_mm, s1, s2, s3]
    """
    p = np.asarray(pcp_mm, dtype=float)
    pet = np.asarray(pet_mm, dtype=float)
    p = np.nan_to_num(p, nan=0.0)
    pet = np.nan_to_num(pet, nan=0.0)
    n = len(p)
    P = params

    s1, s2, s3 = map(float, s_init)
    q_mm = np.empty(n); e_out = np.empty(n)
    S1 = np.empty(n); S2 = np.empty(n); S3 = np.empty(n)

    for i in range(n):
        # ── Tank1: 강수 + 증발 ──
        s1 += p[i]
        e = min(pet[i], s1)
        s1 -= e
        qa = P.a1 * max(s1 - P.ha1, 0.0) + P.a2 * max(s1 - P.ha2, 0.0)
        ia = P.b1 * s1
        out1 = qa + ia
        if out1 > s1 and out1 > 0:           # 음수 저류 방지(비례 축소)
            scale = s1 / out1
            qa *= scale; ia *= scale; out1 = s1
        s1 -= out1
        # ── Tank2 ──
        s2 += ia
        qb = P.a3 * max(s2 - P.hb1, 0.0)
        ib = P.b2 * s2
        out2 = qb + ib
        if out2 > s2 and out2 > 0:
            scale = s2 / out2
            qb *= scale; ib *= scale; out2 = s2
        s2 -= out2
        # ── Tank3 ──
        s3 += ib
        qc = P.a4 * s3
        qc = min(qc, s3)
        s3 -= qc

        q_mm[i] = qa + qb + qc
        e_out[i] = e
        S1[i], S2[i], S3[i] = s1, s2, s3

    q_m3s = q_mm * float(area_km2) / 86.4
    return pd.DataFrame({
        "date": pd.to_datetime(list(dates)),
        "q_mm": q_mm, "q_m3s": q_m3s, "e_mm": e_out,
        "s1": S1, "s2": S2, "s3": S3,
    })


def bounds_from_config(param_ranges: dict | None) -> list[tuple]:
    """{name: [lo, hi]} (yaml) → PARAM_ORDER 순 bounds. 미지정은 DEFAULT_BOUNDS."""
    ranges = dict(param_ranges or {})
    return [tuple(ranges.get(k, DEFAULT_BOUNDS[k])) for k in PARAM_ORDER]
