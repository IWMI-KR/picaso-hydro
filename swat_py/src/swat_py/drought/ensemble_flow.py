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

import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from swat_py.drought.season import daykey_month, in_ym, period_end, period_ym
from swat_py.output.reader_swat_plus import parse_channel_sd_day
from swat_py.runner.file_manager import ignore_swat_outputs

# 12 outlet 채널 (gis_id → 이름)
OUTLETS = {
    13: "avatiu", 3: "avana", 8: "matavera", 10: "muriavai", 25: "totokoitu",
    1: "outlet_ch01", 5: "outlet_ch05", 12: "outlet_ch12", 14: "outlet_ch14",
    15: "outlet_ch15", 16: "outlet_ch16", 29: "outlet_ch29",
}


def _member_forcing(member_csv: Path) -> Dict[tuple, tuple]:
    """멤버 918430.csv → ``{(year, jday): (prcp, tmax, tmin)}``.

    키에 **연도를 포함**한다. 연중일(jday)만으로는 해를 넘는 계절(NDJ·DJF)에서
    12월과 다음 해 1월을 구분할 수 없다.
    """
    df = pd.read_csv(member_csv)
    out: Dict[tuple, tuple] = {}
    for _, r in df.iterrows():
        d = pd.Timestamp(int(r["year"]), int(r["mon"]), int(r["day"]))
        out[(int(d.year), int(d.dayofyear))] = (
            float(r["prcp"]), float(r["tmax"]), float(r["tmin"]))
    return out


def _member_coverage(forcing: Dict[tuple, tuple], daykeys: Dict[tuple, int],
                     ym: List[tuple]) -> List[str]:
    """멤버 forcing 이 예측 각 월을 덮는지 확인 → 부족한 월 설명 목록.

    해를 넘는 계절에서 멤버 CSV 의 연도가 틀리면(옛 acidwg 산출물) 그 달은
    **한 날도 맞지 않아** 기상이 주입되지 않는다. 예전에는 이것이 조용히
    '전 멤버 동일값'으로 나타났으므로 여기서 명시적으로 잡는다.

    2월은 acidwg 가 항상 28일만 생성하므로(윤년 미생성) 하루 부족을 허용한다.
    """
    have: Dict[int, int] = {}
    for k, m in daykeys.items():
        if k in forcing:
            have[m] = have.get(m, 0) + 1
    short: List[str] = []
    for y, m in ym:
        ndays = (pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)).day
        got = have.get(m, 0)
        if got < ndays - 1:             # -1 = 윤년 2/29 미생성 허용
            short.append(f"{y}-{m:02d} ({got}/{ndays}일)")
    return short


def _member_monthly_weather(member_csv: Path, ym: List[tuple]) -> Dict[int, tuple]:
    """멤버 918430.csv → {month: (precip_mm 합, tmax_c 평균, tmin_c 평균)} (예측월).

    이 멤버를 구동한 앙상블 forcing(918430 예측)을 예측월별로 집계 — 지역별
    결과 CSV 의 강수·기온 칼럼용. 섬 단일예측이라 전 수원에 동일 적용.
    ``ym`` 으로 걸러 해를 넘는 달도 포함한다(월 번호는 그대로 키로 쓴다)."""
    df = pd.read_csv(member_csv)
    key = df["year"].astype(int) * 100 + df["mon"].astype(int)
    df = df[key.isin({y * 100 + m for y, m in ym})]
    out: Dict[int, tuple] = {}
    for m, sub in df.groupby(df["mon"].astype(int)):
        out[int(m)] = (float(pd.to_numeric(sub["prcp"], errors="coerce").sum()),
                       float(pd.to_numeric(sub["tmax"], errors="coerce").mean()),
                       float(pd.to_numeric(sub["tmin"], errors="coerce").mean()))
    return out


def _overwrite_forecast_rows(run_dir: Path, forcing: Dict[tuple, tuple],
                             daykeys: Dict[tuple, int]) -> int:
    """예측기간의 모든 ``.pcp``/``.tmp`` 행을 멤버 forcing 으로 덮어쓴다.

    ``daykeys`` 는 :func:`~swat_py.drought.season.daykey_month` 가 만든
    ``{(year, jday): month}`` 조회표다. 연중일 **범위 비교**(``jday0 <= jd <= jday1``)
    는 해를 넘으면 시작>끝으로 뒤집혀 한 행도 고르지 못하므로 쓰지 않는다.

    Returns
    -------
    int : 덮어쓴 행 수(.pcp + .tmp 합계)
    """
    n = 0
    for pcp in run_dir.glob("*.pcp"):
        lines = pcp.read_text().splitlines()
        for i in range(3, len(lines)):
            p = lines[i].split()
            if len(p) < 3:
                continue
            yr, jd = int(float(p[0])), int(float(p[1]))
            if (yr, jd) in daykeys and (yr, jd) in forcing:
                lines[i] = f"  {yr:4d} {jd:5d} {forcing[(yr, jd)][0]:9.3f}"
                n += 1
        pcp.write_text("\n".join(lines) + "\n")
    for tmp in run_dir.glob("*.tmp"):
        lines = tmp.read_text().splitlines()
        for i in range(3, len(lines)):
            p = lines[i].split()
            if len(p) < 4:
                continue
            yr, jd = int(float(p[0])), int(float(p[1]))
            if (yr, jd) in daykeys and (yr, jd) in forcing:
                _, tx, tn = forcing[(yr, jd)]
                lines[i] = f"  {yr:4d} {jd:5d} {tx:9.3f} {tn:9.3f}"
                n += 1
        tmp.write_text("\n".join(lines) + "\n")
    return n


#: 멤버 1개의 SWAT+ 실행 제한(초). 10초는 느린 워커·디스크 경합에서 잘려나가
#: 멤버 손실(=앙상블 축소)을 만든다. 환경변수 SWAT_MEMBER_TIMEOUT 로 조정 가능.
MEMBER_TIMEOUT = int(os.environ.get("SWAT_MEMBER_TIMEOUT", "300"))


def _run_one(args) -> Dict:
    """(member_csv, base_dir, exe, fyear, months, outlets, era5_warmup, reservoirs)
    → 채널 월유량 + 저수지 월 만수대비% dict|None.

    reservoirs: {gis_id: ReservoirForecastParams} — 해당 gid 는 채널 유량 대신
    reservoir_day.txt 물수지 만수대비% 를 산출(저수지 수원). 없으면 {}."""
    (member_csv, base_dir, exe_name, fyear, months, outlets, era5_warmup,
     reservoirs) = args
    reservoirs = reservoirs or {}
    member_csv, base_dir = Path(member_csv), Path(base_dir)
    # 예측 구간을 (연도, 월) 로 풀어 쓴다 — NDJ·DJF 는 끝월이 다음 해다.
    ym = period_ym(fyear, months)
    last = period_end(fyear, months)
    daykeys = daykey_month(ym)          # {(year, jday): month} — 범위비교 대신 조회표
    tmp = Path(tempfile.mkdtemp(prefix="ens_"))
    try:
        run = tmp / "TxtInOut"
        # 출력물·실행파일 제외 — 실행파일(6.6MB)은 base 것을 그대로 쓴다.
        #  멤버마다 복사해 띄우면 백신이 새 복사본을 매번 검사하면서
        #  [WinError 2] 로 실행이 실패한다(1,000멤버 중 13~18% 실패 관측).
        #  SWAT+ 는 입력을 cwd 에서 읽으므로 실행파일 위치는 달라도 된다.
        shutil.copytree(base_dir, run,
                        ignore=lambda d, n: ignore_swat_outputs(d, n) | {exe_name})
        # (선택) warm-up 을 최근접 ERA5 격자 일자료로 재구성 — 운영 예보용.
        #   예보 구간은 아래 acidwg 덮어쓰기가 최종값을 넣으므로, 여기선 warm-up 채움이 목적.
        if era5_warmup:
            from swat_py.drought.warmup_era5 import write_era5_warmup
            write_era5_warmup(run, era5_warmup["grid_points_csv"],
                              era5_warmup["grid_daily_std_dir"], fyear=fyear,
                              warmup_years=int(era5_warmup["warmup_years"]),
                              forecast_end=last)
        forcing = _member_forcing(member_csv)
        # 멤버 기상이 예측 각 월을 덮지 못하면 SWAT+ 가 wgn 으로 조용히 대체해
        # 전 멤버가 같은 값이 된다 → 실행하지 않고 실패로 돌린다.
        short = _member_coverage(forcing, daykeys, ym)
        if short:
            return {"_member": member_csv.parent.name,
                    "_error": f"멤버 기상 부족 {', '.join(short)}"}
        if _overwrite_forecast_rows(run, forcing, daykeys) == 0:
            return {"_member": member_csv.parent.name,
                    "_error": "예측기간 기상행 없음(base 미연장)"}
        exe_path = run / exe_name
        if not exe_path.is_file():
            exe_path = base_dir / exe_name          # base 의 실행파일 공유(cwd 는 run)
        if exe_path.is_file():
            try:
                exe_path.chmod(0o755)           # 리눅스 실행 권한(best-effort, 마운트 EPERM 무시)
            except OSError:
                pass
        try:
            r = subprocess.run([str(exe_path)], cwd=str(run),
                               capture_output=True, timeout=MEMBER_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"_member": member_csv.parent.name, "_error": "timeout"}
        if r.returncode != 0:
            return {"_member": member_csv.parent.name, "_error": r.returncode}
        res: Dict = {"_member": member_csv.parent.name}
        # 이 멤버를 구동한 예측월 강수·기온(지역별 CSV 칼럼용) — 섬 단일예측이라 공통.
        res["_weather"] = _member_monthly_weather(member_csv, ym)
        for gid, name in outlets.items():
            if gid in reservoirs:
                # 저수지 수원 — reservoir_day.txt 물수지 → 월 만수대비% + 월말 저수위(ft)
                from swat_py.drought.reservoir_forecast import member_reservoir_series
                ser = member_reservoir_series(
                    run, reservoirs[gid], fyear=fyear, months=months,
                    sdate=f"{fyear}-01-01")
                if ser:
                    res[name] = {m: v["storage_pct"] for m, v in ser.items()}
                    res.setdefault("_wlevel", {})[name] = {
                        m: v["water_level_ft"] for m, v in ser.items()}
                continue
            # 채널 수원 — 월단위 출력(channel_sd_mon.txt), 각 행=월말·월평균 flo_out.
            df = parse_channel_sd_day(run / "channel_sd_mon.txt", outlet=gid,
                                      sdate=f"{fyear}-01-01")
            if df is None:
                continue
            df = df[in_ym(df["date"], ym).values]   # 연도별 월 — 해를 넘는 계절 포함
            mon = df.groupby(df["date"].dt.month)["flo_out"].mean()
            res[name] = {int(m): float(v) for m, v in mon.items()}
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_ensemble(base_dir: Path, ensemble_dir: Path, *, fyear: int, months: List[int],
                 exe_name: str = "SWAT-Plus.exe", n_members: int = 100,
                 n_workers: int = 6, outlets: Dict[int, str] = None,
                 station: str = "918430", era5_warmup: Dict = None,
                 reservoirs: Dict = None) -> tuple:
    """멤버 폴더들 → (values, aux).

    반환:
      values : {name: DataFrame[member × month]} — 하천=월유량(m³/s), 저수지=만수대비%.
      aux    : {"weather": {var: DataFrame[member × month]},   # var: precip_mm/tmax_c/tmin_c
                "wlevel":  {name: DataFrame[member × month]}}   # 저수지 월말 저수위(ft)

    base_dir     : 예측기간 time.sim 설정된 검보정 SWAT+ TxtInOut (관측 weather 포함)
    ensemble_dir : member_XXXX/{stn}.csv 루트 (acidwg 산출)
    outlets      : {gis_id: name} — None 이면 기본 12개(OUTLETS)
    era5_warmup  : {grid_points_csv, grid_daily_std_dir, warmup_years} — 지정 시 warm-up 을
                   최근접 ERA5 격자 일자료로 재구성(운영 예보). None 이면 검보정 모델 관측 사용.
    """
    outlets = outlets or OUTLETS
    reservoirs = reservoirs or {}
    members = sorted(ensemble_dir.glob("member_*"))[:n_members]
    tasks = [(str(m / f"{station}.csv"), str(base_dir), exe_name, fyear, months,
              outlets, era5_warmup, reservoirs)
             for m in members if (m / f"{station}.csv").is_file()]
    records = []
    n_fail = 0
    # 실패 사유별 멤버 목록 — 예전에는 개수만 세고 사유를 버려서, 999/1000 이
    # 나와도 왜 하나가 빠졌는지 알 수 없었다.
    fails: Dict[str, List[str]] = {}
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
                why = str((r or {}).get("_error", "알 수 없음"))
                fails.setdefault(why, []).append(
                    str((r or {}).get("_member", "?")))
            if done % 10 == 0:
                print(f"    앙상블 {done}/{len(tasks)} (실패 {n_fail})", flush=True)
    # 수원별 값 [member × month] (하천 유량 / 저수지 만수대비%)
    out: Dict[str, pd.DataFrame] = {}
    for name in outlets.values():
        rows = {r["_member"]: r[name] for r in records if name in r}
        if rows:
            out[name] = pd.DataFrame(rows).T.reindex(columns=months)
    # aux — 멤버별 예측월 기상(강수/기온) + 저수지 월말 저수위
    weather: Dict[str, pd.DataFrame] = {}
    for i, var in enumerate(("precip_mm", "tmax_c", "tmin_c")):
        rows = {r["_member"]: {m: vals[i] for m, vals in r["_weather"].items()}
                for r in records if r.get("_weather")}
        if rows:
            weather[var] = pd.DataFrame(rows).T.reindex(columns=months)
    wlevel: Dict[str, pd.DataFrame] = {}
    for name in outlets.values():
        rows = {r["_member"]: r["_wlevel"][name] for r in records
                if r.get("_wlevel") and name in r["_wlevel"]}
        if rows:
            wlevel[name] = pd.DataFrame(rows).T.reindex(columns=months)
    print(f"  앙상블 유효 멤버 {len(records)}/{len(tasks)}")
    if fails:
        # 사유별로 묶어 보여 준다(많은 순). 멤버 이름은 앞 3개만.
        print(f"  ⚠ 실패 멤버 {n_fail}개 — 사유별:")
        for why, who in sorted(fails.items(), key=lambda kv: -len(kv[1]))[:5]:
            head = ", ".join(sorted(who)[:3])
            more = f" 외 {len(who) - 3}개" if len(who) > 3 else ""
            print(f"      [{len(who):>4}] {why}  ({head}{more})")
    return out, {"weather": weather, "wlevel": wlevel}
