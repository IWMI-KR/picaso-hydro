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
import os
import sys
from pathlib import Path

from util_py.config import Config, find_config, load_config
from util_py.era5 import (
    VARIABLES,
    compute_area,
    download_era5_all,
    verify_era5_all,
)


def _picaso_root() -> Path:
    if env := os.environ.get("PICASO_ROOT"):
        return Path(env)
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / "0_database").is_dir():
            return parent
    return cwd


def _load_or_default(config_path: str | None) -> Config:
    """--config 인자 또는 자동 탐색으로 Config 반환. 없으면 smart default."""
    if config_path:
        return load_config(config_path)
    found = find_config()
    if found:
        return load_config(found)
    # YAML 부재 시 PICASO-Hydro 관습 기반 기본값
    cfg = Config()
    root = _picaso_root()
    cfg.project.root = str(root)
    cfg.region.boundary_csv = str(root / "0_database" / "gis" / "admin" / "country_boundary.csv")
    cfg.era5.output_dir = str(root / "0_database" / "era5" / "nc_hourly")
    return cfg


def main() -> int:
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
    parser.add_argument("--url", default=None,
                        help="CDS API URL (YAML era5.cds.url 오버라이드)")
    parser.add_argument("--key", default=None,
                        help="CDS API 키 (YAML era5.cds.key 오버라이드)")
    args = parser.parse_args()

    # ── 우선순위 적용: CLI > YAML > smart default ─────────────────────────
    cfg = _load_or_default(args.config)

    output_dir   = args.output_dir   or cfg.era5.output_dir
    boundary_csv = args.boundary_csv or cfg.region.boundary_csv
    start_year   = args.start_year if args.start_year is not None else cfg.era5.start_year
    end_year     = args.end_year   if args.end_year   is not None else cfg.era5.end_year
    var_keys     = args.vars or (cfg.era5.variables or None)
    cds_url      = args.url or cfg.era5.cds.url
    cds_key      = args.key or cfg.era5.cds.key

    if not boundary_csv:
        parser.error("boundary_csv 미지정: --boundary-csv 또는 util_py.yaml region.boundary_csv 필요")
    if not output_dir:
        parser.error("output_dir 미지정: --output-dir 또는 util_py.yaml era5.output_dir 필요")

    area = compute_area(boundary_csv, buffer=cfg.region.buffer_deg,
                        grid_res=cfg.grid.era5_resolution)
    print("=" * 62)
    print("  ERA5 시간별 자료 다운로드")
    print("=" * 62)
    print(f"  설정 출처  : {args.config or find_config() or '(코드 기본값)'}")
    print(f"  연도 범위  : {start_year} ~ {end_year or '현재 연도'}")
    print(f"  변수       : {var_keys or '전체 8개'}")
    print(f"  저장 폴더  : {output_dir}")
    print(f"  CDS 영역   : N={area[0]} W={area[1]} S={area[2]} E={area[3]}")
    print(f"  덮어쓰기   : {args.overwrite}")
    print("=" * 62)

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

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
