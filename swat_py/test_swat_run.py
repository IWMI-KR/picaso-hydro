"""
swat_py SWAT.exe 실행 테스트 — 보령댐 유역 (2017-2018 보정 기간)
================================================================

【R 패키지(rSWAT)의 SWAT 실행 방식】
  - R 패키지는 inst/extdata/ 폴더에 SWAT2020.exe를 번들로 내장
  - system.file()로 exe 경로를 찾고, file.copy()로 TxtInOut 폴더에 복사
  - 복사 후 setwd(TxtInOut); system("SWAT2020.exe") 으로 실행

【swat_py의 SWAT 실행 방식】
  Python 패키지는 Windows 바이너리(.exe)를 번들로 배포하지 않습니다.
  대신 다음 3가지 경로로 exe를 지정합니다:

  방법 1 (기본, 권장):
      TxtInOut 폴더에 SWAT2020.exe를 미리 배치
      → YAML: model.executable: "SWAT2020.exe"
      → swat_py이 그 폴더에서 직접 실행 (복사 불필요)

  방법 2 (exe_path 지정):
      run_observation(..., exe_path="D:/SWAT_exe/SWAT2020.exe") 로 전달
      → swat_py이 TxtInOut으로 자동 복사 후 실행

  방법 3 (수동 복사 후 실행):
      shutil.copy("D:/SWAT_exe/SWAT2020.exe", cfg.SwatRunDir)
      SwatExecutor(cfg.SwatRunDir, "SWAT2020.exe").run()

  내부 동작 (SwatExecutor):
      subprocess.run(["SWAT2020.exe"], cwd=TxtInOut_폴더,
                     capture_output=True, timeout=3600)
      → 비-제로 returncode → SwatRunError 발생

테스트 내용:
  STEP 1 : 기존 output-Calibration.rch 백업
  STEP 2 : swat_py으로 기상 입력 파일 생성 (pcp1.pcp, tmp1.tmp, ...)
  STEP 3 : file.cio 패치 (NBYR=2, IYR=2017, NYSKIP=0)
  STEP 4 : SWAT2020.exe 실행
  STEP 5 : 출력 파일 rename (output.rch → output-Calibration.rch)
  STEP 6 : 신규 출력 vs 기존 R 출력 비교 (유량, 성능지표)
  STEP 7 : file.cio 복원 (역사 기간 설정으로)
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))

from swat_py.config.env import load_config
from swat_py.io.station import load_station_csv
from swat_py.io.weather_swat import write_all_weather
from swat_py.io.config_swat import patch_file_cio
from swat_py.output.reader_swat import parse_output_rch, extract_rch_outtype
from swat_py.output.aggregator import add_date_parts
from swat_py.metrics.performance import calc_all
from swat_py.runner.executor import SwatExecutor, SwatRunError
from swat_py.runner.file_manager import rename_outputs


# ── 경로 상수 ─────────────────────────────────────────────────────────────────
YAML_FILE   = Path(__file__).parent / "swat_py_boryeong.yaml"
OBS_OUT_DIR = Path("I:/2025-APCC_Cook/rSWAT/swat_sim/rSWAT/Observed/Output")
ANA_DIR     = Path("I:/2025-APCC_Cook/rSWAT/swat_sim/rSWAT/Observed/Analysis")
DB_DIR      = Path("I:/2025-APCC_Cook/rSWAT/Database/SWAT")
REPORT_DIR  = Path(__file__).parent / "test_reports"
REPORT_DIR.mkdir(exist_ok=True)

CALIB_FILE  = OBS_OUT_DIR / "output-Calibration.rch"
BACKUP_FILE = OBS_OUT_DIR / "output-Calibration.rch.bak"


# ── 유틸 ──────────────────────────────────────────────────────────────────────
_pass_count = 0
_fail_count = 0


def _check(label: str, ok: bool, detail: str = "") -> bool:
    global _pass_count, _fail_count
    sym = "✔ PASS" if ok else "✖ FAIL"
    msg = f"  {sym}  {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    if ok:
        _pass_count += 1
    else:
        _fail_count += 1
    return ok


def _banner(title: str) -> None:
    print()
    print("══════════════════════════════════════════════════════════════════════")
    print(f"  {title}")
    print("══════════════════════════════════════════════════════════════════════")


# ══════════════════════════════════════════════════════════════════════════════
#  실행 방식 설명 출력
# ══════════════════════════════════════════════════════════════════════════════
print("█" * 72)
print("  swat_py SWAT.exe 실행 방식 비교 및 구동 테스트")
print("█" * 72)
print("""
┌─ R 패키지(rSWAT) 방식 ──────────────────────────────────────────────────────
│  • SWAT2020.exe를 inst/extdata/ 에 번들로 내장
│  • system.file("extdata/SWAT2020.exe", package="rSWAT") 로 경로 확인
│  • file.copy(exe_src, TxtInOut) 후 setwd(TxtInOut); system("SWAT2020.exe")
└──────────────────────────────────────────────────────────────────────────────

┌─ swat_py 방식 ────────────────────────────────────────────────────────────────
│  Python 패키지는 Windows .exe 바이너리를 번들하지 않음 (배포 정책)
│
│  [방법 1] TxtInOut에 exe 미리 배치 (기본/권장)
│      YAML: model.executable: "SWAT2020.exe"
│      → SwatExecutor(TxtInOut, "SWAT2020.exe").run()
│         subprocess.run(["SWAT2020.exe"], cwd=TxtInOut, ...)
│
│  [방법 2] run_observation(cfg, ..., exe_path="D:/exe/SWAT2020.exe")
│      → swat_py이 TxtInOut으로 복사 후 실행
│
│  [방법 3] 수동 복사 후 직접 실행
│      shutil.copy(exe, cfg.SwatRunDir)
│      SwatExecutor(cfg.SwatRunDir, "SWAT2020.exe").run()
└──────────────────────────────────────────────────────────────────────────────
""")


# ══════════════════════════════════════════════════════════════════════════════
#  설정 로드
# ══════════════════════════════════════════════════════════════════════════════
_banner("전처리 : 설정 파일 로드")
cfg = load_config(YAML_FILE)
run_dir   = Path(cfg.SwatRunDir)
exe_name  = cfg.Executable   # "SWAT2020.exe"
exe_path  = run_dir / exe_name

print(f"  TxtInOut 폴더 : {run_dir}")
print(f"  실행 파일     : {exe_path}")
_check("exe 파일 존재", exe_path.exists(), str(exe_path))
if not exe_path.exists():
    print("\n  [중단] SWAT2020.exe 를 TxtInOut 폴더에 복사한 후 재실행하세요.")
    print(f"  경로: {run_dir / exe_name}")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 1 : 기존 output-Calibration.rch 백업
# ══════════════════════════════════════════════════════════════════════════════
_banner("STEP 1 : 기존 output-Calibration.rch 백업")

if CALIB_FILE.exists():
    shutil.copy2(CALIB_FILE, BACKUP_FILE)
    _check("기존 파일 백업 완료", BACKUP_FILE.exists(), str(BACKUP_FILE))
else:
    _check("백업 (기존 파일 없음 — 신규 생성)", True)


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 2 : 기상 입력 파일 생성 (swat_py weather writers)
# ══════════════════════════════════════════════════════════════════════════════
_banner("STEP 2 : 기상 입력 파일 생성 (write_all_weather)")

wthr_dir = Path(cfg.ObsDayDir)
stations = load_station_csv(wthr_dir / cfg.StnFile, cfg.StnIDs)
print(f"  관측소 : {[s.id for s in stations]}  (총 {len(stations)}개)")

write_all_weather(stations=stations, wthr_dir=wthr_dir, out_dir=run_dir)

for fname in ("pcp1.pcp", "tmp1.tmp", "wnd.wnd", "hmd.hmd", "slr.slr"):
    fpath = run_dir / fname
    exists = fpath.exists()
    size = fpath.stat().st_size if exists else 0
    _check(f"{fname} 생성  ({size:,} bytes)", exists)


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 3 : file.cio 패치 (2017-2018 보정 기간)
# ══════════════════════════════════════════════════════════════════════════════
_banner("STEP 3 : file.cio 패치 (NBYR=2, IYR=2017, NYSKIP=0)")

syear  = cfg.CalibrationStartYear   # 2017
eyear  = cfg.CalibrationEndYear     # 2018
nyskip = cfg.CioNYSKIP              # 0
nbyr   = eyear - syear + 1 + nyskip # 2

patch_file_cio(run_dir, nbyr=nbyr, iyr=syear, nyskip=nyskip)

# 패치 결과 확인
cio_text = (run_dir / "file.cio").read_text(encoding="cp949", errors="replace")
nbyr_ok   = f"{nbyr:16d}" in cio_text
iyr_ok    = f"{syear:16d}" in cio_text
nyskip_ok = f"{nyskip:16d}" in cio_text

_check(f"NBYR = {nbyr}", nbyr_ok)
_check(f"IYR  = {syear}", iyr_ok)
_check(f"NYSKIP = {nyskip}", nyskip_ok)


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 4 : SWAT2020.exe 실행
# ══════════════════════════════════════════════════════════════════════════════
_banner("STEP 4 : SWAT2020.exe 실행 (subprocess)")

print(f"  실행 경로 : {run_dir}")
print(f"  명령      : {exe_name}")
print("  실행 중... (2년 시뮬레이션, 수 초~수십 초 소요)")

t0 = time.time()
try:
    result = SwatExecutor(run_dir, exe_name, timeout=300).run(capture_output=True)
    elapsed = time.time() - t0
    _check(f"SWAT 실행 완료 ({elapsed:.1f}초)", True)
    if result.stdout:
        last_lines = result.stdout.strip().split("\n")[-3:]
        print("  [stdout 마지막 3줄]")
        for ln in last_lines:
            print(f"    {ln}")
except SwatRunError as e:
    elapsed = time.time() - t0
    _check(f"SWAT 실행 실패 (returncode={e.returncode}, {elapsed:.1f}초)", False)
    print(f"  [STDOUT]\n{e.stdout[-1000:]}")
    print(f"  [STDERR]\n{e.stderr[-500:]}")
    # file.cio 복원 후 중단
    patch_file_cio(run_dir, nbyr=25, iyr=1998, nyskip=0)
    sys.exit(1)
except Exception as e:
    _check(f"SWAT 실행 오류: {e}", False)
    sys.exit(1)

# output.rch 생성 확인
rch_new = run_dir / "output.rch"
_check("output.rch 생성됨", rch_new.exists(), f"{rch_new.stat().st_size:,} bytes" if rch_new.exists() else "없음")


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 5 : output.rch → output-Calibration.rch 이동
# ══════════════════════════════════════════════════════════════════════════════
_banner("STEP 5 : output.rch 이동 (rename_outputs)")

OBS_OUT_DIR.mkdir(parents=True, exist_ok=True)
rename_outputs(
    run_dir=run_dir,
    out_dir=OBS_OUT_DIR,
    output_types=["rch"],
    scenario_name="Calibration",
    model="swat2012",
)
_check("output-Calibration.rch 저장됨", CALIB_FILE.exists(), str(CALIB_FILE))


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 6 : 신규 출력 vs 기존 R 출력 비교
# ══════════════════════════════════════════════════════════════════════════════
_banner("STEP 6 : 신규 swat_py 출력 vs 기존 R 출력 비교")

sdate = f"{syear}-01-01"

# ── 신규 swat_py 결과 ──
new_raw = parse_output_rch(CALIB_FILE, outlet=1, sdate=sdate)
if new_raw is None:
    _check("신규 output.rch 파싱 실패", False)
    sys.exit(1)
new_flow = extract_rch_outtype(new_raw, "flow")["flow_cms"]
_check(f"신규 output 파싱 : {len(new_flow)}행", len(new_flow) == 730, f"실제={len(new_flow)}")

# ── R 분석 CSV의 sim값과 직접 비교 (백업은 이전 실행 결과라 신뢰도 낮음) ──
r_daily_ref = ANA_DIR / "Calibration_flow_1-wl-daily.csv"
if r_daily_ref.exists():
    r_ref_df = pd.read_csv(r_daily_ref)
    r_ref_sim = r_ref_df["sim"].values
    max_diff_vs_r = float(np.abs(new_flow.values - r_ref_sim).max())
    _check(
        "신규 vs R 원본 유량 최대 차이 < 0.001 cms",
        max_diff_vs_r < 0.001,
        f"최대 차이={max_diff_vs_r:.2e}",
    )
    print(f"\n  신규(swat_py)  첫 5일 FLOW_OUT: {new_flow.values[:5]}")
    print(f"  R 분석 CSV   첫 5일 FLOW_OUT: {r_ref_sim[:5]}")
else:
    print("  [INFO] R 분석 CSV 없음 — 관측 CSV와 비교합니다.")

# ── 관측 자료와 성능지표 산출 ──
obs_df = pd.read_csv(DB_DIR / cfg.ObsFlowFile, encoding="utf-8-sig")
obs_df["date"] = pd.to_datetime(
    obs_df[["year", "mon", "day"]].rename(columns={"mon": "month"})
)
new_df = new_raw.copy()
new_df["flow_cms"] = new_flow.values
new_df = add_date_parts(new_df[["date", "flow_cms"]].rename(columns={"flow_cms": "sim"}))
merged = pd.merge(new_df[["date", "sim"]], obs_df[["date", "inflow_cms"]].rename(columns={"inflow_cms": "obs"}), on="date", how="inner")
valid = merged.dropna(subset=["obs", "sim"])

metrics = calc_all(valid["obs"].values, valid["sim"].values)
# calc_all returns lowercase keys: nse, rmse, rsr, pbias, r2, mae, nof
print(f"\n  ── 신규 실행 성능지표 (보정 2017-2018) ──")
print(f"  NSE   = {metrics['nse']:+.4f}  (Nash-Sutcliffe Efficiency)")
print(f"  RMSE  = {metrics['rmse']:.4f} cms")
print(f"  PBIAS = {metrics['pbias']:+.2f}%  (음수=과대추정)")
print(f"  R²    = {metrics['r2']:.4f}")
_check("NSE > -1.0 (최소 합리적 수준)", metrics["nse"] > -1.0, f"NSE={metrics['nse']:.4f}")

# ── R 결과와 지표 비교 ──
r_daily_csv = ANA_DIR / "Calibration_flow_1-wl-daily.csv"
if r_daily_csv.exists():
    r_df = pd.read_csv(r_daily_csv)
    r_obs = r_df["obs"].values
    r_sim = r_df["sim"].values
    mask = ~(np.isnan(r_obs) | np.isnan(r_sim))
    r_metrics = calc_all(r_obs[mask], r_sim[mask])
    print(f"\n  ── R 결과 성능지표 (참조) ──")
    print(f"  NSE   = {r_metrics['nse']:+.4f}")
    print(f"  RMSE  = {r_metrics['rmse']:.4f} cms")
    print(f"  PBIAS = {r_metrics['pbias']:+.2f}%")
    print()
    print("  [참고] swat_py 기상파일은 swat_py gap-fill로 재생성되어 R 결과와 미세한 차이가 있을 수 있습니다.")
    print("  완전 일치를 위해서는 R이 생성한 기상파일을 직접 사용해야 합니다.")
    nse_diff = abs(metrics["nse"] - r_metrics["nse"])
    _check(f"NSE 차이 < 0.05 (동일 기상파일 기준 완전일치, 재생성 시 허용오차)", nse_diff < 0.05,
           f"|diff|={nse_diff:.4f}")


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 7 : file.cio 복원 (역사 기간 설정)
# ══════════════════════════════════════════════════════════════════════════════
_banner("STEP 7 : file.cio 복원 (1998~2022 역사 기간)")

patch_file_cio(run_dir, nbyr=25, iyr=1998, nyskip=0)
cio_text2 = (run_dir / "file.cio").read_text(encoding="cp949", errors="replace")
_check("file.cio IYR=1998 복원", f"{1998:16d}" in cio_text2)
_check("file.cio NBYR=25 복원", f"{25:16d}" in cio_text2)


# ══════════════════════════════════════════════════════════════════════════════
#  최종 결과
# ══════════════════════════════════════════════════════════════════════════════
print()
print("═" * 72)
print(f"  PASS {_pass_count}개 / FAIL {_fail_count}개")
print("═" * 72)
if _fail_count == 0:
    print("  ✔ 모든 검사 통과 — swat_py SWAT 실행 파이프라인 정상 작동")
else:
    print("  일부 검사 실패 — 위 로그를 확인하세요.")
print()
print("  백업 파일 위치 (비교용):")
print(f"    {BACKUP_FILE}")
print("  신규 출력 파일:")
print(f"    {CALIB_FILE}")
