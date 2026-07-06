"""acidwg 앙상블 상세화(② 일단위 N멤버 weather) — swat_py 오케스트레이션 진입점.

예측 대상(연·계절)·앙상블 수는 공통 config(picaso-hydro.yaml→swat_py.yaml, `cfg.Drought`)
에서 결정하고, 관측기간·경로·WGEN 모델은 acidwg config(acidwg_py.yaml)에서 읽는다.
예측연도가 관측기간 이내(fyear ≤ eyear_obs)면 hindcast(검증), 이후면 operational 로
동작하되, 출력은 모드와 무관하게 `acidwg_root/forecast/{year}_{season}` 통합 폴더에 생성한다.

경로·대상 모두 `cfg`/acidwg config 로부터 산출되어 OS·설치 위치에 무관하다.
통합 파이프라인(`swat_py.drought.run`)이 이 함수를 그대로 호출한다(중복 제거).

실행: python -m swat_py.drought.ensemble_weather [--forecast 2016_AMJ] [--members N]
                                                 [--config config/swat_py.yaml]
                                                 [--acidwg-config config/acidwg_py.yaml]
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Union


def generate_ensemble_weather(cfg, *, forecast: Optional[str] = None,
                              n_members: Optional[int] = None,
                              acidwg_config: Optional[Union[str, Path]] = None) -> Path:
    """acidwg 앙상블 상세화 — 대상·앙상블수는 cfg(마스터), 경로·obs기간은 acidwg config.

    forecast/n_members 미지정 시 `cfg.Drought` 에서 폴백. acidwg_config 미지정 시
    `cfg.PrjDir/config/acidwg_py.yaml`. 반환: 멤버가 생성된 출력 폴더 경로.
    """
    from acidwg_py.config import SEASON_MONTHS
    from acidwg_py.config import load_config as load_acidwg
    from acidwg_py.run import acid_run, acid_run_hindcast

    dc = getattr(cfg, "Drought", None)
    forecast = forecast or (getattr(dc, "forecast", None) if dc else None)
    if not forecast:
        raise ValueError("예측연월 미지정 — forecast 인자 또는 cfg.Drought.forecast 필요")
    n = int(n_members if n_members is not None else (getattr(dc, "n_members", 100) if dc else 100))
    fyear, season = int(forecast.split("_")[0]), forecast.split("_")[1]

    acidwg_config = Path(acidwg_config) if acidwg_config else \
        Path(cfg.PrjDir) / "config" / "acidwg_py.yaml"
    a = load_acidwg(str(acidwg_config))

    if fyear <= int(a["eyear_obs"]):               # hindcast (관측기간 이내·검증)
        acid_run_hindcast(
            station_csv=a["station_csv"], obs_dir=a["obs_dir"],
            picaso_dir=a["picaso_dir"], output_root=a["acidwg_root"],
            syear_obs=a["syear_obs"], eyear_obs=a["eyear_obs"],
            years=[fyear], seasons=[season],
            n_ensemble=n,                          # ★ 마스터 값 주입(단일 원천)
            model_file=a.get("model_file"),
            retrieve=a.get("retrieve", True), observation_eyear_cap=True,
        )
    else:                                          # operational (hindcast 이후 연도)
        forecast_csv = str(Path(a["picaso_dir"]) / f"{fyear}_{season}_picaso.csv")
        acid_run(
            station_csv=a["station_csv"], obs_dir=a["obs_dir"],
            output_dir=str(Path(a["acidwg_root"]) / "forecast"),
            sim_period=SEASON_MONTHS[season], syear_obs=a["syear_obs"],
            eyear_obs=a["eyear_obs"], forecast_csv=forecast_csv,
            n_ensemble=n, model_file=a.get("model_file"),
            retrieve=a.get("retrieve", True), forecast_year=fyear,
        )
    # 통합 레이아웃: 두 모드 모두 acidwg_root/forecast/{year}_{season}
    out = Path(a["acidwg_root"]) / "forecast" / f"{fyear}_{season}"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swat_py.drought.ensemble_weather",
                                 description="acidwg 앙상블 상세화(② N멤버 weather)")
    ap.add_argument("--config", default="config/swat_py.yaml")
    ap.add_argument("--forecast", default=None,
                    help="예측연월 (기본: config 의 forecast.period)")
    ap.add_argument("--members", type=int, default=None,
                    help="앙상블 수 (기본: config 의 ensemble.n_members)")
    ap.add_argument("--acidwg-config", default=None,
                    help="acidwg 설정 (기본: config/acidwg_py.yaml)")
    args = ap.parse_args(argv)
    from swat_py.config import load_config
    cfg = load_config(args.config)
    out = generate_ensemble_weather(cfg, forecast=args.forecast, n_members=args.members,
                                    acidwg_config=args.acidwg_config)
    print(f"완료: {out}  (member 폴더 {len(list(out.glob('member_*'))) if out.exists() else 0}개)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
