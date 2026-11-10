"""
swat_py 기상자료 stitching 보고서 (docx) 작성.
출력: 기상자료_stitching_보고서.docx
"""
import os
from datetime import date
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DOCX = os.path.join(ROOT, "기상자료_stitching_보고서.docx")

FONT_KR = "맑은 고딕"
FONT_MONO = "Consolas"

def set_font(run, name=FONT_KR, size=10.5, bold=False, color=None, mono=False):
    if mono: name = FONT_MONO
    run.font.name = name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts'); rPr.append(rFonts)
    rFonts.set(qn('w:eastAsia'), name)
    rFonts.set(qn('w:ascii'), name)
    rFonts.set(qn('w:hAnsi'), name)
    run.font.size = Pt(size)
    run.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)

def H(text, level=1):
    p = doc.add_paragraph()
    run = p.add_run(text)
    sizes = {0: 20, 1: 15, 2: 12.5, 3: 11.5}
    colors = {1: (0x1F,0x4E,0x79), 2: (0x2E,0x74,0xB5), 3: (0x40,0x40,0x40)}
    set_font(run, size=sizes.get(level, 11), bold=True,
             color=colors.get(level, (0,0,0)))
    p.paragraph_format.space_before = Pt(10 if level <= 1 else 6)
    p.paragraph_format.space_after = Pt(4)

def P(text, size=10.5, bold=False, color=(0x20,0x20,0x20)):
    p = doc.add_paragraph()
    run = p.add_run(text)
    set_font(run, size=size, bold=bold, color=color)
    p.paragraph_format.space_after = Pt(3)

def B(text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    run = p.add_run(text)
    set_font(run, size=size)
    p.paragraph_format.space_after = Pt(1)

def CODE(text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    set_font(run, size=9, mono=True, color=(0x33,0x33,0x33))
    pPr = p._element.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), 'F4F4F4')
    pPr.append(shd)

def TBL(headers, rows, col_widths=None):
    t = doc.add_table(rows=1+len(rows), cols=len(headers))
    t.style = "Light Grid Accent 1"
    for j, h in enumerate(headers):
        c = t.rows[0].cells[j]
        c.text = ""
        run = c.paragraphs[0].add_run(h)
        set_font(run, size=9.5, bold=True)
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            c = t.rows[i].cells[j]
            c.text = ""
            run = c.paragraphs[0].add_run(str(val))
            set_font(run, size=9.5)
    if col_widths:
        for j, w in enumerate(col_widths):
            for row in t.rows:
                row.cells[j].width = Cm(w)

doc = Document()
for section in doc.sections:
    section.left_margin = Cm(2.0); section.right_margin = Cm(2.0)
    section.top_margin = Cm(2.0); section.bottom_margin = Cm(2.0)
normal = doc.styles["Normal"]
normal.font.name = FONT_KR
normal.font.size = Pt(10.5)

# ── 표지 ──
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("swat_py 기상자료 Stitching 보고서")
set_font(r, size=18, bold=True, color=(0x1F,0x4E,0x79))

p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("관측자료 + 단일 예보 기상의 결합 — 필요성과 절차")
set_font(r, size=12, color=(0x55,0x55,0x55))

p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run(f"작성일 {date.today().isoformat()}  |  swat_py v0.1.0  |  IWMI-KR")
set_font(r, size=10, color=(0x80,0x80,0x80))

# ── 1. 개요 ──
H("1. 개요", level=1)
P("swat_py의 계절예보·앙상블예보 워크플로우는 관측 기상자료(historical/reanalysis)와 "
  "예보 기상자료를 한 시계열로 이어붙여(stitching) SWAT/SWAT-Plus에 입력합니다. "
  "본 보고서는 stitching이 필요한 두 가지 핵심 이유와 swat_py에 구현된 절차를 정리합니다.")

# ── 2. 왜 stitching이 필요한가 ──
H("2. 왜 관측자료와 예보 기상을 결합해야 하는가", level=1)

H("2.1 SWAT 모델의 Warm-up(웜업) 기간 필요성", level=2)
P("SWAT/SWAT-Plus는 토양수분(soil water), 지하수(shallow/deep aquifer), 식생·잔재 등 "
  "다수의 누적성 상태변수(state variables)를 시뮬레이션 중 시간에 따라 갱신합니다. "
  "이 변수들의 초기값은 일반적으로 합리적 추정이 불가능하므로, 시뮬레이션 시작 직후 일정 기간 동안의 "
  "결과는 신뢰할 수 없습니다.")
B("SWAT/SWAT-Plus는 file.cio의 NYSKIP(SWAT2012) / print.prt의 nyskip(SWAT-Plus) "
  "파라미터로 웜업 기간을 출력에서 제외합니다 — swat_py에서는 cfg.CioNYSKIP(기본 3년).")
B("예보 시점(t)부터 갑자기 시뮬레이션을 시작하면 t 직후의 유량·수질은 초기화 오류로 왜곡됩니다.")
B("따라서 t보다 N년 앞선 과거 관측 기상으로 모델을 미리 운영해 상태변수를 안정시켜야 합니다.")
P("→ 결론: 예보 기간만으로는 SWAT을 신뢰성 있게 실행할 수 없으며, 관측(또는 재분석) 기상의 "
  "warm-up 구간을 반드시 앞에 붙여야 합니다.")

H("2.2 예보 기상자료의 변수 부족", level=2)
P("기후·계절·앙상블 예보 산출물(GCM 예보, acidwg_py 앙상블, ECMWF S2S 등)은 일반적으로 "
  "강수(prcp)·최고기온(tmax)·최저기온(tmin) 등 핵심 3변수만 제공하고, 나머지 SWAT 입력 변수는 누락됩니다.")
TBL(
    ["변수", "관측/재분석 (ERA5, GSOD)", "예보 자료 (acidwg/GCM)", "swat_py 처리"],
    [
        ["pcp_mm (강수)",     "있음", "있음", "이어붙이기"],
        ["tmax_c / tmin_c",   "있음", "있음", "이어붙이기"],
        ["tavg_c, tdew_c",    "있음", "보통 없음", "warm-up 구간만 사용, 예보 구간 결측 허용"],
        ["hmd_pct (습도)",    "있음", "없음", "결측 → SWAT WGEN 자동 합성"],
        ["slr_mjm2 (일사량)", "재분석만 있음", "없음", "결측 → SWAT WGEN 자동 합성"],
        ["ws10_ms / ws2_ms",  "있음", "없음", "결측 → SWAT WGEN 자동 합성"],
    ],
    col_widths=[3.5, 4.5, 4.0, 4.0]
)
P("SWAT-Plus의 WGEN(weather generator)은 입력에서 값이 -99(결측)인 변수를 만나면 "
  "월별 통계(wgn 파일)로 자동 합성하여 모델 입력으로 사용합니다. swat_py의 dashboard/stitch.py "
  "주석에 명시되어 있는 동작입니다.")
B("이 때문에 stitching 단계에서 4변수(pcp/tmax/tmin/tavg) 또는 3변수(pcp/tmax/tmin)만 "
  "결합하고 나머지는 -99로 두거나 .hmd/.slr/.wnd 파일 생성을 생략해도 SWAT 실행이 가능합니다.")

# ── 3. 입력 자료 ──
H("3. 입력 자료 구성", level=1)
TBL(
    ["자료원", "역할", "구간", "swat_py 경로"],
    [
        ["관측(ERA5·GSOD)", "warm-up + 보정/검증", "예보 시작일 이전 N년", "$(obs)/weather/daily_std/{id}.csv"],
        ["예보(acidwg)",   "예보 구간 (앙상블 멤버)", "예보 시작일 ~ 예보 종료일", "$(fcst)/operational/{YYYY}/{초기}/member_*/"],
        ["예보(단일 계절)", "예보 구간 (단일 멤버)", "예보 초기월 ~ 연말", "$(fcst)/{...}/{id}*{YYYY-MM}*.csv"],
        ["dummy/climatology","예보 종료 후 padding (옵션)", "예보 종료 ~ 시뮬 종료", "WGEN 또는 평년값 padding"],
    ],
    col_widths=[3.5, 4.0, 4.5, 4.5]
)

# ── 4. Stitching 절차 ──
H("4. Stitching 절차", level=1)

H("4.1 시간축 정의", level=2)
P("핵심 시점 3개: warm-up 시작일 / 예보 시작일 / 예보 종료일")
B("warm_up_start_date — 미명시 시 관측 자료의 가장 이른 날(기본)")
B("forecast_start_date — 이 날부터 예보 자료로 전환")
B("forecast_end_date   — 예보 자료의 마지막 날")

H("4.2 자료원별 컬럼 표준화", level=2)
P("예보 자료가 다른 컬럼명을 쓰는 경우(예: acidwg의 prcp/tmax/tmin), 표준 컬럼명으로 통일:")
CODE("rename = {'prcp': 'pcp_mm', 'tmax': 'tmax_c', 'tmin': 'tmin_c'}")
P("date 컬럼이 없고 year/mon/day 분리 컬럼인 경우 datetime으로 재구성합니다.")

H("4.3 시간 분할 결합 (concat)", level=2)
B("warm-up 구간 = 관측 자료 중 [warm_up_start_date, forecast_start_date − 1일]")
B("예보 구간 = 예보 자료 중 [forecast_start_date, forecast_end_date]")
B("두 DataFrame을 pandas.concat 후 date로 정렬 → 중복 date는 예보 자료 우선 또는 drop_duplicates")

H("4.4 결측 변수 처리", level=2)
B("선택 1 (권장): pcp/tmax/tmin 만 결합 후, 다른 변수(.hmd/.slr/.wnd) 파일 생성 생략 → "
  "SWAT-Plus WGEN이 wgn 통계로 자동 합성")
B("선택 2: 예보 구간 결측 변수를 −99(또는 NaN)으로 채워 자료에 명시 → SWAT 변환 시 -99로 기록")
B("선택 3 (정밀): 예보 구간 결측 변수도 동일 시점의 climatology(평년 일별)로 채움 (구현 비표준)")

H("4.5 SWAT 입력 파일 생성", level=2)
P("결합된 표준 CSV → SWAT-Plus 가중치 파일 5종(.pcp/.tmp/.hmd/.slr/.wnd) 작성:")
CODE(
    "from swat_py.io.weather_swat_plus import write_all_weather_plus\n"
    "write_all_weather_plus(stations, stitch_dir, run_dir)\n"
    "# 결합된 stitch_dir/{id}.csv → run_dir(TxtInOut)에 .pcp/.tmp 등 작성"
)

H("4.6 시뮬레이션 기간 patch", level=2)
P("결합된 자료에 맞춰 SWAT-Plus의 time.sim / print.prt (혹은 SWAT2012의 file.cio) 갱신:")
CODE(
    "nbyr = (forecast_end.year - warm_up_start.year + 1) + nyskip\n"
    "iyr  = warm_up_start.year - nyskip\n"
    "write_time_sim(run_dir, nbyr, iyr)\n"
    "patch_print_prt(run_dir, nbyr, iyr, nyskip)"
)

# ── 5. swat_py 구현 ──
H("5. swat_py 구현 모듈", level=1)

H("5.1 단일 예보 — forecast.seasonal._stitch_weather", level=2)
P("seasonal_forecast의 내부 헬퍼. cfg.ObsDayDir 의 관측자료 + cfg.FcstDataDir 의 예보자료를 "
  "(lookback_years 만큼 과거 + 예보 초기월 이후) 결합해 임시 폴더 _fcst_stitch에 저장.")
CODE(
    "from swat_py.forecast.seasonal import run_seasonal_forecast\n"
    "run_seasonal_forecast(\n"
    "    cfg,\n"
    "    fiyearmon='2025-05',   # 예보 초기 (YYYY-MM)\n"
    "    model='swat_plus',\n"
    "    lookback_years=3,\n"
    ")\n"
    "# 내부적으로 _stitch_weather + write_all_weather_plus + SwatExecutor.run() 순서 호출"
)

H("5.2 앙상블 예보 — dashboard.stitch.stitch_weather_files", level=2)
P("ERA5(warm-up) + acidwg 멤버(예보) 두 자료를 멤버별 station별로 결합. "
  "stitch_all_members로 여러 멤버 일괄 처리 가능.")
CODE(
    "from swat_py.dashboard.stitch import (\n"
    "    stitch_weather_files, stitch_all_members,\n"
    ")\n"
    "\n"
    "# 단일 (member × station)\n"
    "stitch_weather_files(\n"
    "    warm_up_dir          = 'obs/weather/daily_std/era5',\n"
    "    ensemble_member_dir  = 'fcst/operational/2025/JFM/member_001',\n"
    "    output_dir           = 'stitched/2025/JFM/member_001',\n"
    "    station_id           = 'PALAU_91408',\n"
    "    forecast_start_date  = '2025-01-01',\n"
    "    forecast_end_date    = '2025-03-31',\n"
    "    warm_up_start_date   = '2022-01-01',\n"
    ")\n"
    "\n"
    "# 전체 멤버 × station 일괄\n"
    "n = stitch_all_members(\n"
    "    warm_up_dir          = 'obs/weather/daily_std/era5',\n"
    "    ensemble_base_dir    = 'fcst/operational/2025/JFM',\n"
    "    output_base_dir      = 'stitched/2025/JFM',\n"
    "    station_ids          = ['PALAU_91408','PALAU_91409'],\n"
    "    forecast_start_date  = '2025-01-01',\n"
    "    forecast_end_date    = '2025-03-31',\n"
    "    warm_up_start_date   = '2022-01-01',\n"
    "    member_pattern       = 'member_*',\n"
    ")"
)

# ── 6. 검증 / 주의사항 ──
H("6. 검증 및 주의사항", level=1)
B("warm-up 기간 확인: cfg.CioNYSKIP(기본 3년)보다 짧게 잡으면 출력 첫 구간이 비정상일 수 있음.")
B("자료원 단위·기준 일관성: 관측은 mm/일, 예보가 m/일이거나 누적값인 경우가 있음 → 표준화 필수.")
B("결합점(forecast_start_date) 불연속 점검: 평균·분산이 크게 튀면 GCM 편향보정 검토 권장 "
  "(Quantile Mapping, scaling 등).")
B("중복 날짜는 drop_duplicates(keep='last' 또는 'first')로 일관 처리 — swat_py 기본은 'last'(예보 우선).")
B("warm_up_start_date를 너무 이르게 잡으면 SWAT 시뮬레이션 시간 폭증 — 보통 보정·검증 종료 직후로 충분.")
B("예보 종료일 이후 시뮬레이션 끝까지 padding이 필요하면 dummy/climatology를 추가하거나 "
  "print.prt 종료일을 forecast_end_date로 단축.")

# ── 7. 결론 ──
H("7. 결론", level=1)
P("Stitching은 'SWAT은 충분한 warm-up이 있어야 한다'와 '예보 자료는 핵심 3변수만 제공한다'는 "
  "두 제약을 해결하기 위한 필수 전처리입니다. swat_py는 두 가지 유형(단일 계절예보, 다수 멤버 앙상블)을 "
  "모두 자동화하며, 결측 변수는 SWAT 내장 WGEN에 위임함으로써 외부 보완 자료 없이도 운영 예보가 가능합니다.")

# ── 부록 ──
H("부록 A. 핵심 함수 시그니처", level=1)
CODE(
    "swat_py.forecast.seasonal.run_seasonal_forecast(\n"
    "    cfg, fiyearmon, model='swat_plus',\n"
    "    exe_name='SWAT-Plus.exe', lookback_years=3,\n"
    ") -> None\n"
    "\n"
    "swat_py.dashboard.stitch.stitch_weather_files(\n"
    "    warm_up_dir, ensemble_member_dir, output_dir, station_id,\n"
    "    *, forecast_start_date, forecast_end_date,\n"
    "    warm_up_start_date=None,\n"
    ") -> Path  # 저장된 stitched CSV 경로\n"
    "\n"
    "swat_py.dashboard.stitch.stitch_all_members(\n"
    "    warm_up_dir, ensemble_base_dir, output_base_dir,\n"
    "    station_ids, *, forecast_start_date, forecast_end_date,\n"
    "    warm_up_start_date=None, member_pattern='member_*',\n"
    ") -> int  # 처리된 (멤버 × station) 쌍 수"
)

doc.save(OUT_DOCX)
print(f"Saved: {OUT_DOCX}")
print(f"size: {os.path.getsize(OUT_DOCX):,} bytes")
