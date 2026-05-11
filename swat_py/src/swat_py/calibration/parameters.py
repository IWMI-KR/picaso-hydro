"""SWAT 2012 / SWAT-Plus 표준 보정 인자 카탈로그.

문헌 출처
---------
- Arnold, J. G., Moriasi, D. N., Gassman, P. W., et al. (2012).
  SWAT: Model use, calibration, and validation. Trans. ASABE, 55(4), 1491–1508.
- Abbaspour, K. C. (2015). SWAT-CUP: SWAT Calibration and Uncertainty Programs.
- Neitsch, S. L., Arnold, J. G., Kiniry, J. R., Williams, J. R. (2011).
  Soil and Water Assessment Tool Theoretical Documentation, Version 2009.
- Bieger, K. et al. (2017). Introduction to SWAT+, a Completely Restructured
  Version of the Soil and Water Assessment Tool. JAWRA, 53(1), 115-130.

변수별 보편 보정 인자 (Abbaspour 2015 SWAT-CUP 권장 + 후속 문헌 종합)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


# ── 변경 방식 (change_type) ─────────────────────────────────────────────────
# absval : 인자를 value 로 절대 설정
# abschg : 기존값 + value (절대 증분)
# relchg : 기존값 × (1 + value) — 상대 비율 (예: 0.2 → +20%)
# pctchg : 기존값 × (1 + value/100) — 백분율
CHANGE_TYPES = ("absval", "abschg", "relchg", "pctchg")


@dataclass(frozen=True)
class ParameterDef:
    """SWAT 보정 인자 정의 (SWAT 2012 + SWAT-Plus 양쪽)."""
    variable:        str               # flow | ss | tn | tp
    name_swat2012:   str               # SWAT 2012 인자명 (예: CN2)
    name_swat_plus:  str               # SWAT-Plus 인자명 (예: cn2)
    file_swat2012:   str               # 인자가 들어있는 파일 (예: *.mgt)
    file_swat_plus:  str               # SWAT-Plus 파일 (예: hru-data.hru)
    default_range:   Tuple[float, float]  # 권장 보정 범위
    change_type:     str               # 권장 변경 방식
    description:     str               # 인자 설명


# ── 유량 (flow) ─────────────────────────────────────────────────────────────
# Abbaspour 2015 SWAT-CUP 권장 + Arnold 2012 표준
FLOW_PARAMETERS: List[ParameterDef] = [
    ParameterDef("flow", "CN2",       "cn2",        "*.mgt",     "hru-data.hru",   (-0.20, 0.20),    "relchg", "SCS 곡선 번호 (선행수분 II)"),
    ParameterDef("flow", "ALPHA_BF",  "alpha",      "*.gw",      "aquifer.aqu",    (0.0, 1.0),       "absval", "기저유출 알파 계수 (day⁻¹)"),
    ParameterDef("flow", "GW_DELAY",  "delay",      "*.gw",      "aquifer.aqu",    (0.0, 500.0),     "absval", "지하수 지연 시간 (day)"),
    ParameterDef("flow", "GWQMN",     "flo_min",    "*.gw",      "aquifer.aqu",    (0.0, 5000.0),    "absval", "기저유출 발생 임계심도 (mm)"),
    ParameterDef("flow", "GW_REVAP",  "revap_co",   "*.gw",      "aquifer.aqu",    (0.02, 0.20),     "absval", "지하수 재증발 계수"),
    ParameterDef("flow", "REVAPMN",   "revap_min",  "*.gw",      "aquifer.aqu",    (0.0, 500.0),     "absval", "재증발 임계심도 (mm)"),
    ParameterDef("flow", "ESCO",      "esco",       "*.hru/.bsn","hydrology.hyd",  (0.0, 1.0),       "absval", "토양증발 보상계수"),
    ParameterDef("flow", "EPCO",      "epco",       "*.hru/.bsn","hydrology.hyd",  (0.0, 1.0),       "absval", "식물흡수 보상계수"),
    ParameterDef("flow", "SURLAG",    "surlag",     "*.bsn",     "basin.bsn",      (0.05, 24.0),     "absval", "표면유출 지연 (day)"),
    ParameterDef("flow", "SOL_AWC",   "awc",        "*.sol",     "soils.sol",      (-0.04, 0.04),    "abschg", "토양 가용수분 (mm/mm)"),
    ParameterDef("flow", "SOL_K",     "k",          "*.sol",     "soils.sol",      (-0.50, 0.50),    "relchg", "포화수리전도도 (mm/hr)"),
    ParameterDef("flow", "CH_N2",     "n",          "*.rte",     "channel-lte.cha",(0.01, 0.30),     "absval", "Manning n (주하천)"),
    ParameterDef("flow", "CH_K2",     "k",          "*.rte",     "channel-lte.cha",(0.0, 500.0),     "absval", "하상 유효 수리전도도"),
    ParameterDef("flow", "LAT_TTIME", "lat_ttime",  "*.hru",     "hydrology.hyd",  (0.0, 180.0),     "absval", "측방류 이동시간 (day)"),
    ParameterDef("flow", "RCHRG_DP",  "deep_seep",  "*.gw",      "aquifer.aqu",    (0.0, 1.0),       "absval", "심층 대수층 침투 비율"),
]


# ── 부유사 (ss) ─────────────────────────────────────────────────────────────
SS_PARAMETERS: List[ParameterDef] = [
    ParameterDef("ss", "USLE_P",   "usle_p",   "*.mgt",  "hru-data.hru",   (0.0, 1.0),     "absval", "USLE 영농 인자"),
    ParameterDef("ss", "USLE_K",   "usle_k",   "*.sol",  "soils.sol",      (0.0, 0.65),    "absval", "USLE 토양 침식 인자"),
    ParameterDef("ss", "USLE_C",   "usle_c",   "plant.dat","plants.plt",   (0.001, 0.50),  "absval", "USLE 식생피복 인자"),
    ParameterDef("ss", "PRF",      "prf",      "*.bsn",  "basin.bsn",      (0.0, 2.0),     "absval", "하상 유사 routing 첨두율 보정"),
    ParameterDef("ss", "ADJ_PKR",  "adj_pkr",  "*.bsn",  "basin.bsn",      (0.5, 2.0),     "absval", "소유역 첨두율 보정"),
    ParameterDef("ss", "SPCON",    "spcon",    "*.bsn",  "basin.bsn",      (0.0001, 0.01), "absval", "하상 유사 routing 선형 계수"),
    ParameterDef("ss", "SPEXP",    "spexp",    "*.bsn",  "basin.bsn",      (1.0, 2.0),     "absval", "하상 유사 routing 지수"),
    ParameterDef("ss", "CH_COV1",  "cov1",     "*.rte",  "channel-lte.cha",(0.0, 1.0),     "absval", "하상 침식성 인자"),
    ParameterDef("ss", "CH_COV2",  "cov2",     "*.rte",  "channel-lte.cha",(0.0, 1.0),     "absval", "하상 피복 인자"),
    ParameterDef("ss", "LAT_SED",  "lat_sed",  "*.hru",  "hru-data.hru",   (0.0, 5000.0),  "absval", "측방류·기저유출 유사 농도 (mg/L)"),
    ParameterDef("ss", "BIOMIX",   "biomix",   "*.mgt",  "management.sch", (0.0, 1.0),     "absval", "토양 생물혼합 효율"),
]


# ── 총질소 (tn) ─────────────────────────────────────────────────────────────
TN_PARAMETERS: List[ParameterDef] = [
    ParameterDef("tn", "NPERCO",    "nperco",    "*.bsn", "basin.bsn",    (0.0, 1.0),      "absval", "질소 침투 계수"),
    ParameterDef("tn", "SOL_NO3",   "no3",       "*.chm", "nutrients.sol",(0.0, 100.0),    "absval", "초기 NO3 (mg/kg)"),
    ParameterDef("tn", "SOL_ORGN",  "orgn",      "*.chm", "nutrients.sol",(0.0, 10000.0),  "absval", "초기 유기질소 (mg/kg)"),
    ParameterDef("tn", "N_UPDIS",   "n_updis",   "*.bsn", "basin.bsn",    (0.0, 100.0),    "absval", "질소 흡수 분포"),
    ParameterDef("tn", "CMN",       "cmn",       "*.bsn", "basin.bsn",    (0.0001, 0.003), "absval", "유기물 무기화 속도"),
    ParameterDef("tn", "CDN",       "cdn",       "*.bsn", "basin.bsn",    (0.0, 3.0),      "absval", "탈질 지수속도 계수"),
    ParameterDef("tn", "SDNCO",     "sdnco",     "*.bsn", "basin.bsn",    (0.0, 1.0),      "absval", "탈질 수분 임계값"),
    ParameterDef("tn", "HLIFE_NGW", "hlife_ngw", "*.gw",  "aquifer.aqu",  (0.0, 200.0),    "absval", "지하수 NO3 반감기 (day)"),
    ParameterDef("tn", "ERORGN",    "erorgn",    "*.hru", "hru-data.hru", (0.0, 5.0),      "absval", "유기질소 농축비"),
    ParameterDef("tn", "RSDCO",     "rsdco",     "*.bsn", "basin.bsn",    (0.02, 0.10),    "absval", "잔재물 분해 계수"),
    ParameterDef("tn", "AI1",       "ai1",       "*.wwq", "channel-nut.cha",(0.07, 0.09),  "absval", "조류 N 함량비"),
    ParameterDef("tn", "BC1",       "bc1",       "*.swq", "channel-nut.cha",(0.10, 1.00),  "absval", "NH4 → NO2 산화율 (day⁻¹)"),
    ParameterDef("tn", "BC2",       "bc2",       "*.swq", "channel-nut.cha",(0.20, 2.00),  "absval", "NO2 → NO3 산화율 (day⁻¹)"),
    ParameterDef("tn", "BC3",       "bc3",       "*.swq", "channel-nut.cha",(0.02, 0.40),  "absval", "유기 → NH4 가수분해율"),
]


# ── 총인 (tp) ───────────────────────────────────────────────────────────────
TP_PARAMETERS: List[ParameterDef] = [
    ParameterDef("tp", "PPERCO",    "pperco",    "*.bsn", "basin.bsn",      (10.0, 17.5),    "absval", "인 침투 계수"),
    ParameterDef("tp", "PHOSKD",    "phoskd",    "*.bsn", "basin.bsn",      (100.0, 200.0),  "absval", "인 토양 분배 계수"),
    ParameterDef("tp", "PSP",       "psp",       "*.bsn", "basin.bsn",      (0.01, 0.70),    "absval", "인 가용성 지수"),
    ParameterDef("tp", "SOL_LABP",  "lab_p",     "*.chm", "nutrients.sol",  (0.0, 100.0),    "absval", "초기 활성인 (mg/kg)"),
    ParameterDef("tp", "SOL_ORGP",  "orgp",      "*.chm", "nutrients.sol",  (0.0, 1000.0),   "absval", "초기 유기인 (mg/kg)"),
    ParameterDef("tp", "ERORGP",    "erorgp",    "*.hru", "hru-data.hru",   (0.0, 5.0),      "absval", "유기인 농축비"),
    ParameterDef("tp", "GWSOLP",    "gwsolp",    "*.gw",  "aquifer.aqu",    (0.0, 1000.0),   "absval", "지하수 가용인 (mg/L)"),
    ParameterDef("tp", "P_UPDIS",   "p_updis",   "*.bsn", "basin.bsn",      (0.0, 100.0),    "absval", "인 흡수 분포"),
    ParameterDef("tp", "BC4",       "bc4",       "*.swq", "channel-nut.cha",(0.01, 0.70),    "absval", "유기인 → 가용인 (day⁻¹)"),
    ParameterDef("tp", "AI2",       "ai2",       "*.wwq", "channel-nut.cha",(0.01, 0.02),    "absval", "조류 P 함량비"),
]


# ── 통합 카탈로그 ───────────────────────────────────────────────────────────
CATALOG: Dict[str, List[ParameterDef]] = {
    "flow": FLOW_PARAMETERS,
    "ss":   SS_PARAMETERS,
    "tn":   TN_PARAMETERS,
    "tp":   TP_PARAMETERS,
}


# ── 조회 함수 ───────────────────────────────────────────────────────────────

def get_parameters(variable: str) -> List[ParameterDef]:
    """변수별 표준 보정 인자 리스트 반환."""
    v = variable.lower()
    if v not in CATALOG:
        raise ValueError(
            f"미지원 variable: '{variable}'. 가능: {list(CATALOG.keys())}"
        )
    return CATALOG[v]


def find_parameter(name: str, model_type: str = "swat_plus") -> ParameterDef:
    """인자명으로 카탈로그 검색.

    Parameters
    ----------
    name       : 인자명 (SWAT 2012 대소문자 무관, SWAT-Plus 소문자)
    model_type : swat_plus | swat2012
    """
    key_attr = "name_swat_plus" if model_type == "swat_plus" else "name_swat2012"
    name_norm = name.lower() if model_type == "swat_plus" else name.upper()
    for params in CATALOG.values():
        for p in params:
            if getattr(p, key_attr).lower() == name_norm.lower():
                return p
    raise KeyError(f"카탈로그에 없는 인자: '{name}' (model={model_type})")


def list_all_parameters() -> List[ParameterDef]:
    """전체 카탈로그 평탄화 — 변수 무관 모든 인자."""
    out: List[ParameterDef] = []
    for params in CATALOG.values():
        out.extend(params)
    return out


def summary_dataframe():
    """카탈로그를 DataFrame 으로 반환 (요약 표시·문서 출력용)."""
    import pandas as pd
    rows = []
    for var, params in CATALOG.items():
        for p in params:
            rows.append({
                "variable":      var,
                "swat2012":      p.name_swat2012,
                "swat_plus":     p.name_swat_plus,
                "file_swat2012": p.file_swat2012,
                "file_swat_plus":p.file_swat_plus,
                "range":         f"[{p.default_range[0]}, {p.default_range[1]}]",
                "change_type":   p.change_type,
                "description":   p.description,
            })
    return pd.DataFrame(rows)
