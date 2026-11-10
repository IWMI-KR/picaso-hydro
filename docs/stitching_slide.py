"""
swat_py 기상자료 stitching 1페이지 슬라이드.
출력: 기상자료_stitching_슬라이드.pptx
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

OUT_PPTX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "기상자료_stitching_슬라이드.pptx")

COL_TITLE = (0x1F, 0x4E, 0x79)
COL_WARM  = (0x4C, 0x72, 0xB0)   # warm-up (관측)
COL_FCST  = (0xC4, 0x4E, 0x52)   # forecast
COL_TEXT  = (0x20, 0x20, 0x20)
COL_MUTED = (0x55, 0x55, 0x55)

def font(run, name="맑은 고딕", size=10, bold=False, color=None, mono=False):
    if mono: name = "Consolas"
    run.font.name = name
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

def lines(slide, x, y, w, h, items, size=10, color=COL_TEXT, mono=False,
          line_spacing=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
    tf.margin_top = Inches(0.02); tf.margin_bottom = Inches(0.02)
    for k, item in enumerate(items):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        if isinstance(item, tuple):
            txt, bold = item[0], item[1]
            col = item[2] if len(item) > 2 else color
        else:
            txt, bold, col = item, False, color
        r = p.add_run(); r.text = txt
        font(r, size=size, bold=bold, color=col, mono=mono)
    return tb

def card(slide, x, y, w, h, fill=(0xF6,0xF6,0xF6), line=(0xCC,0xCC,0xCC)):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb = RGBColor(*fill)
    s.line.color.rgb = RGBColor(*line); s.line.width = Pt(0.75)
    s.text_frame.text = ""
    return s

def arrow(slide, x, y, w, h, fill, line=None):
    s = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb = RGBColor(*fill)
    if line is None: line = fill
    s.line.color.rgb = RGBColor(*line)
    s.text_frame.text = ""
    return s

# ───── slide ─────
prs = Presentation()
prs.slide_width  = Inches(13.333)
prs.slide_height = Inches(7.5)
slide = prs.slides.add_slide(prs.slide_layouts[6])

# title
text(slide, 0.30, 0.12, 12.7, 0.55,
     "swat_py 기상자료 Stitching — 관측 + 단일 예보",
     size=22, bold=True, color=COL_TITLE)
text(slide, 0.30, 0.74, 12.7, 0.35,
     "왜 이어붙여야 하는가 (Why)  ·  어떻게 이어붙이는가 (How)  ·  swat_py API",
     size=10.5, color=COL_MUTED)

# ── 시간축 다이어그램 ──
# 가로 띠: warm-up (왼쪽) + forecast (오른쪽)
diag_y = 1.30; diag_h = 0.55
warm_x = 0.30; warm_w = 7.5
fcst_x = warm_x + warm_w + 0.05; fcst_w = 4.6

# warm-up bar
s1 = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                            Inches(warm_x), Inches(diag_y),
                            Inches(warm_w), Inches(diag_h))
s1.fill.solid(); s1.fill.fore_color.rgb = RGBColor(*COL_WARM)
s1.line.color.rgb = RGBColor(*COL_WARM)
tf = s1.text_frame; tf.margin_left = Inches(0.1)
p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
r = p.add_run(); r.text = "WARM-UP  ·  관측/재분석 기상  (ERA5, GSOD)"
font(r, size=12, bold=True, color=(0xFF,0xFF,0xFF))

# forecast bar
s2 = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                            Inches(fcst_x), Inches(diag_y),
                            Inches(fcst_w), Inches(diag_h))
s2.fill.solid(); s2.fill.fore_color.rgb = RGBColor(*COL_FCST)
s2.line.color.rgb = RGBColor(*COL_FCST)
tf = s2.text_frame; tf.margin_left = Inches(0.1)
p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
r = p.add_run(); r.text = "FORECAST  ·  예보 기상  (acidwg / GCM)"
font(r, size=12, bold=True, color=(0xFF,0xFF,0xFF))

# tick labels
text(slide, warm_x-0.05, diag_y+diag_h+0.05, 2.2, 0.30,
     "warm_up_start_date", size=9, color=COL_MUTED)
text(slide, fcst_x-1.1, diag_y+diag_h+0.05, 2.3, 0.30,
     "← forecast_start_date →", size=9, bold=True, color=COL_TITLE,
     align=PP_ALIGN.CENTER)
text(slide, fcst_x+fcst_w-2.0, diag_y+diag_h+0.05, 2.2, 0.30,
     "forecast_end_date           ", size=9, color=COL_MUTED, align=PP_ALIGN.RIGHT)

# 변수 라벨 (under bar)
text(slide, warm_x+0.1, diag_y+diag_h+0.35, 6.0, 0.25,
     "변수: pcp · tmax · tmin · tavg · tdew · hmd · slr · ws10 · ws2  (9종 모두)",
     size=9, color=COL_TEXT)
text(slide, fcst_x+0.1, diag_y+diag_h+0.35, 4.2, 0.25,
     "변수: pcp · tmax · tmin  (3종, 나머지 결측)",
     size=9, color=COL_TEXT)

# ── 좌: WHY 카드 ──
card(slide, 0.30, 2.65, 6.30, 2.40, fill=(0xEC,0xF2,0xFA))
text(slide, 0.45, 2.70, 6.0, 0.40, "Why — 왜 stitching이 필요한가",
     size=14, bold=True, color=COL_TITLE)
lines(slide, 0.45, 3.15, 6.0, 1.90, [
    ("① SWAT 모델의 Warm-up 필요", True, COL_TITLE),
    ("  • 토양수분·지하수·식생 등 누적 상태변수의 초기화 오류 회피", False, COL_TEXT),
    ("  • file.cio / print.prt 의 NYSKIP (기본 3년) 만큼 출력 제외", False, COL_TEXT),
    ("  • 예보 시점부터만 실행 시 첫 구간 결과 신뢰 불가", False, COL_TEXT),
    ("", False, COL_TEXT),
    ("② 예보 기상자료의 변수 부족", True, COL_TITLE),
    ("  • GCM·계절예보·앙상블은 보통 pcp/tmax/tmin 3변수만 제공", False, COL_TEXT),
    ("  • hmd / slr / ws 결측 → SWAT-Plus WGEN이 wgn 통계로 자동 합성", False, COL_TEXT),
    ("  • 관측 구간(warm-up)에서는 9변수 모두 활용 가능", False, COL_TEXT),
], size=10)

# ── 우: HOW 카드 ──
card(slide, 6.75, 2.65, 6.30, 2.40, fill=(0xFB,0xEE,0xEE))
text(slide, 6.90, 2.70, 6.0, 0.40, "How — Stitching 절차 6단계",
     size=14, bold=True, color=COL_TITLE)
lines(slide, 6.90, 3.15, 6.0, 1.90, [
    ("① 시간축 정의", True, COL_FCST),
    ("    warm_up_start  →  forecast_start  →  forecast_end", False, COL_TEXT),
    ("② 자료원별 컬럼 표준화 (prcp→pcp_mm, tmax→tmax_c, ...)", True, COL_FCST),
    ("③ 시간 분할 결합 (concat + 정렬 + dedup)", True, COL_FCST),
    ("    warm-up = obs[start, fcst_start − 1]", False, COL_TEXT),
    ("    forecast = ens[fcst_start, fcst_end]", False, COL_TEXT),
    ("④ 결측 변수 처리: −99 또는 .hmd/.slr/.wnd 파일 생략 (WGEN 합성)", True, COL_FCST),
    ("⑤ SWAT 가중치 파일 작성 (write_all_weather_plus)", True, COL_FCST),
    ("⑥ 시뮬레이션 기간 patch (time.sim / print.prt)", True, COL_FCST),
], size=10)

# ── 하단: 코드 예시 (좌) + API (우) ──
card(slide, 0.30, 5.20, 8.0, 1.90, fill=(0xF6,0xF6,0xF6))
text(slide, 0.45, 5.25, 7.7, 0.35, "swat_py 사용 예시",
     size=12, bold=True, color=COL_TITLE)
lines(slide, 0.45, 5.60, 7.7, 1.50, [
    "# (a) 단일 계절예보 — observed + forecast + (옵션) climatology padding",
    "from swat_py.forecast.seasonal import run_seasonal_forecast",
    "run_seasonal_forecast(cfg, fiyearmon='2025-05', lookback_years=3)",
    "",
    "# (b) 앙상블 — ERA5 warm-up + acidwg 멤버, 멤버×station 일괄",
    "from swat_py.dashboard.stitch import stitch_all_members",
    "stitch_all_members(warm_up_dir, ensemble_base_dir, output_base_dir,",
    "    station_ids, forecast_start_date='2025-01-01',",
    "    forecast_end_date='2025-03-31', warm_up_start_date='2022-01-01')",
], size=9, mono=True, color=(0x33,0x33,0x33))

card(slide, 8.45, 5.20, 4.60, 1.90, fill=(0xF6,0xF6,0xF6))
text(slide, 8.60, 5.25, 4.3, 0.35, "관련 모듈",
     size=12, bold=True, color=COL_TITLE)
lines(slide, 8.60, 5.60, 4.3, 1.50, [
    ("forecast.seasonal", True, COL_TEXT),
    ("    run_seasonal_forecast(cfg, ...)", False, COL_MUTED),
    ("    _stitch_weather(...)  — 내부 헬퍼", False, COL_MUTED),
    ("dashboard.stitch", True, COL_TEXT),
    ("    stitch_weather_files(...)", False, COL_MUTED),
    ("    stitch_all_members(...)", False, COL_MUTED),
    ("io.weather_swat_plus", True, COL_TEXT),
    ("    write_all_weather_plus(...)", False, COL_MUTED),
], size=9.5, mono=True)

# footer
text(slide, 0.30, 7.10, 12.7, 0.30,
     "Source: swat_py v0.1.0 (dashboard/stitch.py, forecast/seasonal.py) · IWMI-KR",
     size=8.5, color=(0x80,0x80,0x80))

prs.save(OUT_PPTX)
print(f"Saved: {OUT_PPTX}")
print(f"size: {os.path.getsize(OUT_PPTX):,} bytes")
