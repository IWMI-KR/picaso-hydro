"""PICASO-Hydro 사용자 매뉴얼 — 내용 (10장 ~ 부록)."""
from __future__ import annotations

from manual_content import L, T, chapter

# ── 10 ──────────────────────────────────────────────────────────────────────
chapter("10", "결과 읽기", "Reading the results", [
    ("objectives", L([
        "어느 폴더에 무엇이 있는지 찾을 수 있다",
        "급수 단계를 읽고 무엇을 할지 판단할 수 있다",
        "빈칸과 경고 문구의 뜻을 안다",
    ], [
        "Find what is in which folder",
        "Read the supply stage and decide what to do",
        "Understand blanks and warning notes",
    ])),

    ("h2", T("산출물이 있는 곳", "Where the outputs are")),
    ("code", L([
        "4_drought_risk/forecast/2026_FMA/",
        "+-- ngerimel/",
        "    +-- series.csv          달별 평년·관측·예측",
        "    +-- thresholds.csv      단계 경계값",
        "    +-- stage_prob.csv      달별 단계 확률   <- 보고서에 바로 쓸 표",
        "    +-- dashboard.json      위 전부 + 설명",
        "    +-- ngerimel.png        그림",
    ], [
        "4_drought_risk/forecast/2026_FMA/",
        "+-- ngerimel/",
        "    +-- series.csv          monthly normal, observed and forecast",
        "    +-- thresholds.csv      stage boundaries",
        "    +-- stage_prob.csv      monthly stage probabilities  <- ready for reports",
        "    +-- dashboard.json      all of the above, plus notes",
        "    +-- ngerimel.png        the figure",
    ])),

    ("box", "tip", T("폴더 이름에 붙는 꼬리표", "The tag on the folder name"),
     L(["저수지 초기수위를 바꿔 가며 비교하면 폴더에 `__ic22.0ft-scn` 같은 꼬리표가 "
        "붙습니다. 시나리오끼리 덮어쓰지 않게 하려는 것입니다. `meas` 는 실측 "
        "초기수위, `scn` 은 가정값입니다."],
       ["When you compare different starting levels, the folder gets a tag such as "
        "`__ic22.0ft-scn` so scenarios do not overwrite each other. `meas` means a "
        "measured starting level, `scn` an assumed one."])),

    ("h2", T("단계 확률 표 읽기", "Reading the stage probability table")),
    ("code", L([
        "ym        Normal   Watch   Warning   Crisis   most_likely",
        "2026-02    93.3      6.7       0.0      0.0    Normal",
        "2026-03    61.2     33.1       5.7      0.0    Normal",
        "2026-04    28.4     44.0      22.9      4.7    Watch",
    ], [
        "ym        Normal   Watch   Warning   Crisis   most_likely",
        "2026-02    93.3      6.7       0.0      0.0    Normal",
        "2026-03    61.2     33.1       5.7      0.0    Normal",
        "2026-04    28.4     44.0      22.9      4.7    Watch",
    ])),
    ("keys", L([
        ("가로 한 줄이 한 달", "1,000개 예측 중 몇 %가 각 단계였는지입니다. "
         "한 줄을 더하면 100 이 됩니다."),
        ("most_likely 는 가장 큰 칸", "그달의 대표 단계입니다. 다만 **숫자가 비슷하면 "
         "대표 하나만 보고 판단하지 마십시오** — 2026-04 는 Watch 44% 지만 Warning 과 "
         "Crisis 를 합치면 27.6% 입니다."),
        ("읽는 요령", "한 단계가 **70% 를 넘으면** 그 단계로 보고 움직여도 됩니다. "
         "그 아래로 갈리면 “Watch 쪽으로 기울지만 지켜볼 것”으로 보고하십시오."),
    ], [
        ("One row is one month", "The percentage of the 1,000 forecasts in each "
         "stage. A row adds up to 100."),
        ("most_likely is the largest cell", "The representative stage. But **when the "
         "numbers are close, do not act on it alone** — 2026-04 reads Watch at 44%, "
         "yet Warning and Crisis together are 27.6%."),
        ("Rule of thumb", "If one stage is **above 70%**, you may act on it. Below "
         "that, report it as “leaning towards Watch, keep monitoring”."),
    ])),

    ("h2", T("단계별로 무엇을 하나", "What to do at each stage")),
    ("table", L(
        (["단계", "뜻", "할 일"],
         [["Normal", "평상", "다음 달 예측을 다시 확인"],
          ["Watch", "지켜볼 것", "주 1회 실제 수위를 재고 기록"],
          ["Warning", "경고", "절수 안내 준비 · 보충 가능 여부 확인"],
          ["Crisis", "위기", "제한급수 검토 · 관계 기관 보고"]]),
        (["Stage", "Meaning", "Action"],
         [["Normal", "Business as usual", "Check again with next month's forecast"],
          ["Watch", "Keep an eye on it", "Measure and log the actual level weekly"],
          ["Warning", "Warning", "Draft a conservation advisory; check transfer options"],
          ["Crisis", "Crisis", "Consider rationing; report to the responsible authority"]])),
     {"stage_col": 0}),

    ("box", "warn", T("이 표는 예시입니다", "This table is an example"),
     L(["단계별 조치는 **나라마다 기관마다 다릅니다.** 현지 가뭄대응 규정에 맞게 이 표를 "
        "고쳐 쓰십시오. 모형은 단계를 알려 줄 뿐, 조치를 정하지 않습니다."],
       ["Actions differ **by country and by agency**. Replace this table with your "
        "own drought response rules. The model reports a stage; it does not decide "
        "the response."])),

    ("h2", T("그래프에서 보는 것", "What the figure shows")),
    ("keys", L([
        ("굵은 선 — 예측 중앙값", "1,000개 예측의 한가운데입니다."),
        ("연한 띠 — 예측이 흩어진 범위", "안쪽 띠는 절반, 바깥 띠는 열에 아홉이 들어가는 "
         "범위입니다. 띠가 넓으면 그만큼 불확실하다는 뜻입니다."),
        ("파란 선 — 평년선", "보통 해는 이쯤이라는 기준입니다. 예측선이 이보다 아래면 "
         "평년보다 마른 해입니다. 범례에 통계와 기간이 그대로 적힙니다 "
         "(`Historical Mean (1985–2023)` 또는 `Historical Median (…)`)."),
        ("파란 점선 — 평년 평균선", "평년선을 **중앙값**으로 설정한 경우에만 함께 "
         "나옵니다. 예측선은 늘 앙상블 **평균**이라 통계가 어긋나면 예측이 체계적으로 "
         "낮아 보이므로, 같은 통계의 기준선을 덧그려 그 착시를 없앱니다. 평년과 견줄 "
         "때는 **점선**과 비교하십시오."),
        ("Observed — 관측", "하천은 관측 기상으로 돌린 **모의값**이고, 저수지는 "
         "**실측 수위**입니다. 같은 이름이지만 성격이 다릅니다."),
    ], [
        ("Bold line - forecast median", "The middle of the 1,000 forecasts."),
        ("Shaded bands - the spread", "The inner band holds half the forecasts, the "
         "outer nine in ten. A wide band means high uncertainty."),
        ("Blue line - the normal line", "What a normal year looks like. A forecast "
         "below it is a drier-than-normal year. The legend states the statistic and "
         "period (`Historical Mean (1985–2023)` or `Historical Median (…)`)."),
        ("Blue dashed line - historical mean", "Drawn only when the normal line is "
         "set to the **median**. The forecast line is always the ensemble **mean**, "
         "so mismatched statistics make the forecast look systematically low; the "
         "matching baseline removes that artefact. Compare against the **dashed** "
         "line."),
        ("Observed", "For rivers this is a **simulation driven by observed weather**; "
         "for reservoirs it is the **measured level**. Same label, different things."),
    ])),

    ("box", "warn", T("Observed 선이 끊겨 있다면", "If the Observed line is broken"),
     L(["고장이 아닙니다. **그 기간에 자료가 없다**는 뜻입니다. `dashboard.json` 의 "
        "`observed_note` 에 어느 달이 왜 비었는지 문장으로 적혀 있고, 실행 화면에도 "
        "같은 안내가 나옵니다.",
        "예: “observed(실측 수위)는 2018-01 ~ 2023-08 까지만 있다. 2024-12, 2025-01, "
        "2025-02 은(는) 자료가 없어 빈칸이다 — 계산 실패가 아니다.”"],
       ["Nothing is broken — **there is no data for that period**. The "
        "`observed_note` field in `dashboard.json` says which months and why, and "
        "the same note appears on screen while it runs.",
        "For example: “observed (measured level) only covers 2018-01 to 2023-08. "
        "2024-12, 2025-01 and 2025-02 are blank because there is no data — not "
        "because the calculation failed.”"])),

    ("quiz", L([
        "Normal 48% · Watch 46% 로 나왔습니다. 어떻게 보고하시겠습니까?",
        "하천의 Observed 와 저수지의 Observed 는 무엇이 다릅니까?",
        "예측 띠가 아주 넓다면 무엇을 뜻합니까?",
    ], [
        "A month reads Normal 48%, Watch 46%. How would you report it?",
        "How does Observed differ between a river and a reservoir?",
        "What does a very wide forecast band mean?",
    ])),
])

# ── 11 ──────────────────────────────────────────────────────────────────────
chapter("11", "문제가 생기면", "When something goes wrong", [
    ("p", T("아래는 실제로 겪은 일들입니다. 증상으로 찾으십시오.",
            "These are problems that actually happened. Find yours by symptom.")),

    ("h2", T("설치·실행", "Installing and running")),
    ("table", L(
        (["증상", "원인과 해결"],
         [["`'xxx' 은(는) 내부 또는 외부 명령이 아닙니다`",
           "파이썬 설치 때 **Add Python to PATH** 를 빠뜨린 것. 명령창을 껐다 켜 보고, "
           "안 되면 파이썬 재설치. 급하면 `python -m swat_py.drought.run` 형태로 실행."],
          ["`No module named swat_py`",
           "그 꾸러미가 설치되지 않았습니다. 2장의 `pip install` 을 다시 하십시오."],
          ["`기후 평년/FDC 자료 없음`",
           "평년을 아직 만들지 않았습니다. `swat-drought-climatology` 를 먼저 "
           "돌리거나 `--with-climatology` 를 붙이십시오."]]),
        (["Symptom", "Cause and fix"],
         [["`'xxx' is not recognized as a command`",
           "**Add Python to PATH** was not ticked. Close and reopen the command "
           "window; if it persists, reinstall Python. As a workaround run "
           "`python -m swat_py.drought.run`."],
          ["`No module named swat_py`",
           "That package is not installed. Repeat the `pip install` from chapter 2."],
          ["`climatology / FDC data not found`",
           "The climatology has not been built. Run `swat-drought-climatology` "
           "first, or add `--with-climatology`."]]))),

    ("h2", T("결과가 이상할 때", "When the results look wrong")),
    ("table", L(
        (["증상", "원인과 해결"],
         [["유효 멤버가 1,000 보다 훨씬 적다",
           "날씨 자료가 예측기간을 덮지 못했거나 SWAT+ 실행이 실패한 것. "
           "`util-era5-update` 로 최근 자료를 채우고 다시 돌리십시오. "
           "백신이 실행파일을 검사해 실패하는 경우도 있습니다."],
          ["1,000개 예측이 전부 같은 값이다",
           "멤버 날씨가 제대로 주입되지 않은 것입니다. `1_acidwg/forecast/{기간}/` 에 "
           "member 폴더가 1,000개 있는지, 안에 CSV 가 들어 있는지 확인하십시오."],
          ["예측이 늘 평년보다 젖어 있다 / 말라 있다",
           "평년과 예측이 **서로 다른 기상자료**를 쓰고 있을 수 있습니다. 설정의 "
           "`base_weather` 를 `single_station` 으로 맞추고 평년을 다시 만드십시오."],
          ["저수지가 시작하자마자 Crisis 가 된다",
           "초기 수위를 **해발고도**로 적은 것입니다. 자 눈금으로 바꾸십시오 "
           "(4장 경고 상자). 범위를 벗어나면 프로그램이 바꿔 적을 값을 알려 줍니다."],
          ["평년선이 늘 Watch 구간에 그려진다",
           "가뭄 해 몇 개가 평균을 끌어내린 것입니다. `climatology_stat` 을 "
           "`median` 으로 바꾸고 평년을 다시 만드십시오. 그 뒤로는 평년 평균선이 "
           "파란 **점선**으로 함께 그려집니다."],
          ["저수지 최악 시나리오에서 모든 기간이 똑같이 나온다",
           "중앙값이 만수에 고정돼 순위가 매겨지지 않는 것입니다. "
           "`worst_stat: \"mean\"` 을 넣으면 하위 꼬리가 반영돼 동점이 사라집니다 "
           "(평년선은 그대로 둡니다)."]]),
        (["Symptom", "Cause and fix"],
         [["Far fewer than 1,000 valid members",
           "Either the weather did not cover the forecast period, or SWAT+ failed. "
           "Run `util-era5-update` and try again. Antivirus scanning the executable "
           "can also cause failures."],
          ["All 1,000 forecasts are identical",
           "Member weather was not injected. Check that "
           "`1_acidwg/forecast/{period}/` holds 1,000 member folders, each with CSVs."],
          ["The forecast is always wetter or drier than the normal line",
           "The climatology and the forecast may be using **different weather**. "
           "Set `base_weather` to `single_station` and rebuild the climatology."],
          ["The reservoir goes to Crisis immediately",
           "The starting level was written as an **elevation**. Use the gauge "
           "reading instead (chapter 4 caution box). Out-of-range values stop the "
           "run and the message tells you the value to use."],
          ["The normal line always sits in the Watch band",
           "A few drought years are pulling the average down. Set "
           "`climatology_stat` to `median` and rebuild the climatology. From then on "
           "the historical mean is drawn alongside it as a blue **dashed** line."],
          ["Every period looks identical in the reservoir worst scenario",
           "The median is pinned at full supply, so nothing can be ranked. Adding "
           "`worst_stat: \"mean\"` brings the lower tail back in and the ties "
           "disappear (leave the normal line as it is)."]]))),

    ("h2", T("자료 문제", "Data problems")),
    ("table", L(
        (["증상", "원인과 해결"],
         [["Observed 가 비어 있다",
           "그 기간 자료가 없는 것입니다(고장 아님). `dashboard.json` 의 "
           "`observed_note` 에 이유가 적혀 있습니다."],
          ["새 예보를 받았는데 결과가 그대로다",
           "`acidwg-picaso-convert` 가 이미 변환된 파일을 건너뛴 것입니다. "
           "`--overwrite` 를 붙여 다시 돌리십시오."],
          ["SWAT+ 가 끝까지 가지 못하고 멈춘다",
           "기상자료에 빠진 날이 많은 해까지 기간을 늘린 경우입니다. "
           "`eyear` 를 자료가 온전한 해로 줄이십시오."]]),
        (["Symptom", "Cause and fix"],
         [["Observed is empty",
           "There is no data for that period — nothing is broken. "
           "`observed_note` in `dashboard.json` explains why."],
          ["New outlook received but results unchanged",
           "`acidwg-picaso-convert` skipped files it had already converted. "
           "Re-run it with `--overwrite`."],
          ["SWAT+ stalls and never finishes",
           "The period was extended into a year with many missing weather days. "
           "Reduce `eyear` to the last complete year."]]))),

    ("box", "warn", T("`--workdir` 를 쓸 때", "If you use `--workdir`"),
     L(["작업 폴더를 직접 지정할 수 있지만, **다른 자료가 든 폴더를 지정하지 마십시오.** "
        "프로그램은 그런 경우 아무것도 지우지 않고 중단합니다. 빈 폴더나 새 경로를 "
        "주십시오."],
       ["You may name your own working folder, but **do not point it at a folder "
        "holding other data.** The program will stop without deleting anything. "
        "Give it an empty folder or a new path."])),

    ("box", "tip", T("도움을 청할 때", "When you ask for help"),
     L(["화면에 나온 **오류 메시지 전체**와 아래 정보를 함께 보내 주십시오. "
        "훨씬 빨리 해결됩니다."],
       ["Send the **whole error message** from the screen together with the "
        "information below. It makes help much faster."])),
    ("bullets", L([
        "친 명령 한 줄 그대로",
        "`config/swat_py.yaml` 과 `config/picaso-hydro.yaml`",
        "예측 기간(예: 2026_FMA)과 앙상블 수",
        "`유효 멤버 ___/___` 줄",
    ], [
        "The exact command you typed",
        "`config/swat_py.yaml` and `config/picaso-hydro.yaml`",
        "The forecast period (e.g. 2026_FMA) and the ensemble size",
        "The `valid members ___/___` line",
    ])),
])

# ── 부록 ────────────────────────────────────────────────────────────────────
chapter("A", "명령어 한눈에", "Command reference", [
    ("h2", T("처음 한 번", "Once, at the start")),
    ("table", L(
        (["명령", "하는 일"],
         [["picaso-hydro-init", "프로젝트 폴더와 설정 파일 4종 생성"],
          ["util-download-national", "국가 단위 자료 내려받기 (1~7단계 묶음)"],
          ["swat-exe-fetch", "SWAT+ 실행파일 내려받기"],
          ["swat-promote", "QSWAT+ 모형을 기본 모형으로 승격"],
          ["swat-calibration-finalize --steps all", "자동 검보정 후처리"]]),
        (["Command", "What it does"],
         [["picaso-hydro-init", "Create the project folders and four settings files"],
          ["util-download-national", "Download the national data (steps 1-7)"],
          ["swat-exe-fetch", "Download the SWAT+ executable"],
          ["swat-promote", "Promote the QSWAT+ model to the default model"],
          ["swat-calibration-finalize --steps all", "Finalise the calibration"]]))),

    ("h2", T("매달", "Every month")),
    ("table", L(
        (["명령", "하는 일"],
         [["util-era5-update", "ERA5 를 최신까지 채우기"],
          ["acidwg-picaso-convert --overwrite", "새 PICASO 예보 변환"],
          ["acidwg-run --forecast 2026_FMA", "날씨 1,000벌 생성"],
          ["swat-drought-dashboard --forecast 2026_FMA --members 1000", "예측·단계 산출"],
          ["swat-drought-run --forecast 2026_FMA", "위 세 가지를 한 번에"]]),
        (["Command", "What it does"],
         [["util-era5-update", "Bring ERA5 up to date"],
          ["acidwg-picaso-convert --overwrite", "Convert the new PICASO outlook"],
          ["acidwg-run --forecast 2026_FMA", "Generate the 1,000 weather sets"],
          ["swat-drought-dashboard --forecast 2026_FMA --members 1000", "Forecast and stages"],
          ["swat-drought-run --forecast 2026_FMA", "All three in one"]]))),

    ("h2", T("기준을 바꿨을 때", "After changing the thresholds")),
    ("table", L(
        (["명령", "하는 일"],
         [["swat-drought-climatology", "평년·단계 경계 다시 만들기"],
          ["swat-drought-reclassify", "모형을 다시 돌리지 않고 단계만 재분류"],
          ["swat-drought-figure", "그림만 다시 그리기"]]),
        (["Command", "What it does"],
         [["swat-drought-climatology", "Rebuild the climatology and boundaries"],
          ["swat-drought-reclassify", "Re-classify stages without re-running the model"],
          ["swat-drought-figure", "Redraw the figures only"]]))),

    ("h2", T("고급 · 선택", "Advanced and optional")),
    ("p", T("일상 업무에는 쓰지 않습니다. 필요할 때만 보십시오.",
            "Not part of the monthly routine. Use only when needed.")),
    ("table", L(
        (["명령", "하는 일"],
         [["swat-drought-ensemble-weather", "상세화만 따로 실행 (acidwg-run 을 swat_py 에서 부름)"],
          ["swat-drought-historical-worst", "과거(1985~2023) 계절별 최저강수 해를 가정한 "
                                            "최악 시나리오 모의 — 표와 그림을 함께 냅니다. "
                                            "예측 기반 최악(`worst`)과는 다른 산출입니다"],
          ["util-gis-clip-to-user", "국가 자료를 사용자가 지정한 유역 범위로 잘라내기"],
          ["swat-tank-calibrate", "Tank 모형(간이 유출모형) 검보정 — SWAT+ 와 견주어 볼 때"],
          ["swat-tank-reservoir-calibrate", "Tank 모형으로 저수지 수위 검보정"],
          ["swat-tank-compare", "SWAT+ 와 Tank 결과 비교표·그림"]]),
        (["Command", "What it does"],
         [["swat-drought-ensemble-weather", "Run downscaling on its own (calls acidwg-run from "
                                             "swat_py)"],
          ["swat-drought-historical-worst", "Worst-case run assuming the driest year on "
                                            "record (1985-2023) for each season; writes "
                                            "tables and figures. Distinct from the "
                                            "forecast-based `worst` output"],
          ["util-gis-clip-to-user", "Clip the national data to a catchment boundary you supply"],
          ["swat-tank-calibrate",
           "Calibrate the Tank model (a simple runoff model) for comparison"],
          ["swat-tank-reservoir-calibrate", "Calibrate reservoir level with the Tank model"],
          ["swat-tank-compare", "Compare SWAT+ and Tank results in a table and figure"]]))),

    ("box", "concept", T("Tank 모형", "The Tank model"),
     L(["물통 세 개를 위아래로 포갠 모양으로 유출을 흉내 내는 **간이 모형**입니다. "
        "SWAT+ 보다 훨씬 단순하고 빠릅니다. 두 모형의 답이 비슷하면 결과를 더 "
        "믿을 수 있어, 확인용으로 씁니다."],
       ["A **simple model** that mimics runoff with three stacked tanks. It is much "
        "simpler and faster than SWAT+. When the two models agree, you can trust the "
        "result more — so it is used as a cross-check."])),

    ("box", "tip", T("도움말 보기", "Getting help on a command"),
     L(["어떤 명령이든 뒤에 `--help` 를 붙이면 쓸 수 있는 선택지가 나옵니다."],
       ["Add `--help` after any command to see its options."])),
])

chapter("B", "용어집", "Glossary", [
    ("table", L(
        (["용어", "풀이"],
         [["계절 기후예측", "석 달 동안 비·기온이 평년보다 많을지 적을지를 확률로 알려 주는 예보."],
          ["앙상블 (ensemble)",
           "“일어날 수 있는 경우”를 여러 벌 만들어 함께 보는 방법. 여기서는 1,000벌."],
          ["멤버 (member)", "앙상블 한 벌. 날씨 시나리오 하나."],
          ["상세화 (downscaling)", "넓은 지역 석 달치 확률예보를 지점별 일 단위 날씨로 바꾸는 일."],
          ["SWAT+", "비가 얼마나 하천으로 흘러드는지 계산하는 유역 모형."],
          ["검보정 (calibration)", "모형이 과거 실측을 맞히도록 내부 값을 조정하는 일."],
          ["평년 (climatology)", "긴 과거를 모형으로 돌려 만든 “보통 해” 기준선."],
          ["유황곡선 (FDC)",
           "어떤 유량 아래로 얼마나 자주 떨어지는지를 보여 주는 곡선. "
           "Q90 은 열에 아홉 번은 그보다 많다는 뜻."],
          ["자 눈금 (staff gauge)", "댐·하천에 세운 자에서 읽는 수위. 해발고도가 아님."],
          ["사수위 (dead storage)", "그 아래로는 쓸 수 없는 저수지 바닥 수위."],
          ["만수위 (full supply level)",
           "여수로 마루까지 찼을 때의 수위. 예시 댐은 자 눈금 23.0 ft."],
          ["급수 단계", "Normal · Watch · Warning · Crisis 네 칸."],
          ["YAML", "`이름: 값` 꼴로 설정을 적는 파일 형식."]]),
        (["Term", "Meaning"],
         [["Seasonal climate forecast", "Probabilities that the next three months will be wetter "
                                         "or drier than normal."],
          ["Ensemble", "Running many plausible cases together — here, 1,000 of them."],
          ["Member", "One case in the ensemble; one weather scenario."],
          ["Downscaling",
           "Turning a broad three-month outlook into daily weather at each station."],
          ["SWAT+", "The catchment model that converts rainfall into river flow."],
          ["Calibration", "Adjusting the model until it reproduces measured past flows."],
          ["Climatology", "A “normal year” baseline built by running the model over a long past "
                           "period."],
          ["Flow duration curve (FDC)", "How often flow falls below a given value. Q90 means flow "
                                         "exceeds it nine times out of ten."],
          ["Staff gauge",
           "The water level read off a gauge board — not elevation above sea level."],
          ["Dead storage", "The level below which reservoir water cannot be used."],
          ["Full supply level", "The level when water reaches the spillway crest. 23.0 ft on the "
                                 "sample dam's gauge."],
          ["Supply stage", "One of Normal, Watch, Warning, Crisis."],
          ["YAML", "A settings file format written as `name: value`."]]))),
])

chapter("C", "계절 코드", "Season codes", [
    ("p", T("예측 기간은 `연도_계절코드` 로 적습니다. 계절은 **석 달이 한 묶음**이고 "
            "한 달씩 밀려 모두 12개입니다.",
            "A forecast period is written `year_SEASON`. Each season is **three "
            "months**, shifting one month at a time — twelve in all.")),
    ("table", L(
        (["코드", "달", "코드", "달"],
         [["JFM", "1·2·3월", "JAS", "7·8·9월"],
          ["FMA", "2·3·4월", "ASO", "8·9·10월"],
          ["MAM", "3·4·5월", "SON", "9·10·11월"],
          ["AMJ", "4·5·6월", "OND", "10·11·12월"],
          ["MJJ", "5·6·7월", "NDJ", "11·12·1월 (해를 넘김)"],
          ["JJA", "6·7·8월", "DJF", "12·1·2월 (해를 넘김)"]]),
        (["Code", "Months", "Code", "Months"],
         [["JFM", "Jan-Feb-Mar", "JAS", "Jul-Aug-Sep"],
          ["FMA", "Feb-Mar-Apr", "ASO", "Aug-Sep-Oct"],
          ["MAM", "Mar-Apr-May", "SON", "Sep-Oct-Nov"],
          ["AMJ", "Apr-May-Jun", "OND", "Oct-Nov-Dec"],
          ["MJJ", "May-Jun-Jul", "NDJ", "Nov-Dec-Jan (crosses the year)"],
          ["JJA", "Jun-Jul-Aug", "DJF", "Dec-Jan-Feb (crosses the year)"]]))),

    ("box", "warn", T("해를 넘기는 계절", "Seasons that cross the year"),
     L(["`NDJ` 와 `DJF` 는 **연도가 바뀝니다.** `2026_NDJ` 는 2026년 11·12월과 "
        "**2027년** 1월입니다. 결과 파일의 연도 표기를 볼 때 유의하십시오."],
       ["`NDJ` and `DJF` **cross into the next year.** `2026_NDJ` means November and "
        "December 2026 plus January **2027**. Keep this in mind when reading the "
        "year labels in the output."])),
])
