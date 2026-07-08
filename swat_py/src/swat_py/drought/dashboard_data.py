"""가뭄위험 대시보드 데이터 오케스트레이션 (outlet × ①~⑤) → 4_drought_risk/forecast/{period}.

단계
  0. base 준비: calibrated(검보정 완료·지역화 포함) + time.sim(예측기간, 관측 선행) → 앙상블용
  1. ① 평년 + ④ FDC : 장기 기후 CSV(channel_daily_YYYY.csv)
  2. ② 관측/모의    : 장기 기후 CSV의 예측 직전월(예 2016 Jan–Mar) 모의(관측기상)
  3. ③⑤ 예측 앙상블 : ensemble_flow.run_ensemble → 수원별 [member×month]
       → SWAT+ 결과는 3_swatplus/forecast/{period}/{outlet}.csv 로 수원별 저장
         (하천: precip_mm,tmax_c,tmin_c,flo_m3s / 저수지: …,water_level_ft,storage_pct)
       → 평균/분위·단계확률은 4_drought_risk/forecast/{period}/{outlet}/ 로 저장
  4. outlet별 series.csv/thresholds.csv/stage_prob.csv/dashboard.json + summary.csv 저장

CLI: python -m swat_py.drought.dashboard_data [--forecast 2016_AMJ] [--members 100] [--demo N]
     인자 생략 시 config(picaso-hydro.yaml→swat_py.yaml)의 forecast.period·ensemble.n_members 사용.
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from swat_py.dashboard.json_writers import dumps_json   # NaN→null 표준 JSON
from swat_py.drought.climatology import (
    climatology_daily_path, load_daily_flow, outlet_climatology_and_thresholds,
)
from swat_py.drought.fdc import stage_thresholds
from swat_py.drought.ensemble_flow import OUTLETS, run_ensemble
from swat_py.drought.stages import stage_probabilities4

SEASON_MONTHS = {"JFM": [1, 2, 3], "FMA": [2, 3, 4], "MAM": [3, 4, 5], "AMJ": [4, 5, 6],
                 "MJJ": [5, 6, 7], "JJA": [6, 7, 8], "JAS": [7, 8, 9], "ASO": [8, 9, 10],
                 "SON": [9, 10, 11], "OND": [10, 11, 12], "NDJ": [11, 12, 1], "DJF": [12, 1, 2]}
QLEVELS = [0.05, 0.25, 0.50, 0.75, 0.95]


def _forecast_station(cfg) -> str:
    """obs_weather_std/stations-acidwg.csv 의 (주) 스테이션 ID — 예측 상세화 기준."""
    csv = Path(cfg.ObsDayDir) / "stations-acidwg.csv"
    df = pd.read_csv(csv)
    idcol = "ID" if "ID" in df.columns else df.columns[min(3, df.shape[1] - 1)]
    return str(df[idcol].iloc[0])


def _member_dir(cfg, fyear: int, season: str) -> Path:
    """예측 연·계절의 앙상블 멤버 폴더 — 통합 forecast 레이아웃.

    acidwg 는 hindcast·operational 모드와 무관하게 1_acidwg/forecast/{year}_{season}/ 아래에
    member_XXXX 를 둔다. (구 hindcast/{year}/{season}·operational/{year}/{season} 은 하위호환 폴백.)
    실제 멤버가 있는 폴더를 자동 선택한다.
    """
    dc = getattr(cfg, "Drought", None)
    base = Path(cfg.PrjDir) / "1_acidwg"
    key = f"{fyear}_{season}"
    cands = []
    if dc and dc.ensemble_root:                       # 설정 우선(있으면)
        cands.append(Path(dc.ensemble_root) / key)
    cands.append(base / "forecast" / key)             # 통합 레이아웃(기본)
    cands += [base / "hindcast" / str(fyear) / season,   # 구 레이아웃(폴백)
              base / "operational" / str(fyear) / season]
    for d in cands:
        if d.is_dir() and any(d.glob("member_*")):
            return d
    return base / "forecast" / key                    # 기본: 통합 forecast


def prepare_base(cfg, base_dir: Path, fyear: int, months: List[int]) -> str:
    """calibrated(검보정 완료·지역화 포함, 파라미터 baked-in) 복사 + time.sim(웜업 선행 ~
    예측끝월) → 예측 앙상블 base TxtInOut. default+수동적용이 아닌 calibrated 를 그대로 사용."""
    if base_dir.parent.exists():
        # Windows: 삭제지연/읽기전용 대응 — 오류 무시 후 소멸 대기
        shutil.rmtree(base_dir.parent, ignore_errors=True)
        for _ in range(25):
            if not base_dir.parent.exists():
                break
            time.sleep(0.2)
    shutil.copytree(Path(cfg.CalibratedDir), base_dir)
    nyskip = int(cfg.CioNYSKIP)                   # 마스터 warm_up_years (단일 관리)
    start_yr = fyear - nyskip                      # 웜업 nyskip년 → 출력 fyear
    last = pd.Timestamp(fyear, months[-1], 1) + pd.offsets.MonthEnd(0)
    ts = base_dir / "time.sim"
    lines = ts.read_text().splitlines()
    lines[2] = f"       1      {start_yr}       {last.dayofyear}      {fyear}         0"
    ts.write_text("\n".join(lines) + "\n")
    # print.prt: nyskip 동기화 + 채널을 월단위(mon)로만 출력, 그 외 객체 출력 전부 off.
    #   예측은 월유량(채널)만 필요 → 일단위 대용량 출력(90채널×일 + HRU·hyd 등) 제거로 대폭 가속.
    pp = base_dir / "print.prt"
    pl = pp.read_text().splitlines()
    if len(pl) >= 3 and pl[2].split():
        toks = pl[2].split()
        toks[0] = str(nyskip)
        pl[2] = "  ".join(toks)
    # 저수지 수원이 있으면 reservoir 일단위 출력 필요(reservoir_day.txt → 만수대비% 물수지).
    _res_needed = bool([s for s in getattr(getattr(cfg, "Drought", None), "sources", []) or []
                        if getattr(s, "type", "") == "reservoir"])
    try:
        hdr = next(i for i, l in enumerate(pl) if l.split()[:1] == ["objects"])
        for i in range(hdr + 1, len(pl)):
            t = pl[i].split()
            if len(t) < 5:
                continue
            if t[0] == "channel_sd":
                pl[i] = f"{t[0]:<28} n             y             n             n"  # 월유량
            elif t[0] == "reservoir" and _res_needed:
                pl[i] = f"{t[0]:<28} y             n             n             n"  # 일 저수량
            else:
                pl[i] = f"{t[0]:<28} n             n             n             n"
    except StopIteration:
        pass
    pp.write_text("\n".join(pl) + "\n")
    # 실행파일: OS 자동 대응 + 미발견 시 자동 다운로드(공식 Releases → default·calibrated).
    from swat_py.runner.file_manager import resolve_swat_exe
    exe_src = resolve_swat_exe(cfg.Executable, cfg.DefaultDir,
                               fetch_dirs=[cfg.DefaultDir, cfg.CalibratedDir])
    exe = base_dir / exe_src.name               # 해석된 실제 바이너리 이름 사용
    if not exe.is_file():
        shutil.copyfile(exe_src, exe)           # copyfile: 마운트 EPERM 회피
        try:
            exe.chmod(0o755)                    # 실행 권한(best-effort)
        except OSError:
            pass
    return exe_src.name


def _observed_monthly(daily: pd.DataFrame, outlet: str, fyear: int,
                      obs_months: List[int]) -> Dict[int, float]:
    """예측 직전월(관측기상 모의) 월평균 유량."""
    s = daily[["date", outlet]].copy()
    s = s[(s["date"].dt.year == fyear) & (s["date"].dt.month.isin(obs_months))]
    return {int(m): float(v) for m, v in s.groupby(s["date"].dt.month)[outlet].mean().items()}


def _seasonal_stage_row(mem, months, q185, q275, q355, season):
    """앙상블 멤버별 **3개월 평균값**(저수지=평균 저수량%, 하천=평균 유출량)을 산정해
    단계 분류 → 계절 전체 단계확률 1행 반환(월별 대신 계절 단일 리스크).

    각 멤버의 예측월 평균을 먼저 구한 뒤 임계와 비교하므로, 월별 확률의 평균이 아니라
    '계절 평균 상태'의 확률 분포를 준다. mem 없음/자료 없음 시 None.
    """
    if mem is None:
        return None
    cols = [m for m in months if m in mem.columns]
    if not cols:
        return None
    season_vals = mem[cols].mean(axis=1).dropna()      # 멤버별 3개월 평균
    if not len(season_vals):
        return None
    sp = stage_probabilities4(season_vals.values, q185, q275, q355)
    return {"season": season, **sp}


def build(cfg, forecast: str, *, n_members: int = 100, n_workers: int = 6) -> Dict:
    fyear = int(forecast.split("_")[0]); season = forecast.split("_")[1]
    months = SEASON_MONTHS[season]
    obs_months = [m for m in range(1, months[0]) if m >= 1] or []   # 예측 시작 이전월(동일 연도)
    dc = getattr(cfg, "Drought", None)
    outlets = (dict(dc.outlets) if dc and dc.outlets else OUTLETS)
    station = (dc.forecast_station if (dc and dc.forecast_station)
               else _forecast_station(cfg))
    root = Path(cfg.PrjDir) / "4_drought_risk"
    # 파일명 자동 산출(하드코딩 없음): {syear+warmup}_{eyear}. climatology_csv 명시 시 우선.
    clim_csv = climatology_daily_path(cfg)
    member_dir = _member_dir(cfg, fyear, season)   # hindcast 또는 operational 자동 선택
    # 저수지 초기조건 시나리오 태그(예 __ic44.0ft-scn) — 출력 폴더에만 적용해 동일 연월/
    # 계절의 초기조건별 결과를 구분(입력·멤버·평년 경로는 실제 연월 기준 그대로).
    fc_suffix = dc.forecast_suffix() if dc else ""
    period_label = f"{forecast}{fc_suffix}"
    out_root = root / "forecast" / period_label     # 4_drought_risk/forecast/{period[+ic]}
    out_root.mkdir(parents=True, exist_ok=True)
    daily = load_daily_flow(clim_csv)

    # ── 예측 앙상블 (③⑤) ──
    # base·멤버 실행은 로컬(C:) — 프로젝트 루트(I:)는 네트워크 공유라 N멤버가 각자
    # base 를 네트워크에서 복사하면 극심히 느리다. 결과 CSV(소용량)만 I: 에 저장.
    base = Path(tempfile.gettempdir()) / "picaso_ens_base" / "TxtInOut"
    print(f"[base] 예측 앙상블용 모델 준비 (fyear={fyear}, months={months})")
    exe_name = prepare_base(cfg, base, fyear, months)   # 해석/다운로드된 실행파일 이름
    print(f"[ensemble] {n_members} 멤버 SWAT+ 실행")
    print(f"[ensemble] 멤버 폴더: {member_dir}")
    # (선택) warm-up 을 최근접 ERA5 격자로 재구성 — 운영 예보용(drought.era5_warmup=true).
    era5_warmup = None
    if dc and getattr(dc, "era5_warmup", False):
        era5_root = Path(cfg.PrjDir) / "0_database" / "era5"
        era5_warmup = {"grid_points_csv": str(era5_root / "grid_points-era5.csv"),
                       "grid_daily_std_dir": str(era5_root / "grid_daily_std"),
                       "warmup_years": int(cfg.CioNYSKIP)}
        print(f"[ensemble] warm-up = 최근접 ERA5 격자 ({era5_warmup['grid_daily_std_dir']})")
    # 저수지 수원 예측 매개변수 준비 — 해당 gid 는 채널 유량 대신 reservoir_day 물수지 만수대비%.
    reservoirs_params: Dict = {}
    res_name_gid: Dict[str, int] = {}
    if dc and getattr(dc, "sources", None):
        from swat_py.drought.reservoir_forecast import build_reservoir_forecast_params
        from swat_py.io.reservoir import load_stage_storage
        for s in dc.sources:
            if s.type != "reservoir":
                continue
            rcfg = (getattr(cfg, "Reservoirs", {}) or {}).get(s.reservoir)
            if not (rcfg and rcfg.stage_storage_file):
                print(f"[WARN] 저수지 수원 '{s.name}' — reservoirs 레지스트리/곡선 없음, 건너뜀")
                continue
            try:
                curve = load_stage_storage(rcfg.stage_storage_file, name=s.reservoir)
                for gid, nm in s.outlets.items():
                    reservoirs_params[gid] = build_reservoir_forecast_params(s, rcfg, curve)
                    res_name_gid[nm] = gid
            except Exception as e:
                print(f"[WARN] 저수지 '{s.name}' 예측 매개변수 준비 실패: {e}")

    ens, aux = run_ensemble(base, member_dir,
                       fyear=fyear, months=months, exe_name=exe_name,
                       n_members=n_members, n_workers=n_workers,
                       outlets=outlets, station=station, era5_warmup=era5_warmup,
                       reservoirs=reservoirs_params)

    # SWAT+ 앙상블 예측 결과 → 3_swatplus/forecast/{period[+ic]} 의 수원별 파일.
    #   각 파일 = long format (member×month), 유량/저수량 칼럼 앞에 앙상블 강수·기온.
    #   하천  {outlet}.csv : member,month,precip_mm,tmax_c,tmin_c,flo_m3s
    #   저수지 {outlet}.csv : member,month,precip_mm,tmax_c,tmin_c,water_level_ft,storage_pct
    swat_fc = Path(cfg.PrjDir) / "3_swatplus" / "forecast" / period_label
    swat_fc.mkdir(parents=True, exist_ok=True)
    weather = aux.get("weather", {})     # {var: DataFrame[member×month]}
    wlevel = aux.get("wlevel", {})       # {name: DataFrame[member×month]} (저수지)

    def _cell(df, member, month):
        if df is not None and member in df.index and month in df.columns:
            return float(df.loc[member, month])
        return float("nan")

    n_valid = max((m.shape[0] for m in ens.values()), default=0)
    for name, mem_df in ens.items():
        is_res = name in res_name_gid
        rows = []
        for member, row in mem_df.iterrows():
            for month in mem_df.columns:
                rec = {"member": member, "month": int(month),
                       "precip_mm": _cell(weather.get("precip_mm"), member, month),
                       "tmax_c": _cell(weather.get("tmax_c"), member, month),
                       "tmin_c": _cell(weather.get("tmin_c"), member, month)}
                if is_res:
                    rec["water_level_ft"] = _cell(wlevel.get(name), member, month)
                    rec["storage_pct"] = float(row[month])   # 만수대비 저수량%
                else:
                    rec["flo_m3s"] = float(row[month])
                rows.append(rec)
        cols = ["member", "month", "precip_mm", "tmax_c", "tmin_c"] + (
            ["water_level_ft", "storage_pct"] if is_res else ["flo_m3s"])
        pd.DataFrame(rows, columns=cols).to_csv(
            swat_fc / f"{name}.csv", index=False, encoding="utf-8-sig")
    print(f"[forecast] SWAT+ 앙상블 결과(수원 {len(ens)}종 × 유효멤버 {n_valid}"
          f"/{n_members}) → {swat_fc}")

    summary_rows = []
    season_summary_rows = []            # 계절(3개월 평균) 단일 리스크
    for outlet in outlets.values():
        # ── 저수지 수원: 유량 대신 만수 대비 저수량 %(capacity_fraction) 기반 ──
        res_gid = res_name_gid.get(outlet)
        if res_gid is not None:
            mem = ens.get(outlet)   # [member × month] 만수대비%
            thr_method, thr_values = dc.threshold_for(res_gid)   # capacity_fraction, [100,85,65]
            st = stage_thresholds([], thr_method, thr_values)
            q185, q275, q355 = st["normal_watch"], st["watch_warning"], st["warning_crisis"]
            out_dir = out_root / outlet
            out_dir.mkdir(exist_ok=True)
            # stream(Cook)과 동일 스키마: forecast_mean(=만수대비%) + hist_mean·observed(저수지 없음→NaN)
            series = pd.DataFrame({"month": range(1, 13)})
            series["hist_mean"] = float("nan")
            series["observed"] = float("nan")
            if mem is not None:
                series["forecast_mean"] = series["month"].map(mem.mean(axis=0).to_dict())
                for q in QLEVELS:
                    series[f"p{int(q*100)}"] = series["month"].map(
                        mem.quantile(q, axis=0).to_dict())
                mem.rename_axis("member").to_csv(out_dir / "ensemble_members.csv",
                                                 encoding="utf-8-sig")
            series.to_csv(out_dir / "series.csv", index=False, encoding="utf-8-sig")
            tv = list(thr_values) if thr_values else [None, None, None]
            pd.DataFrame([{"method": thr_method, "variable": "capacity_pct",
                           "nw_input": tv[0], "ww_input": tv[1], "wc_input": tv[2],
                           "n_ensemble": int(mem.shape[0]) if mem is not None else 0,
                           "normal_watch": q185, "watch_warning": q275,
                           "warning_crisis": q355}]
                         ).to_csv(out_dir / "thresholds.csv", index=False,
                                  encoding="utf-8-sig")
            stage_rows = []
            if mem is not None:
                for m in months:
                    if m in mem.columns:
                        sp = stage_probabilities4(mem[m].dropna().values, q185, q275, q355)
                        stage_rows.append({"month": m, **sp})
            pd.DataFrame(stage_rows).to_csv(out_dir / "stage_prob.csv", index=False,
                                            encoding="utf-8-sig")
            # 계절(3개월 평균 저수량%) 단일 단계확률
            season_row = _seasonal_stage_row(mem, months, q185, q275, q355, season)
            if season_row:
                pd.DataFrame([season_row]).to_csv(out_dir / "stage_prob_season.csv",
                                                  index=False, encoding="utf-8-sig")
                season_summary_rows.append({"outlet": outlet, "season": season,
                    "most_likely": season_row["most_likely"], "Normal": season_row["Normal"],
                    "Watch": season_row["Watch"], "Warning": season_row["Warning"],
                    "Crisis": season_row["Crisis"]})
            (out_dir / "dashboard.json").write_text(dumps_json({
                "outlet": outlet, "type": "reservoir", "unit": "capacity_pct",
                "forecast": forecast, "months": months,
                "thresholds": {"normal_watch": q185, "watch_warning": q275,
                               "warning_crisis": q355},
                "series": series.to_dict(orient="list"),   # NaN→null 은 dumps_json 이 처리
                "stages": stage_rows, "season_stage": season_row,
            }, indent=1), encoding="utf-8")
            for sr in stage_rows:
                summary_rows.append({"outlet": outlet, "month": sr["month"],
                                     "most_likely": sr["most_likely"],
                                     "Normal": sr["Normal"], "Watch": sr["Watch"],
                                     "Warning": sr["Warning"], "Crisis": sr["Crisis"]})
            print(f"  ✔ {outlet:<12s} [저수지] 만수대비% 단계="
                  f"{[s['most_likely'] for s in stage_rows]}")
            continue

        if outlet not in daily.columns:
            continue
        ct = outlet_climatology_and_thresholds(daily, outlet)
        thr = ct["thresholds"]     # 참조용 유황유량(Q95/Q185/Q275/Q355)
        # 4단계 경계 — 수원별(outlet별) 설정(method/values). sources 없으면 flat(하위호환).
        if dc is not None:
            thr_method, thr_values = dc.threshold_for(outlet)
        else:
            thr_method, thr_values = "fdc_exceedance", None
        st = stage_thresholds(daily[outlet].dropna().values, thr_method, thr_values)
        q185, q275, q355 = st["normal_watch"], st["watch_warning"], st["warning_crisis"]
        clim = ct["monthly"].set_index("month")

        obs = _observed_monthly(daily, outlet, fyear, obs_months)
        mem = ens.get(outlet)   # DataFrame [member × month]

        # ① 평년(1~12), ② 관측(직전월), ③ 예측 평균+분위(예측월)
        series = pd.DataFrame({"month": range(1, 13)})
        series["hist_mean"] = series["month"].map(clim["mean"])
        series["observed"] = series["month"].map(obs)
        if mem is not None:
            fmean = mem.mean(axis=0)
            series["forecast_mean"] = series["month"].map(fmean.to_dict())
            for q in QLEVELS:
                series[f"p{int(q*100)}"] = series["month"].map(
                    mem.quantile(q, axis=0).to_dict())
        out_dir = out_root / outlet
        out_dir.mkdir(exist_ok=True)
        series.to_csv(out_dir / "series.csv", index=False, encoding="utf-8-sig")
        tv = list(thr_values) if thr_values else [None, None, None]
        n_ens = int(mem.shape[0]) if mem is not None else 0
        pd.DataFrame([{"method": thr_method,
                       "nw_input": tv[0], "ww_input": tv[1], "wc_input": tv[2],
                       "n_ensemble": n_ens,
                       "normal_watch": q185, "watch_warning": q275, "warning_crisis": q355,
                       **{k: thr[k] for k in ("Q95d", "Q185d", "Q275d", "Q355d")}}]
                     ).to_csv(out_dir / "thresholds.csv", index=False, encoding="utf-8-sig")
        # 원시 앙상블 멤버 유량(member×month) 저장 → 재분류 시 SWAT 재실행 불필요
        if mem is not None:
            mem.rename_axis("member").to_csv(out_dir / "ensemble_members.csv",
                                             encoding="utf-8-sig")

        # ⑤ 단계확률 (예측월) — 4단계(Normal/Watch/Warning/Crisis)
        stage_rows = []
        if mem is not None:
            for m in months:
                if m in mem.columns:
                    sp = stage_probabilities4(mem[m].dropna().values, q185, q275, q355)
                    stage_rows.append({"month": m, **sp})
        pd.DataFrame(stage_rows).to_csv(out_dir / "stage_prob.csv", index=False,
                                        encoding="utf-8-sig")
        # 계절(3개월 평균 유출량) 단일 단계확률
        season_row = _seasonal_stage_row(mem, months, q185, q275, q355, season)
        if season_row:
            pd.DataFrame([season_row]).to_csv(out_dir / "stage_prob_season.csv",
                                              index=False, encoding="utf-8-sig")
            season_summary_rows.append({"outlet": outlet, "season": season,
                "most_likely": season_row["most_likely"], "Normal": season_row["Normal"],
                "Watch": season_row["Watch"], "Warning": season_row["Warning"],
                "Crisis": season_row["Crisis"]})

        # dashboard.json
        (out_dir / "dashboard.json").write_text(dumps_json({
            "outlet": outlet, "forecast": forecast, "months": months,
            "thresholds": {"normal_watch": q185, "watch_warning": q275,
                           "warning_crisis": q355},
            "series": series.to_dict(orient="list"),   # NaN→null 은 dumps_json 이 처리
            "stages": stage_rows, "season_stage": season_row,
        }, indent=1), encoding="utf-8")

        for sr in stage_rows:
            summary_rows.append({"outlet": outlet, "month": sr["month"],
                                 "most_likely": sr["most_likely"],
                                 "Normal": sr["Normal"], "Watch": sr["Watch"],
                                 "Warning": sr["Warning"], "Crisis": sr["Crisis"]})
        print(f"  ✔ {outlet:<12s} Q275={q275:.4f} Q355={q355:.4f} "
              f"단계={[s['most_likely'] for s in stage_rows]}")

    pd.DataFrame(summary_rows).to_csv(out_root / "summary.csv", index=False,
                                      encoding="utf-8-sig")
    # 계절(3개월 평균) 단일 리스크 요약
    pd.DataFrame(season_summary_rows).to_csv(out_root / "summary_season.csv",
                                             index=False, encoding="utf-8-sig")
    print(f"\n산출물 → {out_root}")
    return {"out_root": str(out_root), "n_outlets": len(outlets)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swat_py.drought.dashboard_data")
    ap.add_argument("--config", default="config/swat_py.yaml",
                    help="swat_py 설정 (같은 폴더의 picaso-hydro.yaml 공통값 자동 병합)")
    ap.add_argument("--forecast", default=None,
                    help="예측연월 {year}_{season} (기본: config 의 forecast.period)")
    ap.add_argument("--members", type=int, default=None,
                    help="앙상블 수 (기본: config 의 ensemble.n_members)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--demo", type=int, default=0, help=">0 이면 그 수만큼만(검증)")
    args = ap.parse_args(argv)
    from swat_py.config import load_config
    cfg = load_config(args.config)
    dc = getattr(cfg, "Drought", None)

    # 예측연월·앙상블 수 미지정 시 config(picaso-hydro.yaml→swat_py.yaml)에서 폴백.
    forecast = args.forecast or (getattr(dc, "forecast", None) if dc else None)
    if not forecast:
        raise SystemExit(
            "예측연월 미지정 — --forecast 로 주거나 config 의 forecast.period "
            "(picaso-hydro.yaml) 를 설정하세요.")
    members = (args.members if args.members is not None
               else int(getattr(dc, "n_members", 100) if dc else 100))
    n = args.demo if args.demo else members

    print(f"[config] {args.config} → forecast={forecast} "
          f"({'CLI' if args.forecast else 'yaml'}) · members={n} "
          f"({'demo' if args.demo else ('CLI' if args.members is not None else 'yaml')})")
    res = build(cfg, forecast, n_members=n, n_workers=args.workers)
    from swat_py.drought.figure import make_all_figures
    make_all_figures(Path(res["out_root"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
