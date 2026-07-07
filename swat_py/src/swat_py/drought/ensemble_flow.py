"""예측 앙상블 SWAT+ 실행 → 12채널 예측월 유량 (대시보드 ③⑤ 입력).

멤버별로:
  1. 검보정(9-param) SWAT+ 모델(관측 weather 포함)을 복사
  2. **예측월(2016 Apr–Jun)** 의 전 스테이션 강수·기온을 acidwg 멤버(918430)로 덮어씀
     (관측 선행기간은 그대로 → spin-up 확보; 예측월은 단일 예측을 basin-wide 적용)
  3. SWAT+ 실행 → channel_sd_day.txt 에서 12채널 예측월 월유량 추출
전 멤버 집계 → {channel: DataFrame[member × month]} (m³/s).

⚠ acidwg 는 918430 만 예측하므로, 예측월 6개 타 스테이션은 918430 예측으로 대체(소규모
섬 단일예측 basin-wide). 관측 누출(leakage) 방지를 위해 예측월엔 관측을 쓰지 않음.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from swat_py.output.reader_swat_plus import parse_channel_sd_day

# 12 outlet 채널 (gis_id → 이름)
OUTLETS = {
    13: "avatiu", 3: "avana", 8: "matavera", 10: "muriavai", 25: "totokoitu",
    1: "outlet_ch01", 5: "outlet_ch05", 12: "outlet_ch12", 14: "outlet_ch14",
    15: "outlet_ch15", 16: "outlet_ch16", 29: "outlet_ch29",
}


def _member_forcing(member_csv: Path) -> Dict[int, tuple]:
    """멤버 918430.csv → {jday: (prcp, tmax, tmin)} (예측연도)."""
    df = pd.read_csv(member_csv)
    out = {}
    for _, r in df.iterrows():
        d = pd.Timestamp(int(r["year"]), int(r["mon"]), int(r["day"]))
        out[d.dayofyear] = (float(r["prcp"]), float(r["tmax"]), float(r["tmin"]))
    return out


def _overwrite_forecast_rows(run_dir: Path, forcing: Dict[int, tuple],
                             fyear: int, jday0: int, jday1: int) -> None:
    """예측월(fyear, jday0..jday1) 의 모든 .pcp/.tmp 를 멤버 forcing 으로 덮어씀."""
    for pcp in run_dir.glob("*.pcp"):
        lines = pcp.read_text().splitlines()
        for i in range(3, len(lines)):
            p = lines[i].split()
            if len(p) < 3:
                continue
            yr, jd = int(float(p[0])), int(float(p[1]))
            if yr == fyear and jday0 <= jd <= jday1 and jd in forcing:
                lines[i] = f"  {yr:4d} {jd:5d} {forcing[jd][0]:9.3f}"
        pcp.write_text("\n".join(lines) + "\n")
    for tmp in run_dir.glob("*.tmp"):
        lines = tmp.read_text().splitlines()
        for i in range(3, len(lines)):
            p = lines[i].split()
            if len(p) < 4:
                continue
            yr, jd = int(float(p[0])), int(float(p[1]))
            if yr == fyear and jday0 <= jd <= jday1 and jd in forcing:
                _, tx, tn = forcing[jd]
                lines[i] = f"  {yr:4d} {jd:5d} {tx:9.3f} {tn:9.3f}"
        tmp.write_text("\n".join(lines) + "\n")


def _run_one(args) -> Dict:
    """(member_csv, base_dir, exe, fyear, months, outlets, era5_warmup) → 채널 월유량 dict|None."""
    member_csv, base_dir, exe_name, fyear, months, outlets, era5_warmup = args
    member_csv, base_dir = Path(member_csv), Path(base_dir)
    jday0 = pd.Timestamp(fyear, months[0], 1).dayofyear
    last = pd.Timestamp(fyear, months[-1], 1) + pd.offsets.MonthEnd(0)
    jday1 = last.dayofyear
    tmp = Path(tempfile.mkdtemp(prefix="ens_"))
    try:
        run = tmp / "TxtInOut"
        shutil.copytree(base_dir, run)
        # (선택) warm-up 을 최근접 ERA5 격자 일자료로 재구성 — 운영 예보용.
        #   예보 구간은 아래 acidwg 덮어쓰기가 최종값을 넣으므로, 여기선 warm-up 채움이 목적.
        if era5_warmup:
            from swat_py.drought.warmup_era5 import write_era5_warmup
            write_era5_warmup(run, era5_warmup["grid_points_csv"],
                              era5_warmup["grid_daily_std_dir"], fyear=fyear,
                              warmup_years=int(era5_warmup["warmup_years"]),
                              forecast_end=last)
        _overwrite_forecast_rows(run, _member_forcing(member_csv), fyear, jday0, jday1)
        exe_path = run / exe_name
        if exe_path.is_file():
            try:
                exe_path.chmod(0o755)           # 리눅스 실행 권한(best-effort, 마운트 EPERM 무시)
            except OSError:
                pass
        try:
            r = subprocess.run([str(exe_path)], cwd=str(run),
                               capture_output=True, timeout=900)
        except subprocess.TimeoutExpired:
            return {"_member": member_csv.parent.name, "_error": "timeout"}
        if r.returncode != 0:
            return {"_member": member_csv.parent.name, "_error": r.returncode}
        res: Dict = {"_member": member_csv.parent.name}
        for gid, name in outlets.items():
            # 월단위 출력(channel_sd_mon.txt) — parse_channel_sd_day 는 yr/mon/day
            # 컬럼이 있어 월단위 파일에도 그대로 작동(각 행=월말 날짜·월평균 flo_out).
            df = parse_channel_sd_day(run / "channel_sd_mon.txt", outlet=gid,
                                      sdate=f"{fyear}-01-01")
            if df is None:
                continue
            df = df[(df["date"].dt.year == fyear) & (df["date"].dt.month.isin(months))]
            mon = df.groupby(df["date"].dt.month)["flo_out"].mean()
            res[name] = {int(m): float(v) for m, v in mon.items()}
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_ensemble(base_dir: Path, ensemble_dir: Path, *, fyear: int, months: List[int],
                 exe_name: str = "SWAT-Plus.exe", n_members: int = 100,
                 n_workers: int = 6, outlets: Dict[int, str] = None,
                 station: str = "918430", era5_warmup: Dict = None) -> Dict[str, pd.DataFrame]:
    """멤버 폴더들 → 채널별 [member × month] 월유량 DataFrame dict.

    base_dir     : 예측기간 time.sim 설정된 검보정 SWAT+ TxtInOut (관측 weather 포함)
    ensemble_dir : member_XXXX/{stn}.csv 루트 (acidwg 산출)
    outlets      : {gis_id: name} — None 이면 기본 12개(OUTLETS)
    era5_warmup  : {grid_points_csv, grid_daily_std_dir, warmup_years} — 지정 시 warm-up 을
                   최근접 ERA5 격자 일자료로 재구성(운영 예보). None 이면 검보정 모델 관측 사용.
    """
    outlets = outlets or OUTLETS
    members = sorted(ensemble_dir.glob("member_*"))[:n_members]
    tasks = [(str(m / f"{station}.csv"), str(base_dir), exe_name, fyear, months,
              outlets, era5_warmup)
             for m in members if (m / f"{station}.csv").is_file()]
    records = []
    n_fail = 0
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_run_one, t): t for t in tasks}
        done = 0
        for fu in as_completed(futs):
            done += 1
            try:
                r = fu.result()
            except Exception as e:                      # 워커 예외도 스킵(전체 실패 방지)
                r = {"_error": str(e)[:60]}
            if r and "_error" not in r:
                records.append(r)
            else:
                n_fail += 1
            if done % 10 == 0:
                print(f"    앙상블 {done}/{len(tasks)} (실패 {n_fail})", flush=True)
    # 채널별 [member × month]
    out: Dict[str, pd.DataFrame] = {}
    for name in outlets.values():
        rows = {r["_member"]: r[name] for r in records if name in r}
        if rows:
            out[name] = pd.DataFrame(rows).T.reindex(columns=months)
    print(f"  앙상블 유효 멤버 {len(records)}/{len(tasks)}")
    return out
