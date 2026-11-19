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
    """(member_csv, base_dir, exe, fyear, months, outlets, era5_warmup, reservoirs,
    daily_store) → 채널 월유량 + 저수지 월 만수대비% dict|None.

    reservoirs: {gis_id: ReservoirForecastParams} — 해당 gid 는 채널 유량 대신
    reservoir_day.txt 물수지 만수대비% 를 산출(저수지 수원). 없으면 {}.
    daily_store: True 면 ``_daily`` 키에 수원별 일배열을 함께 담아 돌려준다
    (초기수위 변경 시 SWAT+ 재실행을 없애는 자료 — daily_store 모듈 docstring 참조).
    SWAT+ 가 일단위 출력을 쓰지 않는 프로젝트에서는 담을 것이 없어 자동으로 빈다."""
    (member_csv, base_dir, exe_name, fyear, months, outlets, era5_warmup,
     reservoirs, daily_store) = args
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
        #  멤버당 6.6MB 복사가 불필요하다. SWAT+ 는 입력을 cwd 에서 읽으므로
        #  실행파일 위치는 달라도 된다.
        #  ※ 2026-10-18 정정: 한때 관측된 [WinError 2] 다발(1,000멤버 중 13~18% 실패)을
        #    백신의 실행파일 검사 탓으로 적어 두었으나, 실제 원인은 **같은 프로젝트의
        #    run_all_periods 중복 실행**이었다(공유 base 를 서로 지움). 단일 실행에서는
        #    팔라우 6기간 전부 1000/1000 성공했다. 백신 가설은 근거가 없다.
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
        # ── 0차: 일단위 채널 유량 — **파일을 한 번만** 읽는다 ──────────────────
        #  channel_sd_day.txt 는 멤버당 5.6MB(팔라우 34채널×365일)다. 수원마다 다시
        #  읽으면 파싱이 SWAT+ 실행시간(1.0s)을 넘어선다. 필요한 채널을 모아 한 번에.
        #  (일단위 출력이 꺼진 프로젝트(쿡)에서는 파일이 없어 빈 dict → 기존 거동 유지.)
        from swat_py.output.reader_swat_plus import parse_channel_sd_day_multi
        need_gids = set()
        for gid, _nm in outlets.items():
            if gid in reservoirs:
                src = getattr(reservoirs[gid], "diversion_from_outlet", None)
                if src:
                    need_gids.add(int(src))
            elif daily_store:
                need_gids.add(int(gid))         # 하천 수원의 일유량(일수 기준 단계용)
        chan_day = (parse_channel_sd_day_multi(run / "channel_sd_day.txt",
                                               sorted(need_gids), f"{fyear}-01-01")
                    if need_gids else {})
        q_day: Dict[int, pd.Series] = {}
        for g, dfc in chan_day.items():
            if dfc is None or dfc.empty or "flo_out" not in dfc:
                continue
            q_day[int(g)] = pd.Series(
                pd.to_numeric(dfc["flo_out"], errors="coerce").fillna(0.0).values,
                index=pd.to_datetime(dfc["date"]).values)
        daily_out: Dict[str, Dict] = {}         # 수원 이름 → 일배열(저장용)

        # ── 1차: 저수지 수원 ──────────────────────────────────────────────
        #  reservoir_day.txt 물수지 → 월 만수대비% + 월말 저수위(ft).
        #  전환유입을 쓰는 저수지는 **그 달에 실제 가져간 물**을 수원 채널별로 모아 둔다.
        from swat_py.drought.reservoir_forecast import (
            member_reservoir_full, subtract_diversion,
        )
        diverted: Dict[int, Dict[int, float]] = {}      # 수원 채널 gid → {월: m³}
        for gid, name in outlets.items():
            if gid not in reservoirs:
                continue
            params = reservoirs[gid]
            src_gid = getattr(params, "diversion_from_outlet", None)
            full = member_reservoir_full(
                run, params, fyear=fyear, months=months, sdate=f"{fyear}-01-01",
                src_q=q_day.get(int(src_gid)) if src_gid else None)
            ser = (full or {}).get("monthly")
            if not ser:
                continue
            res[name] = {m: v["storage_pct"] for m, v in ser.items()}
            res.setdefault("_wlevel", {})[name] = {
                m: v["water_level_ft"] for m, v in ser.items()}
            if daily_store:
                # 초기수위와 무관한 강제력 2개만 — 멤버당 728B(원시 보관은 11.8MB).
                daily_out[name] = {"dates": full["dates"],
                                   "res_net_m3": full["res_net_m3"],
                                   "src_q_m3s": full["src_q_m3s"]}
            if src_gid:
                acc = diverted.setdefault(int(src_gid), {})
                for m, v in ser.items():
                    acc[m] = acc.get(m, 0.0) + float(v.get("diversion_m3", 0.0) or 0.0)

        # ── 2차: 채널 수원 ────────────────────────────────────────────────
        #  월단위 출력(channel_sd_mon.txt), 각 행=월평균 flo_out.
        #  ★ 저수지로 전환해 간 물은 하천에 남아 있지 않다 — 빼지 않으면 같은 물을
        #    두 번 세게 된다(제니토스 2026-10-20 §4-다). 1차에서 모은 실제 전환량을 뺀다.
        month_year = {m: y for y, m in ym}
        for gid, name in outlets.items():
            if gid in reservoirs:
                continue
            df = parse_channel_sd_day(run / "channel_sd_mon.txt", outlet=gid,
                                      sdate=f"{fyear}-01-01")
            if df is None:
                continue
            df = df[in_ym(df["date"], ym).values]   # 연도별 월 — 해를 넘는 계절 포함
            mon = df.groupby(df["date"].dt.month)["flo_out"].mean()
            vals = {int(m): float(v) for m, v in mon.items()}
            if gid in diverted:
                vals = subtract_diversion(vals, diverted[gid], month_year)
            res[name] = vals
            if daily_store and int(gid) in q_day:
                # 하천 일유량(원시) — 전환분을 빼지 않은 값이다. 전환량은 초기수위에
                # 따라 달라지므로, 뺄 양은 통계 단계에서 같은 물수지로 다시 구한다.
                qs = q_day[int(gid)]
                sel = in_ym(pd.Series(qs.index), ym).values
                if sel.any():
                    daily_out[name] = {
                        "dates": pd.DatetimeIndex(qs.index[sel]).normalize()
                                   .values.astype("datetime64[D]"),
                        "q_m3s": np.asarray(qs.values[sel], dtype="float32")}
        if daily_out:
            res["_daily"] = daily_out
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_ensemble(base_dir: Path, ensemble_dir: Path, *, fyear: int, months: List[int],
                 exe_name: str = "SWAT-Plus.exe", n_members: int = 100,
                 n_workers: int = 6, outlets: Dict[int, str] = None,
                 station: str = "918430", era5_warmup: Dict = None,
                 reservoirs: Dict = None, daily_store: bool = True) -> tuple:
    """멤버 폴더들 → (values, aux).

    반환:
      values : {name: DataFrame[member × month]} — 하천=월유량(m³/s), 저수지=만수대비%.
      aux    : {"weather": {var: DataFrame[member × month]},   # var: precip_mm/tmax_c/tmin_c
                "wlevel":  {name: DataFrame[member × month]},   # 저수지 월말 저수위(ft)
                "daily":   {name: {"members": [...], "dates": (D,),
                                   변수: (M, D) float32}}}      # 일단위 강제력
      ``daily`` 는 SWAT+ 가 일단위 출력을 쓴 수원에만 생긴다(쿡처럼 꺼져 있으면 빈 dict).

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
              outlets, era5_warmup, reservoirs, bool(daily_store))
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
    # 일단위 강제력 — 수원별로 (멤버 × 일) 2차원 배열로 쌓는다.
    #  멤버마다 일수가 어긋나면(출력창이 다른 멤버) 가장 흔한 길이만 남긴다 —
    #  길이가 섞인 배열을 만들면 조용히 잘못 정렬되어 추적이 어렵다.
    daily: Dict[str, Dict] = {}
    if daily_store:
        from swat_py.drought.daily_store import common_members, stack_members
        per_src: Dict[str, Dict[str, Dict]] = {}
        dates_of: Dict[str, object] = {}
        for r in records:
            for nm, d in (r.get("_daily") or {}).items():
                per_src.setdefault(nm, {})[r["_member"]] = d
                dates_of.setdefault(nm, d["dates"])
        for nm, per_mem in per_src.items():
            names = sorted(per_mem)
            dts = dates_of[nm]
            varnames = [k for k in ("res_net_m3", "src_q_m3s", "q_m3s")
                        if any(v.get(k) is not None for v in per_mem.values())]
            if not varnames:
                continue
            keep = common_members(per_mem, varnames[0], names, len(dts))
            arrs = {k: stack_members(per_mem, k, keep) for k in varnames}
            arrs = {k: v for k, v in arrs.items() if v is not None}
            if not arrs:
                continue
            daily[nm] = {"members": keep, "dates": dts, **arrs}
            print(f"  일단위 수집 [{nm}] {len(keep)}멤버 × {len(dts)}일 "
                  f"× {len(arrs)}변수 ({sum(a.nbytes for a in arrs.values())/2**20:.2f}MB)")
    print(f"  앙상블 유효 멤버 {len(records)}/{len(tasks)}")
    if fails:
        # 사유별로 묶어 보여 준다(많은 순). 멤버 이름은 앞 3개만.
        print(f"  ⚠ 실패 멤버 {n_fail}개 — 사유별:")
        for why, who in sorted(fails.items(), key=lambda kv: -len(kv[1]))[:5]:
            head = ", ".join(sorted(who)[:3])
            more = f" 외 {len(who) - 3}개" if len(who) > 3 else ""
            print(f"      [{len(who):>4}] {why}  ({head}{more})")
    return out, {"weather": weather, "wlevel": wlevel, "daily": daily}
