"""PICASO-Hydro 사용자 매뉴얼 — 한국어/영문 docx 생성.

    cd docs/manual
    python build_manual.py            # 두 언어 모두
    python build_manual.py ko         # 한국어만

내용은 manual_content*.py, 모양은 manual_kit.py 에 있다. 이 파일은 조립만 한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document

import manual_content  # noqa: F401  (CHAPTERS 를 채운다 — import 순서가 곧 장 순서)
import manual_content2  # noqa: F401
import manual_content3  # noqa: F401
import manual_kit as K
from manual_content import CHAPTERS, META

HERE = Path(__file__).resolve().parent
LANGS = {"ko": 0, "en": 1}
OUT = {"ko": "PICASO-Hydro_사용자매뉴얼_KO.docx",
       "en": "PICASO-Hydro_User-Manual_EN.docx"}


def pick(pair, i):
    """T()/L() 쌍에서 언어 하나를 고른다."""
    return pair[i] if isinstance(pair, tuple) and len(pair) == 2 else pair


def render(doc, blocks, i, font):
    for b in blocks:
        kind = b[0]
        if kind == "h2":
            K.h2(doc, pick(b[1], i), font)
        elif kind == "h3":
            K.h3(doc, pick(b[1], i), font)
        elif kind == "p":
            K.para(doc, pick(b[1], i), font)
        elif kind == "bullets":
            K.bullets(doc, pick(b[1], i), font)
        elif kind == "check":
            K.checklist(doc, pick(b[1], i), font)
        elif kind == "code":
            cap = pick(b[2], i) if len(b) > 2 else None
            K.code(doc, pick(b[1], i), font, caption=cap)
        elif kind == "keys":
            K.keylist(doc, pick(b[1], i), font)
        elif kind == "box":
            K.box(doc, b[1], pick(b[2], i), pick(b[3], i), font)
        elif kind == "objectives":
            K.objectives(doc, pick(META["objectives_t"], i), pick(b[1], i), font)
        elif kind == "quiz":
            K.quiz(doc, pick(META["quiz_t"], i), pick(b[1], i), font,
                   answer_label=pick(META["answer_t"], i))
        elif kind == "step":
            lines = pick(b[3], i) if len(b) > 3 else ()
            checks = pick(b[4], i) if len(b) > 4 else ()
            K.step(doc, b[1], pick(b[2], i), font, lines, checks)
        elif kind == "table":
            header, rows = pick(b[1], i)
            opt = b[2] if len(b) > 2 else {}
            K.table(doc, header, rows, font, stage_col=opt.get("stage_col"))
        else:
            raise ValueError(f"알 수 없는 블록: {kind}")


def build(lang):
    i = LANGS[lang]
    font = K.KO_FONT if lang == "ko" else K.EN_FONT
    doc = Document()
    K.setup(doc, font)

    K.cover(doc,
            title=pick(META["title"], i),
            subtitle=pick(META["subtitle"], i),
            tagline=pick(META["tagline"], i),
            band_text=pick(META["band"], i),
            meta_rows=[pick(r, i) for r in META["meta_rows"]],
            body_font=font)
    K.toc(doc, heading=pick(META["toc_h"], i),
          note=pick(META["toc_note"], i), body_font=font)
    K.header_footer(doc, left_text=pick(META["header"], i),
                    right_text=pick(META["footer"], i), body_font=font)

    for n, ch in enumerate(CHAPTERS):
        K.h1(doc, ch["num"], pick(ch["title"], i), font, page_break=(n > 0))
        render(doc, ch["blocks"], i, font)

    path = HERE / OUT[lang]
    doc.save(path)
    return path


def main(argv):
    want = argv[1:] or ["ko", "en"]
    print(f"장 {len(CHAPTERS)}개: {', '.join(c['num'] for c in CHAPTERS)}")
    for lang in want:
        if lang not in LANGS:
            raise SystemExit(f"언어는 ko | en 중에서: {lang!r}")
        p = build(lang)
        print(f"  {lang}  →  {p}  ({p.stat().st_size/1024:.0f} KB)")
    print("\nWord 에서 열고 목차를 클릭한 뒤 F9 를 누르면 쪽 번호가 채워집니다.")


if __name__ == "__main__":
    main(sys.argv)
