"""앙상블 **일단위 강제력** 저장소 — 초기수위 변경 시 SWAT+ 재실행을 없애는 자료.

왜 필요한가 (유진호 박사 2026-11-12 메일 Palau 1·2·3번, 11-17 통화 정리)
---------------------------------------------------------------------------
1번(모두 Normal) · 2번(월말 기준이라 월 중 저하를 놓침) · 3번(초기수위를 바꿔도 선만 바뀜)
은 모두 **일단위 자료가 없어서** 생긴다. 월말 한 점만 남기면 월 중 저하가 사라지고,
초기수위를 바꿀 때 다시 풀 재료가 없다.

그런데 원시 출력을 그대로 보관할 수는 없다 (멤버 1개 실측, 팔라우 2016_AMJ):
  · 멤버당 출력 .txt 11.8 MB × 1,000멤버 × 167기간 = **1.97 TB**
반면 **초기수위와 무관한 강제력 2개만** 남기면:
  · 2변수 × 91일 × float32 = 멤버당 **728 B** → 167기간 전부 **122 MB** (약 1/16,000)

그리고 **추가 모델 실행 시간은 0** 이다 — ``prepare_base`` 가 전환유입이 설정된
프로젝트에서는 이미 일단위 출력을 켜고 돌린다(일단위 ON 1.0s vs OFF 0.9s 실측).
지금까지 그 파일들을 쓰고 **지우고** 있었을 뿐이다.

저장 형식
---------
NPZ — 넘파이(NumPy)가 숫자 배열 여러 개를 한 파일에 압축해 담는 형식. 행·열 표가 아니라
숫자 덩어리라 같은 내용의 CSV보다 10~20배 작다.
``3_swatplus/forecast/{기간}/daily/{수원}_daily.npz``

  members     : (M,)    멤버 이름
  dates       : (D,)    예측기간 일자 (datetime64[D])
  res_net_m3  : (M, D)  저수지 일 순유입 m³/일   — 저수지 수원만
  src_q_m3s   : (M, D)  전환 수원 채널 일유량 m³/s — 저수지 수원만
  q_m3s       : (M, D)  하천 일유량 m³/s          — 하천 수원만

float32(숫자 하나를 4바이트로 적는 방식)로 저장한다. 유량·저수량은 유효숫자 7자리면
충분하므로 8바이트(float64)를 쓸 이유가 없다. 이 반올림 때문에 일배열로 다시 푼 월말
수위는 월 물수지 결과와 **약 4e-08 ft**(0.01 µm) 어긋난다 — 실측으로 확인한 값이며,
단계 경계(0.05 ft 단위로 적는 21.85/19.55/14.95)에 영향을 줄 수 없는 크기다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

#: 일배열이 들어가는 하위 폴더 이름(``3_swatplus/forecast/{기간}/`` 아래).
DAILY_SUBDIR = "daily"


def daily_npz_path(period_dir: Path, outlet: str) -> Path:
    """``{period_dir}/daily/{outlet}_daily.npz`` 경로(폴더는 만들지 않는다)."""
    return Path(period_dir) / DAILY_SUBDIR / f"{outlet}_daily.npz"


def save_daily(period_dir: Path, outlet: str, *,
               members: List[str], dates: np.ndarray,
               arrays: Dict[str, np.ndarray]) -> Optional[Path]:
    """멤버별 일배열을 NPZ 하나로 저장 → 경로. 담을 것이 없으면 None.

    Parameters
    ----------
    members : 멤버 이름 M개 — ``arrays`` 각 배열의 행 순서와 **같아야** 한다.
    dates   : 예측기간 일자 D개.
    arrays  : {변수명: (M, D) 배열}. None 인 변수는 버린다.
    """
    keep = {k: np.asarray(v, dtype="float32") for k, v in arrays.items()
            if v is not None}
    if not members or not keep:
        return None
    out = daily_npz_path(period_dir, outlet)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "members": np.asarray(members, dtype="U32"),
        "dates": np.asarray(dates, dtype="datetime64[D]"), **keep}
    np.savez_compressed(out, **payload)
    return out


def load_daily(period_dir: Path, outlet: str) -> Optional[Dict[str, np.ndarray]]:
    """저장된 NPZ → {members, dates, 변수…}. 파일이 없으면 None."""
    f = daily_npz_path(period_dir, outlet)
    if not f.is_file():
        return None
    with np.load(f, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def stack_members(per_member: Dict[str, Dict[str, object]], var: str,
                  members: List[str]) -> Optional[np.ndarray]:
    """{멤버: {변수: 1차원 배열}} → (M, D) 2차원 배열. 변수가 없으면 None.

    멤버마다 일수가 다르면(출력 창이 어긋난 멤버) **가장 흔한 길이**만 남기고
    나머지 멤버는 버린다 — 길이가 섞인 배열을 만들면 조용히 잘못 정렬된다.
    버린 멤버는 호출부가 ``members`` 반환값으로 알 수 있다.
    """
    rows = [(m, np.asarray(per_member[m][var], dtype="float32"))
            for m in members
            if m in per_member and per_member[m].get(var) is not None]
    if not rows:
        return None
    lens = [len(a) for _, a in rows]
    want = max(set(lens), key=lens.count)
    rows = [(m, a) for m, a in rows if len(a) == want]
    if not rows:
        return None
    return np.vstack([a for _, a in rows])


def common_members(per_member: Dict[str, Dict[str, object]], var: str,
                   members: List[str], n_days: int) -> List[str]:
    """:func:`stack_members` 가 실제로 남기는 멤버 이름(순서 동일)."""
    return [m for m in members
            if m in per_member and per_member[m].get(var) is not None
            and len(np.asarray(per_member[m][var])) == n_days]
