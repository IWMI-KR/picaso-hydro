"""
시나리오_폴더구조_비교보고서.md → .docx 변환.
md_to_docx.py 의 로직을 재사용하되 입력/출력 파일만 다름.
"""
import os
import re
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_MD  = os.path.join(ROOT, "시나리오_폴더구조_비교보고서.md")
DST_DOC = os.path.join(ROOT, "시나리오_폴더구조_비교보고서.docx")

FONT_KR = "맑은 고딕"
FONT_MONO = "Consolas"


def _set_font(run, name=FONT_KR, size=10.5, bold=False, italic=False,
              color=None, mono=False):
    if mono:
        name = FONT_MONO
    run.font.name = name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.append(rFonts)
    rFonts.set(qn('w:eastAsia'), name)
    rFonts.set(qn('w:ascii'), name)
    rFonts.set(qn('w:hAnsi'), name)
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = RGBColor(*color)


INLINE_PATTERN = re.compile(
    r"(\*\*(?P<bold>[^*]+)\*\*)"
    r"|(`(?P<code>[^`]+)`)"
    r"|(\[(?P<link_text>[^\]]+)\]\((?P<link_url>[^)]+)\))"
)


def _add_inline(paragraph, text, size=10.5, base_color=(0x20, 0x20, 0x20)):
    pos = 0
    for m in INLINE_PATTERN.finditer(text):
        if m.start() > pos:
            run = paragraph.add_run(text[pos:m.start()])
            _set_font(run, size=size, color=base_color)
        if m.group("bold") is not None:
            run = paragraph.add_run(m.group("bold"))
            _set_font(run, size=size, bold=True, color=base_color)
        elif m.group("code") is not None:
            run = paragraph.add_run(m.group("code"))
            _set_font(run, size=size - 0.5, mono=True,
                      color=(0x88, 0x33, 0x22))
        elif m.group("link_text") is not None:
            run = paragraph.add_run(m.group("link_text"))
            _set_font(run, size=size, color=(0x1F, 0x4E, 0x79))
            run.underline = True
        pos = m.end()
    if pos < len(text):
        run = paragraph.add_run(text[pos:])
        _set_font(run, size=size, color=base_color)


doc = Document()
for section in doc.sections:
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)

normal = doc.styles["Normal"]
normal.font.name = FONT_KR
normal.font.size = Pt(10.5)

with open(SRC_MD, "r", encoding="utf-8") as fh:
    lines = fh.read().splitlines()


def emit_heading(text, level):
    p = doc.add_paragraph()
    run = p.add_run(text)
    sizes = {1: 20, 2: 15, 3: 12.5, 4: 11.5}
    colors = {1: (0x1F, 0x4E, 0x79), 2: (0x1F, 0x4E, 0x79),
              3: (0x2E, 0x74, 0xB5), 4: (0x40, 0x40, 0x40)}
    _set_font(run, size=sizes.get(level, 11), bold=True,
              color=colors.get(level, (0, 0, 0)))
    p.paragraph_format.space_before = Pt(12 if level <= 2 else 6)
    p.paragraph_format.space_after = Pt(4)


def emit_table(rows):
    n_cols = max(len(r) for r in rows)
    rows = [r + [""] * (n_cols - len(r)) for r in rows]
    t = doc.add_table(rows=len(rows), cols=n_cols)
    t.style = "Light Grid Accent 1"
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            tcell = t.rows[i].cells[j]
            tcell.text = ""
            p = tcell.paragraphs[0]
            _add_inline(p, cell, size=9.5)
            if i == 0:
                for run in p.runs:
                    run.bold = True
    return t


def emit_code_block(code_lines, lang=None):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    text = "\n".join(code_lines)
    run = p.add_run(text)
    _set_font(run, size=9, mono=True, color=(0x33, 0x33, 0x33))
    pPr = p._element.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), 'F4F4F4')
    pPr.append(shd)


def emit_quote(text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.6)
    _add_inline(p, text, size=10.5, base_color=(0x55, 0x55, 0x55))
    for run in p.runs:
        run.italic = True


def emit_list_item(text, ordered=False):
    style = "List Number" if ordered else "List Bullet"
    p = doc.add_paragraph(style=style)
    p.paragraph_format.space_after = Pt(0)
    _add_inline(p, text, size=10.5)


def emit_para(text):
    if not text.strip():
        return
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    _add_inline(p, text, size=10.5)


def emit_hr():
    p = doc.add_paragraph()
    pPr = p._element.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), 'BBBBBB')
    pBdr.append(bottom)
    pPr.append(pBdr)


i = 0
N = len(lines)

HEAD_RE = re.compile(r"^(#{1,6})\s+(.+)$")
UL_RE   = re.compile(r"^[\-\*]\s+(.+)$")
OL_RE   = re.compile(r"^\d+\.\s+(.+)$")
TBL_SEP = re.compile(r"^\|?\s*:?[-]+:?(\s*\|\s*:?[-]+:?)+\s*\|?$")


def parse_table_row(line):
    s = line.strip().strip("|").strip()
    cells = [c.strip() for c in s.split("|")]
    return cells


while i < N:
    line = lines[i]
    stripped = line.strip()

    if not stripped:
        i += 1
        continue

    if stripped in ("---", "***", "___"):
        emit_hr()
        i += 1
        continue

    if stripped.startswith("```"):
        lang = stripped[3:].strip() or None
        i += 1
        buf = []
        while i < N and not lines[i].strip().startswith("```"):
            buf.append(lines[i])
            i += 1
        emit_code_block(buf, lang=lang)
        if i < N:
            i += 1
        continue

    m = HEAD_RE.match(line)
    if m:
        level = len(m.group(1))
        text = m.group(2).strip()
        emit_heading(text, level)
        i += 1
        continue

    if stripped.startswith("> "):
        emit_quote(stripped[2:])
        i += 1
        continue

    if "|" in line and i + 1 < N and TBL_SEP.match(lines[i + 1].strip()):
        header = parse_table_row(line)
        i += 2
        body = []
        while i < N and lines[i].strip().startswith("|"):
            body.append(parse_table_row(lines[i]))
            i += 1
        emit_table([header] + body)
        continue

    if UL_RE.match(line):
        while i < N and UL_RE.match(lines[i]):
            emit_list_item(UL_RE.match(lines[i]).group(1), ordered=False)
            i += 1
        continue

    if OL_RE.match(line):
        while i < N and OL_RE.match(lines[i]):
            emit_list_item(OL_RE.match(lines[i]).group(1), ordered=True)
            i += 1
        continue

    buf = [line]
    i += 1
    while i < N:
        nxt = lines[i]
        if not nxt.strip():
            break
        if HEAD_RE.match(nxt) or nxt.strip().startswith("```"):
            break
        if UL_RE.match(nxt) or OL_RE.match(nxt):
            break
        if nxt.strip() in ("---", "***", "___"):
            break
        if "|" in nxt and i + 1 < N and TBL_SEP.match(lines[i + 1].strip()):
            break
        if nxt.strip().startswith("> "):
            break
        buf.append(nxt)
        i += 1
    emit_para(" ".join(b.strip() for b in buf))


doc.save(DST_DOC)
print(f"Saved: {DST_DOC}")
print(f"size : {os.path.getsize(DST_DOC):,} bytes")
