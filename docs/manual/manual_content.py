"""PICASO-Hydro 사용자 매뉴얼 — 내용 (한국어 / English 병렬).

한 곳에 두 언어를 나란히 둔다. 한쪽만 고치면 바로 눈에 띄므로 번역이 어긋나지 않는다.
  T(ko, en)        한 줄
  L([ko…],[en…])   여러 줄

블록 종류: h2 h3 p bullets check steps code keys box table quiz objectives
"""
from __future__ import annotations


def T(ko, en):
    return (ko, en)


def L(ko, en):
    return (ko, en)


GH = "https://github.com/IWMI-KR/picaso-hydro.git"

META = {
    "title": T("PICASO-Hydro 사용자 매뉴얼", "PICASO-Hydro User Manual"),
    "subtitle": T("계절 기후예측으로 가뭄·급수를 내다보는 수문 예측 패키지",
                  "A hydrological forecasting package that turns seasonal climate "
                  "outlooks into drought and water-supply guidance"),
    "tagline": T("이 매뉴얼은 컴퓨터를 전문으로 다루지 않는 분을 위해 썼습니다. "
                 "명령을 한 줄씩 따라 치면 끝까지 갈 수 있습니다.",
                 "Written for readers who are not computer specialists. "
                 "Type the commands one line at a time and you will get there."),
    "band": T("기상청 · 물관리 담당자를 위한 실무 안내서",
              "A practical guide for meteorological and water-management staff"),
    "meta_rows": [
        T(("대상", "쿡 제도 · 팔라우 기상청 / 물관리 담당자"),
          ("Audience", "Cook Islands & Palau — meteorological and water staff")),
        T(("버전", "1.0 (2026-11)"), ("Version", "1.0 (Nov 2026)")),
        T(("대상 코드", "GitHub IWMI-KR/picaso-hydro · main"),
          ("Code", "GitHub IWMI-KR/picaso-hydro · main")),
        T(("펴낸 곳", "유역통합관리연구원(IWMI) · APEC기후센터(APCC)"),
          ("Published by", "IWMI · APEC Climate Center (APCC)")),
    ],
    "toc_h": T("목차", "Contents"),
    "toc_note": T("Word 에서 이 목차를 클릭하고 F9 를 누르면 쪽 번호가 채워집니다.",
                  "Click this table in Word and press F9 to fill in the page numbers."),
    "header": T("PICASO-Hydro 사용자 매뉴얼", "PICASO-Hydro User Manual"),
    "footer": T("IWMI · APCC 2026", "IWMI · APCC 2026"),
    "objectives_t": T("이 장을 마치면", "After this chapter you can"),
    "quiz_t": T("확인 문제", "Check yourself"),
    "answer_t": T("답", "Answer"),
}

# ════════════════════════════════════════════════════════════════════════════
CHAPTERS = []


def chapter(num, title_ko, title_en, blocks):
    CHAPTERS.append({"num": num, "title": T(title_ko, title_en), "blocks": blocks})


# ── 0 ───────────────────────────────────────────────────────────────────────
chapter("0", "이 매뉴얼을 읽는 법", "How to use this manual", [
    ("p", T("이 매뉴얼은 **처음부터 끝까지 순서대로** 따라 하도록 만들었습니다. "
            "2장부터 9장까지 한 번 통과하면 예측 한 번을 끝낼 수 있습니다.",
            "This manual is meant to be followed **in order**. Working through "
            "chapters 2 to 9 once will produce one complete forecast.")),
    ("p", T("이미 설치가 끝난 분은 9장(예측 실행)과 10장(결과 읽기)만 보셔도 됩니다.",
            "If the software is already installed, chapters 9 (running a forecast) "
            "and 10 (reading the results) may be enough.")),

    ("h2", T("이 책에 나오는 상자", "Boxes used in this manual")),
    ("box", "concept", T("개념", "Concept"),
     L(["처음 나오는 용어를 풀어 줍니다. 몰라도 실행은 되지만, 알면 결과를 읽기 쉽습니다."],
       ["Explains a term the first time it appears. You can run the software "
        "without it, but results are easier to read with it."])),
    ("box", "why", T("왜 이렇게 하나?", "Why do it this way?"),
     L(["그냥 외우지 않아도 되도록 이유를 적었습니다. 교육할 때 이 부분을 쓰십시오."],
       ["The reason, so you do not have to memorise. Use these when training others."])),
    ("box", "warn", T("주의", "Caution"),
     L(["건너뛰면 결과가 틀리거나 자료가 사라질 수 있는 곳입니다. 꼭 읽으십시오."],
       ["Skipping this can give wrong results or lose data. Please read it."])),
    ("box", "tip", T("도움말", "Tip"),
     L(["알아 두면 시간을 아끼는 요령입니다."],
       ["A shortcut that saves time."])),

    ("h2", T("글꼴 약속", "Typographic conventions")),
    ("bullets", L([
        "`이런 글씨` 는 **그대로 쳐야 하는 명령이나 파일 이름**입니다.",
        "회색 상자는 **명령창에 치는 것** 또는 **화면에 보이는 것**입니다. "
        "보이는 것에는 번호를 붙여 바로 아래에서 설명합니다.",
        "☐ 는 확인할 항목입니다. 종이에 인쇄해 표시하며 쓰셔도 됩니다.",
    ], [
        "`This type` means **a command or file name to type exactly**.",
        "Grey boxes are **what you type** or **what you see on screen**. "
        "Numbered items below explain what you see.",
        "☐ marks something to check. You may print the page and tick them off.",
    ])),

    ("box", "warn", T("명령창이 처음이신가요?", "New to the command line?"),
     L(["Windows 에서 시작 단추를 누르고 `cmd` 라고 친 뒤 Enter 를 누르면 검은 창이 뜹니다. "
        "이 창에 명령을 한 줄 치고 Enter 를 누르는 것이 전부입니다.",
        "틀리게 쳐도 컴퓨터가 망가지지 않습니다. 메시지를 읽고 다시 치면 됩니다."],
       ["On Windows, press Start, type `cmd` and hit Enter — a black window opens. "
        "All you do is type one line and press Enter.",
        "A typing mistake will not break anything. Read the message and try again."])),
])

# ── 1 ───────────────────────────────────────────────────────────────────────
chapter("1", "PICASO-Hydro 란 무엇인가", "What PICASO-Hydro is", [
    ("objectives", L([
        "PICASO-Hydro 가 무엇을 입력받아 무엇을 내놓는지 설명할 수 있다",
        "네 개의 꾸러미(패키지)가 각각 무슨 일을 하는지 안다",
    ], [
        "Explain what PICASO-Hydro takes in and what it produces",
        "Say what each of the four packages does",
    ])),

    ("p", T("PICASO-Hydro 는 **석 달 앞의 기후 전망을 하천 유량과 저수지 수위로 바꿔 주는** "
            "프로그램 묶음입니다. 결과는 급수 단계(Normal·Watch·Warning·Crisis)로 나옵니다.",
            "PICASO-Hydro is a set of programs that **turns a three-month climate "
            "outlook into river flow and reservoir level**. The result is a water "
            "supply stage: Normal, Watch, Warning or Crisis.")),

    ("box", "concept", T("계절 기후예측 (seasonal climate forecast)",
                         "Seasonal climate forecast"),
     L(["석 달 동안 비가 평년보다 많을지 적을지를 **확률**로 알려 주는 예보입니다. "
        "“4월에 몇 mm” 같은 수치가 아니라 “많음 40% · 보통 35% · 적음 25%” 식입니다. "
        "APCC 의 PICASO 가 이 예보를 만듭니다."],
       ["A forecast that gives the **probability** that the coming three months "
        "will be wetter or drier than normal — not “40 mm in April”, but "
        "“above 40%, near 35%, below 25%”. APCC's PICASO produces it."])),

    ("h2", T("전체 흐름", "The whole chain")),
    ("code", L([
        "  ① PICASO 계절예보            석 달치 강수·기온 확률",
        "        │   acidwg_py",
        "        ▼",
        "  ② 일 단위 날씨 1,000벌       같은 확률을 따르는 날씨 시나리오",
        "        │   swat_py",
        "        ▼",
        "  ③ 유역 모형 SWAT+ 1,000회    하천 유량 · 저수지 유입",
        "        │",
        "        ▼",
        "  ④ 급수 단계 확률             Normal 60% · Watch 40% …",
    ], [
        "  (1) PICASO seasonal outlook    3-month rainfall & temperature odds",
        "        |   acidwg_py",
        "        v",
        "  (2) 1,000 daily weather sets   scenarios obeying those odds",
        "        |   swat_py",
        "        v",
        "  (3) SWAT+ catchment model      river flow & reservoir inflow, 1,000 runs",
        "        |",
        "        v",
        "  (4) Stage probabilities        Normal 60%, Watch 40% ...",
    ])),

    ("box", "why", T("왜 1,000번이나 돌리나", "Why run it a thousand times"),
     L(["계절예보는 “비가 적을 확률 60%” 처럼 **확률**로만 옵니다. 날씨 한 벌만 만들어 "
        "모형을 한 번 돌리면 그 한 가지 경우밖에 못 봅니다.",
        "1,000벌을 만들어 1,000번 돌리면, 그중 몇 번이 Watch 였는지를 셀 수 있습니다. "
        "그 비율이 곧 **단계 확률**입니다."],
       ["A seasonal outlook only gives odds, such as “60% chance of below-normal "
        "rain”. One weather set and one model run shows only one of those futures.",
        "With 1,000 sets you can count how many ended in Watch. That count is the "
        "**stage probability**."])),

    ("h2", T("네 개의 꾸러미", "The four packages")),
    ("table", L(
        (["꾸러미", "하는 일", "언제 쓰나"],
         [["util_py", "기상·지형 자료를 내려받고 정리", "처음 한 번 (그 뒤 월 1회 갱신)"],
          ["acidwg_py", "계절예보 → 일 단위 날씨 1,000벌", "예측할 때마다"],
          ["swat_py", "유역 모형 실행 · 검보정 · 단계 판정", "예측할 때마다"],
          ["picaso_hydro", "프로젝트 폴더와 설정을 만들어 줌", "처음 한 번"]]),
        (["Package", "What it does", "When you use it"],
         [["util_py", "Download and tidy weather and terrain data",
           "Once at the start (then monthly top-up)"],
          ["acidwg_py", "Seasonal outlook to 1,000 daily weather sets", "Every forecast"],
          ["swat_py", "Run the catchment model, calibrate, classify stages", "Every forecast"],
          ["picaso_hydro", "Create the project folders and settings", "Once at the start"]]))),

    ("quiz", L([
        "PICASO-Hydro 에 들어가는 것과 나오는 것을 각각 한 가지씩 적어 보십시오.",
        "1,000번 돌리는 까닭을 한 문장으로 설명해 보십시오.",
    ], [
        "Name one thing that goes into PICASO-Hydro and one thing that comes out.",
        "In one sentence, why does it run a thousand times?",
    ])),
])

# ── 2 ───────────────────────────────────────────────────────────────────────
chapter("2", "설치", "Installation", [
    ("objectives", L([
        "파이썬을 설치하고 설치됐는지 확인할 수 있다",
        "네 꾸러미를 설치하고 명령이 듣는지 확인할 수 있다",
    ], [
        "Install Python and confirm it is there",
        "Install the four packages and confirm the commands respond",
    ])),

    ("step", 1, T("파이썬을 설치합니다", "Install Python"), L([
        "python.org 에서 **3.10 이상**을 내려받아 설치합니다.",
        "설치 화면 맨 아래 **Add Python to PATH** 를 반드시 체크하십시오.",
    ], [
        "Download **3.10 or newer** from python.org and install it.",
        "On the first screen, be sure to tick **Add Python to PATH**.",
    ]), L(["체크를 빠뜨렸다면 제거 후 다시 설치하는 편이 빠릅니다."],
          ["If you missed the tick box, reinstalling is quicker than fixing it."])),

    ("code", L(["python --version", "", "Python 3.12.4        ← 이런 줄이 나오면 성공"],
               ["python --version", "", "Python 3.12.4        <- this line means success"]),
     T("확인", "Check")),

    ("step", 2, T("네 꾸러미를 설치합니다", "Install the four packages"), L([
        "명령창에 아래 네 줄을 **한 줄씩** 치고 Enter 를 누릅니다. 각 줄마다 1~3분 걸립니다.",
    ], [
        "Type the four lines below **one at a time**, pressing Enter after each. "
        "Each takes one to three minutes.",
    ]), ()),

    ("code", L([
        f'pip install "git+{GH}#subdirectory=picaso_hydro"',
        f'pip install "git+{GH}#subdirectory=util_py"',
        f'pip install "git+{GH}#subdirectory=acidwg_py"',
        f'pip install "git+{GH}#subdirectory=swat_py"',
    ], [
        f'pip install "git+{GH}#subdirectory=picaso_hydro"',
        f'pip install "git+{GH}#subdirectory=util_py"',
        f'pip install "git+{GH}#subdirectory=acidwg_py"',
        f'pip install "git+{GH}#subdirectory=swat_py"',
    ])),

    ("step", 3, T("설치를 확인합니다", "Confirm the installation"), L([
        "아래를 치면 도움말이 뜹니다. 도움말이 보이면 성공입니다.",
    ], [
        "Type this; a help message appears. If you see it, you are done.",
    ]), ()),

    ("code", L(["picaso-hydro-init --help", "swat-drought-run --help"],
               ["picaso-hydro-init --help", "swat-drought-run --help"])),

    ("box", "warn", T("'명령을 찾을 수 없습니다' 가 뜨면",
                      "If you see “command not found”"),
     L(["파이썬 설치 때 **Add Python to PATH** 를 체크하지 않은 것입니다. "
        "명령창을 껐다 켜 보고, 그래도 안 되면 파이썬을 다시 설치하십시오.",
        "급하면 `python -m swat_py.drought.run` 처럼 `python -m` 을 "
        "앞에 붙여도 똑같이 동작합니다."],
       ["Python was installed without **Add Python to PATH**. Close and reopen the "
        "command window; if it still fails, reinstall Python.",
        "As a workaround, prefix with `python -m`, e.g. `python -m swat_py.drought.run`."])),

    ("h2", T("나중에 최신판으로 올리기", "Updating later")),
    ("code", L([
        'pip install --upgrade --force-reinstall --no-cache-dir --no-deps \\',
        f'  "git+{GH}@main#subdirectory=swat_py"',
    ], [
        'pip install --upgrade --force-reinstall --no-cache-dir --no-deps \\',
        f'  "git+{GH}@main#subdirectory=swat_py"',
    ])),
])

# ── 3 ───────────────────────────────────────────────────────────────────────
chapter("3", "프로젝트 만들기", "Creating a project", [
    ("objectives", L([
        "명령 한 줄로 프로젝트 폴더를 만들 수 있다",
        "어느 폴더에 무엇이 들어가는지 안다",
    ], [
        "Create the project folders with a single command",
        "Know what goes in each folder",
    ])),

    ("p", T("**프로젝트**는 한 지역의 자료·설정·결과를 모아 두는 폴더 하나입니다. "
            "쿡 제도와 팔라우는 서로 다른 프로젝트입니다.",
            "A **project** is one folder holding the data, settings and results for "
            "one area. Cook Islands and Palau are separate projects.")),

    ("step", 1, T("폴더를 만들고 그 안으로 들어갑니다", "Make a folder and go into it"),
     (), ()),
    ("code", L(["mkdir C:\\PICASO-Palau", "cd C:\\PICASO-Palau"],
               ["mkdir C:\\PICASO-Palau", "cd C:\\PICASO-Palau"])),

    ("step", 2, T("초기화 명령을 칩니다", "Run the initialiser"), L([
        "폴더 구조와 **설정 파일 4종**이 한 번에 만들어집니다.",
    ], [
        "This creates the folder tree and **four settings files** in one go.",
    ]), ()),
    ("code", L(["picaso-hydro-init"], ["picaso-hydro-init"])),

    ("h2", T("화면에 무엇이 보이나", "What you see")),
    ("code", L([
        "  [config] config/picaso-hydro.yaml  ✓",
        "  [config] config/swat_py.yaml  ✓",
        "  [config] config/acidwg_py.yaml  ✓",
        "  [config] config/util_py.yaml  ✓",
        "  [경계] 0_database/gis/admin/country_boundary.csv  ✓ (샘플: 대상 국가로 교체 필요)",
        "================================================================",
        "  완료. 다음 단계:",
        "    1) country_boundary.csv 를 대상 국가 경계로 교체",
        "    2) util-gis-download → util-era5-download … 로 0_database 채우기",
    ], [
        "  [config] config/picaso-hydro.yaml  OK",
        "  [config] config/swat_py.yaml  OK",
        "  [config] config/acidwg_py.yaml  OK",
        "  [config] config/util_py.yaml  OK",
        "  [boundary] 0_database/gis/admin/country_boundary.csv  OK (sample - replace)",
        "================================================================",
        "  Done. Next:",
        "    1) Replace country_boundary.csv with your country's boundary",
        "    2) Fill 0_database with util-gis-download, util-era5-download ...",
    ])),
    ("keys", L([
        ("설정 파일 4종이 생겼습니다", "이것이 **4장에서 고칠 파일**입니다. "
         "지금은 예시 값이 들어 있어 그대로도 실행은 됩니다."),
        ("국가 경계 파일은 샘플입니다", "`country_boundary.csv` 를 대상 국가 것으로 "
         "반드시 바꿔야 합니다. 이 파일로 내려받을 범위가 정해집니다."),
        ("다음에 할 일을 알려 줍니다", "화면이 다음 명령을 일러 줍니다. "
         "막히면 이 안내를 다시 읽으십시오."),
    ], [
        ("Four settings files were created", "These are **the files you edit in "
         "chapter 4**. They hold example values and will run as they are."),
        ("The boundary file is a sample", "You must replace `country_boundary.csv` "
         "with your country's. It decides the area that gets downloaded."),
        ("It tells you what comes next", "The screen names the next command. "
         "Re-read this if you get stuck."),
    ])),

    ("h2", T("폴더 구조", "The folder tree")),
    ("code", L([
        "C:\\PICASO-Palau",
        "├── config\\              설정 파일 4종          ← 4장에서 고칩니다",
        "├── 0_database\\          내려받은 원자료        ← 5장",
        "│   ├── gis\\  era5\\  gsod\\  obs\\  picaso\\",
        "├── 1_acidwg\\            날씨 1,000벌          ← 6장",
        "├── 2_qswat\\             QSWAT+ 로 만든 유역모형 (QGIS 에서 작업)",
        "├── 3_swatplus\\          SWAT+ 모형·검보정·예측 ← 7·9장",
        "├── 4_drought_risk\\      평년·단계 결과         ← 8·9·10장",
        "└── reports\\             보고용 그림·표",
    ], [
        "C:\\PICASO-Palau",
        "+-- config\\              four settings files    <- chapter 4",
        "+-- 0_database\\          downloaded raw data    <- chapter 5",
        "|   +-- gis\\  era5\\  gsod\\  obs\\  picaso\\",
        "+-- 1_acidwg\\            the 1,000 weather sets <- chapter 6",
        "+-- 2_qswat\\             catchment model from QSWAT+ (built in QGIS)",
        "+-- 3_swatplus\\          SWAT+ model, calibration, forecast <- ch. 7 & 9",
        "+-- 4_drought_risk\\      climatology and stage results <- ch. 8, 9, 10",
        "+-- reports\\             figures and tables for reporting",
    ])),

    ("box", "tip", T("폴더 이름은 바꾸지 마십시오", "Do not rename these folders"),
     L(["프로그램이 이 이름으로 파일을 찾습니다. 번호(`0_`, `1_`…)는 **작업 순서**입니다."],
       ["The programs look for these exact names. The numbers (`0_`, `1_`...) are "
        "the order of work."])),
])

# ── 4 ───────────────────────────────────────────────────────────────────────
chapter("4", "설정 파일 고치기", "Editing the settings files", [
    ("objectives", L([
        "네 설정 파일이 각각 무엇을 정하는지 안다",
        "내 지역에 맞게 **고쳐야 하는 줄**을 찾아 바꿀 수 있다",
    ], [
        "Say what each of the four settings files controls",
        "Find and change the **lines you must edit** for your area",
    ])),

    ("p", T("3장에서 만들어진 `config` 폴더의 파일 네 개가 이 장의 대상입니다. "
            "메모장으로 열어 고치면 됩니다. **고칠 줄만 짚어 드립니다.**",
            "This chapter is about the four files in the `config` folder created in "
            "chapter 3. Open them in Notepad. **Only the lines you must change are "
            "pointed out.**")),

    ("box", "warn", T("들여쓰기를 지키십시오", "Keep the indentation"),
     L(["YAML 은 **줄 앞의 빈칸 개수**로 구조를 읽습니다. 빈칸을 더하거나 빼면 "
        "프로그램이 설정을 읽지 못합니다. **값만 바꾸고 빈칸은 그대로** 두십시오.",
        "Tab 키 대신 **스페이스바**를 쓰십시오."],
       ["YAML uses the **number of leading spaces** to read the structure. Adding or "
        "removing spaces will break it. **Change only the value; leave the spaces.**",
        "Use the **space bar**, never the Tab key."])),

    ("box", "concept", T("YAML (야믈)", "YAML"),
     L(["`이름: 값` 꼴로 설정을 적는 형식입니다. `#` 뒤는 설명이라 프로그램이 무시합니다 — "
        "마음껏 메모해 두십시오."],
       ["A format that writes settings as `name: value`. Anything after `#` is a "
        "comment the program ignores — use it for your own notes."])),

    ("h2", T("네 파일의 역할", "What each file is for")),
    ("table", L(
        (["파일", "정하는 것", "꼭 고쳐야 하나"],
         [["picaso-hydro.yaml", "모든 프로그램이 함께 쓰는 값 — 예측 연월·앙상블 수", "**예**"],
          ["util_py.yaml", "자료를 어디서 얼마나 내려받을지", "**예**"],
          ["acidwg_py.yaml", "날씨 1,000벌을 어떻게 만들지", "거의 그대로"],
          ["swat_py.yaml", "유역·수원·급수 단계 기준", "**예** (가장 많이)"]]),
        (["File", "What it sets", "Must you edit it?"],
         [["picaso-hydro.yaml",
           "Values shared by every program — forecast period, ensemble size",
           "**Yes**"],
          ["util_py.yaml", "Where and how much data to download", "**Yes**"],
          ["acidwg_py.yaml", "How the 1,000 weather sets are made", "Mostly as-is"],
          ["swat_py.yaml", "Catchments, sources and supply-stage thresholds",
           "**Yes** (the most)"]]))),

    ("h2", T("① picaso-hydro.yaml — 공통 값", "① picaso-hydro.yaml — shared values")),
    ("code", L([
        "project:",
        '  root:     "${env:PICASO_ROOT:C:/PICASO-Palau}"   ← 자동으로 채워집니다',
        "",
        "forecast:",
        '  period: "2026_FMA"        ← ① 예측할 연도와 계절',
        "",
        "ensemble:",
        "  n_members: 1000           ← ② 날씨를 몇 벌 만들지",
        "",
        "simulation:",
        "  warm_up_years: 3          ← ③ 모형 준비운동 기간(건드리지 마십시오)",
    ], [
        "project:",
        '  root:     "${env:PICASO_ROOT:C:/PICASO-Palau}"   <- filled in for you',
        "",
        "forecast:",
        '  period: "2026_FMA"        <- (1) year and season to forecast',
        "",
        "ensemble:",
        "  n_members: 1000           <- (2) how many weather sets",
        "",
        "simulation:",
        "  warm_up_years: 3          <- (3) model warm-up (leave alone)",
    ])),
    ("keys", L([
        ("예측 연월", "`2026_FMA` = 2026년 2·3·4월. 계절 코드는 부록 C 에 있습니다. "
         "**매달 예측할 때 이 줄을 바꿉니다.**"),
        ("앙상블 수", "연습할 때는 `30` 으로 줄이면 몇 분이면 끝납니다. "
         "실제 예측은 `1000` 으로 하십시오."),
        ("준비운동 기간", "모형이 안정되기까지 버리는 햇수입니다. 3년이 기본이고 "
         "바꿀 일이 거의 없습니다."),
    ], [
        ("Forecast period", "`2026_FMA` = Feb-Mar-Apr 2026. Season codes are in "
         "Appendix C. **You change this line for each new forecast.**"),
        ("Ensemble size", "Use `30` while practising — it finishes in minutes. "
         "Use `1000` for a real forecast."),
        ("Warm-up years", "Years discarded while the model settles. Three is the "
         "default and rarely needs changing."),
    ])),

    ("box", "tip", T("처음에는 30 벌로 연습하십시오", "Practise with 30 members first"),
     L(["1,000벌은 한 번에 4~5분, 전 기간이면 몇 시간씩 걸립니다. "
        "설정이 맞는지 확인할 때는 `n_members: 30` 으로 두고 빨리 돌려 보십시오."],
       ["A 1,000-member run takes 4-5 minutes per period, and hours for a full "
        "re-run. While checking your settings, set `n_members: 30` and run quickly."])),

    ("h2", T("② util_py.yaml — 자료 내려받기", "② util_py.yaml — downloading data")),
    ("code", L([
        "region:",
        '  boundary_csv: "$(project.root)/0_database/gis/admin/country_boundary.csv"',
        "  utc_offset:   null        ← ① 대상국 표준시 (꼭 적으십시오)",
        "  buffer_deg:   0.25",
        "",
        "era5:",
        "  cds:",
        "    url: null               ← ② CDS 인증 (파일로 두는 쪽을 권합니다)",
        "    key: null",
    ], [
        "region:",
        '  boundary_csv: "$(project.root)/0_database/gis/admin/country_boundary.csv"',
        "  utc_offset:   null        <- (1) your country's time zone (do set this)",
        "  buffer_deg:   0.25",
        "",
        "era5:",
        "  cds:",
        "    url: null               <- (2) CDS login (a file is the better place)",
        "    key: null",
    ])),
    ("keys", L([
        ("표준시를 직접 적으십시오", "`null` 로 두면 경도에서 짐작합니다. 쿡 제도는 "
         "**−10**, 팔라우는 **+9** 입니다. 짐작값과 법정 표준시가 다른 나라가 많아, "
         "적어 두는 편이 안전합니다."),
        ("CDS 인증", "ERA5 기상자료를 받으려면 cds.climate.copernicus.eu 가입이 "
         "필요합니다. 받은 열쇠는 이 파일 대신 개인 폴더의 `.cdsapirc` 에 두십시오 — "
         "설정 파일을 남과 주고받을 때 열쇠가 새지 않습니다."),
    ], [
        ("Write the time zone yourself", "Left as `null` it is guessed from "
         "longitude. Cook Islands is **-10**, Palau **+9**. Legal time often differs "
         "from the guess, so it is safer to state it."),
        ("CDS login", "ERA5 data needs a free account at cds.climate.copernicus.eu. "
         "Keep the key in `.cdsapirc` in your home folder rather than here — then "
         "the key does not travel when you share settings."),
    ])),

    ("h2", T("③ swat_py.yaml — 수원과 급수 단계",
             "③ swat_py.yaml — sources and supply stages")),
    ("p", T("가장 중요한 파일입니다. 샘플에는 **하천과 저수지가 모두** 예시로 들어 있어, "
            "필요 없는 쪽을 지우고 쓰면 됩니다.",
            "The most important file. The sample contains **both a river and a "
            "reservoir** as examples — delete whichever you do not need.")),

    ("h3", T("평년 기간", "Climatology period")),
    ("code", L([
        "drought:",
        '  base_weather: "single_station"',
        "  syear: 1982               ← ① 평년을 계산할 시작 연도",
        "  eyear: 2023               ← ② 끝 연도",
        '  climatology_stat: "mean"  ← ③ 평년선을 평균으로 할지 중앙값으로 할지',
    ], [
        "drought:",
        '  base_weather: "single_station"',
        "  syear: 1982               <- (1) first year of the climatology",
        "  eyear: 2023               <- (2) last year",
        '  climatology_stat: "mean"  <- (3) mean or median for the normal line',
    ])),
    ("keys", L([
        ("시작 연도", "관측 기록이 있는 가장 이른 해로 두십시오."),
        ("끝 연도", "기상자료가 **온전한** 마지막 해입니다. 중간에 빠진 날이 많은 해까지 "
         "늘리면 모형이 끝까지 돌지 못하고 멈춥니다."),
        ("평년선 통계", "`mean`(평균)이 기본입니다. 저수지 수위처럼 위가 만수로 막혀 "
         "있고 가뭄 해가 몇 번 섞인 경우에는 `median`(중앙값)이 '보통 해'를 더 "
         "정직하게 보여 줍니다. **단계 경계에는 영향이 없습니다** — 화면의 선만 바뀝니다."),
    ], [
        ("First year", "Set it to the earliest year with observations."),
        ("Last year", "The last year with **complete** weather data. Extending into "
         "a year with many missing days will make the model stall."),
        ("Statistic", "`mean` is the default. Where the top is capped — a reservoir "
         "at full supply — and a few drought years sit in the record, `median` shows "
         "a “typical year” more honestly. **Stage boundaries are unaffected**; only "
         "the displayed line changes."),
    ])),

    ("h3", T("수원 — 하천", "Sources — a river")),
    ("code", L([
        "  sources:",
        "    streams:",
        '      type: "stream"',
        "      thresholds:",
        '        method: "fdc_exceedance"   ← ① 유량 분포로 단계를 가름',
        "        values: [70, 90, 95]       ← ② Q70 / Q90 / Q95",
        "      outlets:                     ← ③ 소유역 번호: 이름",
        '        13: "avatiu"',
        '        3:  "avana"',
    ], [
        "  sources:",
        "    streams:",
        '      type: "stream"',
        "      thresholds:",
        '        method: "fdc_exceedance"   <- (1) stages from the flow distribution',
        "        values: [70, 90, 95]       <- (2) Q70 / Q90 / Q95",
        "      outlets:                     <- (3) sub-catchment id: name",
        '        13: "avatiu"',
        '        3:  "avana"',
    ])),
    ("keys", L([
        ("판정 방법", "하천은 유황곡선(얼마나 자주 그 유량 아래로 떨어지는가)으로 "
         "단계를 가릅니다."),
        ("경계 세 개", "`[70, 90, 95]` 는 Q70·Q90·Q95 를 뜻합니다. 숫자가 **클수록 "
         "더 마른 상태**입니다. 순서는 항상 Normal|Watch, Watch|Warning, Warning|Crisis."),
        ("소유역 번호", "QSWAT+ 로 유역을 나눌 때 정해지는 번호입니다. "
         "`2_qswat` 폴더의 모형에서 확인하십시오."),
    ], [
        ("Method", "For rivers, stages come from the flow-duration curve — how often "
         "flow falls below a given value."),
        ("Three boundaries", "`[70, 90, 95]` means Q70, Q90, Q95. A **larger number "
         "is a drier state**. The order is always Normal|Watch, Watch|Warning, "
         "Warning|Crisis."),
        ("Sub-catchment ids", "Numbers assigned when QSWAT+ divides the catchment. "
         "Look them up in the model under `2_qswat`."),
    ])),

    ("h3", T("수원 — 저수지", "Sources — a reservoir")),
    ("code", L([
        "    example_dam:",
        '      type: "reservoir"',
        '      reservoir: "example_dam"',
        "      thresholds:",
        '        method: "level_fraction"   ← ① 만수 "수위" 대비 %',
        "        values: [95, 85, 65]",
        "      outlets:",
        '        4: "example_dam"',
        "      initial_condition:",
        "        init_water_level_ft: 22.0  ← ② 예측 시작 시점의 수위 (자 눈금)",
        "        measured: No",
    ], [
        "    example_dam:",
        '      type: "reservoir"',
        '      reservoir: "example_dam"',
        "      thresholds:",
        '        method: "level_fraction"   <- (1) % of full supply *level*',
        "        values: [95, 85, 65]",
        "      outlets:",
        '        4: "example_dam"',
        "      initial_condition:",
        "        init_water_level_ft: 22.0  <- (2) level at forecast start (gauge)",
        "        measured: No",
    ])),
    ("keys", L([
        ("수위 기준 vs 저수량 기준", "`level_fraction` 은 만수 **수위**의 %, "
         "`capacity_fraction` 은 만수 **저수량(부피)**의 % 입니다. 수위–내용적 곡선이 "
         "직선이 아니라 **같은 85%가 서로 다른 물**을 가리킵니다. 반드시 발주처와 "
         "합의하고 적으십시오."),
        ("초기 수위는 자(staff gauge) 눈금", "현장 수위계에서 **읽은 그 숫자**를 적습니다. "
         "해발고도가 아닙니다. 범위를 벗어난 값을 넣으면 프로그램이 멈추고 "
         "바꿔 적을 값을 알려 줍니다."),
    ], [
        ("Level vs volume", "`level_fraction` is a % of full supply **level**; "
         "`capacity_fraction` is a % of stored **volume**. The stage-storage curve is "
         "not a straight line, so **the same 85% means different water**. Agree which "
         "one with the client before you write it."),
        ("Initial level is the staff gauge", "Write **the number you read on the "
         "gauge**, not elevation above sea level. An out-of-range value stops the "
         "program, and it tells you the value to use instead."),
    ])),

    ("box", "warn", T("기준면을 섞지 마십시오", "Do not mix the two datums"),
     L(["저수지에는 두 가지 높이 기준이 있습니다 — 수위계 **자 눈금**과 **해발고도(MSL)**. "
        "예시 댐은 만수가 자 눈금 23.0 ft 이고 해발로는 45 ft 입니다. 22 ft 차이입니다.",
        "설정에 적는 **운영 값**(`init_water_level_ft`, `diversion_target_ft`)은 모두 "
        "**자 눈금**입니다. 반면 댐 제원(`spillway_ft`, `bottom_ft`, `crest_ft`)은 "
        "측량 성과라 **해발고도**입니다. 둘을 잇는 값이 `obs_datum_offset_ft` 입니다."],
       ["A reservoir has two height references — the **staff gauge** and **mean sea "
        "level (MSL)**. In the sample dam, full supply is 23.0 ft on the gauge and "
        "45 ft above sea level: a 22 ft difference.",
        "**Operating values** you type (`init_water_level_ft`, `diversion_target_ft`) "
        "are all **gauge**. Dam dimensions (`spillway_ft`, `bottom_ft`, `crest_ft`) "
        "come from survey and are **MSL**. `obs_datum_offset_ft` links the two."])),

    ("box", "why", T("왜 만수(100%)가 아니라 95% 에서 Watch 가 시작되나",
                     "Why Watch starts at 95%, not at full supply"),
     L(["경계를 만수에 두면 실측 수위가 늘 만수 바로 아래라 **거의 항상 Watch** 가 "
        "되어 버립니다. 실제로 0.06 ft 차이로 단계가 갈린 적이 있습니다.",
        "95% 로 내리면 만수 근처의 일상적인 오르내림은 Normal 로 두고, 물이 실제로 "
        "줄어들 때만 Watch 가 됩니다."],
       ["With the boundary at full supply, the measured level sits just below it "
        "almost always — so the stage reads **Watch nearly every month**. In one case "
        "0.06 ft decided the stage.",
        "At 95%, everyday movement near full supply stays Normal and Watch appears "
        "only when water is genuinely going down."])),

    ("h3", T("저수지가 없다면", "If you have no reservoir")),
    ("p", T("`sources` 아래 `example_dam` 블록과 파일 맨 아래 `reservoirs:` 블록을 "
            "통째로 지우십시오. 하천만 있는 프로젝트(쿡 제도)는 그렇게 씁니다.",
            "Delete the whole `example_dam` block under `sources` and the "
            "`reservoirs:` block at the end of the file. A river-only project "
            "(Cook Islands) is set up that way.")),

    ("h2", T("④ acidwg_py.yaml", "④ acidwg_py.yaml")),
    ("p", T("대개 손댈 것이 없습니다. 관측 기록이 짧다면 `observation` 의 "
            "`syear`·`eyear` 만 맞추십시오. 이 기간은 **날씨 생성모형을 학습시키는 "
            "기간**이라, 위 평년 기간과 **달라도 됩니다.**",
            "Usually nothing to change. If your record is short, adjust `syear` and "
            "`eyear` under `observation`. This is the period used to **train the "
            "weather generator**, so it **may differ** from the climatology period "
            "above.")),

    ("quiz", L([
        "예측할 계절을 바꾸려면 어느 파일의 어느 줄을 고쳐야 합니까?",
        "저수지 초기 수위를 해발고도로 적으면 어떤 일이 일어납니까?",
        "연습용으로 빨리 돌려 보려면 무엇을 바꾸면 됩니까?",
    ], [
        "Which line in which file changes the season you forecast?",
        "What happens if you write the initial reservoir level as an elevation?",
        "What would you change to get a quick practice run?",
    ])),
])
