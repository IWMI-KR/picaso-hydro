"""
국제 관측 유량 자료 다운로드 CLI

소스 (--source)
---------------
    caravan : Zenodo 글로벌 6,800 유역 (자동: bbox 교차 서브셋만)
    usgs    : 미국 NWIS REST API (즉시, 미국 한정)
    auto    : bbox 가 미국이면 usgs, 그 외 caravan

사용법
------
    util-streamflow-download                              # YAML 자동 탐색, source=auto
    util-streamflow-download --source caravan             # 강제 CARAVAN
    util-streamflow-download --source caravan --sub-datasets camelsaus
    util-streamflow-download --source usgs --bbox -106 39 -105 40

    # bbox 직접 지정 (boundary_csv 없이)
    util-streamflow-download --bbox -125 32 -114 42 --source usgs
"""

from __future__ import annotations

import argparse
import sys

from util_py.config import load_effective_config
from util_py.gis_download import _read_bbox_iso
from util_py.streamflow import (
    _bbox_in_usgs_coverage,
    caravan_subsets_for_bbox,
    download_streamflow_caravan,
    download_streamflow_usgs,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="국제 관측 유량 자료 다운로드 (CARAVAN + USGS NWIS)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=None,
                        help="util_py.yaml 경로")
    parser.add_argument("--boundary-csv", default=None,
                        help="경계 CSV (bbox 추출용)")
    parser.add_argument("--bbox", nargs=4, type=float, default=None,
                        metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
                        help="bbox 직접 지정 (boundary-csv 무시)")
    parser.add_argument("--output-dir", default=None,
                        help="출력 폴더 (YAML streamflow.obs_dir)")
    parser.add_argument("--source", choices=["caravan", "usgs", "auto"],
                        default="auto", help="자료 소스")
    parser.add_argument("--sub-datasets", nargs="+", default=None,
                        help="CARAVAN 서브셋 명시 (예: camels camelsaus)")
    parser.add_argument("--start-date", default=None,
                        help="USGS 시작일 (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None,
                        help="USGS 종료일 (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    cfg = load_effective_config(args.config)

    # bbox 결정
    if args.bbox:
        bbox = tuple(args.bbox)
    else:
        bcsv = args.boundary_csv or cfg.region.boundary_csv
        if not bcsv:
            parser.error("bbox 또는 boundary_csv 필수")
        bbox, _, _, _ = _read_bbox_iso(bcsv)

    output_dir = args.output_dir or cfg.streamflow.obs_dir
    if not output_dir:
        parser.error("output_dir 미지정 (YAML streamflow.obs_dir 또는 --output-dir)")

    # source 결정
    src = args.source
    if src == "auto":
        if _bbox_in_usgs_coverage(bbox):
            src = "usgs"
            print("[auto] bbox 가 USGS 권역 → usgs")
        elif caravan_subsets_for_bbox(bbox):
            src = "caravan"
            subs = [s["name"] for s in caravan_subsets_for_bbox(bbox)]
            print(f"[auto] CARAVAN 서브셋 매칭: {subs} → caravan")
        else:
            print(f"[auto] bbox {bbox} 와 매칭되는 자료 없음.")
            print("       → CARAVAN/USGS 둘 다 미수록. 국가 수문기관 직접 문의 필요.")
            print("       (GRDC https://grdc.bafg.de 가 가장 광범위하지만 수기 신청)")
            return 1

    if src == "usgs":
        download_streamflow_usgs(
            output_dir=output_dir, bbox=bbox,
            start_date=args.start_date or cfg.streamflow.usgs.start_date,
            end_date=args.end_date or cfg.streamflow.usgs.end_date,
            parameter=cfg.streamflow.usgs.parameter,
            nwis_url=cfg.streamflow.usgs.nwis_url,
        )
    elif src == "caravan":
        download_streamflow_caravan(
            output_dir=output_dir, bbox=bbox,
            sub_datasets=args.sub_datasets or (cfg.streamflow.caravan.sub_datasets or None),
            zenodo_record_id=cfg.streamflow.caravan.zenodo_record_id,
            base_url=cfg.streamflow.caravan.base_url,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
