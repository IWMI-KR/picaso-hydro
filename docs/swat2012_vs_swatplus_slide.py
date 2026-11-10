"""
SWAT2012 vs SWAT-Plus 비교 1페이지 슬라이드.
출력: swat2012_vs_swatplus.pptx (docs 폴더)
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

OUT_PPTX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "swat2012_vs_swatplus.pptx")

# colors
COL_2012 = (0x4C, 0x72, 0xB0)
COL_PLUS = (0xC4, 0x4E, 0x52)
COL_TITLE = (0x1F, 0x4E, 0x79)
COL_TEXT = (0x20, 0x20, 0x20)
COL_MUTED = (0x55, 0x55, 0x55)
COL_LINE = (0xCC, 0xCC, 0xCC)

def set_font(run, name="맑은 고딕", size=10, bold=False, color=None, mono=False):
    if mono: name = "Consolas"
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)

def add_text(slide, x, y, w, h, text, size=11, bold=False, color=COL_TEXT,
             align=PP_ALIGN.LEFT, mono=False):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
    tf.margin_top = Inches(0.02); tf.margin_bottom = Inches(0.02)
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run(); r.text = text
    set_font(r, size=size, bold=bold, color=color, mono=mono)
    return tb

def add_lines(slide, x, y, w, h, items, size=10, color=COL_TEXT, mono=False):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
    tf.margin_top = Inches(0.02); tf.margin_bottom = Inches(0.02)
    for k, item in enumerate(items):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        # support tuple (text, bold)
        if isinstance(item, tuple):
            txt, bold = item
        else:
            txt, bold = item, False
        r = p.add_run(); r.text = txt
        set_font(r, size=size, bold=bold, color=color, mono=mono)
    return tb

def add_card(slide, x, y, w, h, fill=(0xF6,0xF6,0xF6), line=COL_LINE):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                   Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(*fill)
    shape.line.color.rgb = RGBColor(*line)
    shape.line.width = Pt(0.75)
    # hide default text
    shape.text_frame.text = ""
    return shape

def shade_cell(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('a:fill')   # not standard for table cells; use w fallback below
    # python-pptx table fill via cell.fill
    cell.fill.solid()
    cell.fill.fore_color.rgb = RGBColor.from_string(hex_color)

def add_table(slide, x, y, w, h, headers, rows, header_color=COL_TITLE,
              col_widths=None, font_size=9.5):
    n_rows = len(rows) + 1
    n_cols = len(headers)
    tbl_shape = slide.shapes.add_table(n_rows, n_cols,
                                       Inches(x), Inches(y),
                                       Inches(w), Inches(h))
    table = tbl_shape.table
    if col_widths:
        total = sum(col_widths)
        for j, cw in enumerate(col_widths):
            table.columns[j].width = Inches(w * cw / total)
    # header
    for j, h_text in enumerate(headers):
        cell = table.cell(0, j)
        cell.fill.solid(); cell.fill.fore_color.rgb = RGBColor(*header_color)
        tf = cell.text_frame
        tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
        tf.margin_top = Inches(0.03); tf.margin_bottom = Inches(0.03)
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
        r = p.add_run(); r.text = h_text
        set_font(r, size=font_size, bold=True, color=(0xFF,0xFF,0xFF))
    # body
    for i, row in enumerate(rows, start=1):
        for j, cell_text in enumerate(row):
            cell = table.cell(i, j)
            # alt row shading
            if i % 2 == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(0xF6,0xF6,0xF6)
            else:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(0xFF,0xFF,0xFF)
            tf = cell.text_frame
            tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
            tf.margin_top = Inches(0.02); tf.margin_bottom = Inches(0.02)
            p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
            r = p.add_run(); r.text = cell_text
            # column 0 bold, cols 1/2 normal
            set_font(r, size=font_size, bold=(j == 0),
                     color=(COL_2012 if j==1 else COL_PLUS if j==2 else COL_TEXT))
    return tbl_shape

# ───────────── slide ─────────────
prs = Presentation()
prs.slide_width  = Inches(13.333)
prs.slide_height = Inches(7.5)
slide = prs.slides.add_slide(prs.slide_layouts[6])

# title
add_text(slide, 0.30, 0.12, 12.7, 0.55,
         "SWAT2012 vs SWAT-Plus — 핵심 비교",
         size=22, bold=True, color=COL_TITLE)

# subtitle
add_text(slide, 0.30, 0.74, 12.7, 0.35,
         "Soil and Water Assessment Tool 두 세대의 구조·입출력·생태계 차이 한눈에 보기  |  swat_py 패키지 기준",
         size=10.5, color=COL_MUTED)

# ── 좌/우 카드 (모델 개요) ──
# left card: SWAT2012
add_card(slide, 0.30, 1.20, 6.30, 1.55, fill=(0xEC,0xF2,0xFA))
add_text(slide, 0.45, 1.25, 6.0, 0.45, "SWAT2012",
         size=16, bold=True, color=COL_2012)
add_text(slide, 0.45, 1.62, 6.0, 0.35,
         "USDA-ARS / Texas A&M, 1990s~ · 안정·검증된 레거시 표준",
         size=10, color=COL_MUTED)
add_lines(slide, 0.45, 1.95, 6.0, 0.85, [
    "• 공간단위: Subbasin → HRU(Hydrologic Response Unit, 비공간)",
    "• 채널: subbasin당 단일 reach, output.rch 단일 출력",
    "• 관리: lookup table 기반 일정한 스케줄",
    "• GIS: ArcSWAT(ArcGIS, 유료) / QSWAT(QGIS)",
], size=10)

# right card: SWAT-Plus
add_card(slide, 6.75, 1.20, 6.30, 1.55, fill=(0xFB,0xEE,0xEE))
add_text(slide, 6.90, 1.25, 6.0, 0.45, "SWAT-Plus (SWAT+)",
         size=16, bold=True, color=COL_PLUS)
add_text(slide, 6.90, 1.62, 6.0, 0.35,
         "USDA-ARS, 2017~ · 모듈형 재작성, 활발한 개발 중",
         size=10, color=COL_MUTED)
add_lines(slide, 6.90, 1.95, 6.0, 0.85, [
    "• 공간단위: Subbasin → LSU(Landscape Unit) → HRU, 공간 흐름",
    "• 채널: 객체화(channel.*), subbasin당 다수 채널",
    "• 관리: decision table(dtbl) — 조건부 동적 스케줄",
    "• GIS: QSWAT+ (QGIS, 무료)",
], size=10)

# ── 비교표 ──
headers = ["항목", "SWAT2012", "SWAT-Plus"]
rows = [
    ["출시 / 세대",      "1990s~, 안정 (frozen)",        "2017~, 활발한 개발"],
    ["언어 / 구조",      "Fortran 77/90, 절차형",         "Fortran 2003, 모듈·OOP"],
    ["공간 위계",        "Subbasin → HRU (lumped)",       "Subbasin → LSU → HRU"],
    ["네트워크 연결",     "고정 (HRU→reach→subbasin)",     "object connectivity (.con)"],
    ["채널 출력",        "output.rch (단일 reach)",       "channel_sd_day.txt (다채널)"],
    ["관리 방식",        "lookup table (정적)",           "decision table (동적, 조건부)"],
    ["DB",              "ASCII + Access (.mdb)",          "SQLite + ASCII"],
    ["GIS 인터페이스",    "ArcSWAT / QSWAT",                "QSWAT+ (QGIS, 무료)"],
    ["보정 도구",        "SWAT-CUP (SUFI-2, GLUE 등)",    "SWAT+ Toolbox, IPEAT-Plus, swat_py"],
    ["습도 단위 (입력)",   "%",                              "0–1 fraction (자동 변환)"],
    ["풍속 (입력)",       "10 m 또는 2 m",                   "2 m (ws2_ms)"],
    ["기상 가중치 인덱스", "(파일별 분산)",                   "weather-sta.cli 통합"],
    ["향후 방향",        "유지보수 모드",                    "SWAT2012을 점진 대체"],
]
add_table(slide, 0.30, 2.95, 8.45, 4.10, headers, rows,
          col_widths=[2.3, 3.0, 3.1], font_size=9.5)

# ── 우측 하단 패널: swat_py 설정 팁 + 권장 사용 ──
add_card(slide, 8.95, 2.95, 4.10, 2.05, fill=(0xF6,0xF6,0xF6))
add_text(slide, 9.10, 3.00, 3.9, 0.35, "swat_py 에서 모델 선택",
         size=12, bold=True, color=COL_TITLE)
add_lines(slide, 9.10, 3.35, 3.9, 1.60, [
    ("swat_py.yaml:", True),
    ("  model:", False),
    ("    type: swat_plus       # 또는 swat2012", False),
    ("    executable: SWAT-Plus.exe", False),
    ("", False),
    ("→ 출력 폴더 자동 분리:", False),
    ("  swat_plus  → 3_swatplus/", False),
    ("  swat2012   → 3_swat2012/", False),
], size=9.5, mono=True, color=COL_TEXT)

add_card(slide, 8.95, 5.10, 4.10, 1.95, fill=(0xF6,0xF6,0xF6))
add_text(slide, 9.10, 5.15, 3.9, 0.35, "권장 사용 가이드",
         size=12, bold=True, color=COL_TITLE)
add_lines(slide, 9.10, 5.50, 3.9, 1.50, [
    ("✓ 신규 프로젝트 → SWAT-Plus 권장",  True),
    ("  · 모듈 구조, decision table, QSWAT+ 무료", False),
    ("  · 활발한 개발·커뮤니티·교육 자료", False),
    ("", False),
    ("✓ 기존 모델 보완 → SWAT2012 유지", True),
    ("  · 이미 보정·검증된 모델 자산 활용", False),
    ("  · SWAT-CUP 워크플로우와 연속성", False),
], size=9.5)

# footer
add_text(slide, 0.30, 7.05, 12.7, 0.35,
         "Source: SWAT/SWAT-Plus official docs (swat.tamu.edu) · swat_py v0.1.0 manual · IWMI-KR",
         size=8.5, color=(0x80,0x80,0x80))

prs.save(OUT_PPTX)
print(f"Saved: {OUT_PPTX}")
print(f"size: {os.path.getsize(OUT_PPTX):,} bytes")
