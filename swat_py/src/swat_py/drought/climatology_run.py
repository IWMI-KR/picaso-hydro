"""장기 기후 SWAT+ 재실행 — 대시보드 ①평년·임계값용 채널 **월유량** 생산.

검보정 완료 master(`CalibratedDir`; 지역화 포함 최적 파라미터 baked-in)를 그대로 복사하고,
기상은 stations-acidwg.csv(장기기록) 단일 관측소로 전 유역 재배정한 뒤 time.sim 을
drought.syear~eyear(= acidwg observation, 웜업 `CioNYSKIP` 제외 후 출력)로 확장해 1회 실행한다.
시간 절약을 위해 SWAT+ print.prt 를 **월단위(channel_sd_mon.txt)** 로만 출력하도록 설정하여
대용량 일자료(channel_sd_day.txt ~수백MB)를 만들지 않는다. drought.outlets 채널 유량을
`4_drought_risk/climatology/` 에 2종 저장:
  - channel_monthly_{tag}.csv      (월유량 시계열, wide: date + 채널)
  - channel_monthly_avg_{tag}.csv  (월 평년 1~12)
  (tag = climatology_tag(cfg) = {syear+warmup}_{eyear})

가뭄단계 경계(fdc_exceedance Q70/Q90/Q95 = stage_thresholds)는 예보와 동일한 **월유량 분포**
에서 산정되므로 월단위 자료로 충분하다. (일유량 유황 대표유량 Q95d·Q355d 등 day-count
참고값만 미제공.)

경로는 모두 `cfg.PrjDir`(project.root) 기준으로 산출되어 OS·설치 위치에 무관하다.

실행: python -m swat_py.drought.climatology_run [--config config/swat_py.yaml]
프로그램: from swat_py.drought.climatology_run import run_climatology; run_climatology(cfg)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from swat_py.drought.climatology import climatology_tag
from swat_py.drought.ensemble_flow import OUTLETS
from swat_py.io.station import load_station_csv
from swat_py.io.weather_swat_plus import write_cli_index
from swat_py.output.reader_swat_plus import _detect_colnames


def to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """일유량 → 월 평균 시계열 (연·월별). wide: date(월초) + outlet열."""
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    cols = [c for c in d.columns if c != "date"]
    d["ym"] = d["date"].dt.to_period("M")
    m = d.groupby("ym")[cols].mean().reset_index()
    m["date"] = m["ym"].dt.to_timestamp()
    return m[["date", *cols]]


def to_monthly_avg(daily: pd.DataFrame) -> pd.DataFrame:
    """일유량 → 월 평년 (1~12월, 연·월 평균 후 다년 평균). wide: month + outlet열."""
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    cols = [c for c in d.columns if c != "date"]
    d["year"] = d["date"].dt.year
    d["month"] = d["date"].dt.month
    ym = d.groupby(["year", "month"])[cols].mean().reset_index()
    return ym.groupby("month")[cols].mean().reset_index()


def extract_all_outlets(cha_path: Path, outlets: dict, out_first: str) -> pd.DataFrame:
    """channel_sd_day.txt 를 **1회만** 읽어 전 outlet 일유량(flo_out) wide 추출.

    outlet 마다(12회) 1.2GB 파일을 통째로 재파싱하는 대신, 필요한 5개 열
    (gis_id/yr/mon/day/flo_out)만 순수 파이썬 스트리밍으로 1회 읽고 대상 채널만 필터해
    date×outlet wide 로 피벗한다(저메모리·고속).
    """
    cols = _detect_colnames(cha_path)
    lc = [c.lower() for c in cols]
    gi, yi, mi, di, fi = (lc.index(k) for k in ("gis_id", "yr", "mon", "day", "flo_out"))
    targets = {int(k) for k in outlets}
    fmax = max(gi, yi, mi, di, fi)
    recs = []
    with open(cha_path, "r", encoding="utf-8", errors="replace") as fh:
        for _ in range(3):                     # 헤더 3줄 skip (데이터는 4행부터)
            fh.readline()
        for line in fh:
            p = line.split()
            if len(p) <= fmax:
                continue
            try:
                g = int(p[gi])
            except ValueError:
                continue
            if g not in targets:
                continue
            recs.append((int(p[yi]), int(p[mi]), int(p[di]), g, float(p[fi])))
    out = pd.DataFrame(recs, columns=["yr", "mon", "day", "gid", "flo"])
    out["date"] = pd.to_datetime(
        dict(year=out["yr"], month=out["mon"], day=out["day"]))
    wide = out.pivot_table(index="date", columns="gid", values="flo", aggfunc="first")
    wide = wide.rename(columns=dict(outlets)).reset_index()
    wide = wide[wide["date"] >= pd.Timestamp(out_first)].sort_values("date").reset_index(drop=True)
    ordered = ["date"] + [name for gid, name in outlets.items() if name in wide.columns]
    return wide[ordered]


# ── master 기상파일 해석 ──────────────────────────────────────────────────────

#: SWAT+ 관측 기상 확장자 5종 (weather-sta.cli 가 참조하는 순서)
WEATHER_EXTS = ("pcp", "tmp", "slr", "hmd", "wnd")


def _weather_set_ok(work: Path, prefix: str) -> bool:
    """``{prefix}.{pcp,tmp,slr,hmd,wnd}`` 5종이 모두 존재하고 **비어 있지 않은가**.

    크기 0 파일을 정상으로 보면 SWAT+ 가 조용히 기상발생기(wgn)로 대체해
    관측이 아닌 합성 날씨로 모의하게 되므로 반드시 크기까지 확인한다.
    """
    return all((work / f"{prefix}.{e}").is_file()
               and (work / f"{prefix}.{e}").stat().st_size > 0
               for e in WEATHER_EXTS)


def _pcp_lonlat(path: Path):
    """SWAT+ ``.pcp`` 헤더 3행(nbyr tstep lat lon elev)에서 (lon, lat). 실패 시 None."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for _ in range(2):
                fh.readline()
            t = fh.readline().split()
        return float(t[3]), float(t[2])
    except Exception:
        return None


def resolve_master_weather_prefix(work: Path, station: str,
                                  lon=None, lat=None) -> str:
    """작업본(master 복사본)에서 실제로 사용할 기상파일 **접두어**를 찾는다.

    ``stations-acidwg.csv`` 의 관측소 ID 와 SWAT+ master 안의 기상파일 이름이
    서로 다른 체계일 수 있다(예: NOAA 11자리 ``91408040310`` vs SWAT 6자리 ``914080``).
    이름이 어긋나면 SWAT+ 는 없는 파일을 빈 파일로 만들고 wgn 으로 대체해버려
    **오류 없이 잘못된 결과**를 낸다. 그래서 여기서 미리 해석한다.

    해석 순서
    ---------
    1. ``station`` 이름 그대로 5종이 모두 존재 → 그대로 사용
    2. 부분 일치 — 한쪽이 다른 쪽의 접두어인 후보 (짧은 이름 우선)
    3. 위경도 최근접 — ``.pcp`` 헤더 좌표가 ``lon``/``lat`` 과 0.05도 이내
    4. 모두 실패 → :class:`FileNotFoundError` (후보 목록을 함께 안내)
    """
    if _weather_set_ok(work, station):
        return station

    cands = sorted({p.stem for p in work.glob("*.pcp")
                    if _weather_set_ok(work, p.stem)})
    if not cands:
        raise FileNotFoundError(
            f"master 에 사용 가능한 관측 기상파일이 없습니다: {work}\n"
            f"  필요: {{ID}}.{{{','.join(WEATHER_EXTS)}}} 5종(크기 0 아님)")

    # 2) 부분 일치 (짧은 쪽 우선 — 6자리 SWAT ID 가 11자리 NOAA ID 의 접두어인 사례)
    partial = [c for c in cands if c.startswith(station) or station.startswith(c)]
    if partial:
        pick = min(partial, key=len)
        print(f"  [해석] 관측소 '{station}' 기상파일 없음 → 이름 부분일치 '{pick}' 사용")
        return pick

    # 3) 위경도 최근접
    if lon is not None and lat is not None:
        best, best_d = None, None
        for c in cands:
            ll = _pcp_lonlat(work / f"{c}.pcp")
            if ll is None:
                continue
            d = abs(ll[0] - float(lon)) + abs(ll[1] - float(lat))
            if best_d is None or d < best_d:
                best, best_d = c, d
        if best is not None and best_d <= 0.05:
            print(f"  [해석] 관측소 '{station}' 기상파일 없음 → 위경도 최근접 "
                  f"'{best}' 사용 (Δ{best_d:.4f}°)")
            return best

    raise FileNotFoundError(
        f"관측소 '{station}' 의 기상파일을 master 에서 찾지 못했습니다: {work}\n"
        f"  후보: {cands}\n"
        f"  → stations-acidwg.csv 의 ID 를 master 파일명과 맞추거나, "
        f"master 에 {station}.{{{','.join(WEATHER_EXTS)}}} 를 추가하세요.")


def setup_acidwg_weather(cfg, work: Path) -> str:
    """장기 평년 실행 기상 = stations-acidwg.csv(장기기록) 단일 관측소로 전 유역 재배정.

    검보정용 다중 우량계(stations-hydro.csv; 단기 기록)는 장기 실행이 불가하므로, 작업본의
    .cli 인덱스를 장기 관측소만 나열하고 weather-sta.cli 의 전 subbasin 을 그 관측소
    기상파일(.pcp/.tmp/.slr/.hmd/.wnd)로 재배정한다. 해당 관측소 파일은 default 마스터에
    이미 존재하므로 그대로 재사용한다.

    파일명은 :func:`resolve_master_weather_prefix` 로 해석하므로
    ``stations-acidwg.csv`` 의 ID 체계가 master 파일명과 달라도 자동 대응한다
    (예: NOAA 11자리 ``91408040310`` ↔ SWAT 6자리 ``914080``).
    해석·검증에 실패하면 ``FileNotFoundError`` 로 중단한다 — 그대로 진행하면
    SWAT+ 가 빈 파일을 만들고 wgn 으로 대체해 **오류 없이 잘못된 결과**를 내기 때문.

    Returns
    -------
    str : 실제로 사용된 기상파일 접두어(관측소 ID 와 다를 수 있음).
    """
    stns = load_station_csv(Path(cfg.ObsDayDir) / "stations-acidwg.csv", [])  # 전체(=장기 관측소)
    stn = stns[0]
    # master 안의 **실제 기상파일 이름**으로 해석 — ID 체계가 달라도 자동 대응.
    # 해석 실패 시 여기서 중단한다. 그대로 SWAT+ 에 넘기면 없는 파일을 빈 파일로
    # 만들고 wgn(기상발생기)으로 조용히 대체해 오류 없이 잘못된 결과를 낸다.
    station = resolve_master_weather_prefix(
        work, stn.id, lon=getattr(stn, "lon", None), lat=getattr(stn, "lat", None))
    # .cli 인덱스를 단일 관측소만 나열 (SWAT+ 가 단기 우량계 .pcp 를 읽지 않도록)
    for var in ("pcp", "tmp", "wnd", "hmd", "slr"):
        write_cli_index(var, [station], work)
    # weather-sta.cli 전 행을 장기 관측소 기상으로 재배정 (wgn 열은 유지)
    p = work / "weather-sta.cli"
    lines = p.read_text(encoding="utf-8").splitlines()
    out = lines[:2]
    for ln in lines[2:]:
        t = ln.split()
        if len(t) < 7:
            out.append(ln)
            continue
        t[2], t[3], t[4] = f"{station}.pcp", f"{station}.tmp", f"{station}.slr"
        t[5], t[6] = f"{station}.hmd", f"{station}.wnd"
        out.append(f"{t[0]:<28}{t[1]:<24}" + "".join(f"{x:<27}" for x in t[2:7])
                   + f"{'null':<10}null")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")

    # 사후 검증 — 재작성한 참조가 실제 파일(크기 0 아님)로 해석되는지 확인.
    if not _weather_set_ok(work, station):
        raise FileNotFoundError(
            f"기상 재배정 후 파일 확인 실패: {station}.* (work={work})\n"
            f"  SWAT+ 가 빈 파일을 wgn 으로 대체해 잘못된 결과를 낼 수 있어 중단합니다.")
    return station


def run_climatology(cfg, *, workdir: Optional[Path] = None,
                    timeout: int = 7200) -> Dict[str, str]:
    """장기 기후 SWAT+ 를 1회 실행하고 채널 **월유량** 2종 CSV(월/월평년)를 저장한다.

    반환: {"monthly": ..., "monthly_avg": ..., "n_outlets": N} 경로 dict.
    """
    prj = Path(cfg.PrjDir)
    master_dir = Path(cfg.CalibratedDir)      # 검보정 완료 master(지역화 baked-in)
    # ★ SWAT 구동은 로컬 임시(예: /tmp, C:\Temp)에서 — 프로젝트 루트가 네트워크 공유일 때 정체 가능.
    #   print.prt 를 월단위 출력으로 제한해 대용량 일자료(channel_sd_day.txt)를 아예 만들지 않는다.
    work = (Path(workdir) if workdir
            else Path(tempfile.gettempdir()) / "picaso_clim_run" / "TxtInOut")
    out_dir = prj / "4_drought_risk" / "climatology"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 기간 — drought.syear/eyear(= acidwg observation). 웜업(CioNYSKIP) 제외 후 출력.
    dc = cfg.Drought
    warmup = int(cfg.CioNYSKIP)
    syear = dc.syear or (dc.climatology_years[0] if dc.climatology_years else 2003)
    eyear = dc.eyear or (dc.climatology_years[-1] if dc.climatology_years else 2024)
    out_first = f"{syear + warmup}-01-01"      # 웜업 제외 후 출력 시작
    tag = climatology_tag(cfg)                  # 파일명 태그 = {syear+warmup}_{eyear}

    if work.parent.exists():
        shutil.rmtree(work.parent)
    print(f"[1/5] calibrated master 복사 → {work}")
    shutil.copytree(master_dir, work)

    stn = setup_acidwg_weather(cfg, work)
    print(f"[2/5] 기상 재배정 → stations-acidwg.csv({stn}) 단일 관측소")

    # time.sim 확장
    ts = work / "time.sim"
    lines = ts.read_text().splitlines()
    lines[2] = f"       1      {syear}       366      {eyear}         0"
    ts.write_text("\n".join(lines) + "\n")
    print(f"[3/5] time.sim → {syear}–{eyear} (웜업 {warmup}년 → 출력 {out_first}~)")

    # print.prt: 채널을 월단위(mon)로만 출력, 그 외 객체 출력 off → 대용량 일자료 미생산(시간 절약).
    pp = work / "print.prt"
    pl = pp.read_text().splitlines()
    if len(pl) >= 3 and pl[2].split():
        toks = pl[2].split()
        toks[0] = str(warmup)                       # nyskip 동기화(웜업 제외)
        pl[2] = "  ".join(toks)
    try:
        hdr = next(i for i, ln in enumerate(pl) if ln.split()[:1] == ["objects"])
        for i in range(hdr + 1, len(pl)):
            t = pl[i].split()
            if len(t) < 5:
                continue
            mon = "y" if t[0] == "channel_sd" else "n"
            pl[i] = f"{t[0]:<28} n             {mon}             n             n"
    except StopIteration:
        pass
    pp.write_text("\n".join(pl) + "\n")

    # 실행파일: OS 자동 대응 + 미발견 시 자동 다운로드(공식 Releases → calibrated·default).
    from swat_py.runner.file_manager import resolve_swat_exe
    exe_src = resolve_swat_exe(cfg.Executable, master_dir,
                               fetch_dirs=[cfg.CalibratedDir, cfg.DefaultDir])
    exe = work / exe_src.name                   # 해석된 실제 바이너리 이름 사용
    if not exe.is_file():
        shutil.copyfile(exe_src, exe)           # copyfile: 마운트 EPERM 회피(메타데이터 복사 안 함)
        try:
            exe.chmod(0o755)                    # 실행 권한(best-effort)
        except OSError:
            pass
    print("[4/5] SWAT+ 실행 … (장기, 수 분)")
    # ★ stdout 은 파이프(capture_output) 대신 로그파일로 리디렉션 — SWAT 가 수십년치
    #   진행메시지를 파이프에 쓰다 버퍼(~64KB)가 차면 블록되고, run() 은 종료 후에야
    #   파이프를 읽어 상호 교착(deadlock)이 발생하기 때문.
    swat_log = work / "swat_run.log"
    with swat_log.open("w", encoding="utf-8", errors="replace") as _fh:
        r = subprocess.run([str(exe)], cwd=str(work), stdout=_fh,
                           stderr=subprocess.STDOUT, timeout=timeout)
    if r.returncode != 0:
        sys.stderr.write(swat_log.read_text(encoding="utf-8", errors="replace")[-1500:])
        raise SystemExit(f"SWAT 실행 실패 rc={r.returncode} (log: {swat_log})")

    # 채널 추출 — 월단위 파일(channel_sd_mon.txt). outlet 매핑은 drought.outlets(없으면 기본 12).
    outlets = {int(k): v for k, v in (dict(dc.outlets) or OUTLETS).items()}
    print(f"[5/5] channel_sd_mon.txt → {len(outlets)}채널 추출 (월단위, drought.outlets 매핑)")
    merged = extract_all_outlets(work / "channel_sd_mon.txt", outlets, out_first)
    for name in [c for c in merged.columns if c != "date"]:
        s = merged[["date", name]].dropna()
        print(f"  {name:<12s} n={len(s)} {s['date'].min().date()}~{s['date'].max().date()}")

    # 결과 2종 저장(일자료 미생산). merged 는 이미 월단위 → to_monthly 는 월초 정규화(멱등).
    monthly = to_monthly(merged)
    monthly_csv = out_dir / f"channel_monthly_{tag}.csv"
    monthly.to_csv(monthly_csv, index=False, encoding="utf-8-sig")
    mavg = to_monthly_avg(merged)
    mavg_csv = out_dir / f"channel_monthly_avg_{tag}.csv"
    mavg.to_csv(mavg_csv, index=False, encoding="utf-8-sig")

    print("\n저장:")
    print(f"  monthly      : {monthly_csv}  shape={monthly.shape}")
    print(f"  monthly_avg  : {mavg_csv}  shape={mavg.shape}")
    return {"monthly": str(monthly_csv), "monthly_avg": str(mavg_csv),
            "n_outlets": len(outlets)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swat_py.drought.climatology_run",
                                 description="장기 기후 SWAT+ 재실행 → ①평년·④FDC 채널유량")
    ap.add_argument("--config", default="config/swat_py.yaml",
                    help="swat_py 설정 (같은 폴더의 picaso-hydro.yaml 공통값 자동 병합)")
    ap.add_argument("--workdir", default=None,
                    help="SWAT 구동 임시폴더(기본: 시스템 임시)")
    ap.add_argument("--timeout", type=int, default=7200, help="SWAT 실행 제한(초)")
    args = ap.parse_args(argv)
    from swat_py.config import load_config
    cfg = load_config(args.config)
    run_climatology(cfg, workdir=Path(args.workdir) if args.workdir else None,
                    timeout=args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
