"""PICASO-Hydro 사용자 매뉴얼 — 내용 (5장 ~ 부록).

``manual_content.py`` 의 CHAPTERS 에 이어 붙인다. 쓰는 법은 그쪽 설명 참조.
"""
from __future__ import annotations

from manual_content import L, T, chapter

# ── 5 ───────────────────────────────────────────────────────────────────────
chapter("5", "자료 준비", "Preparing the data", [
    ("objectives", L([
        "모형에 필요한 자료가 무엇인지 안다",
        "명령 한 줄로 국가 단위 자료를 내려받을 수 있다",
    ], [
        "Know what data the model needs",
        "Download the national data with a single command",
    ])),

    ("p", T("`util_py` 가 지형·기상 자료를 인터넷에서 받아 SWAT+ 가 읽는 모양으로 "
            "정리합니다. **처음 한 번**만 하면 되고, 그 뒤에는 월 1회 갱신입니다.",
            "`util_py` downloads terrain and weather data and tidies it into the "
            "shape SWAT+ reads. You do this **once**, then top it up monthly.")),

    ("box", "warn", T("먼저 국가 경계부터", "The boundary comes first"),
     L(["`0_database/gis/admin/country_boundary.csv` 를 대상 국가 것으로 바꾸지 않으면 "
        "엉뚱한 지역을 내려받습니다. 칸은 `NAME, ISO3, ISO2, xmin, ymin, xmax, ymax` 입니다."],
       ["Unless you replace `0_database/gis/admin/country_boundary.csv` with your "
        "country's, you will download the wrong area. The columns are "
        "`NAME, ISO3, ISO2, xmin, ymin, xmax, ymax`."])),

    ("h2", T("한 줄로 끝내기", "Doing it in one line")),
    ("code", L(["util-download-national"], ["util-download-national"])),
    ("p", T("이 명령이 아래 순서를 **정해진 차례대로** 실행합니다. 중간에 실패하면 "
            "멈춥니다(계속하려면 `--continue-on-error`).",
            "This runs the steps below **in the required order**. It stops at the "
            "first failure (add `--continue-on-error` to carry on).")),

    ("table", L(
        (["차례", "명령", "하는 일"],
         [["1", "util-gis-download", "지형·토양·토지이용 — **가장 먼저** (뒤 단계가 경계를 씀)"],
          ["2", "util-era5-download", "ERA5 재분석 기상 (CDS 가입 필요)"],
          ["3", "util-era5-extract", "격자점별 일자료로 뽑기"],
          ["4", "util-gsod-download", "NOAA 관측소 일자료"],
          ["5", "util-weather-standardize", "SWAT+ 표준 형식으로 변환"],
          ["6", "util-weather-validate", "ERA5 와 관측을 견줘 확인"],
          ["7", "util-streamflow-download", "국제 관측 유량 (선택)"]]),
        (["Step", "Command", "What it does"],
         [["1", "util-gis-download", "Terrain, soil, land use - **first**; later steps need the "
                                      "boundary"],
          ["2", "util-era5-download", "ERA5 reanalysis weather (needs a CDS account)"],
          ["3", "util-era5-extract", "Pull out daily values per grid point"],
          ["4", "util-gsod-download", "NOAA station daily data"],
          ["5", "util-weather-standardize", "Convert to the SWAT+ format"],
          ["6", "util-weather-validate", "Compare ERA5 against observations"],
          ["7", "util-streamflow-download", "International streamflow records (optional)"]]))),

    ("box", "tip", T("시간이 오래 걸립니다", "This takes a while"),
     L(["ERA5 내려받기는 신청이 줄을 서기 때문에 **몇 시간**이 걸릴 수 있습니다. "
        "밤에 걸어 두십시오. 중간에 끊겨도 다시 실행하면 받은 것은 건너뜁니다."],
       ["ERA5 requests queue on the server, so it can take **several hours**. "
        "Start it overnight. If it is interrupted, re-running skips what you "
        "already have."])),

    ("h2", T("잘 됐는지 확인", "Checking it worked")),
    ("check", L([
        "`0_database/gis/admin/` 에 `admin.shp` 가 있다",
        "`0_database/era5/grid_daily_std/` 에 CSV 가 여러 개 있다",
        "`0_database/obs/weather/` 에 관측소 목록 `stations-*.csv` 가 있다",
    ], [
        "`admin.shp` exists in `0_database/gis/admin/`",
        "Several CSV files exist in `0_database/era5/grid_daily_std/`",
        "A station list `stations-*.csv` exists in `0_database/obs/weather/`",
    ])),

    ("h2", T("매달 갱신", "Monthly top-up")),
    ("code", L(["util-era5-update"], ["util-era5-update"])),
    ("p", T("예측을 돌리기 전에 이 명령으로 ERA5 를 최신까지 채웁니다. 모형이 예보 "
            "시작 시점까지 '준비운동'을 하려면 최근 날씨가 필요합니다.",
            "Run this before each forecast to bring ERA5 up to date. The model needs "
            "recent weather to warm up to the forecast start date.")),
])

# ── 6 ───────────────────────────────────────────────────────────────────────
chapter("6", "기후예측을 날씨로 바꾸기", "Turning the outlook into weather", [
    ("objectives", L([
        "PICASO 예보 파일을 프로그램이 읽는 모양으로 바꿀 수 있다",
        "날씨 1,000벌을 만들고 잘 만들어졌는지 확인할 수 있다",
    ], [
        "Convert the PICASO outlook files into the form the program reads",
        "Generate 1,000 weather sets and check they were made",
    ])),

    ("p", T("`acidwg_py` 가 하는 일입니다. 명령은 둘뿐입니다.",
            "This is what `acidwg_py` does. There are only two commands.")),

    ("step", 1, T("PICASO 예보 파일을 변환합니다", "Convert the PICASO files"), L([
        "APCC 에서 받은 파일을 `0_database/picaso/prec/` 와 `t2m/` 에 풀어 둔 뒤 "
        "아래를 칩니다.",
    ], [
        "Unpack the files from APCC into `0_database/picaso/prec/` and `t2m/`, "
        "then type:",
    ]), ()),
    ("code", L(["acidwg-picaso-convert"], ["acidwg-picaso-convert"])),

    ("box", "warn", T("자료를 새로 받았다면 --overwrite",
                      "Use --overwrite when data is resent"),
     L(["이 명령은 **이미 변환된 것은 건너뜁니다.** APCC 가 같은 이름으로 내용이 다른 "
        "파일을 다시 보냈다면, `--overwrite` 를 붙이지 않으면 **옛 자료가 그대로 남습니다.** "
        "실제로 1,008개 파일을 다시 받았을 때 겹치는 946개가 전부 내용이 달랐던 적이 있습니다."],
       ["The command **skips files it has already converted.** If APCC resends files "
        "with the same names but different contents, **the old data stays** unless "
        "you add `--overwrite`. In one case 946 of the overlapping files had all "
        "changed."])),
    ("code", L(["acidwg-picaso-convert --overwrite"],
               ["acidwg-picaso-convert --overwrite"])),

    ("step", 2, T("날씨 1,000벌을 만듭니다", "Generate the 1,000 weather sets"), (), ()),
    ("code", L(["acidwg-run --forecast 2026_FMA"], ["acidwg-run --forecast 2026_FMA"])),

    ("h2", T("화면에 무엇이 보이나", "What you see")),
    ("code", L([
        "변환 완료: 167개 파일 생성",
        "앙상블 생성: 100%|###############| 1000/1000 [04:12<00:00]",
        "[acidwg_py] 완료: 1000개 시나리오 -> 1_acidwg/forecast/2026_FMA",
    ], [
        "Conversion complete: 167 files created",
        "Generating ensemble: 100%|######| 1000/1000 [04:12<00:00]",
        "[acidwg_py] done: 1000 scenarios -> 1_acidwg/forecast/2026_FMA",
    ])),
    ("keys", L([
        ("1000/1000 이면 성공", "앞 숫자가 뒤 숫자보다 작으면 일부가 실패한 것입니다. "
         "11장을 보십시오."),
        ("결과가 간 곳", "`1_acidwg/forecast/2026_FMA/member_0001 …` 폴더가 1,000개 "
         "생깁니다. 안에는 관측소별 일 단위 날씨 CSV 가 들어 있습니다."),
    ], [
        ("1000/1000 means success", "If the first number is smaller, some members "
         "failed. See chapter 11."),
        ("Where it went", "You get 1,000 folders `1_acidwg/forecast/2026_FMA/"
         "member_0001 ...`, each holding daily weather CSVs per station."),
    ])),

    ("box", "concept", T("앙상블 멤버 (ensemble member)", "Ensemble member"),
     L(["“일어날 수 있는 날씨 한 벌”입니다. 1,000명이 각자 그럴듯한 날씨를 하나씩 "
        "그려 왔다고 생각하시면 됩니다. 모두 같은 계절예보를 따르지만 날짜별 비는 "
        "서로 다릅니다."],
       ["One plausible set of weather. Imagine 1,000 people each drawing a weather "
        "sequence that obeys the same seasonal outlook but differs day by day."])),
])

# ── 7 ───────────────────────────────────────────────────────────────────────
chapter("7", "모형 검보정", "Calibrating the model", [
    ("objectives", L([
        "검보정이 무엇이고 왜 필요한지 설명할 수 있다",
        "검보정 결과가 쓸 만한지 숫자로 판단할 수 있다",
    ], [
        "Explain what calibration is and why it is needed",
        "Judge from the numbers whether a calibration is good enough",
    ])),

    ("box", "concept", T("검보정 (calibration)", "Calibration"),
     L(["모형이 **과거의 실제 유량을 맞히도록** 모형 안의 값들을 조정하는 일입니다. "
        "이것을 하지 않은 모형의 예측은 믿을 수 없습니다.",
        "한 번 해 두면 그 유역에서는 다시 하지 않아도 됩니다."],
       ["Adjusting the model's internal values until it **reproduces measured past "
        "flows**. Forecasts from an uncalibrated model cannot be trusted.",
        "Once done for a catchment, you do not repeat it."])),

    ("p", T("검보정은 **한 번만** 하는 준비 작업입니다. 이미 검보정된 프로젝트를 "
            "받으셨다면 이 장은 건너뛰고 8장으로 가십시오.",
            "Calibration is a **one-off** preparation step. If you received an "
            "already-calibrated project, skip to chapter 8.")),

    ("step", 1, T("SWAT+ 실행파일을 받습니다", "Fetch the SWAT+ executable"), (), ()),
    ("code", L(["swat-exe-fetch"], ["swat-exe-fetch"])),

    ("step", 2, T("QSWAT+ 모형을 기본 모형으로 올립니다", "Promote the QSWAT+ model"),
     L(["QGIS 의 QSWAT+ 로 만든 유역 모형을 `3_swatplus/default` 로 옮깁니다."],
       ["Moves the catchment model built in QGIS/QSWAT+ into `3_swatplus/default`."]),
     ()),
    ("code", L(["swat-promote"], ["swat-promote"])),

    ("step", 3, T("자동 검보정을 돌립니다", "Run the automatic calibration"),
     L(["관측 유량과 맞을 때까지 모형이 스스로 값을 바꿔 가며 여러 번 돌립니다. "
        "**몇 시간** 걸립니다."],
       ["The model repeatedly adjusts itself until it matches the observed flow. "
        "This takes **hours**."]), ()),
    ("code", L(["swat-calibration-finalize --steps all"],
               ["swat-calibration-finalize --steps all"])),

    ("h2", T("결과가 쓸 만한지 보기", "Judging the result")),
    ("p", T("`3_swatplus/calibration/results/cal_val_summary.csv` 를 엑셀로 엽니다.",
            "Open `3_swatplus/calibration/results/cal_val_summary.csv` in Excel.")),
    ("table", L(
        (["지표", "뜻", "쓸 만한 값"],
         [["KGE", "모형과 관측이 얼마나 닮았는가 (1 이 완벽)", "0.5 이상"],
          ["NSE", "같은 뜻의 다른 지표 (1 이 완벽)", "0.5 이상"],
          ["PBIAS", "전체적으로 많이/적게 보는 정도 (%)", "±15% 안쪽"],
          ["RMSE", "평균적으로 얼마나 빗나가는가", "작을수록 좋음"]]),
        (["Metric", "Meaning", "Usable when"],
         [["KGE", "How closely model and observation agree (1 is perfect)", "0.5 or above"],
          ["NSE", "Another measure of the same thing (1 is perfect)", "0.5 or above"],
          ["PBIAS", "Overall over- or under-estimate (%)", "within +/-15%"],
          ["RMSE", "Typical size of the error", "smaller is better"]]))),

    ("box", "why", T("왜 보정기간과 검정기간을 나누나",
                     "Why split calibration and validation"),
     L(["같은 자료로 맞추고 같은 자료로 채점하면 잘 나오는 것이 당연합니다. "
        "그래서 앞 기간으로 맞추고(보정), **쓰지 않은 뒷 기간으로 채점**합니다(검정). "
        "검정 점수가 훨씬 나쁘면 그 모형은 과거만 외운 것입니다."],
       ["Tuning and scoring on the same data always looks good. So the model is "
        "tuned on an earlier period and **scored on a later period it never saw**. "
        "If the validation score is far worse, the model merely memorised the past."])),

    ("box", "warn", T("관측 자료의 0 을 조심하십시오", "Beware zeros in the observations"),
     L(["저수지 수위가 0 으로 적힌 날은 거의 **결측을 0 으로 써 둔 것**입니다. "
        "그대로 두면 검보정 점수까지 망가집니다. 실제로 나흘치 0 때문에 KGE 가 "
        "0.60 에서 0.66 으로 달라진 사례가 있습니다.",
        "프로그램이 사수위보다 낮은 값은 자동으로 걸러냅니다. 하천처럼 기준선이 없는 "
        "경우에는 설정에 `min_valid` 를 적어 주십시오.",
        "다만 **하천 유량 0 은 실제로 있을 수 있습니다**(건기에 마르는 하천). "
        "무조건 지우지 마십시오."],
       ["A reservoir level recorded as 0 is almost always **a gap written as zero**. "
        "Left in, it corrupts the calibration score — in one case four such days "
        "moved KGE from 0.60 to 0.66.",
        "The program automatically drops values below the dead storage level. Where "
        "there is no such reference, set `min_valid` in the settings.",
        "But **a river flow of 0 can be real** (an ephemeral stream in the dry "
        "season). Do not delete those."])),
])

# ── 8 ───────────────────────────────────────────────────────────────────────
chapter("8", "평년과 단계 기준 만들기", "Building the climatology and thresholds", [
    ("objectives", L([
        "평년이 무엇이고 왜 먼저 만들어야 하는지 안다",
        "평년을 만들고 산출물을 확인할 수 있다",
    ], [
        "Say what the climatology is and why it comes first",
        "Build it and check the outputs",
    ])),

    ("box", "concept", T("평년 (climatology)", "Climatology"),
     L(["긴 과거 기간을 모형으로 돌려 만든 “보통 해는 이쯤” 하는 기준선입니다. "
        "그래프의 파란 선이 이것으로, 범례는 설정한 통계와 기간을 그대로 적습니다 "
        "— `Historical Mean (1985–2023)` 또는 `Historical Median (1985–2023)`.",
        "급수 단계의 경계(Q70·Q90·Q95 등)도 이 기간의 분포에서 나옵니다. "
        "그래서 **예측보다 먼저** 만들어야 합니다."],
       ["A baseline of “what a normal year looks like”, produced by running the "
        "model over a long past period. It is the blue line on the figure; the "
        "legend states the statistic and period you configured — "
        "`Historical Mean (1985–2023)` or `Historical Median (1985–2023)`.",
        "The stage boundaries (Q70, Q90, Q95 and so on) also come from this period's "
        "distribution — which is why it must be built **before** any forecast."])),

    ("code", L(["swat-drought-climatology"], ["swat-drought-climatology"])),
    ("p", T("설정의 `syear`~`eyear` 를 한 번에 돌립니다. 40년이면 **수 분** 걸립니다.",
            "This runs `syear` to `eyear` from your settings in one go. "
            "Forty years takes **a few minutes**.")),

    ("h2", T("무엇이 만들어지나", "What gets created")),
    ("code", L([
        "4_drought_risk/climatology/",
        "+-- channel_monthly_1985_2023.csv        월별 유량 시계열",
        "+-- channel_monthly_avg_1985_2023.csv    1~12월 평년값",
        "+-- reservoir_monthly_avg_1985_2023.csv  저수지 월 평년 수위",
        "+-- climatology_settings_1985_2023.json  이 평년을 만든 설정",
    ], [
        "4_drought_risk/climatology/",
        "+-- channel_monthly_1985_2023.csv        monthly flow series",
        "+-- channel_monthly_avg_1985_2023.csv    the 12 monthly normals",
        "+-- reservoir_monthly_avg_1985_2023.csv  monthly normal reservoir level",
        "+-- climatology_settings_1985_2023.json  the settings used",
    ])),
    ("keys", L([
        ("파일 이름의 숫자", "`1985_2023` 은 **출력 시작연도와 끝연도**입니다. "
         "시작은 `syear + warm_up_years`(1982+3)입니다. 설정의 기간을 바꾸면 "
         "파일 이름이 통째로 바뀌므로 **평년을 다시 만들어야 합니다.**"),
        ("저수지 평년에는 두 가지 통계", "`_level_ft_mean` 과 `_level_ft_median` 열이 "
         "함께 들어 있어, 어느 쪽을 쓸지 파일만 보고 견줄 수 있습니다."),
        ("설정 지문 파일", "이 평년을 **어떤 설정으로** 만들었는지 적어 둔 것입니다. "
         "나중에 설정을 바꾸면 프로그램이 이 파일과 견줘 경고합니다."),
    ], [
        ("The numbers in the name", "`1985_2023` are the **first and last output "
         "years**. The first is `syear + warm_up_years` (1982+3). Changing the period "
         "renames every file, so **you must rebuild the climatology.**"),
        ("Two statistics for reservoirs", "Columns `_level_ft_mean` and "
         "`_level_ft_median` are both written, so you can compare them in the file."),
        ("The settings fingerprint", "A record of **which settings** produced this "
         "climatology. If you later change them, the program compares and warns."),
    ])),

    ("box", "warn", T("'평년이 낡았다' 경고가 뜨면", "If you see “climatology is stale”"),
     L(["취수량·보충수·기간 같은 설정을 바꾸면 평년도 다시 만들어야 합니다. "
        "그러지 않으면 **기준선과 예측이 서로 다른 조건**으로 계산됩니다.",
        "경고에 무엇이 달라졌는지 항목별로 나옵니다. `swat-drought-climatology` 를 "
        "다시 돌리면 해결됩니다."],
       ["If you change settings such as withdrawal, transfer or the period, the "
        "climatology must be rebuilt. Otherwise **the baseline and the forecast are "
        "computed on different assumptions**.",
        "The warning lists exactly what changed. Re-run "
        "`swat-drought-climatology` to fix it."])),
])

# ── 9 ───────────────────────────────────────────────────────────────────────
chapter("9", "가뭄예측 실행", "Running the forecast", [
    ("objectives", L([
        "예측 한 번을 처음부터 끝까지 돌릴 수 있다",
        "실행 중 화면을 읽고 정상인지 판단할 수 있다",
    ], [
        "Run one complete forecast",
        "Read the screen while it runs and tell whether it is going well",
    ])),

    ("h2", T("매달 하는 일 — 네 줄", "The monthly routine — four lines")),
    ("code", L([
        "util-era5-update                             (1) 최근 날씨 채우기",
        "acidwg-picaso-convert --overwrite            (2) 새 예보 변환",
        "acidwg-run --forecast 2026_FMA               (3) 날씨 1,000벌",
        "swat-drought-dashboard --forecast 2026_FMA --members 1000    (4) 예측·단계",
    ], [
        "util-era5-update                             (1) top up recent weather",
        "acidwg-picaso-convert --overwrite            (2) convert the new outlook",
        "acidwg-run --forecast 2026_FMA               (3) 1,000 weather sets",
        "swat-drought-dashboard --forecast 2026_FMA --members 1000    (4) forecast",
    ])),

    ("box", "tip", T("한 줄로 묶기", "All in one"),
     L(["(2)(3)(4) 를 한꺼번에 하려면 아래 한 줄이면 됩니다. 평년까지 다시 만들려면 "
        "`--with-climatology` 를 붙입니다."],
       ["Steps 2-4 can be done with the single line below. Add "
        "`--with-climatology` to rebuild the climatology too."])),
    ("code", L(["swat-drought-run --forecast 2026_FMA"],
               ["swat-drought-run --forecast 2026_FMA"])),

    ("h2", T("실행 중 화면", "What the screen shows")),
    ("code", L([
        "================================================================",
        "  PICASO 가뭄예측 파이프라인 - 2026_FMA",
        "  앙상블 1000멤버 · warm-up 3yr",
        "================================================================",
        "[base] 예측 앙상블용 모델 준비 - 예측기간 2026-02 ~ 2026-04",
        "[base] 입력물 412개 20.3MB 복사 (출력물 118개 1,180MB 제외)",
        "[ensemble] 1000 멤버 SWAT+ 실행",
        "  유효 멤버 1000/1000",
        "  OK ngerikiil   경계 0.2689/0.1501/0.0755 m³/s (fdc_exceedance) "
        "단계=['Normal','Watch','Watch']",
        "  OK ngerimel    [저수지] 수위 ft (만수 23.00, 경계 21.85/19.55/14.95)",
    ], [
        "================================================================",
        "  PICASO drought forecast pipeline - 2026_FMA",
        "  ensemble 1000 members, warm-up 3yr",
        "================================================================",
        "[base] preparing the ensemble base - forecast period 2026-02 to 2026-04",
        "[base] copied 412 input files, 20.3MB (118 output files, 1,180MB skipped)",
        "[ensemble] running SWAT+ for 1000 members",
        "  valid members 1000/1000",
        "  OK ngerikiil   경계 0.2689/0.1501/0.0755 m³/s (fdc_exceedance) "
        "stages=['Normal','Watch','Watch']",
        "  OK ngerimel    [reservoir] level ft (full 23.00, bounds 21.85/19.55/14.95)",
    ])),
    ("keys", L([
        ("예측기간이 맞는지 먼저 보십시오", "`2026-02 ~ 2026-04` 가 의도한 달인지 "
         "확인합니다. 여기가 틀리면 뒤는 모두 헛일입니다."),
        ("유효 멤버 1000/1000", "**이 숫자가 가장 중요합니다.** 1,000 보다 작으면 "
         "일부가 실패한 것입니다. 900 아래로 떨어지면 결과를 쓰지 마시고 11장을 보십시오."),
        ("수원별 한 줄", "수원마다 경계값과 달별 단계가 한 줄로 나옵니다. 저수지는 "
         "만수 수위와 세 경계가 함께 찍힙니다 — 설정이 제대로 먹었는지 여기서 "
         "확인할 수 있습니다."),
    ], [
        ("Check the period first", "Confirm `2026-02 to 2026-04` is the period you "
         "meant. If this is wrong, everything after it is wasted."),
        ("valid members 1000/1000", "**The most important number.** Below 1,000 some "
         "members failed. Below 900, do not use the result - see chapter 11."),
        ("One line per source", "Each source prints its boundaries and monthly "
         "stages. For a reservoir the full supply level and three boundaries appear "
         "- a quick way to confirm your settings took effect."),
    ])),

    ("box", "tip", T("얼마나 걸리나", "How long it takes"),
     L(["1,000멤버 한 기간에 **4~5분**입니다(컴퓨터에 따라 다름). 여러 해를 한꺼번에 "
        "돌리면 몇 시간이 됩니다. 두 프로젝트를 **동시에 돌리지 마십시오** — "
        "서로 느려지고 실패가 늘어납니다."],
       ["About **4-5 minutes** for one period with 1,000 members, depending on your "
        "computer. A multi-year re-run takes hours. **Do not run two projects at the "
        "same time** - they slow each other down and failures increase."])),
])
