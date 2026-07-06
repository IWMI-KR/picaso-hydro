"""PICASO 가뭄예측 end-to-end 오케스트레이터 (통합 config C안).

예측연월 하나로:
  ① (전제) 장기 기후 SWAT+ → 평년·FDC
  ② acidwg 앙상블 상세화 (N멤버 weather)
  ③ 검보정 SWAT+ 앙상블 (동일 N·동일 warm-up·동일 기간) → Drought Risk 대시보드
까지 자동 연결한다.

★ config 3분할 (config/ 폴더):
    picaso-hydro.yaml = acidwg·swat **공통**(예측연월·앙상블 수·warm-up·경로) — SSOT
    swat_py.yaml      = swat 전용(보정·tank·대시보드 outlets/thresholds)
    acidwg_py.yaml    = acidwg 전용(관측기간·WGEN 모델·출력)
  두 로더가 각자 picaso-hydro.yaml 을 자동 병합하며, 이 오케스트레이터가 공통 예측연월·
  앙상블 수를 acidwg 에 **인자로 주입**해 상세화·모델링을 동일 값으로 일관 실행한다.

실행: python -m swat_py.drought.run --forecast 2016_AMJ [--members N] [--workers W]
                                    [--with-climatology] [--acidwg-config PATH]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from swat_py.drought.climatology import climatology_daily_path
from swat_py.drought.climatology_run import run_climatology
from swat_py.drought.ensemble_weather import generate_ensemble_weather


def run_pipeline(cfg, *, forecast=None, n_members=None, n_workers=4,
                 with_climatology=False, acidwg_config=None, skip_acidwg=False) -> dict:
    dc = cfg.Drought
    forecast = forecast or dc.forecast
    n = int(n_members or dc.n_members)
    root = Path(cfg.PrjDir)
    acidwg_config = Path(acidwg_config) if acidwg_config else \
        root / "config" / "acidwg_py.yaml"      # 공통 picaso-hydro.yaml 과 동거

    print("=" * 64)
    print(f"  PICASO 가뭄예측 파이프라인 — {forecast}")
    print(f"  앙상블 {n}멤버 · warm-up {cfg.CioNYSKIP}yr (마스터 단일 관리)")
    print("=" * 64)

    # ① 장기 기후(평년·FDC) — 전제. 파일명은 {syear+warmup}_{eyear} 로 자동 산출.
    clim_csv = climatology_daily_path(cfg)
    if with_climatology:
        print("[1/3] 장기 기후 SWAT+ 재실행 …")
        run_climatology(cfg)
    elif not clim_csv.is_file():
        raise SystemExit(f"기후 평년/FDC 자료 없음: {clim_csv}\n"
                         f"  → --with-climatology 로 먼저 생성하거나 "
                         f"python -m swat_py.drought.climatology_run 실행")

    # ② acidwg 앙상블 상세화 (마스터 N 주입)
    if not skip_acidwg:
        print(f"[2/3] acidwg 앙상블 상세화 {n}멤버 ({forecast}) …")
        generate_ensemble_weather(cfg, forecast=forecast, n_members=n,
                                  acidwg_config=acidwg_config)

    # ③ SWAT+ 앙상블 + Drought Risk 대시보드
    print("[3/3] SWAT+ 앙상블 + Drought Risk 대시보드 …")
    from swat_py.drought.dashboard_data import build
    from swat_py.drought.figure import make_all_figures
    res = build(cfg, forecast, n_members=n, n_workers=n_workers)
    make_all_figures(Path(res["out_root"]))
    print(f"\n✔ 완료 — {res['out_root']}")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swat_py.drought.run",
                                 description="PICASO 가뭄예측 end-to-end 파이프라인")
    ap.add_argument("--config", default="config/swat_py.yaml", help="마스터 config")
    ap.add_argument("--forecast", default=None, help="예측연월 (기본: yaml drought.forecast)")
    ap.add_argument("--members", type=int, default=None, help="앙상블 수 (기본: yaml)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--with-climatology", action="store_true", help="장기 기후 SWAT+ 선행 실행")
    ap.add_argument("--skip-acidwg", action="store_true", help="acidwg 상세화 생략(기존 멤버 사용)")
    ap.add_argument("--acidwg-config", default=None)
    args = ap.parse_args(argv)
    from swat_py.config import load_config
    cfg = load_config(args.config)
    run_pipeline(cfg, forecast=args.forecast, n_members=args.members,
                 n_workers=args.workers, with_climatology=args.with_climatology,
                 acidwg_config=args.acidwg_config, skip_acidwg=args.skip_acidwg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
