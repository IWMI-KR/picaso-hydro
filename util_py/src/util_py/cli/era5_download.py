"""
ERA5 시간별 자료 다운로드 CLI

설정 우선순위
-------------
    CLI 인자 > util_py.yaml > 환경변수 > smart default

사용법
------
    # PICASO-Hydro 안에서 (util_py.yaml 자동 탐색)
    util-era5-download --start-year 2022

    # 명시적 YAML
    util-era5-download --config /path/to/util_py.yaml

    # 다른 프로젝트
    set PICASO_ROOT=D:/MyProject
    util-era5-download

    # CLI로 모두 직접 지정 (YAML 무시)
    util-era5-download --output-dir D:/data/era5 --boundary-csv D:/cfg/boundary.csv

CDS API 인증
-------------
    util_py.yaml의 era5.cds.url/key 또는 .cdsapirc / CDSAPI_URL,KEY 환경변수.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from util_py.config import config_source, load_effective_config
from util_py.era5 import (
    VARIABLES,
    compute_area,
    download_era5_all,
    plan_era5_downloads,
    verify_era5_all,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="ERA5 시간별 자료 다운로드 (CDS API)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=None,
                        help="util_py.yaml 경로 (생략 시 자동 탐색)")
    parser.add_argument("--start-year", type=int, default=None,
                        help="다운로드 시작 연도 (YAML era5.start_year 오버라이드)")
    parser.add_argument("--end-year", type=int, default=None,
                        help="다운로드 종료 연도 (YAML era5.end_year 오버라이드)")
    parser.add_argument("--vars", nargs="+", default=None,
                        choices=list(VARIABLES.keys()), metavar="VAR",
                        help=f"변수 목록 (가능: {list(VARIABLES.keys())})")
    parser.add_argument("--output-dir", default=None,
                        help="NC 파일 저장 폴더 (YAML era5.output_dir 오버라이드)")
    parser.add_argument("--boundary-csv", default=None,
                        help="country_boundary.csv (YAML region.boundary_csv 오버라이드)")
    parser.add_argument("--overwrite", action="store_true",
                        help="기존 파일 덮어쓰기")
    parser.add_argument("--verify-only", action="store_true",
                        help="다운로드 없이 검증만 수행")
    parser.add_argument("--dry-run", action="store_true",
                        help="다운로드 없이 '무엇을 받고 무엇을 건너뛸지' 계획만 출력")
    parser.add_argument("--no-extract", action="store_true",
                        help="새 파일을 받아도 era5-extract 를 자동 실행하지 않음")
    parser.add_argument("--url", default=None,
                        help="CDS API URL (YAML era5.cds.url 오버라이드)")
    parser.add_argument("--key", default=None,
                        help="CDS API 키 (YAML era5.cds.key 오버라이드)")
    args = parser.parse_args(argv)

    # ── 우선순위 적용: CLI > YAML > smart default ─────────────────────────
    cfg = load_effective_config(args.config)

    output_dir   = args.output_dir   or cfg.era5.output_dir
    boundary_csv = args.boundary_csv or cfg.region.boundary_csv
    start_year   = args.start_year if args.start_year is not None else cfg.era5.start_year
    end_year     = args.end_year   if args.end_year   is not None else cfg.era5.end_year
    var_keys     = args.vars or (cfg.era5.variables or None)
    cds_url      = args.url or cfg.era5.cds.url
    cds_key      = args.key or cfg.era5.cds.key

    if not boundary_csv:
        parser.error("boundary_csv 미지정: --boundary-csv 또는 "
                     "util_py.yaml region.boundary_csv 필요")
    if not output_dir:
        parser.error("output_dir 미지정: --output-dir 또는 util_py.yaml era5.output_dir 필요")

    area = compute_area(boundary_csv, buffer=cfg.region.buffer_deg,
                        grid_res=cfg.grid.era5_resolution)
    print("=" * 62)
    print("  ERA5 시간별 자료 다운로드")
    print("=" * 62)
    print(f"  설정 출처  : {config_source(args.config)}")
    print(f"  연도 범위  : {start_year} ~ {end_year or '현재 연도'}")
    print(f"  변수       : {var_keys or '전체 8개'}")
    print(f"  저장 폴더  : {output_dir}")
    print(f"  CDS 영역   : N={area[0]} W={area[1]} S={area[2]} E={area[3]}")
    print(f"  덮어쓰기   : {args.overwrite}")
    print("=" * 62)

    # ── 계획 수립 (현재 연도는 월 단위, 지난 연도는 연 단위) ─────────────────
    plan    = plan_era5_downloads(output_dir, start_year, end_year, var_keys)
    missing = [p for p in plan if not p["exists"]]

    def _stamp(item) -> str:
        return (f"{item['year']}{item['month']:02d}"
                if item["month"] else str(item["year"]))

    print(f"  대상 {len(plan)}개 중 신규 {len(missing)}개 / 기존 {len(plan) - len(missing)}개")
    if missing:
        preview = ", ".join(f"{_stamp(i)}·{i['var']}" for i in missing[:10])
        print(f"  신규 대상: {preview}{' ...' if len(missing) > 10 else ''}")
    print("=" * 62)

    if args.dry_run:
        print("\n[계획 모드 — 실제 다운로드 없음]")
        for item in plan:
            mark = "SKIP" if item["exists"] else "GET "
            print(f"  [{mark}] {Path(item['path']).name:<34s} {item['reason']}")
        print(f"\n계획: 신규 {len(missing)}개 / 건너뜀 {len(plan) - len(missing)}개")
        return 0

    if args.verify_only:
        print("\n[검증 모드]")
        df = verify_era5_all(
            output_dir=output_dir,
            start_year=start_year,
            end_year=end_year,
            var_keys=var_keys,
        )
        n_ok   = df["ok"].sum()
        n_fail = len(df) - n_ok
        print(df.to_string(index=False))
        print(f"\n결과: {n_ok}개 정상 / {n_fail}개 문제")
        return 0 if n_fail == 0 else 1

    created, failed = download_era5_all(
        output_dir   = output_dir,
        boundary_csv = boundary_csv,
        start_year   = start_year,
        end_year     = end_year,
        var_keys     = var_keys,
        overwrite    = args.overwrite,
        url          = cds_url,
        key          = cds_key,
    )

    print(f"\n{'='*62}")
    print(f"  다운로드 완료: {len(created)}개 성공 / {len(failed)}개 실패")
    if failed:
        print("  실패 목록:")
        for f in failed:
            print(f"    - {f}")
    print(f"{'='*62}")

    n_fail = 0
    if created:
        print("\n[다운로드 완료 파일 검증]")
        df = verify_era5_all(
            output_dir=output_dir,
            start_year=start_year,
            end_year=end_year,
            var_keys=var_keys,
        )
        n_ok   = df["ok"].sum()
        n_fail = len(df) - n_ok
        print(df.to_string(index=False))
        print(f"\n검증 결과: {n_ok}개 정상 / {n_fail}개 문제")

    # ── 새로 받은 파일이 있으면 곧바로 격자점 추출 ───────────────────────────
    # 격자점 CSV 는 전 기간을 다시 쓰므로 --overwrite 가 필요하다.
    # (없으면 "파일이 이미 있다"는 이유로 전 격자점이 skip 되어 갱신되지 않음)
    new_files = [i for i in missing if Path(i["path"]).exists()]
    if not new_files:
        print("\n  신규 파일 없음 → era5-extract 생략")
    elif args.no_extract:
        print(f"\n  신규 {len(new_files)}개 — --no-extract 지정으로 추출 생략"
              f" (별도로 'util-era5-extract --overwrite' 필요)")
    elif failed or n_fail:
        print("\n  [경고] 실패·검증문제가 있어 era5-extract 를 생략합니다."
              " 해결 후 'util-era5-extract --overwrite' 를 실행하세요.")
    else:
        print(f"\n  신규 {len(new_files)}개 파일 반영 → era5-extract 실행")
        from util_py.cli import era5_extract
        extract_argv = (["--config", args.config] if args.config else []) + ["--overwrite"]
        rc = era5_extract.main(extract_argv)
        if rc not in (0, None):
            print(f"  [경고] era5-extract 종료코드 {rc}")
            return rc

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
