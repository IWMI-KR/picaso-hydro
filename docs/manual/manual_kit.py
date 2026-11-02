"""PICASO-Hydro 사용자 매뉴얼 — docx 디자인 도구상자.

여기에는 **모양**만 있다. 내용은 ``manual_content.py``, 조립은 ``build_manual.py``.

설계 의도
---------
대상이 컴퓨터 비전문가(쿡·팔라우 기상청·물관리 담당)라서, 세 가지 틀을 섞었다.
  · 작업카드(A) — 번호 붙은 단계 + 체크박스. "어디까지 했는지" 가 보이게.
  · 교육교재(B) — 학습목표 · "왜 이렇게 하나" 상자 · 확인문제.
  · 화면해설(C) — 터미널에 **보이는 것**을 그대로 싣고 번호를 찍어 설명.

색에만 의존하지 않는다(흑백 인쇄 대비): 상자는 굵은 왼쪽 테두리 + 제목 글자로 구분.
"""
from __future__ import annotations

from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# ── 색 ──────────────────────────────────────────────────────────────────────
INK      = RGBColor(0x1B, 0x1B, 0x19)
INK2     = RGBColor(0x55, 0x54, 0x4E)
ACCENT   = RGBColor(0x18, 0x5F, 0xA5)
ACCENT_H = "185FA5"
PAPER_H  = "FFFFFF"
TINT_H   = "F3F5F8"      # 옅은 회청
CODE_H   = "F4F3EF"      # 터미널 블록
WHY_H    = "FCF7EC"      # 왜 상자
WARN_H   = "FDF3F2"      # 경고
TIP_H    = "F2F9F4"      # 도움말
STEP_H   = "1B1B19"      # 단계 번호 원

STAGE_H = {"normal": "2E7D4F", "watch": "B8860B",
           "warning": "C2601F", "crisis": "A32D2D"}

KO_FONT, EN_FONT, MONO = "맑은 고딕", "Segoe UI", "Consolas"


# ── 낮은 수준 도우미 ────────────────────────────────────────────────────────

def _font(run, name, size=None, bold=None, color=None, mono=False):
    run.font.name = MONO if mono else name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), KO_FONT if not mono else MONO)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    return run


def _shade(el, hex_fill):
    """문단·셀 배경색."""
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    pr = el.get_or_add_tcPr() if el.tag.endswith("}tc") else el.get_or_add_pPr()
    pr.append(shd)


def _para_border(p, *, left=None, width=18, space=8, all_sides=None, color="D8D6CF"):
    """문단 테두리. left=색이면 왼쪽만 굵게(상자 느낌)."""
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    sides = ["top", "left", "bottom", "right"] if all_sides else (["left"] if left else [])
    for side in sides:
        e = OxmlElement(f"w:{side}")
        e.set(qn("w:val"), "single")
        is_accent = (side == "left" and left)
        e.set(qn("w:sz"), str(width if is_accent else 6))
        e.set(qn("w:space"), str(space))
        e.set(qn("w:color"), (left if is_accent else (all_sides or color)))
        bdr.append(e)
    pPr.append(bdr)


def _cell_border(cell, *, left=None, width=24):
    tcPr = cell._tc.get_or_add_tcPr()
    bdr = OxmlElement("w:tcBorders")
    if left:
        e = OxmlElement("w:left")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), str(width))
        e.set(qn("w:color"), left)
        bdr.append(e)
    tcPr.append(bdr)


def _no_table_border(table):
    tbl = table._tbl
    pr = tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{side}")
        e.set(qn("w:val"), "none")
        borders.append(e)
    pr.append(borders)


def _field(paragraph, code):
    """Word 필드(PAGE, TOC 등)."""
    r = paragraph.add_run()
    b = OxmlElement("w:fldChar")
    b.set(qn("w:fldCharType"), "begin")
    t = OxmlElement("w:instrText")
    t.set(qn("xml:space"), "preserve")
    t.text = code
    s = OxmlElement("w:fldChar")
    s.set(qn("w:fldCharType"), "separate")
    e = OxmlElement("w:fldChar")
    e.set(qn("w:fldCharType"), "end")
    for x in (b, t, s, e):
        r._r.append(x)
    return r


def _spacing(p, before=0, after=6, line=None):
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    if line:
        pf.line_spacing = line


# ── 문서 뼈대 ───────────────────────────────────────────────────────────────

def setup(doc, body_font):
    """A4 · 여백 · 기본 글꼴."""
    for s in doc.sections:
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)
        s.left_margin = s.right_margin = Cm(2.3)
        s.top_margin, s.bottom_margin = Cm(2.2), Cm(1.9)
    st = doc.styles["Normal"]
    st.font.name = body_font
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), KO_FONT)
    st.paragraph_format.space_after = Pt(6)
    st.paragraph_format.line_spacing = 1.45


def cover(doc, *, title, subtitle, tagline, meta_rows, band_text, body_font):
    """표지 — 색 띠 + 제목 + 메타 표."""
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    c = t.cell(0, 0)
    c.width = Cm(16.4)
    _shade(c._tc, ACCENT_H)
    p = c.paragraphs[0]
    _spacing(p, before=30, after=30)
    _font(p.add_run(band_text), body_font, 11, True, RGBColor(0xFF, 0xFF, 0xFF))
    _no_table_border(t)

    doc.add_paragraph()
    p = doc.add_paragraph()
    _spacing(p, before=36, after=2)
    _font(p.add_run(title), body_font, 30, True, INK)
    p = doc.add_paragraph()
    _spacing(p, after=16)
    _font(p.add_run(subtitle), body_font, 15, False, ACCENT)

    p = doc.add_paragraph()
    _spacing(p, after=30)
    _para_border(p, left=ACCENT_H, width=16)
    _font(p.add_run(tagline), body_font, 10.5, False, INK2)

    tb = doc.add_table(rows=len(meta_rows), cols=2)
    _no_table_border(tb)
    for i, (k, v) in enumerate(meta_rows):
        tb.cell(i, 0).width = Cm(3.6)
        pk = tb.cell(i, 0).paragraphs[0]
        _spacing(pk, after=2)
        _font(pk.add_run(k), body_font, 9.5, True, INK2)
        pv = tb.cell(i, 1).paragraphs[0]
        _spacing(pv, after=2)
        _font(pv.add_run(v), body_font, 9.5, False, INK)
    doc.add_page_break()


def toc(doc, *, heading, note, body_font):
    h = doc.add_paragraph()
    _spacing(h, after=4)
    _font(h.add_run(heading), body_font, 19, True, INK)
    n = doc.add_paragraph()
    _spacing(n, after=14)
    _font(n.add_run(note), body_font, 9, False, INK2)
    _field(doc.add_paragraph(), r'TOC \o "1-2" \h \z \u')
    doc.add_page_break()


def header_footer(doc, *, left_text, right_text, body_font):
    sec = doc.sections[0]
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _font(hp.add_run(left_text), body_font, 8, False, INK2)
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(fp.add_run(""), body_font, 9, False, INK2)
    _field(fp, "PAGE")
    _font(fp.add_run(f"   ·   {right_text}"), body_font, 8, False, INK2)


# ── 본문 요소 ───────────────────────────────────────────────────────────────

def h1(doc, num, text, body_font, *, page_break=True):
    if page_break:
        doc.add_page_break()
    p = doc.add_paragraph(style="Heading 1")
    _spacing(p, before=0, after=3)
    if num:
        _font(p.add_run(f"{num}  "), body_font, 22, True, ACCENT)
    _font(p.add_run(text), body_font, 22, True, INK)
    bar = doc.add_paragraph()
    _spacing(bar, before=0, after=12)
    _para_border(bar, all_sides=None, color=ACCENT_H)
    pPr = bar._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    e = OxmlElement("w:bottom")
    e.set(qn("w:val"), "single")
    e.set(qn("w:sz"), "12")
    e.set(qn("w:space"), "1")
    e.set(qn("w:color"), ACCENT_H)
    bdr.append(e)
    pPr.append(bdr)
    return p


def h2(doc, text, body_font):
    p = doc.add_paragraph(style="Heading 2")
    _spacing(p, before=15, after=4)
    _font(p.add_run(text), body_font, 14.5, True, INK)
    return p


def h3(doc, text, body_font):
    p = doc.add_paragraph(style="Heading 3")
    _spacing(p, before=11, after=3)
    _font(p.add_run(text), body_font, 11.5, True, ACCENT)
    return p


def para(doc, text, body_font, *, size=10.5, color=INK, after=6, indent=0):
    p = doc.add_paragraph()
    _spacing(p, after=after)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    _rich(p, text, body_font, size, color)
    return p


def _rich(p, text, body_font, size, color):
    """``**굵게**`` 와 ``` `코드` ``` 만 해석하는 아주 작은 서식기."""
    import re
    for tok in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**"):
            _font(p.add_run(tok[2:-2]), body_font, size, True, color)
        elif tok.startswith("`") and tok.endswith("`"):
            _font(p.add_run(tok[1:-1]), body_font, size - 0.5, False,
                  RGBColor(0x8A, 0x3B, 0x1F), mono=True)
        else:
            _font(p.add_run(tok), body_font, size, None, color)


def bullets(doc, items, body_font, *, size=10.5):
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        _spacing(p, after=2)
        p.paragraph_format.left_indent = Cm(0.75)
        _rich(p, it, body_font, size, INK)


def checklist(doc, items, body_font):
    for it in items:
        p = doc.add_paragraph()
        _spacing(p, after=2)
        p.paragraph_format.left_indent = Cm(0.5)
        _font(p.add_run("☐  "), body_font, 11, False, INK2)
        _rich(p, it, body_font, 10.5, INK)


def step(doc, n, title, body_font, lines=(), checks=()):
    """번호 원 + 제목 + 설명 (작업카드 A)."""
    t = doc.add_table(rows=1, cols=2)
    _no_table_border(t)
    left = t.cell(0, 0)
    left.width = Cm(1.05)
    _shade(left._tc, STEP_H)
    pn = left.paragraphs[0]
    pn.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(pn, before=3, after=3)
    _font(pn.add_run(str(n)), body_font, 15, True, RGBColor(0xFF, 0xFF, 0xFF))
    right = t.cell(0, 1)
    right.width = Cm(15.0)
    ph = right.paragraphs[0]
    _spacing(ph, before=1, after=3)
    ph.paragraph_format.left_indent = Cm(0.3)
    _font(ph.add_run(title), body_font, 12, True, INK)
    for ln in lines:
        p = right.add_paragraph()
        _spacing(p, after=2)
        p.paragraph_format.left_indent = Cm(0.3)
        _rich(p, ln, body_font, 10.5, INK)
    for ck in checks:
        p = right.add_paragraph()
        _spacing(p, after=1)
        p.paragraph_format.left_indent = Cm(0.3)
        _font(p.add_run("☐  "), body_font, 11, False, INK2)
        _rich(p, ck, body_font, 10.5, INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)


def code(doc, lines, body_font, *, caption=None):
    """터미널에 치는 명령 / 보이는 출력."""
    if caption:
        p = doc.add_paragraph()
        _spacing(p, before=6, after=2)
        _font(p.add_run(caption), body_font, 8.5, True, INK2)
    t = doc.add_table(rows=1, cols=1)
    _no_table_border(t)
    c = t.cell(0, 0)
    c.width = Cm(16.4)
    _shade(c._tc, CODE_H)
    _cell_border(c, left="C9C6BC", width=14)
    first = True
    for ln in lines:
        p = c.paragraphs[0] if first else c.add_paragraph()
        first = False
        _spacing(p, before=2 if p is c.paragraphs[0] else 0, after=0, line=1.2)
        p.paragraph_format.left_indent = Cm(0.25)
        _font(p.add_run(ln if ln else " "), body_font, 9, False,
              RGBColor(0x2A, 0x2A, 0x26), mono=True)
    doc.add_paragraph().paragraph_format.space_after = Pt(5)


def keylist(doc, rows, body_font):
    """``code`` 출력에 번호를 찍어 해설 (화면해설 C)."""
    t = doc.add_table(rows=len(rows), cols=2)
    _no_table_border(t)
    for i, (title, desc) in enumerate(rows):
        lc = t.cell(i, 0)
        lc.width = Cm(0.95)
        pn = lc.paragraphs[0]
        pn.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(pn, before=2, after=4)
        _shade(lc._tc, ACCENT_H)
        _font(pn.add_run(str(i + 1)), body_font, 10.5, True, RGBColor(0xFF, 0xFF, 0xFF))
        rc = t.cell(i, 1)
        rc.width = Cm(15.1)
        pt = rc.paragraphs[0]
        _spacing(pt, before=2, after=1)
        pt.paragraph_format.left_indent = Cm(0.3)
        _font(pt.add_run(title), body_font, 10.5, True, INK)
        pd = rc.add_paragraph()
        _spacing(pd, after=5)
        pd.paragraph_format.left_indent = Cm(0.3)
        _rich(pd, desc, body_font, 10, INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)


_BOX = {"why":  (WHY_H,  "B8860B"),
        "concept": (TINT_H, ACCENT_H),
        "warn": (WARN_H, "A32D2D"),
        "tip":  (TIP_H,  "2E7D4F")}


def box(doc, kind, title, lines, body_font):
    fill, bar = _BOX[kind]
    t = doc.add_table(rows=1, cols=1)
    _no_table_border(t)
    c = t.cell(0, 0)
    c.width = Cm(16.4)
    _shade(c._tc, fill)
    _cell_border(c, left=bar, width=28)
    p = c.paragraphs[0]
    _spacing(p, before=4, after=2)
    p.paragraph_format.left_indent = Cm(0.3)
    _font(p.add_run(title), body_font, 10.5, True, RGBColor.from_string(bar))
    for ln in lines:
        q = c.add_paragraph()
        _spacing(q, after=3)
        q.paragraph_format.left_indent = Cm(0.3)
        _rich(q, ln, body_font, 10, INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(5)


def table(doc, header, rows, body_font, *, widths=None, stage_col=None):
    t = doc.add_table(rows=1 + len(rows), cols=len(header))
    t.style = "Table Grid"
    for j, htxt in enumerate(header):
        cell = t.cell(0, j)
        _shade(cell._tc, TINT_H)
        p = cell.paragraphs[0]
        _spacing(p, before=2, after=2)
        _font(p.add_run(htxt), body_font, 9.5, True, INK)
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            cell = t.cell(i, j)
            p = cell.paragraphs[0]
            _spacing(p, before=2, after=2)
            if stage_col is not None and j == stage_col:
                key = str(val).strip().lower()
                col = STAGE_H.get(key)
                if col:
                    _cell_border(cell, left=col, width=28)
                    _font(p.add_run(str(val)), body_font, 9.5, True,
                          RGBColor.from_string(col))
                    continue
            _rich(p, str(val), body_font, 9.5, INK)
    if widths:
        for j, w in enumerate(widths):
            for i in range(len(rows) + 1):
                t.cell(i, j).width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(5)


def objectives(doc, title, items, body_font):
    box(doc, "concept", title, items, body_font)


def quiz(doc, title, items, body_font, answer_label="답"):
    p = doc.add_paragraph()
    _spacing(p, before=14, after=5)
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    e = OxmlElement("w:top")
    e.set(qn("w:val"), "single")
    e.set(qn("w:sz"), "14")
    e.set(qn("w:space"), "6")
    e.set(qn("w:color"), ACCENT_H)
    bdr.append(e)
    pPr.append(bdr)
    _font(p.add_run(title), body_font, 11, True, ACCENT)
    for i, q in enumerate(items, 1):
        qp = doc.add_paragraph()
        _spacing(qp, after=1)
        qp.paragraph_format.left_indent = Cm(0.3)
        _font(qp.add_run(f"Q{i}.  "), body_font, 10.5, True, INK2)
        _rich(qp, q, body_font, 10.5, INK)
        ap = doc.add_paragraph()
        _spacing(ap, after=6)
        ap.paragraph_format.left_indent = Cm(0.9)
        _font(ap.add_run(f"{answer_label}: " + "_" * 58), body_font, 10, False, INK2)
