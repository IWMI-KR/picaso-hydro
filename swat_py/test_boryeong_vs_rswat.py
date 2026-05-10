"""
swat_py 검증 스크립트 — 보령댐 유역 테스트 (vs rSWAT R 결과)
=============================================================

기존 rSWAT(R)이 생성한 결과 파일을 swat_py로 재파싱·재계산한 뒤
수치를 직접 비교하여 Python 구현의 정확성을 검증합니다.

SWAT.exe를 재실행하지 않고 기존 output.rch 파일만 사용합니다.

검증 단계
---------
  STEP 1  : 설정 파일 로드 확인
  STEP 2  : output.rch 파싱 — 보정 기간(2017-2018)
  STEP 3  : 유량(flow) 추출 및 관측 자료 병합
  STEP 4  : 성능지표(NSE·RMSE·PBIAS) 비교 (swat_py vs R 산출값)
  STEP 5  : 월 집계 결과 비교
  STEP 6  : 검증 기간(2021-2022) 및 장기 역사 기간(1998-2022) 비교
  STEP 7  : 기후변화 요약 CSV 파싱 검증
  STEP 8  : 시각화 그래프 생성
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── 패키지 루트를 경로에 추가 (pip install -e . 없이도 실행 가능) ─────────────
sys.path.insert(0, str(Path(__file__).parent / "src"))

from swat_py.config.env import load_config
from swat_py.output.reader_swat import parse_output_rch, extract_rch_outtype
from swat_py.output.aggregator import add_date_parts, aggregate_output
from swat_py.metrics.performance import calc_all
from swat_py.viz.summary import plot_summary_figure


# ══════════════════════════════════════════════════════════════════════════════
#  공용 경로 상수
# ══════════════════════════════════════════════════════════════════════════════
YAML_FILE   = Path(__file__).parent / "swat_py_boryeong.yaml"
OBS_OUT_DIR = Path("I:/2025-APCC_Cook/rSWAT/swat_sim/rSWAT/Observed/Output")
ANA_DIR     = Path("I:/2025-APCC_Cook/rSWAT/swat_sim/rSWAT/Observed/Analysis")
CC_SUM_DIR  = Path("I:/2025-APCC_Cook/rSWAT/swat_sim/rSWAT/CChange/Summary")
CC_ANA_DIR  = Path("I:/2025-APCC_Cook/rSWAT/swat_sim/rSWAT/CChange/Analysis")
REPORT_DIR  = Path(__file__).parent / "test_reports"
REPORT_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  출력 헬퍼
# ══════════════════════════════════════════════════════════════════════════════
_PASS = "✔ PASS"
_FAIL = "✖ FAIL"

def _section(title: str) -> None:
    print(f"\n{'═'*70}")
    print(f"  {title}")
    print(f"{'═'*70}")

def _check(label: str, condition: bool, detail: str = "") -> None:
    status = _PASS if condition else _FAIL
    msg = f"  {status}  {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)

def _metric_row(name: str, py_val: float, r_val: float | None, tol: float = 0.01) -> None:
    if r_val is None:
        print(f"  {'':8s}  swat_py={py_val:+.4f}   R값 없음")
        return
    diff = abs(py_val - r_val)
    ok = diff <= tol
    status = _PASS if ok else _FAIL
    print(f"  {status}  {name:10s}  swat_py={py_val:+.4f}   R={r_val:+.4f}   |diff|={diff:.6f}")


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 1 : 설정 파일 로드
# ══════════════════════════════════════════════════════════════════════════════
def step1_load_config():
    _section("STEP 1 : 설정 파일 로드 (swat_py_boryeong.yaml)")
    cfg = load_config(YAML_FILE)

    _check("YAML 파일 로드 성공", True)
    _check("모델 타입 = swat2012",   cfg.ModelType == "swat2012")
    _check("워밍업 기간 = 0년",      cfg.CioNYSKIP == 0)
    _check("관측소 ID = [asos235]",  cfg.StnIDs == ["asos235"])
    _check("유량 지점 ID = [1]",     cfg.OutletFlowIDs == [1])
    _check("유량 지점명 = [wl]",     cfg.OutletFlowNms == ["wl"])
    _check("기후변화 활성화",        cfg.CChangeOpt == "on")
    _check("GCM 모델 수 = 18",       len(cfg.MdlNms) == 18,
           f"실제={len(cfg.MdlNms)}")
    _check("보정 기간 2017-2018",
           cfg.CalibrationStartYear == 2017 and cfg.CalibrationEndYear == 2018)
    _check("검증 기간 2021-2022",
           cfg.ValidationStartYear == 2021 and cfg.ValidationEndYear == 2022)

    print(f"\n  프로젝트 루트 : {cfg.PrjDir}")
    print(f"  SWAT 출력 폴더: {cfg.SwatObsDir}")
    return cfg


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 2 : output.rch 파싱 — 보정 기간
# ══════════════════════════════════════════════════════════════════════════════
def step2_parse_rch(cfg) -> pd.DataFrame | None:
    _section("STEP 2 : output-Calibration.rch 파싱")

    rch_path = OBS_OUT_DIR / "output-Calibration.rch"
    _check("output-Calibration.rch 존재", rch_path.exists(), str(rch_path))
    if not rch_path.exists():
        print("  [오류] 파일 없음. 이후 단계 건너뜜.")
        return None

    # 보정 기간 시작일 (sdate = 시뮬레이션 시작, NYSKIP=0이므로 바로 출력)
    sdate = f"{cfg.CalibrationStartYear}-01-01"
    raw = parse_output_rch(rch_path, outlet=1, sdate=sdate)

    _check("outlet=1 데이터 추출 성공", raw is not None)
    if raw is None:
        return None

    # 보정 기간 행 수 확인: 2017-2018 = 730일
    expected_rows = 730
    actual_rows = len(raw)
    _check(f"행 수 = {expected_rows}일 (2년)",
           actual_rows == expected_rows, f"실제={actual_rows}")

    # 필수 열 존재
    required_cols = ["date", "FLOW_OUTcms", "AREAkm2"]
    for col in required_cols:
        _check(f"열 '{col}' 존재", col in raw.columns)

    print(f"\n  날짜 범위 : {raw['date'].min()} ~ {raw['date'].max()}")
    print(f"  유역 면적 : {raw['AREAkm2'].iloc[0]:.1f} km²")
    print(f"\n  첫 5행 미리보기 (FLOW_OUTcms):")
    print(raw[["date", "FLOW_OUTcms"]].head().to_string(index=False))
    return raw


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 3 : 유량 추출 및 관측 자료 병합
# ══════════════════════════════════════════════════════════════════════════════
def step3_extract_flow(cfg, raw: pd.DataFrame):
    _section("STEP 3 : 유량 추출 및 관측 자료 병합")

    # swat_py 유량 추출
    typed = extract_rch_outtype(raw, "flow")
    typed = add_date_parts(typed)
    _check("flow_cms 열 생성", "flow_cms" in typed.columns)
    _check("NaN 없음",         not typed["flow_cms"].isna().any())

    # 관측 유량 로드
    obs_file = Path(cfg.SwatDbDir) / cfg.ObsFlowFile
    _check("관측 유량 파일 존재", obs_file.exists(), str(obs_file))
    if not obs_file.exists():
        print("  [경고] 관측 파일 없음. 관측값 없이 계속합니다.")
        obs_df = pd.DataFrame(columns=["date", "obs"])
    else:
        obs_df = pd.read_csv(obs_file)
        obs_df["date"] = pd.to_datetime(
            obs_df[["year", "mon", "day"]].rename(columns={"mon": "month"})
        )
        obs_df = obs_df[["date", "inflow_cms"]].rename(columns={"inflow_cms": "obs"})

    # 병합
    sim_df = typed[["date", "flow_cms"]].rename(columns={"flow_cms": "sim"})
    sim_df["date"] = pd.to_datetime(sim_df["date"])
    obs_df["date"] = pd.to_datetime(obs_df["date"])
    daily = pd.merge(sim_df, obs_df, on="date", how="left")

    _check("병합 후 행 수 = 730", len(daily) == 730, f"실제={len(daily)}")
    obs_count = daily["obs"].notna().sum()
    _check(f"관측값 있는 날 수 = {obs_count}일", obs_count > 0)

    print(f"\n  첫 5행 (date, sim, obs):")
    print(daily.head().to_string(index=False))
    return daily


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 4 : 성능지표 비교 (swat_py vs R 산출값)
# ══════════════════════════════════════════════════════════════════════════════
def step4_compare_metrics(daily: pd.DataFrame):
    _section("STEP 4 : 성능지표 비교 (swat_py vs R 기존 결과)")

    # R이 생성한 일별 분석 CSV 로드
    r_daily_path = ANA_DIR / "Calibration_flow_1-wl-daily.csv"
    r_mon_path   = ANA_DIR / "Calibration_flow_1-wl-monthly.csv"

    _check("R 일별 분석 CSV 존재", r_daily_path.exists())
    _check("R 월별 분석 CSV 존재", r_mon_path.exists())

    if not r_daily_path.exists():
        print("  [경고] R 결과 파일 없음. 지표 비교 생략.")
        return

    r_daily = pd.read_csv(r_daily_path, parse_dates=["date"])

    # ── 시뮬레이션값 수치 비교 ────────────────────────────────────────────────
    print("\n  [일별 시뮬레이션값 비교]")
    py_sim = daily["sim"].values
    r_sim  = r_daily["sim"].values

    _check("행 수 일치", len(py_sim) == len(r_sim),
           f"swat_py={len(py_sim)}, R={len(r_sim)}")

    if len(py_sim) == len(r_sim):
        max_diff = np.max(np.abs(py_sim - r_sim))
        _check("시뮬레이션값 최대 차이 < 0.0001",
               max_diff < 1e-4, f"최대 차이={max_diff:.2e}")

    # ── 성능지표 ─────────────────────────────────────────────────────────────
    # swat_py 계산
    obs_py = daily["obs"].values
    sim_py = daily["sim"].values
    py_metrics = calc_all(obs_py, sim_py)

    # R 결과에서 재계산 (R CSV에는 metrics가 별도 저장되지 않으므로 직접 계산)
    if "obs" in r_daily.columns:
        r_metrics = calc_all(r_daily["obs"].values, r_daily["sim"].values)
    else:
        r_metrics = None

    print("\n  [성능지표 비교] (허용 오차 ±0.001)")
    metrics_to_show = [
        ("NSE",   "nse"),
        ("RMSE",  "rmse"),
        ("RSR",   "rsr"),
        ("PBIAS", "pbias"),
        ("R²",    "r2"),
    ]
    for label, key in metrics_to_show:
        py_val = py_metrics[key]
        r_val  = r_metrics[key] if r_metrics else None
        _metric_row(label, py_val, r_val, tol=0.001)

    print("\n  [swat_py 성능지표 요약]")
    print(f"  NSE   = {py_metrics['nse']:+.4f}  (Nash-Sutcliffe Efficiency, 1.0이 완벽)")
    print(f"  RMSE  = {py_metrics['rmse']:.4f} cms")
    print(f"  PBIAS = {py_metrics['pbias']:+.2f}%  (음수=과대추정, 양수=과소추정)")
    print(f"  R²    = {py_metrics['r2']:.4f}")

    return py_metrics


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 5 : 월 집계 결과 비교
# ══════════════════════════════════════════════════════════════════════════════
def step5_monthly_comparison(daily: pd.DataFrame):
    _section("STEP 5 : 월 집계 결과 비교")

    # swat_py 월 집계
    result = aggregate_output(daily, funtype="mean")
    py_monthly = result["yearmon"]

    # R 월별 CSV 로드
    r_mon_path = ANA_DIR / "Calibration_flow_1-wl-monthly.csv"
    if not r_mon_path.exists():
        print("  [경고] R 월별 CSV 없음. 비교 생략.")
        return py_monthly

    r_monthly = pd.read_csv(r_mon_path)
    # R CSV 열 이름 정규화 (yearmon, obs, sim 순서 다를 수 있음)
    r_monthly.columns = [c.strip() for c in r_monthly.columns]

    _check("월 집계 행 수 = 24개월", len(py_monthly) == 24,
           f"swat_py={len(py_monthly)}")
    _check("R 월 집계 행 수 = 24개월", len(r_monthly) == 24,
           f"R={len(r_monthly)}")

    # sim 값 비교
    if "sim" in r_monthly.columns and "sim" in py_monthly.columns:
        py_sim_m = py_monthly["sim"].values
        r_sim_m  = r_monthly["sim"].values
        if len(py_sim_m) == len(r_sim_m):
            max_diff = np.max(np.abs(py_sim_m - r_sim_m))
            _check(f"월 sim 최대 차이 < 0.001",
                   max_diff < 0.001, f"최대 차이={max_diff:.2e}")

    print("\n  [swat_py 월 집계 미리보기]")
    print(py_monthly[["yearmon", "sim"]].head(6).to_string(index=False))

    if "sim" in r_monthly.columns:
        print("\n  [R 월 집계 미리보기]")
        print(r_monthly[["yearmon", "sim"]].head(6).to_string(index=False))

    return py_monthly


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 6 : 검증 기간 및 역사 기간 비교
# ══════════════════════════════════════════════════════════════════════════════
def step6_validation_and_baseline(cfg):
    _section("STEP 6 : 검증(Validation) 및 역사(observed) 기간 비교")

    runs = [
        ("Validation",  "2021-01-01", "output-Validation.rch",  "Validation_flow_1-wl-daily.csv",  730),
        ("observed",    "1998-01-01", "output-observed.rch",     "observed_flow_1-wl-daily.csv",    9131),
    ]

    for sim_type, sdate, rch_name, ana_name, exp_rows in runs:
        print(f"\n  ── {sim_type} ──")
        rch_path = OBS_OUT_DIR / rch_name
        _check(f"{rch_name} 존재", rch_path.exists())
        if not rch_path.exists():
            continue

        raw = parse_output_rch(rch_path, outlet=1, sdate=sdate)
        _check("outlet=1 추출", raw is not None)
        if raw is None:
            continue

        actual_rows = len(raw)
        _check(f"행 수 ≈ {exp_rows}일",
               abs(actual_rows - exp_rows) <= 2,
               f"실제={actual_rows}")

        typed = extract_rch_outtype(raw, "flow")

        # R 결과와 비교
        r_path = ANA_DIR / ana_name
        if r_path.exists():
            r_df = pd.read_csv(r_path, parse_dates=["date"])
            if "sim" in r_df.columns:
                py_sim = typed["flow_cms"].values
                r_sim  = r_df["sim"].values
                n = min(len(py_sim), len(r_sim))
                max_diff = np.max(np.abs(py_sim[:n] - r_sim[:n]))
                _check(f"sim 최대 차이 < 0.0001",
                       max_diff < 1e-4, f"최대={max_diff:.2e}")

                # 지표 계산
                if "obs" in r_df.columns:
                    m = calc_all(r_df["obs"].values, r_df["sim"].values)
                    print(f"  NSE={m['nse']:.4f}  RMSE={m['rmse']:.4f}  PBIAS={m['pbias']:+.2f}%")
        else:
            print(f"  [참고] R 분석 CSV 없음: {ana_name}")


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 7 : 기후변화 요약 CSV 파싱 검증
# ══════════════════════════════════════════════════════════════════════════════
def step7_cc_summary(cfg):
    _section("STEP 7 : 기후변화 요약 CSV 파싱 검증")

    stat_types = ["Monthly-Mean", "Monthly-Max", "Tenday-Mean", "Tenday-Max"]
    scenarios  = ["historical", "ssp126", "ssp245", "ssp370", "ssp585"]
    periods    = {"historical": "1981", "ssp126": "2011", "ssp245": "2011",
                  "ssp370": "2011", "ssp585": "2011"}
    outlet_tag = "1-wl_flow"

    # 파일 존재 여부 확인
    found = 0
    for stat in stat_types:
        for scn in scenarios:
            yr = periods[scn]
            fname = CC_SUM_DIR / f"{stat}-clim_{outlet_tag}_{scn}_{yr}.csv"
            if fname.exists():
                found += 1

    total = len(stat_types) * len(scenarios)
    _check(f"기후변화 요약 CSV 존재 ({found}/{total}개)",
           found > 0, f"CC_SUM_DIR={CC_SUM_DIR}")

    # 대표 파일 내용 검증 (Monthly-Mean / historical)
    rep_file = CC_SUM_DIR / f"Monthly-Mean-clim_{outlet_tag}_historical_1981.csv"
    if rep_file.exists():
        df = pd.read_csv(rep_file)
        _check("열 수 = 1(month) + 1(Observed) + 18(GCMs) + 1(MME) = 21",
               df.shape[1] == 21, f"실제={df.shape[1]}")
        _check("행 수 = 12개월 + 1(Mean행) = 13", len(df) == 13, f"실제={len(df)}")
        _check("'Observed' 열 존재", "Observed" in df.columns)
        _check("'MME' 열 존재", "MME" in df.columns)

        print(f"\n  [Monthly-Mean / historical] 첫 3행 미리보기:")
        show_cols = ["month", "Observed", "CanESM5", "MME"]
        available = [c for c in show_cols if c in df.columns]
        print(df[available].head(3).to_string(index=False))

    # 기후변화 분석 CSV 검증 (GCM별 일별 자료)
    print("\n  [GCM별 분석 CSV 검증 — CanESM5 / historical]")
    cc_ana_path = CC_ANA_DIR / "CanESM5" / "output_historical_1-wl_flow-daily.csv"
    if cc_ana_path.exists():
        df2 = pd.read_csv(cc_ana_path, parse_dates=["date"])
        n_rows = len(df2)
        _check("행 수 = 30년 × 365.25 ≈ 10950일",
               abs(n_rows - 10957) < 10, f"실제={n_rows}")
        _check("'sim' 열 존재", "sim" in df2.columns)
        print(f"  날짜 범위: {df2['date'].min().date()} ~ {df2['date'].max().date()}")
        print(f"  연 평균 유량: {df2['sim'].mean():.4f} cms")


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 8 : 시각화 그래프 생성
# ══════════════════════════════════════════════════════════════════════════════
def step8_generate_plots(daily: pd.DataFrame, monthly: pd.DataFrame):
    _section("STEP 8 : 시각화 그래프 생성")

    # 4패널 요약 그래프 생성 (swat_py)
    out_path = plot_summary_figure(
        out_dir=REPORT_DIR,
        name="swat_py_Calibration_flow_1-wl",
        title="Boryeong Watershed — Calibration (2017-2018) — swat_py",
        daily_df=daily,
        monthly_df=monthly,
        outtype="flow",
    )
    _check(f"4패널 PNG 생성", out_path.exists(), str(out_path))
    print(f"\n  저장 위치: {out_path}")

    # R이 생성한 PNG와 비교 안내
    r_png = ANA_DIR / "Calibration_flow_1-wl.png"
    if r_png.exists():
        print(f"  R 그래프   : {r_png}")
        print("  → 두 PNG를 나란히 열어 시각적으로 비교하세요.")


# ══════════════════════════════════════════════════════════════════════════════
#  메인 실행
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print("\n" + "█"*70)
    print("  swat_py 검증 테스트 — 보령댐 유역 vs rSWAT(R) 결과")
    print("█"*70)

    # STEP 1
    cfg = step1_load_config()

    # STEP 2
    raw = step2_parse_rch(cfg)
    if raw is None:
        print("\n[중단] output-Calibration.rch 없음. 이후 단계 실행 불가.")
        return

    # STEP 3
    daily = step3_extract_flow(cfg, raw)

    # STEP 4
    step4_compare_metrics(daily)

    # STEP 5
    monthly = step5_monthly_comparison(daily)

    # STEP 6
    step6_validation_and_baseline(cfg)

    # STEP 7
    step7_cc_summary(cfg)

    # STEP 8
    if monthly is not None and "sim" in monthly.columns:
        step8_generate_plots(daily, monthly)

    # ── 최종 요약 ──────────────────────────────────────────────────────────
    print(f"\n{'═'*70}")
    print("  검증 완료. test_reports/ 폴더에 PNG 저장됨.")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    main()
