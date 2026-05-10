"""국제 관측 유량 자료 다운로드 (SWAT 검증용).

데이터 소스
-----------
CARAVAN (Zenodo)   : 글로벌 6,800 유역 일자료 + 메타 + 기상.
                     CAMELS-US/AUS/BR/CL/GB + LamaH-CE + HYSETS 통합.
USGS NWIS          : 미국 전역 일·시간 단위. REST API 무인증, 즉시 응답.

GRDC (BfG/WMO 9,500 관측소) 는 가장 광범위하지만 *수기 신청* 필수로 자동화 미지원.
소형 도서국·소수국가는 국가 수문기관 직접 연락이 유일한 경로입니다.

CARAVAN 서브셋 영역
-------------------
camels       : 미국 671 유역 (Newman et al. 2015)
camelsaus    : 호주 222 유역
camelsbr     : 브라질 897 유역
camelscl     : 칠레 516 유역
camelsgb     : 영국 671 유역
lamah        : 중부 유럽 859 유역 (Austria 중심)
hysets       : 캐나다·미국 14,425 유역

각 서브셋의 대략적 bbox 가 :data:`CARAVAN_SUBSETS` 에 내장되어 있어
사용자 bbox 와 교차하지 않는 서브셋은 다운로드를 건너뜁니다 (대용량 절약).
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

BBox = Tuple[float, float, float, float]   # (xmin, ymin, xmax, ymax)


# ── CARAVAN 서브셋 메타 ──────────────────────────────────────────────────────

# (이름, 대략 bbox, 유역 수, 설명)
CARAVAN_SUBSETS: List[Dict] = [
    {"name": "camels",    "bbox": (-125.0,  25.0,  -65.0,  50.0),
     "n_catchments": 671,    "country": "USA",          "size_mb": 250},
    {"name": "camelsaus", "bbox": ( 110.0, -45.0,  155.0, -10.0),
     "n_catchments": 222,    "country": "Australia",    "size_mb": 80},
    {"name": "camelsbr",  "bbox": ( -75.0, -35.0,  -30.0,   5.0),
     "n_catchments": 897,    "country": "Brazil",       "size_mb": 320},
    {"name": "camelscl",  "bbox": ( -75.0, -55.0,  -65.0, -17.0),
     "n_catchments": 516,    "country": "Chile",        "size_mb": 180},
    {"name": "camelsgb",  "bbox": ( -10.0,  50.0,    2.0,  60.0),
     "n_catchments": 671,    "country": "UK",           "size_mb": 240},
    {"name": "lamah",     "bbox": (   8.0,  45.0,   18.0,  50.0),
     "n_catchments": 859,    "country": "Central Europe", "size_mb": 320},
    {"name": "hysets",    "bbox": (-145.0,  25.0,  -55.0,  75.0),
     "n_catchments": 14425,  "country": "Canada/USA",   "size_mb": 1500},
]


def _bbox_intersects(a: BBox, b: BBox) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def caravan_subsets_for_bbox(bbox: BBox) -> List[Dict]:
    """bbox 와 교차하는 CARAVAN 서브셋 목록 반환."""
    return [s for s in CARAVAN_SUBSETS if _bbox_intersects(bbox, s["bbox"])]


# ── HTTP 헬퍼 ────────────────────────────────────────────────────────────────

def _http_download(url: str, dest: Path, timeout: int = 600,
                   show_progress: bool = True) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "util_py-streamflow/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            with dest.open("wb") as f:
                downloaded = 0
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if show_progress and total > 0:
                        pct = 100 * downloaded / total
                        print(f"\r    {dest.name}  "
                              f"{downloaded/1e6:6.1f} / {total/1e6:6.1f} MB  "
                              f"({pct:5.1f}%)", end="", flush=True)
        if show_progress:
            print()
    except urllib.error.HTTPError as e:
        if dest.exists():
            dest.unlink()
        raise RuntimeError(f"HTTP {e.code} {url}") from e
    return dest


# ── 1. CARAVAN 다운로드 ─────────────────────────────────────────────────────

def download_streamflow_caravan(
    output_dir: Union[str, Path],
    bbox: Optional[BBox] = None,
    sub_datasets: Optional[List[str]] = None,
    zenodo_record_id: str = "7944025",
    base_url: str = "https://zenodo.org/records/{record_id}/files",
    bbox_filter: bool = True,
) -> Dict[str, List[Path]]:
    """CARAVAN 글로벌 유역 자료 다운로드 (Zenodo).

    Parameters
    ----------
    output_dir       : 출력 폴더 (각 서브셋이 하위 폴더로 분리)
    bbox             : (xmin, ymin, xmax, ymax) — None 이면 전체 다운로드
    sub_datasets     : 받을 서브셋 명시 (None + bbox 면 자동 선택, None + bbox 없으면 전체)
    zenodo_record_id : Zenodo record ID (기본 v1.4)
    base_url         : URL 패턴 (``{record_id}`` 치환)
    bbox_filter      : True 면 다운로드 후 bbox 교차하는 catchment 만 보존

    Returns
    -------
    dict : {sub_dataset_name: [extracted_csv_paths]}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 서브셋 선택
    if sub_datasets:
        targets = [s for s in CARAVAN_SUBSETS if s["name"] in sub_datasets]
        if len(targets) != len(sub_datasets):
            unknown = set(sub_datasets) - {s["name"] for s in targets}
            raise ValueError(f"알 수 없는 서브셋: {unknown}. "
                             f"가능: {[s['name'] for s in CARAVAN_SUBSETS]}")
    elif bbox is not None:
        targets = caravan_subsets_for_bbox(bbox)
    else:
        targets = CARAVAN_SUBSETS

    print("=" * 64)
    print("  CARAVAN 글로벌 유역 자료 다운로드 (Zenodo)")
    print("=" * 64)
    if bbox:
        print(f"  bbox          : {bbox}")
    print(f"  Zenodo record : {zenodo_record_id}")
    print(f"  대상 서브셋   : {[s['name'] for s in targets] or '(없음)'}")
    print(f"  output_dir    : {output_dir}")
    print("=" * 64)

    if not targets:
        print("\n  ⚠️  bbox 와 교차하는 CARAVAN 서브셋 없음.")
        print("      해당 지역(예: 소형 도서국, 일부 아시아·아프리카)은")
        print("      CARAVAN 미수록. 국가 수문기관에 직접 문의 필요.")
        return {}

    base = base_url.format(record_id=zenodo_record_id)
    results: Dict[str, List[Path]] = {}

    for subset in targets:
        name = subset["name"]
        url = f"{base}/caravan-{name}.zip"
        print(f"\n  [{name.upper()}] {subset['country']} "
              f"({subset['n_catchments']:,} 유역, ~{subset['size_mb']} MB)")
        print(f"           ← {url}")

        sub_out = output_dir / f"caravan-{name}"
        sub_out.mkdir(exist_ok=True)

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            try:
                _http_download(url, tmp_path)
            except RuntimeError as e:
                print(f"           [FAIL] {e}")
                continue

            extracted = _extract_caravan_subset(
                tmp_path, sub_out, bbox if bbox_filter else None
            )
            results[name] = extracted
            print(f"           [OK] {len(extracted)} catchment timeseries → {sub_out}")
        finally:
            tmp_path.unlink(missing_ok=True)

    return results


def _extract_caravan_subset(
    zip_path: Path,
    out_dir: Path,
    bbox: Optional[BBox] = None,
) -> List[Path]:
    """CARAVAN ZIP 에서 timeseries CSV 와 attributes 추출.

    bbox 가 주어지면 attributes 의 lat/lon 으로 catchment 필터.
    """
    extracted: List[Path] = []
    keep_ids: Optional[set] = None

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        # bbox 필터링: attributes/*.csv 에서 lat/lon 컬럼 확인
        if bbox is not None:
            attr_names = [n for n in names
                          if n.endswith(".csv") and "/attributes" in n]
            for an in attr_names:
                with zf.open(an) as f:
                    df = pd.read_csv(f)
                lat_col = next((c for c in df.columns
                                if c.lower() in ("gauge_lat", "lat", "latitude")), None)
                lon_col = next((c for c in df.columns
                                if c.lower() in ("gauge_lon", "lon", "longitude")), None)
                id_col  = next((c for c in df.columns
                                if c.lower() in ("gauge_id", "id", "basin_id")), None)
                if lat_col and lon_col and id_col:
                    in_box = (
                        (df[lon_col] >= bbox[0]) & (df[lon_col] <= bbox[2]) &
                        (df[lat_col] >= bbox[1]) & (df[lat_col] <= bbox[3])
                    )
                    keep_ids = set(df.loc[in_box, id_col].astype(str))
                    break

        # timeseries 추출
        for name in names:
            if not name.endswith(".csv"):
                continue
            if "/timeseries" not in name:
                continue
            stem = Path(name).stem  # gauge_id
            if keep_ids is not None and stem not in keep_ids:
                continue
            dst = out_dir / Path(name).name
            with zf.open(name) as src, dst.open("wb") as out:
                shutil.copyfileobj(src, out)
            extracted.append(dst)

        # attributes 도 함께 보관 (참고용)
        for name in names:
            if name.endswith(".csv") and "/attributes" in name:
                dst = out_dir / Path(name).name
                with zf.open(name) as src, dst.open("wb") as out:
                    shutil.copyfileobj(src, out)

    return extracted


# ── 2. USGS NWIS (미국 전용) ────────────────────────────────────────────────

# 대략적인 미국 본토 + 알래스카 + 하와이 + 푸에르토리코 bbox
_USGS_COVERAGE = (-180.0, 17.0, -65.0, 72.0)


def _bbox_in_usgs_coverage(bbox: BBox) -> bool:
    """bbox 가 USGS NWIS 권역과 교차?"""
    return _bbox_intersects(bbox, _USGS_COVERAGE)


def download_streamflow_usgs(
    output_dir: Union[str, Path],
    bbox: BBox,
    start_date: str = "1990-01-01",
    end_date: Optional[str] = None,
    parameter: str = "00060",
    nwis_url: str = "https://waterservices.usgs.gov/nwis/dv/",
) -> List[Path]:
    """USGS NWIS Daily Values 다운로드 (미국 전용, REST API).

    Parameters
    ----------
    output_dir : 출력 폴더
    bbox       : (xmin, ymin, xmax, ymax) — 면적 ≤ 25 도² 권장 (NWIS 제한)
    start_date : YYYY-MM-DD
    end_date   : YYYY-MM-DD (None → 오늘)
    parameter  : 00060 = 유량(cfs), 00065 = 수위(ft), 00010 = 수온(°C)

    Returns
    -------
    list of Path : 저장된 파일들 (관측소별 1개 + 통합 1개)
    """
    if not _bbox_in_usgs_coverage(bbox):
        raise ValueError(
            f"bbox {bbox} 가 USGS NWIS 권역(미국+알래스카+하와이+PR) 밖입니다."
        )

    # NWIS bBox 인자: west,south,east,north (decimal degrees, 4자리)
    # 면적 25 도² 제한
    width  = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    if width * height > 25:
        raise ValueError(
            f"NWIS bbox 면적 한계 25 도² 초과: {width*height:.1f}. "
            f"더 작은 영역으로 분할 필요."
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if end_date is None:
        end_date = pd.Timestamp.today().strftime("%Y-%m-%d")

    bbox_str = ",".join(f"{v:.4f}" for v in bbox)

    print("=" * 64)
    print("  USGS NWIS Daily Values 다운로드")
    print("=" * 64)
    print(f"  bbox       : {bbox_str}")
    print(f"  parameter  : {parameter}  (00060=유량 cfs)")
    print(f"  기간       : {start_date} ~ {end_date}")
    print(f"  output_dir : {output_dir}")
    print("=" * 64)

    params = {
        "format":           "json",
        "bBox":             bbox_str,
        "startDT":          start_date,
        "endDT":            end_date,
        "parameterCd":      parameter,
        "siteStatus":       "all",
    }
    url = f"{nwis_url}?{urllib.parse.urlencode(params)}"
    print(f"\n  GET {url[:120]}{'...' if len(url) > 120 else ''}")

    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"NWIS HTTP {e.code}: {url}") from e

    series = data.get("value", {}).get("timeSeries", [])
    print(f"\n  반환된 timeseries: {len(series)}")
    if not series:
        print("  ⚠️  해당 영역+기간+파라미터에 자료 없음.")
        return []

    saved: List[Path] = []
    rows_all = []

    for ts in series:
        site_info = ts["sourceInfo"]
        site_no   = site_info["siteCode"][0]["value"]
        site_name = site_info["siteName"]
        lat = float(site_info["geoLocation"]["geogLocation"]["latitude"])
        lon = float(site_info["geoLocation"]["geogLocation"]["longitude"])

        values = ts["values"][0]["value"]
        if not values:
            continue

        df = pd.DataFrame(values)
        df["dateTime"] = pd.to_datetime(df["dateTime"])
        df["value"]    = pd.to_numeric(df["value"], errors="coerce")
        df = df.rename(columns={"dateTime": "date", "value": "discharge_cfs"})
        df = df[["date", "discharge_cfs", "qualifiers"]]

        out = output_dir / f"usgs_{site_no}.csv"
        df.to_csv(out, index=False)
        saved.append(out)

        rows_all.append({
            "site_no":   site_no,
            "site_name": site_name,
            "lat":       lat,
            "lon":       lon,
            "n_records": len(df),
            "first_date": df["date"].min().strftime("%Y-%m-%d") if len(df) else "",
            "last_date":  df["date"].max().strftime("%Y-%m-%d") if len(df) else "",
        })
        print(f"    [OK] {site_no:<10s} {site_name:<40s} {len(df):>6,} 행")

    # 메타 통합
    if rows_all:
        meta = pd.DataFrame(rows_all)
        meta_path = output_dir / "stations-usgs.csv"
        meta.to_csv(meta_path, index=False)
        saved.append(meta_path)
        print(f"\n  메타 저장: {meta_path}")

    return saved
