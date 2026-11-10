"""
PICASO-Hydro 개발 최종 발표 PPTX 생성기.

docs/ 폴더의 매뉴얼/보고서 콘텐츠를 종합하여 16:9 발표용 슬라이드를 생성한다.
출력: PICASO-Hydro_최종발표.pptx
"""
from __future__ import annotations

import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

OUT_PPTX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "PICASO-Hydro_최종발표.pptx")

# ───────── 색상 팔레트 ─────────
COL_TITLE = (0x1F, 0x4E, 0x79)   # 메인 진청
COL_ACC1  = (0x4C, 0x72, 0xB0)   # util_py / SWAT2012
COL_ACC2  = (0xC4, 0x4E, 0x52)   # acidwg_py / SWAT-Plus
COL_ACC3  = (0x55, 0xA8, 0x68)   # swat_py
COL_GOLD  = (0xD4, 0xA0, 0x17)
COL_TEXT  = (0x20, 0x20, 0x20)
COL_MUTED = (0x55, 0x55, 0x55)
COL_LINE  = (0xCC, 0xCC, 0xCC)
COL_BG_BLUE  = (0xEC, 0xF2, 0xFA)
COL_BG_RED   = (0xFB, 0xEE, 0xEE)
COL_BG_GREEN = (0xEC, 0xF6, 0xEE)
COL_BG_GREY  = (0xF6, 0xF6, 0xF6)


# ───────── 헬퍼 ─────────
def font(run, name="맑은 고딕", size=11, bold=False, color=None, mono=False):
    run.font.name = "Consolas" if mono else name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)


def text(slide, x, y, w, h, txt, size=11, bold=False, color=COL_TEXT,
         align=PP_ALIGN.LEFT, mono=False):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
    tf.margin_top = Inches(0.02); tf.margin_bottom = Inches(0.02)
    p = tf.paragraphs[0]; p.alignment = align
    r = p.add_run(); r.text = txt
    font(r, size=size, bold=bold, color=color, mono=mono)
    return tb


def lines(slide, x, y, w, h, items, size=10, color=COL_TEXT, mono=False):
    """items: list of str | (text, bold) | (text, bold, color)."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
    tf.margin_top = Inches(0.02); tf.margin_bottom = Inches(0.02)
    for k, item in enumerate(items):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        if isinstance(item, tuple):
            txt = item[0]
            bold = item[1] if len(item) > 1 else False
            col = item[2] if len(item) > 2 else color
        else:
            txt, bold, col = item, False, color
        r = p.add_run(); r.text = txt
        font(r, size=size, bold=bold, color=col, mono=mono)
    return tb


def card(slide, x, y, w, h, fill=COL_BG_GREY, line=COL_LINE):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb = RGBColor(*fill)
    s.line.color.rgb = RGBColor(*line); s.line.width = Pt(0.75)
    s.text_frame.text = ""
    return s


def rect(slide, x, y, w, h, fill, line=None):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb = RGBColor(*fill)
    if line is None: line = fill
    s.line.color.rgb = RGBColor(*line)
    s.text_frame.text = ""
    return s


def arrow(slide, x, y, w, h, fill):
    s = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb = RGBColor(*fill)
    s.line.color.rgb = RGBColor(*fill)
    s.text_frame.text = ""
    return s


def table(slide, x, y, w, h, headers, rows, col_widths=None,
          header_color=COL_TITLE, font_size=10):
    n_rows = len(rows) + 1
    n_cols = len(headers)
    shape = slide.shapes.add_table(n_rows, n_cols,
                                   Inches(x), Inches(y),
                                   Inches(w), Inches(h))
    tbl = shape.table
    if col_widths:
        total = sum(col_widths)
        for j, cw in enumerate(col_widths):
            tbl.columns[j].width = Inches(w * cw / total)
    # header
    for j, h_text in enumerate(headers):
        cell = tbl.cell(0, j)
        cell.fill.solid(); cell.fill.fore_color.rgb = RGBColor(*header_color)
        tf = cell.text_frame
        tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
        tf.margin_top = Inches(0.03); tf.margin_bottom = Inches(0.03)
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
        r = p.add_run(); r.text = h_text
        font(r, size=font_size, bold=True, color=(0xFF, 0xFF, 0xFF))
    # body
    for i, row in enumerate(rows, start=1):
        for j, cell_text in enumerate(row):
            cell = tbl.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(*(COL_BG_GREY if i % 2 == 0
                                                  else (0xFF, 0xFF, 0xFF)))
            tf = cell.text_frame
            tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
            tf.margin_top = Inches(0.02); tf.margin_bottom = Inches(0.02)
            p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
            r = p.add_run(); r.text = cell_text
            font(r, size=font_size, bold=(j == 0), color=COL_TEXT)
    return shape


def slide_header(slide, idx, total, title, subtitle=None):
    """모든 본문 슬라이드 공통 헤더 + 푸터."""
    # 좌측 컬러 바
    rect(slide, 0.0, 0.0, 0.18, 7.5, COL_TITLE)
    # 슬라이드 번호 / 라벨
    text(slide, 12.0, 0.18, 1.2, 0.30, f"{idx} / {total}",
         size=9, color=COL_MUTED, align=PP_ALIGN.RIGHT)
    # 타이틀
    text(slide, 0.40, 0.18, 11.5, 0.55, title,
         size=22, bold=True, color=COL_TITLE)
    if subtitle:
        text(slide, 0.40, 0.78, 12.6, 0.34, subtitle,
             size=11, color=COL_MUTED)
    # 헤더 구분선
    rect(slide, 0.40, 1.16, 12.6, 0.012, COL_LINE)
    # 푸터
    text(slide, 0.40, 7.12, 12.6, 0.28,
         "PICASO-Hydro · IWMI-KR · 2026  |  util_py 0.1.0 · acidwg_py 1.0.0 · swat_py 0.1.0",
         size=8.5, color=COL_MUTED)


# ───────── 프레젠테이션 초기화 ─────────
prs = Presentation()
prs.slide_width  = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]

TOTAL = 14  # 슬라이드 총 수 (표지 1 + 본문 13)


# ─────────────────────────────────────
# 슬라이드 1 — 표지
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
# 배경 그라데이션 효과 (사각형 두 개)
rect(s, 0, 0, 13.333, 7.5, COL_TITLE)
rect(s, 0, 5.8, 13.333, 1.7, (0x15, 0x3A, 0x5C))
# 좌측 강조 바
rect(s, 0.9, 2.30, 0.12, 1.40, (0xFF, 0xFF, 0xFF))

text(s, 1.20, 2.20, 11.0, 0.55,
     "PICASO-Hydro",
     size=14, bold=True, color=(0xD4, 0xE3, 0xF2))
text(s, 1.20, 2.60, 11.0, 1.10,
     "SWAT 기반 수문 모델링 자동화 패키지 개발",
     size=36, bold=True, color=(0xFF, 0xFF, 0xFF))
text(s, 1.20, 3.78, 11.0, 0.55,
     "Python 자동화 파이프라인 · 1000-멤버 앙상블 · 기후변화 시나리오",
     size=16, color=(0xC8, 0xD8, 0xE6))

# 핵심 산출 칩 3개
chip_y = 4.85
for i, (label, col, desc) in enumerate([
    ("util_py",   COL_ACC1, "자료 수집·표준화·검증"),
    ("acidwg_py", COL_ACC2, "1000-멤버 다운스케일링"),
    ("swat_py",   COL_ACC3, "모델 실행·보정·예보"),
]):
    cx = 1.20 + i * 3.85
    rect(s, cx, chip_y, 3.55, 0.50, col)
    text(s, cx + 0.10, chip_y + 0.08, 3.35, 0.35,
         label, size=14, bold=True, color=(0xFF, 0xFF, 0xFF))
    text(s, cx + 0.10, chip_y + 0.55, 3.35, 0.30,
         desc, size=10, color=(0xC8, 0xD8, 0xE6))

# 하단 메타
text(s, 0.9, 6.05, 12.0, 0.40,
     "개발 최종 발표",
     size=20, bold=True, color=(0xFF, 0xFF, 0xFF))
text(s, 0.9, 6.55, 12.0, 0.34,
     "유역통합관리연구원(IWMI-KR) · APCC 계절예측 기반 PICASO-Hydro 사업 · 2026-05-12",
     size=12, color=(0xC8, 0xD8, 0xE6))
text(s, 0.9, 6.93, 12.0, 0.34,
     "MIT License  ·  github.com/IWMI-KR/picaso-hydro",
     size=10, color=(0x9F, 0xB6, 0xCB))


# ─────────────────────────────────────
# 슬라이드 2 — 목차
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 2, TOTAL, "발표 목차",
             "프로젝트 개요부터 향후 과제까지 13개 주제")

agenda = [
    ("1.  프로젝트 개요 — 배경·목표·범위",                          COL_TITLE),
    ("2.  산출물 구성 — 3개 Python 패키지",                          COL_TITLE),
    ("3.  시스템 아키텍처 — 데이터 흐름",                            COL_TITLE),
    ("4.  util_py — 자료 수집·표준화·검증",                          COL_ACC1),
    ("5.  acidwg_py — 1000-멤버 다운스케일링",                        COL_ACC2),
    ("6.  swat_py — 핵심 기능과 표준 7단계 워크플로우",              COL_ACC3),
    ("7.  SWAT2012 / SWAT-Plus 동시 지원",                            COL_TITLE),
    ("8.  기상자료 표준 std CSV + Stitching",                         COL_TITLE),
    ("9.  자동 보정 — 5종 알고리즘 + 다목적 가중합",                COL_TITLE),
    ("10. 성능 평가 지표 7종 + 디렉토리 옵션 C",                     COL_TITLE),
    ("11. 기후변화 시나리오 + 앙상블 확률예보",                       COL_TITLE),
    ("12. 시각화 & 대시보드",                                          COL_TITLE),
    ("13. 테스트 현황 · 결론 · 향후 과제",                            COL_TITLE),
]
# 2단 배치
left = agenda[:7]; right = agenda[7:]
for i, (txt, col) in enumerate(left):
    y = 1.55 + i * 0.55
    rect(s, 0.60, y + 0.10, 0.08, 0.30, col)
    text(s, 0.85, y, 6.0, 0.45, txt, size=14, color=COL_TEXT)
for i, (txt, col) in enumerate(right):
    y = 1.55 + i * 0.55
    rect(s, 7.00, y + 0.10, 0.08, 0.30, col)
    text(s, 7.25, y, 6.0, 0.45, txt, size=14, color=COL_TEXT)


# ─────────────────────────────────────
# 슬라이드 3 — 프로젝트 개요
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 3, TOTAL, "프로젝트 개요",
             "APCC 계절예측 활용 SWAT 수문 모델링 자동화 — 왜? 무엇을? 누가?")

# 배경 카드
card(s, 0.40, 1.30, 6.30, 2.85, fill=COL_BG_BLUE)
text(s, 0.55, 1.38, 6.0, 0.40,
     "배경 (Background)", size=14, bold=True, color=COL_TITLE)
lines(s, 0.55, 1.80, 6.0, 2.30, [
    ("• 수문 모델(SWAT)은 입력 자료 수집·전처리·보정·검증에",      False),
    ("   수개월의 수작업이 필요 — 재현성과 확장성에 한계",          False),
    ("• APCC 계절예측은 R 기반(rACID, rSWAT) 워크플로우로 제공",   False),
    ("   되어 Python 생태계 활용 및 운영 자동화 어려움",            False),
    ("• 기후변화·앙상블 예보의 1000-멤버 단위 분석은 수작업으로", False),
    ("   처리 불가 → 운영 가능한 자동화 파이프라인 부재",            False),
    ("• 다국적·도서국가(예: Cook Islands) 적용을 위한 통합",        False),
    ("   재현 가능 표준이 필요",                                       False),
], size=11)

# 목표 카드
card(s, 6.85, 1.30, 6.10, 2.85, fill=COL_BG_RED)
text(s, 7.00, 1.38, 6.0, 0.40,
     "목표 (Objectives)", size=14, bold=True, color=COL_TITLE)
lines(s, 7.00, 1.80, 5.9, 2.30, [
    ("① 입력 자료 수집·표준화 자동화",         True, COL_ACC2),
    ("    DEM/LULC/Soil/기상/유량 일괄 수집",  False),
    ("② 1000-멤버 통계 다운스케일링 구현",     True, COL_ACC2),
    ("    rACID R 패키지 → Python 포팅",       False),
    ("③ SWAT2012·SWAT-Plus 자동 실행·보정",   True, COL_ACC2),
    ("    5종 알고리즘 + 다목적 가중합",        False),
    ("④ 기후변화·앙상블 예보 운영화",          True, COL_ACC2),
    ("    GCM × RCP 매트릭스, 1000-멤버 통합", False),
], size=11)

# 하단: 특징/범위
card(s, 0.40, 4.30, 12.55, 2.65, fill=COL_BG_GREY)
text(s, 0.55, 4.38, 12.2, 0.40,
     "핵심 특징 (Key Features)", size=14, bold=True, color=COL_TITLE)
feat_y = 4.85
feats = [
    ("재현성",    "YAML 단일 설정 + Git 버전관리\n동일 입력 → 동일 출력 보장"),
    ("확장성",    "도서국가(Cook Islands)부터\n대륙규모까지 동일 코드"),
    ("자동화",    "Stage 1·2 CLI 진입점 10종\n원-커맨드 자료 수집·실행"),
    ("표준화",    "11컬럼 std CSV 단일 포맷\nERA5/GSOD/관측 통합"),
    ("운영성",    "1000-멤버 병렬 + 진행률\n네트워크 드라이브 호환"),
]
w_each = 12.55 / len(feats) - 0.10
for i, (k, v) in enumerate(feats):
    cx = 0.55 + i * (w_each + 0.10)
    rect(s, cx, feat_y, w_each, 0.45, COL_TITLE)
    text(s, cx + 0.10, feat_y + 0.06, w_each - 0.20, 0.35,
         k, size=13, bold=True, color=(0xFF, 0xFF, 0xFF))
    text(s, cx + 0.05, feat_y + 0.55, w_each, 1.40,
         v, size=10, color=COL_TEXT)


# ─────────────────────────────────────
# 슬라이드 4 — 산출물 (3개 패키지)
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 4, TOTAL, "산출물 — 3개 Python 패키지",
             "각 패키지는 독립 설치 가능하며, 표준 std CSV 포맷으로 연동된다.")

panels = [
    ("util_py", "v0.1.0", COL_ACC1, COL_BG_BLUE,
     "SWAT 입력 자료 자동 수집·가공",
     [
         "• DEM / LULC / Soil / Basin / River 자동 다운로드",
         "• ERA5 (CDS API) · GSOD · CARAVAN · USGS NWIS",
         "• 표준 11컬럼 std CSV 포맷 통합",
         "• ERA5 vs 관측 산점 검증 (논문급 그래프)",
         "• Stage 1 (국가 전체) / Stage 2 (영역 클립)",
     ],
     "243 tests passed", "8 CLI 진입점"),
    ("acidwg_py", "v1.0.0", COL_ACC2, COL_BG_RED,
     "APCC 계절예측 통계 다운스케일링",
     [
         "• rACID (R) → Python 포팅",
         "• 1,000-멤버 일자료 앙상블 생성",
         "• Quantile mapping + 시간 분해",
         "• util_py 표준 포맷 직접 입력",
         "• operational + hindcast 모두 지원",
     ],
     "108 tests passed", "2 CLI 진입점"),
    ("swat_py", "v0.1.0", COL_ACC3, COL_BG_GREEN,
     "SWAT/SWAT-Plus 자동 실행·보정·예보",
     [
         "• SWAT2012 / SWAT-Plus 동시 지원",
         "• 자동 보정 5종 + 다목적 가중합",
         "• 기후변화 GCM × RCP 매트릭스",
         "• 1000-멤버 앙상블 확률예보 통합",
         "• 7개 성능지표 자동 계산",
     ],
     "45 tests passed", "JSX 대시보드"),
]
pw = 4.10; px0 = 0.40
for i, (name, ver, col, bg, sub, items, t1, t2) in enumerate(panels):
    x = px0 + i * (pw + 0.10)
    card(s, x, 1.35, pw, 5.55, fill=bg)
    # 헤더 바
    rect(s, x, 1.35, pw, 0.65, col)
    text(s, x + 0.15, 1.42, pw - 0.30, 0.40, name,
         size=18, bold=True, color=(0xFF, 0xFF, 0xFF))
    text(s, x + 0.15, 1.78, pw - 0.30, 0.25, ver,
         size=10, color=(0xE0, 0xE0, 0xE0))
    # 한줄 설명
    text(s, x + 0.15, 2.15, pw - 0.30, 0.35, sub,
         size=12, bold=True, color=COL_TITLE)
    # 기능
    lines(s, x + 0.15, 2.55, pw - 0.30, 2.80, items, size=10.5)
    # 메트릭 박스
    rect(s, x + 0.15, 5.55, pw - 0.30, 0.50, (0xFF, 0xFF, 0xFF),
         line=COL_LINE)
    text(s, x + 0.25, 5.62, pw - 0.50, 0.35,
         f"✓ {t1}", size=10, bold=True, color=col)
    rect(s, x + 0.15, 6.15, pw - 0.30, 0.50, (0xFF, 0xFF, 0xFF),
         line=COL_LINE)
    text(s, x + 0.25, 6.22, pw - 0.50, 0.35,
         f"✓ {t2}", size=10, bold=True, color=col)


# ─────────────────────────────────────
# 슬라이드 5 — 시스템 아키텍처 / 데이터 흐름
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 5, TOTAL, "시스템 아키텍처 — 데이터 흐름",
             "외부 자료원 → util_py → acidwg_py → swat_py → 결과/대시보드")

# 5단 흐름도
boxes = [
    ("외부 자료원",   "CDS API\nNOAA GSOD\nCARAVAN\nUSGS NWIS\nAPCC 예측", COL_MUTED, COL_BG_GREY),
    ("util_py",       "DEM/LULC/Soil\nERA5/GSOD\n표준 std CSV\nERA5 검증",   COL_ACC1,  COL_BG_BLUE),
    ("acidwg_py",     "PICASO 변환\n1000-멤버\n앙상블 생성",                   COL_ACC2,  COL_BG_RED),
    ("swat_py",       "TxtInOut 실행\n자동 보정\n기후변화\n앙상블 예보",       COL_ACC3,  COL_BG_GREEN),
    ("결과 / 산출물", "성능지표 표\n시계열·산점도\nJSX 대시보드\n기후 Δ 분석", COL_GOLD,  (0xFB, 0xF3, 0xDC)),
]
bx0 = 0.40; bw = 2.30; bgap = 0.20
by = 1.50; bh = 2.20
arrow_w = 0.20
for i, (name, body, col, bg) in enumerate(boxes):
    x = bx0 + i * (bw + bgap + arrow_w)
    card(s, x, by, bw, bh, fill=bg)
    rect(s, x, by, bw, 0.50, col)
    text(s, x + 0.10, by + 0.07, bw - 0.20, 0.40, name,
         size=13, bold=True, color=(0xFF, 0xFF, 0xFF))
    lines(s, x + 0.10, by + 0.60, bw - 0.20, 1.55,
          [(line, False) for line in body.split("\n")], size=10)
    if i < len(boxes) - 1:
        ax = x + bw + 0.05
        arrow(s, ax, by + bh / 2 - 0.15, arrow_w + bgap - 0.10, 0.30, col)

# 하단: 표준 std CSV 포맷
card(s, 0.40, 4.20, 7.60, 2.70, fill=COL_BG_GREY)
text(s, 0.55, 4.28, 7.3, 0.40,
     "통합 키 — 표준 std CSV (11 컬럼)",
     size=14, bold=True, color=COL_TITLE)
lines(s, 0.55, 4.70, 7.3, 2.10, [
    ("date, pcp_mm, tmax_c, tmin_c, tavg_c, tdew_c,",         False, COL_TEXT),
    ("hmd_pct, slr_mjm2, ws10_ms, ws2_ms, source",            False, COL_TEXT),
    ("",                                                       False, COL_TEXT),
    ("• 모든 자료원(ERA5/GSOD/관측/예보)을 동일 포맷으로 통합", False),
    ("• 결측은 빈 셀 또는 NaN → 변환 시 −99.0 자동 채움",     False),
    ("• util_py 가 생성 → acidwg_py · swat_py 가 직접 소비",   False),
    ("• 단위·컬럼 컨벤션이 정해져 있어 휴먼에러 차단",          False),
], size=10.5, mono=False)
# 코드 라인
lines(s, 0.55, 5.20, 7.3, 0.50, [
    ("date,pcp_mm,tmax_c,tmin_c,...,source",     True),
    ("2010-01-01,0.0,28.4,22.1,...,ERA5",        False),
], size=9.5, mono=True, color=(0x33, 0x33, 0x33))

# 의존 관계
card(s, 8.10, 4.20, 4.85, 2.70, fill=COL_BG_BLUE)
text(s, 8.25, 4.28, 4.6, 0.40,
     "패키지 의존 관계", size=14, bold=True, color=COL_TITLE)
lines(s, 8.25, 4.70, 4.6, 2.10, [
    ("util_py",                                          True, COL_ACC1),
    ("    └ rasterio, geopandas, cdsapi, netCDF4",       False, COL_MUTED),
    ("",                                                  False, COL_TEXT),
    ("acidwg_py",                                         True, COL_ACC2),
    ("    └ util_py 표준 std CSV 포맷",                  False),
    ("    └ scipy, scikit-learn, statsmodels",            False, COL_MUTED),
    ("",                                                  False, COL_TEXT),
    ("swat_py",                                           True, COL_ACC3),
    ("    └ acidwg_py 1000-멤버 출력",                    False),
    ("    └ TxtInOut + SWAT-Plus.exe",                    False, COL_MUTED),
], size=10.5)


# ─────────────────────────────────────
# 슬라이드 6 — util_py
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 6, TOTAL, "util_py — 자료 수집·표준화·검증",
             "Stage 1 (국가 전체) → Stage 2 (영역 클립)의 2단계 CLI 워크플로우")

# Stage 1
card(s, 0.40, 1.35, 6.30, 3.10, fill=COL_BG_BLUE)
text(s, 0.55, 1.43, 6.0, 0.40,
     "Stage 1 — 국가 전체 자료 수집", size=14, bold=True, color=COL_ACC1)
lines(s, 0.55, 1.85, 6.0, 2.50, [
    ("util-gis-download",                                          True, COL_TITLE),
    ("    DEM · 행정경계 · LULC · Soil · Basin · River",          False, COL_MUTED),
    ("util-era5-download / extract",                                True, COL_TITLE),
    ("    CDS API → NC → 격자점 hourly/daily CSV",                False, COL_MUTED),
    ("util-gsod-download",                                          True, COL_TITLE),
    ("    NOAA GSOD 일자료 + 지점 메타",                          False, COL_MUTED),
    ("util-weather-standardize",                                    True, COL_TITLE),
    ("    ERA5/GSOD/local → 11컬럼 std CSV 통합",                 False, COL_MUTED),
    ("util-weather-validate",                                       True, COL_TITLE),
    ("    ERA5 vs 관측 산점 검증 (R², RMSE, Bias)",                False, COL_MUTED),
], size=10.5)

# Stage 2
card(s, 6.85, 1.35, 6.10, 3.10, fill=COL_BG_BLUE)
text(s, 7.00, 1.43, 5.8, 0.40,
     "Stage 2 — SWAT 모델링 영역 클립",
     size=14, bold=True, color=COL_ACC1)
lines(s, 7.00, 1.85, 5.8, 2.50, [
    ("util-gis-clip-to-user --area <name>",         True, COL_TITLE),
    ("    국가 단위 자료를 SWAT 모델 영역으로 절단", False, COL_MUTED),
    ("    DEM, LULC, Soil, 행정, 하천망 일괄 클립", False, COL_MUTED),
    ("",                                              False),
    ("util-streamflow-download",                      True, COL_TITLE),
    ("    CARAVAN / USGS NWIS 유량 일자료 자동 매칭", False, COL_MUTED),
    ("",                                              False),
    ("환경변수 1개로 모든 경로 자동 산출",           True, COL_ACC1),
    ("    set PICASO_ROOT=D:\\MyProject",            False, COL_MUTED),
    ("    → 0_database, 3_swatplus 등 자동 배치",   False, COL_MUTED),
], size=10.5)

# 하단: 표준화 11컬럼 (요점 강조) + ERA5 검증
card(s, 0.40, 4.60, 8.10, 2.30, fill=COL_BG_GREY)
text(s, 0.55, 4.68, 7.8, 0.40,
     "표준 std CSV 11컬럼 — 모든 후속 패키지의 입력",
     size=13, bold=True, color=COL_TITLE)
table(s, 0.55, 5.10, 7.80, 1.75,
      ["컬럼", "단위", "설명"],
      [
          ["date",    "YYYY-MM-DD", "일자 (필수, 일별 연속)"],
          ["pcp_mm",  "mm",         "일강수량"],
          ["tmax/tmin/tavg_c", "°C", "일최고/최저/평균 기온"],
          ["tdew_c / hmd_pct", "°C / %", "이슬점·상대습도 (자동 fraction)"],
          ["slr_mjm2 / ws10_ms / ws2_ms", "MJ/m²·m/s", "일사·풍속(10m·2m)"],
          ["source",  "str", "자료 출처 라벨 (GSOD/ERA5/OBS+ERA5)"],
      ],
      col_widths=[2.5, 2.0, 5.0], font_size=9.5)

card(s, 8.60, 4.60, 4.35, 2.30, fill=COL_BG_BLUE)
text(s, 8.75, 4.68, 4.1, 0.40,
     "ERA5 vs 관측 검증",
     size=13, bold=True, color=COL_ACC1)
lines(s, 8.75, 5.10, 4.1, 1.75, [
    ("• 변수별 산점도 + 회귀선",          False),
    ("• 지표: R², RMSE, Bias, MAE",        False),
    ("• 월별/연별/계절별 분해",            False),
    ("• 다국가 일괄 비교 (논문 그림 수준)", False),
    ("• util-weather-validate 단일 명령",   True,  COL_ACC1),
], size=10.5)


# ─────────────────────────────────────
# 슬라이드 7 — acidwg_py
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 7, TOTAL, "acidwg_py — 1000-멤버 통계 다운스케일링",
             "APCC 계절예측 (월/계절 단위) → 일자료 1,000 멤버 앙상블")

# 다이어그램: 입력 → 변환 → 출력
diag_y = 1.45; diag_h = 0.65
boxes = [
    ("APCC 계절예측",   "월·계절 단위\n원본 forecast", COL_MUTED, (0xE5, 0xE5, 0xE5)),
    ("acidwg-picaso-convert", "표준 forecast\nCSV 포맷", COL_ACC1, COL_BG_BLUE),
    ("acidwg-run",      "1000-멤버\n일자료 생성",     COL_ACC2, COL_BG_RED),
    ("std CSV 출력",    "swat_py 입력\n11컬럼 포맷",   COL_ACC3, COL_BG_GREEN),
]
bw = 2.85; gap = 0.45
for i, (name, body, col, bg) in enumerate(boxes):
    x = 0.40 + i * (bw + gap)
    card(s, x, diag_y, bw, 1.40, fill=bg)
    rect(s, x, diag_y, bw, 0.45, col)
    text(s, x + 0.10, diag_y + 0.05, bw - 0.20, 0.35,
         name, size=12, bold=True, color=(0xFF, 0xFF, 0xFF))
    lines(s, x + 0.10, diag_y + 0.55, bw - 0.20, 0.85,
          [(line, False) for line in body.split("\n")], size=10)
    if i < len(boxes) - 1:
        arrow(s, x + bw + 0.05, diag_y + 0.50, gap - 0.10, 0.40, COL_TITLE)

# 핵심 알고리즘
card(s, 0.40, 3.10, 6.30, 3.85, fill=COL_BG_BLUE)
text(s, 0.55, 3.18, 6.0, 0.40,
     "핵심 알고리즘 (rACID 포팅)",
     size=14, bold=True, color=COL_ACC2)
lines(s, 0.55, 3.60, 6.0, 3.30, [
    ("① Quantile Mapping (분위수 매핑)",                  True,  COL_TITLE),
    ("    GCM 분포 → 관측 분포 일치 보정",                 False),
    ("    변수별 별도 캘리브레이션 (pcp/tmax/tmin)",        False, COL_MUTED),
    ("",                                                    False),
    ("② 시간 분해 (월 → 일)",                              True,  COL_TITLE),
    ("    K-NN 유사 일자 검색 + 무작위 셔플",                False),
    ("    기상자료 시공간 일관성 보존",                      False, COL_MUTED),
    ("",                                                    False),
    ("③ 1,000-멤버 앙상블 생성",                           True,  COL_TITLE),
    ("    초기조건 변동 + 확률적 잡음",                      False),
    ("    operational + hindcast 동일 코드",                False, COL_MUTED),
    ("",                                                    False),
    ("④ 표준 std CSV 11컬럼 출력",                         True,  COL_TITLE),
    ("    멤버별 폴더 분리 → swat_py 직접 소비 가능",        False),
], size=10.5)

# 사용 예시
card(s, 6.85, 3.10, 6.10, 3.85, fill=COL_BG_RED)
text(s, 7.00, 3.18, 5.8, 0.40,
     "사용 예시 — 2단계 CLI",
     size=14, bold=True, color=COL_ACC2)
lines(s, 7.00, 3.60, 5.8, 1.10, [
    ("# 1) APCC 원본 → forecast 표준 포맷",      False),
    ("acidwg-picaso-convert \\",                   False),
    ("    --src 0_database/picaso/raw/ \\",      False),
    ("    --dst 0_database/picaso/forecast/",     False),
], size=10, mono=True)
lines(s, 7.00, 4.80, 5.8, 2.10, [
    ("# 2) 1000-멤버 앙상블 생성",                                       False),
    ("acidwg-run \\",                                                      False),
    ("    --config acidwg_py.yaml \\",                                    False),
    ("    --start 2025-01 --end 2025-12 \\",                              False),
    ("    --n-members 1000 \\",                                            False),
    ("    --n-workers 8",                                                  False),
    ("",                                                                   False),
    ("# 출력 디렉토리 구조",                                              False),
    ("ensemble/M0001/<station>.csv  ← std CSV",                            False),
    ("ensemble/M0002/<station>.csv",                                        False),
    ("...",                                                                 False),
    ("ensemble/M1000/<station>.csv",                                        False),
], size=10, mono=True, color=(0x33, 0x33, 0x33))


# ─────────────────────────────────────
# 슬라이드 8 — swat_py 핵심 + 표준 워크플로우
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 8, TOTAL, "swat_py — 핵심 기능과 표준 7단계 워크플로우",
             "TxtInOut 자동 실행 → 보정 → 검증 → 기후변화 → 앙상블 예보까지 단일 파이프라인")

# 좌측 — 7단계
card(s, 0.40, 1.35, 5.20, 5.60, fill=COL_BG_GREEN)
text(s, 0.55, 1.43, 5.0, 0.40,
     "표준 7단계 워크플로우",
     size=14, bold=True, color=COL_ACC3)
steps = [
    ("① 설정 로드", "load_config('swat_py.yaml')\n→ EnvConfig"),
    ("② 보정",     "Calibration 기간 시뮬\n관측-시뮬 비교 + 7지표"),
    ("③ 검증",     "Validation 기간 (독립)\n동일 지표로 신뢰성 확인"),
    ("④ 역사 기준", "Baseline 기간 시뮬\n기후변화 비교 기준선"),
    ("⑤ 기후변화", "GCM × RCP × 미래기간\n매트릭스 자동 루프 + Δ 분석"),
    ("⑥ 앙상블 예보", "acidwg_py 1000-멤버 통합\n분위수 시계열 + 확률곡선"),
    ("⑦ 계절 예보", "단일 멤버\n계절 단위 결정 시뮬"),
]
for i, (k, v) in enumerate(steps):
    y = 1.85 + i * 0.71
    rect(s, 0.55, y, 0.55, 0.55, COL_ACC3)
    text(s, 0.55, y + 0.10, 0.55, 0.35,
         k.split()[0], size=14, bold=True,
         color=(0xFF, 0xFF, 0xFF), align=PP_ALIGN.CENTER)
    text(s, 1.20, y, 4.40, 0.30,
         k.split(maxsplit=1)[1] if len(k.split()) > 1 else k,
         size=12, bold=True, color=COL_TITLE)
    text(s, 1.20, y + 0.28, 4.40, 0.50,
         v, size=9.5, color=COL_TEXT)

# 우측 상단 — 모듈맵
card(s, 5.80, 1.35, 7.15, 2.80, fill=COL_BG_GREY)
text(s, 5.95, 1.43, 6.85, 0.40,
     "패키지 모듈맵", size=14, bold=True, color=COL_TITLE)
mods = [
    ("config / env",    "YAML 로더 · EnvConfig 데이터클래스"),
    ("io",              "표준 CSV → SWAT/SWAT-Plus 가중치 5종"),
    ("runner",          "TxtInOut 실행 · 파일 관리"),
    ("metrics",         "NSE · RMSE · RSR · PBIAS · R² · MAE · NOF"),
    ("calibration",     "5종 알고리즘 + 다목적 가중합 + DDS"),
    ("cchange",         "GCM × RCP × 기간 매트릭스 + Δ 분석"),
    ("forecast",        "ensemble (1000-멤버) · seasonal"),
    ("output / viz / dashboard", "출력 파싱 · 그래프 · JSX 대시보드"),
]
for i, (k, v) in enumerate(mods):
    y = 1.85 + i * 0.28
    text(s, 5.95, y, 2.20, 0.25, k, size=10.5, bold=True, color=COL_ACC3, mono=True)
    text(s, 8.20, y, 4.60, 0.25, v, size=10, color=COL_TEXT)

# 우측 하단 — 빠른 시작 예시
card(s, 5.80, 4.30, 7.15, 2.65, fill=(0x1F, 0x1F, 0x1F))
text(s, 5.95, 4.38, 6.85, 0.35,
     "$  python sample_workflow.py",
     size=11, bold=True, color=(0x8F, 0xD1, 0x8F), mono=True)
lines(s, 5.95, 4.75, 6.85, 2.15, [
    ("from swat_py.config.env import load_config",                                False, (0xE0, 0xE0, 0xE0)),
    ("from swat_py.calibration.analysis_swat_plus import (",                      False, (0xE0, 0xE0, 0xE0)),
    ("    run_observation_plus, run_calibration_analysis_plus)",                  False, (0xE0, 0xE0, 0xE0)),
    ("from swat_py.cchange.runner_swat_plus import run_cchange_plus",             False, (0xE0, 0xE0, 0xE0)),
    ("",                                                                            False, (0xFF, 0xFF, 0xFF)),
    ("cfg = load_config('swat_py.yaml')",                                          False, (0xE5, 0xC0, 0x7B)),
    ("OUT = cfg.SimOutputTypes  # ['flow','sedc','tnc','tpc']",                   False, (0xE0, 0xE0, 0xE0)),
    ("",                                                                            False, (0xFF, 0xFF, 0xFF)),
    ("run_observation_plus(cfg, sim_type='Calibration',",                          False, (0xE5, 0xC0, 0x7B)),
    ("    syear=cfg.CalibrationStartYear, eyear=cfg.CalibrationEndYear)",          False, (0xE5, 0xC0, 0x7B)),
    ("run_calibration_analysis_plus(cfg, out_types=OUT, ...)",                     False, (0xE5, 0xC0, 0x7B)),
    ("if cfg.CChangeOpt.lower() == 'on':",                                         False, (0xE5, 0xC0, 0x7B)),
    ("    run_cchange_plus(cfg)        # GCM × RCP 매트릭스 자동",               False, (0x8F, 0xD1, 0x8F)),
], size=9.5, mono=True)


# ─────────────────────────────────────
# 슬라이드 9 — SWAT2012 vs SWAT-Plus
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 9, TOTAL, "SWAT2012 / SWAT-Plus 동시 지원",
             "YAML model.type 한 줄로 모델 세대 전환 — 출력 폴더·모듈 자동 분리")

# 좌측 — SWAT2012
card(s, 0.40, 1.35, 4.20, 2.10, fill=COL_BG_BLUE)
text(s, 0.55, 1.43, 4.0, 0.40,
     "SWAT2012", size=16, bold=True, color=COL_ACC1)
text(s, 0.55, 1.80, 4.0, 0.30,
     "USDA-ARS / TAMU, 1990s~ · 안정 표준",
     size=9.5, color=COL_MUTED)
lines(s, 0.55, 2.15, 4.0, 1.20, [
    "• Subbasin → HRU (lumped)",
    "• output.rch 단일 채널 출력",
    "• lookup table 기반 정적 관리",
    "• ArcSWAT / QSWAT (ArcGIS/QGIS)",
], size=10)

# 가운데 — SWAT-Plus
card(s, 4.80, 1.35, 4.20, 2.10, fill=COL_BG_RED)
text(s, 4.95, 1.43, 4.0, 0.40,
     "SWAT-Plus", size=16, bold=True, color=COL_ACC2)
text(s, 4.95, 1.80, 4.0, 0.30,
     "USDA-ARS, 2017~ · 모듈형, 활발한 개발",
     size=9.5, color=COL_MUTED)
lines(s, 4.95, 2.15, 4.0, 1.20, [
    "• Subbasin → LSU → HRU (공간)",
    "• channel_sd_day.txt (다채널)",
    "• decision table (조건부 동적)",
    "• QSWAT+ (QGIS, 무료)",
], size=10)

# 우측 — swat_py 통합
card(s, 9.20, 1.35, 3.75, 2.10, fill=COL_BG_GREEN)
text(s, 9.35, 1.43, 3.5, 0.40,
     "swat_py 통합", size=14, bold=True, color=COL_ACC3)
lines(s, 9.35, 1.85, 3.5, 1.50, [
    ("model:",                              False, COL_TEXT),
    ("  type: swat_plus",                   True,  COL_ACC3),
    ("  # 또는 swat2012",                   False, COL_MUTED),
    ("",                                     False, COL_TEXT),
    ("→ 3_swatplus/  또는  3_swat2012/",   False, COL_TEXT),
    ("→ 자동 폴더·모듈 분리",                True,  COL_ACC3),
], size=10, mono=True)

# 비교표
table(s, 0.40, 3.65, 12.55, 3.30,
      ["항목", "SWAT2012", "SWAT-Plus", "swat_py 처리"],
      [
          ["출시 세대", "1990s~ (frozen)", "2017~ (active)", "model.type 로 전환"],
          ["언어 구조", "Fortran 77/90 절차형", "Fortran 2003 모듈/OOP", "—"],
          ["공간 위계", "Subbasin → HRU", "Subbasin → LSU → HRU", "동일 API, 모듈 분리"],
          ["채널 출력", "output.rch", "channel_sd_day.txt", "reader_swat / reader_swat_plus"],
          ["습도 입력", "%", "0–1 fraction", "자동 변환 (hmd_pct)"],
          ["풍속 입력", "10 m 또는 2 m", "2 m (ws2_ms)", "표준 CSV 컬럼 매핑"],
          ["관리 방식", "lookup table (정적)", "decision table (동적)", "—"],
          ["보정 도구", "SWAT-CUP", "SWAT+ Toolbox · IPEAT-Plus", "swat_py.calibration"],
      ],
      col_widths=[1.8, 3.2, 3.2, 4.35], font_size=10)


# ─────────────────────────────────────
# 슬라이드 10 — Stitching (예보 + 관측)
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 10, TOTAL, "기상자료 Stitching — 관측(Warm-up) + 예보",
             "SWAT warm-up 요구 + 예보의 변수 부족 문제를 표준 절차로 해결")

# 시간축 다이어그램
diag_y = 1.40; diag_h = 0.55
warm_x = 0.40; warm_w = 8.10
fcst_x = warm_x + warm_w + 0.05; fcst_w = 4.45

rect(s, warm_x, diag_y, warm_w, diag_h, COL_ACC1)
text(s, warm_x, diag_y + 0.08, warm_w, 0.40,
     "WARM-UP  ·  관측/재분석 기상  (ERA5, GSOD)",
     size=13, bold=True, color=(0xFF, 0xFF, 0xFF),
     align=PP_ALIGN.CENTER)

rect(s, fcst_x, diag_y, fcst_w, diag_h, COL_ACC2)
text(s, fcst_x, diag_y + 0.08, fcst_w, 0.40,
     "FORECAST  ·  예보 기상  (acidwg / GCM)",
     size=13, bold=True, color=(0xFF, 0xFF, 0xFF),
     align=PP_ALIGN.CENTER)

text(s, warm_x - 0.05, diag_y + diag_h + 0.05, 2.4, 0.30,
     "warm_up_start_date", size=9, color=COL_MUTED)
text(s, fcst_x - 1.2, diag_y + diag_h + 0.05, 2.4, 0.30,
     "← forecast_start_date →", size=9, bold=True, color=COL_TITLE,
     align=PP_ALIGN.CENTER)
text(s, fcst_x + fcst_w - 2.4, diag_y + diag_h + 0.05, 2.4, 0.30,
     "forecast_end_date         ", size=9, color=COL_MUTED, align=PP_ALIGN.RIGHT)

text(s, warm_x + 0.10, diag_y + diag_h + 0.35, 7.5, 0.25,
     "변수 9종: pcp · tmax · tmin · tavg · tdew · hmd · slr · ws10 · ws2",
     size=9.5, color=COL_TEXT)
text(s, fcst_x + 0.10, diag_y + diag_h + 0.35, 4.2, 0.25,
     "변수 3종: pcp · tmax · tmin (나머지 결측)",
     size=9.5, color=COL_TEXT)

# Why / How
card(s, 0.40, 2.65, 6.30, 2.40, fill=COL_BG_BLUE)
text(s, 0.55, 2.73, 6.0, 0.40,
     "Why — 왜 필요한가",
     size=14, bold=True, color=COL_TITLE)
lines(s, 0.55, 3.15, 6.0, 1.85, [
    ("① SWAT warm-up 요구",                                   True, COL_ACC1),
    ("    토양수분·지하수·식생 누적상태 초기화 오류 회피",      False),
    ("    file.cio NYSKIP 만큼 출력 제외 (기본 3년)",          False),
    ("② 예보 자료의 변수 부족",                                True, COL_ACC1),
    ("    GCM·계절·앙상블 보통 pcp/tmax/tmin 3변수만 제공",   False),
    ("    hmd/slr/ws 결측 → SWAT WGEN으로 자동 합성",          False),
], size=10.5)

card(s, 6.85, 2.65, 6.10, 2.40, fill=COL_BG_RED)
text(s, 7.00, 2.73, 5.8, 0.40,
     "How — Stitching 6단계",
     size=14, bold=True, color=COL_TITLE)
lines(s, 7.00, 3.15, 5.8, 1.85, [
    ("① 시간축 정의 (warm_up → forecast → end)",  True, COL_ACC2),
    ("② 자료원별 컬럼 표준화 (std CSV)",            True, COL_ACC2),
    ("③ 시간 분할 결합 (concat + dedup)",           True, COL_ACC2),
    ("④ 결측 변수 처리 (-99 또는 파일 생략)",       True, COL_ACC2),
    ("⑤ SWAT 가중치 작성 (write_all_weather_plus)", True, COL_ACC2),
    ("⑥ time.sim / print.prt 패치",                  True, COL_ACC2),
], size=10.5)

# 코드 예시
card(s, 0.40, 5.20, 12.55, 1.75, fill=(0x1F, 0x1F, 0x1F))
text(s, 0.55, 5.28, 12.2, 0.30,
     "▶ swat_py 사용 예시",
     size=11, bold=True, color=(0x8F, 0xD1, 0x8F), mono=True)
lines(s, 0.55, 5.65, 12.2, 1.25, [
    ("# 단일 계절예보 — observed + forecast + (옵션) climatology padding",                  False, (0x8F, 0x8F, 0x8F)),
    ("from swat_py.forecast.seasonal import run_seasonal_forecast",                          False, (0xE0, 0xE0, 0xE0)),
    ("run_seasonal_forecast(cfg, fiyearmon='2025-05', lookback_years=3)",                    False, (0xE5, 0xC0, 0x7B)),
    ("",                                                                                       False, (0xFF, 0xFF, 0xFF)),
    ("# 1000-멤버 앙상블 — ERA5 warm-up + acidwg 멤버, 멤버×station 일괄",                  False, (0x8F, 0x8F, 0x8F)),
    ("from swat_py.dashboard.stitch import stitch_all_members",                              False, (0xE0, 0xE0, 0xE0)),
    ("stitch_all_members(warm_up_dir, ensemble_base_dir, output_base_dir,",                  False, (0xE5, 0xC0, 0x7B)),
    ("    station_ids, forecast_start_date='2025-01-01', forecast_end_date='2025-03-31')",   False, (0xE5, 0xC0, 0x7B)),
], size=9.5, mono=True)


# ─────────────────────────────────────
# 슬라이드 11 — 자동 보정 알고리즘
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 11, TOTAL, "자동 보정 — 5종 알고리즘 + 다목적 가중합",
             "수문 모델 인자를 자동으로 최적화 — 단일 obs / 다중 obs 가중합 모두 지원")

# 5개 알고리즘 카드
algos = [
    ("manual",   "수동 인자 변경",     "지정한 값으로 1회 실행\n빠른 sanity check"),
    ("SUFI-2",   "Sequential Uncertainty Fitting", "Bayesian sampling\n95% PPU 산출"),
    ("PSO",      "Particle Swarm Opt.", "입자떼 글로벌 최적화\n빠른 수렴"),
    ("DE",       "Differential Evolution", "벡터 차이 기반 진화\n비선형 강건"),
    ("SCE-UA",   "Shuffled Complex Evolution", "복합 탐색\n수문 분야 표준"),
]
aw = 2.45; ax0 = 0.40
for i, (k, full, desc) in enumerate(algos):
    x = ax0 + i * (aw + 0.10)
    card(s, x, 1.35, aw, 1.95, fill=COL_BG_GREEN)
    rect(s, x, 1.35, aw, 0.50, COL_ACC3)
    text(s, x + 0.10, 1.42, aw - 0.20, 0.35, k,
         size=14, bold=True, color=(0xFF, 0xFF, 0xFF))
    text(s, x + 0.10, 1.95, aw - 0.20, 0.30, full,
         size=9.5, bold=True, color=COL_TITLE)
    text(s, x + 0.10, 2.30, aw - 0.20, 0.95, desc,
         size=10, color=COL_TEXT)

# 가운데: change_type
card(s, 0.40, 3.45, 6.30, 3.50, fill=COL_BG_GREY)
text(s, 0.55, 3.53, 6.0, 0.40,
     "인자 변경 타입 (change_type)",
     size=14, bold=True, color=COL_TITLE)
table(s, 0.55, 3.95, 6.00, 1.65,
      ["타입", "수식", "용도"],
      [
          ["absval", "p = r", "절대값 설정 (range가 범위)"],
          ["relchg", "p = p₀ × (1 + r)", "비율 변경 (CN2 등)"],
          ["abschg", "p = p₀ + r", "절대 가감 (sol_awc 등)"],
      ],
      col_widths=[1.5, 2.0, 2.5], font_size=9.5)

text(s, 0.55, 5.65, 6.0, 0.35,
     "▶ YAML 예시",
     size=11, bold=True, color=COL_TITLE)
lines(s, 0.55, 6.00, 6.0, 0.95, [
    ("calibration:",                                  False, COL_TEXT),
    ("  parameters:",                                 False, COL_TEXT),
    ("    - {file: hydrology.hyd, key: cn3_swf,",    False, (0x33, 0x33, 0x33)),
    ("       range: [0.5, 1.0], change_type: absval}", False, (0x33, 0x33, 0x33)),
    ("  method: {name: sufi2, n_iterations: 100}",   False, (0x33, 0x33, 0x33)),
], size=9.5, mono=True)

# 우: 다목적 가중합
card(s, 6.85, 3.45, 6.10, 3.50, fill=COL_BG_GREEN)
text(s, 7.00, 3.53, 5.8, 0.40,
     "다목적 가중합 (Weighted Sum)",
     size=14, bold=True, color=COL_ACC3)
lines(s, 7.00, 3.95, 5.8, 3.00, [
    ("• 다수 관측소 × 다수 변수 동시 보정",          True),
    ("",                                              False),
    ("OF = Σ wᵢ · (1 − NSEᵢ)",                       True, COL_TITLE),
    ("    or Σ wᵢ · RSRᵢ  /  Σ wᵢ · |PBIASᵢ|",       False),
    ("",                                              False),
    ("• 각 obs 의 중요도(wᵢ)를 yaml 에 명시",        True),
    ("    weights: {S1.flow: 0.5, S2.tn: 0.3, ...}", False, (0x33, 0x33, 0x33)),
    ("",                                              False),
    ("• 자동 정규화 + 결측 obs 자동 제외",            True),
    ("• 단일 obs는 자동으로 가중치 1.0",              True),
    ("• 결과: results/best_n.csv + 인자 분포 그래프", True, COL_ACC3),
], size=10.5)


# ─────────────────────────────────────
# 슬라이드 12 — 성능지표 + 디렉토리 옵션 C
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 12, TOTAL, "성능 평가 지표 7종 · 디렉토리 옵션 C",
             "단일 함수 호출로 7개 지표 일괄 산출 · 마스터/작업 폴더 분리 표준")

# 지표표
text(s, 0.40, 1.35, 8.0, 0.40,
     "성능 평가 지표 — calc_all(obs, sim)",
     size=14, bold=True, color=COL_TITLE)
table(s, 0.40, 1.80, 8.10, 4.30,
      ["지표", "수식 / 의미", "이상값", "용도"],
      [
          ["NSE",   "Nash-Sutcliffe Efficiency",       "1.0",  "수문 표준, 종합 성능"],
          ["RMSE",  "Root Mean Square Error",          "0",    "절대 오차 (단위 보존)"],
          ["RSR",   "RMSE / std(obs)",                  "0",    "관측 변동성 대비 오차"],
          ["PBIAS", "100·Σ(obs−sim)/Σobs",              "0 %",  "체계적 과대/과소 추정"],
          ["R²",    "결정계수 (sim ~ obs 회귀)",         "1.0",  "선형 상관 강도"],
          ["MAE",   "Mean Absolute Error",              "0",    "이상치 둔감 평균"],
          ["NOF",   "Normalized Objective Function",   "0",    "통합 최적화 기준"],
      ],
      col_widths=[1.0, 3.2, 1.2, 2.7], font_size=10)

text(s, 0.40, 6.20, 8.10, 0.70,
     "NaN 자동 제거(쌍 단위), 분모=0 시 NaN 반환 — 단일 함수로 즉시 산출",
     size=10, color=COL_MUTED)

# 우: 디렉토리 옵션 C
card(s, 8.60, 1.35, 4.35, 5.55, fill=COL_BG_GREEN)
text(s, 8.75, 1.43, 4.1, 0.40,
     "디렉토리 옵션 C", size=14, bold=True, color=COL_ACC3)
text(s, 8.75, 1.80, 4.1, 0.30,
     "마스터(READ-ONLY) ↔ 작업 폴더 분리",
     size=9.5, color=COL_MUTED)

lines(s, 8.75, 2.20, 4.1, 4.50, [
    ("$PICASO_ROOT/",                          True, COL_TITLE),
    ("├ Database/",                            False),
    ("│  └ obs/weather/daily_std/",            False, COL_MUTED),
    ("│",                                       False),
    ("├ 3_swatplus/  ← model.type 따라",       True, COL_TITLE),
    ("│  ├ default/        READ-ONLY",          False, COL_ACC1),
    ("│  ├ calibrated/     READ-ONLY",          False, COL_ACC1),
    ("│  ├ calibration/",                       False),
    ("│  │  ├ runs/<run_id>/TxtInOut/",         False, COL_MUTED),
    ("│  │  └ results/  ← best_n.csv",          False, COL_ACC3),
    ("│  ├ forecast/",                          False),
    ("│  └ cchange/",                           False),
    ("│     ├ runs/<gcm>_<rcp>_<period>/",     False, COL_MUTED),
    ("│     └ summary/  ← Δ 분석",              False, COL_ACC3),
    ("",                                         False),
    ("✓ 마스터는 절대 덮어쓰지 않음",          True, COL_ACC3),
    ("✓ 작업 폴더는 자유 재실험",                True, COL_ACC3),
], size=9.5, mono=True)


# ─────────────────────────────────────
# 슬라이드 13 — 기후변화 + 앙상블
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 13, TOTAL, "기후변화 시나리오 + 앙상블 확률예보",
             "GCM × RCP × 미래기간 매트릭스 자동 실행 → 1,000-멤버 확률 분석")

# 기후변화
card(s, 0.40, 1.35, 6.30, 5.60, fill=COL_BG_BLUE)
text(s, 0.55, 1.43, 6.0, 0.40,
     "기후변화 시나리오 (cchange)",
     size=14, bold=True, color=COL_ACC1)

text(s, 0.55, 1.85, 6.0, 0.35,
     "▶ 자동 매트릭스 실행",
     size=11, bold=True, color=COL_TITLE)
table(s, 0.55, 2.20, 6.00, 1.60,
      ["축", "예시"],
      [
          ["GCM",       "ACCESS-CM2 · CanESM5 · MPI-ESM"],
          ["RCP/SSP",   "ssp126 · ssp245 · ssp585"],
          ["미래 기간",  "near (2031-2050)"],
          ["미래 기간",  "far  (2071-2090)"],
      ],
      col_widths=[1.8, 4.2], font_size=10)

text(s, 0.55, 3.95, 6.0, 0.35,
     "▶ Δ 분석 (변화율)",
     size=11, bold=True, color=COL_TITLE)
lines(s, 0.55, 4.30, 6.0, 2.60, [
    ("• baseline(역사) 대비 미래 변화율(%)",                       False),
    ("• 변수별: flow · sedc · tnc · tpc",                            False),
    ("• 시간 분해: 연 · 월 · 계절",                                  False),
    ("• 출력: cchange/summary/<var>_delta.csv",                      False),
    ("• 시각화: plot_cchange_lines (GCM × RCP × period)",            True, COL_ACC1),
    ("",                                                              False),
    ("▶ 코드 (1줄 호출)",                                            True, COL_TITLE),
    ("run_cchange_plus(cfg)",                                         False, COL_TEXT),
    ("analyse_cchange_cha_plus(cfg, out_types=OUT)",                  False, COL_TEXT),
    ("plot_cchange_lines(cfg, out_types=OUT)",                        False, COL_TEXT),
], size=10)

# 앙상블 예보
card(s, 6.85, 1.35, 6.10, 5.60, fill=COL_BG_RED)
text(s, 7.00, 1.43, 5.8, 0.40,
     "1000-멤버 앙상블 확률예보 (forecast.ensemble)",
     size=14, bold=True, color=COL_ACC2)

# 분위수 시각화 모사
text(s, 7.00, 1.85, 5.8, 0.35,
     "▶ 산출 분위수",
     size=11, bold=True, color=COL_TITLE)
# 분위수 막대
qs = [("5%", 0x44, COL_ACC2),
      ("25%", 0x77, COL_ACC2),
      ("50%", 0xBB, COL_ACC2),
      ("75%", 0x77, COL_ACC2),
      ("95%", 0x44, COL_ACC2)]
qx0 = 7.00; qw = 1.10; qgap = 0.05
for i, (lbl, alpha, base) in enumerate(qs):
    x = qx0 + i * (qw + qgap)
    rect(s, x, 2.30, qw, 0.55, base)
    text(s, x, 2.36, qw, 0.40, lbl,
         size=11, bold=True, color=(0xFF, 0xFF, 0xFF),
         align=PP_ALIGN.CENTER)

lines(s, 7.00, 3.05, 5.8, 4.00, [
    ("• acidwg_py 1000-멤버 std CSV 직접 소비",     True, COL_ACC2),
    ("• 멤버별 stitch (warm-up + forecast) 자동",   True, COL_ACC2),
    ("• 멤버별 SWAT 실행 (병렬, n_workers 조절)",   True, COL_ACC2),
    ("• 결과 집계 → 분위수 시계열 + 확률 곡선",     True, COL_ACC2),
    ("",                                              False),
    ("▶ 사용 예시",                                  True, COL_TITLE),
    ("ens_cfg = EnsembleConfig(",                     False, COL_TEXT),
    ("    ensemble_dir=cfg.EnsembleDir,",             False, COL_TEXT),
    ("    n_members=1000, parallel=True,",            False, COL_TEXT),
    ("    n_workers=8,",                              False, COL_TEXT),
    ("    quantiles=[0.05,0.25,0.50,0.75,0.95])",     False, COL_TEXT),
    ("results = run_ensemble_forecast(",              False, COL_TEXT),
    ("    cfg=cfg, ens_cfg=ens_cfg,",                 False, COL_TEXT),
    ("    syear=2026, eyear=2030)",                   False, COL_TEXT),
    ("plot_ensemble_forecast(results=results, ...)",  False, COL_ACC2),
], size=9.5, mono=True)


# ─────────────────────────────────────
# 슬라이드 14 — 결론·테스트 현황·향후 과제
# ─────────────────────────────────────
s = prs.slides.add_slide(BLANK)
slide_header(s, 14, TOTAL, "테스트 현황 · 결론 · 향후 과제",
             "검증된 모듈 · 393 tests passed · 운영 단계 진입")

# 좌: 테스트 현황
card(s, 0.40, 1.35, 6.30, 2.60, fill=COL_BG_GREEN)
text(s, 0.55, 1.43, 6.0, 0.40,
     "테스트 / 품질 현황",
     size=14, bold=True, color=COL_ACC3)
table(s, 0.55, 1.90, 6.00, 1.85,
      ["패키지", "버전", "테스트", "상태"],
      [
          ["util_py",   "0.1.0", "243 passed",  "운영"],
          ["acidwg_py", "1.0.0", "108 passed",  "운영"],
          ["swat_py",   "0.1.0", "45 passed",   "운영"],
          ["합계",       "—",     "396 tests",   "MIT License"],
      ],
      col_widths=[2.0, 1.2, 1.5, 1.3], font_size=10.5)

# 우: 결론
card(s, 6.85, 1.35, 6.10, 2.60, fill=COL_BG_BLUE)
text(s, 7.00, 1.43, 5.8, 0.40,
     "결론 — 핵심 성과",
     size=14, bold=True, color=COL_TITLE)
lines(s, 7.00, 1.85, 5.8, 2.00, [
    ("✓ R(rACID, rSWAT) → Python 완전 포팅",       True,  COL_ACC1),
    ("✓ 표준 std CSV 11컬럼으로 자료원 통합",      True,  COL_ACC1),
    ("✓ SWAT2012 / SWAT-Plus 동시 지원",            True,  COL_ACC1),
    ("✓ 5종 알고리즘 + 다목적 가중합 보정",         True,  COL_ACC1),
    ("✓ 1,000-멤버 앙상블 운영 가능",                True,  COL_ACC1),
    ("✓ Cook Islands 사례 적용 검증 완료",          True,  COL_ACC1),
], size=11)

# 향후 과제
card(s, 0.40, 4.10, 12.55, 2.85, fill=COL_BG_GREY)
text(s, 0.55, 4.18, 12.2, 0.40,
     "향후 과제 (Roadmap)",
     size=14, bold=True, color=COL_TITLE)
roadmap = [
    ("단기 (~Q3)", COL_ACC1,
     ["• SUFI-2 외 PSO/DE/SCE-UA 안정화",
      "• JSX 대시보드 운영 배포",
      "• 단위 변환 (mm/day flow) 면적 자동화",
      "• Linux/macOS CI 추가"]),
    ("중기 (~연말)", COL_ACC2,
     ["• 다국가 일괄 보정 파이프라인",
      "• 수질 (TN/TP) 자동 보정 강화",
      "• 실시간 운영 스케줄러 통합",
      "• 사용자 문서 영문화"]),
    ("장기 (다년)", COL_ACC3,
     ["• 기계학습 보정 (Surrogate-DDS)",
      "• 베이지안 시나리오 가중",
      "• PaaS·웹앱 서비스화",
      "• 학술 논문 1편 + 케이스 스터디"]),
]
rw = 12.55 / 3 - 0.10
for i, (k, col, items) in enumerate(roadmap):
    x = 0.55 + i * (rw + 0.10)
    rect(s, x, 4.65, rw, 0.45, col)
    text(s, x + 0.10, 4.71, rw - 0.20, 0.35,
         k, size=12, bold=True, color=(0xFF, 0xFF, 0xFF))
    lines(s, x + 0.10, 5.20, rw - 0.20, 1.70,
          [(it, False) for it in items], size=10.5)


# ───────── 저장 ─────────
prs.save(OUT_PPTX)
print(f"Saved: {OUT_PPTX}")
print(f"size : {os.path.getsize(OUT_PPTX):,} bytes")
print(f"slides: {len(prs.slides)}")
