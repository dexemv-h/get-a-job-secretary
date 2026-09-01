"""
OPIc 모의고사 엔진.

Background Survey → Self Assessment(1~6) → 15문항 콤보 → 문항별 녹음/전사 → 최종 등급.

주의:
  아래 문항 구성(blueprint)은 공개적으로 알려진 일반적인 OPIc 출제 형태를 옮긴 것이다.
  실제 시험의 문항 배치·난이도 알고리즘은 공개돼 있지 않으므로 그대로 재현한다고 주장하지 않는다.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .calibration import opic_dir
from .delivery import DeliveryMetrics, analyze_delivery
from .rater import _parse_json

load_dotenv()

_DEFAULT_MODEL = "claude-opus-4-7"

# Self Assessment 6단계 (공개된 문항 설명의 요약)
SELF_ASSESSMENT = {
    1: "낱말이나 외운 표현 몇 개만 말할 수 있다.",
    2: "물건·색·요일·음식 같은 기본 어휘와 간단한 질문을 다룰 수 있다.",
    3: "나 자신, 직장, 가족, 취미를 간단한 문장으로 말할 수 있다.",
    4: "일상 주제에 대해 문장을 연결해 대화할 수 있고 자주 쓰는 문법을 쓴다.",
    5: "익숙하지 않은 주제도 문장을 연결해 설명할 수 있고 어휘가 다양하다.",
    6: "친숙하지 않은 주제나 추상적인 소재도 논리적으로 길게 설명할 수 있다.",
}

# Background Survey 항목 (대화형으로 수집)
SURVEY_FIELDS = [
    ("job", "직업 (예: 사무직 회사원 / 학생 / 취업 준비 중)"),
    ("residence", "거주 형태 (예: 가족과 함께 아파트 / 자취 / 기숙사)"),
    ("leisure", "여가 활동 (쉼표로 여러 개, 예: 영화 보기, 카페 가기, 공연 보기)"),
    ("hobbies", "취미·관심사 (예: 음악 감상, 사진 찍기, 요리)"),
    ("sports", "운동 (예: 헬스, 조깅, 없음)"),
    ("travel", "여행 경험 (예: 국내 여행, 해외 여행, 출장)"),
]

# 문항 기능 정의 — rater 의 기능 분석 항목과 대응된다.
FUNCTIONS = {
    "self_intro": "자기소개",
    "description": "묘사 (장소·사람·사물)",
    "routine": "습관·루틴 서술",
    "past_experience": "과거 경험 서술 (narration)",
    "comparison": "비교·변화 서술",
    "roleplay_ask": "롤플레이 — 정보 요청 질문하기",
    "roleplay_problem": "롤플레이 — 예상치 못한 문제 상황 해결 (complication)",
    "roleplay_experience": "롤플레이 관련 본인 경험 서술",
    "issue": "사회적 이슈·추상 주제 논의",
}

# 난이도대별 15문항 구성. (category, function)
_COMBO_BASIC = [
    ("자기소개", "self_intro"),
    ("설문 주제 A", "description"), ("설문 주제 A", "routine"), ("설문 주제 A", "past_experience"),
    ("설문 주제 B", "description"), ("설문 주제 B", "routine"), ("설문 주제 B", "past_experience"),
    ("롤플레이", "roleplay_ask"), ("롤플레이", "roleplay_problem"), ("롤플레이", "roleplay_experience"),
    ("설문 주제 C", "description"), ("설문 주제 C", "routine"), ("설문 주제 C", "past_experience"),
    ("돌발 주제", "description"), ("돌발 주제", "past_experience"),
]

_COMBO_MID = [
    ("자기소개", "self_intro"),
    ("설문 주제 A", "description"), ("설문 주제 A", "routine"), ("설문 주제 A", "past_experience"),
    ("돌발 주제 A", "description"), ("돌발 주제 A", "routine"), ("돌발 주제 A", "past_experience"),
    ("롤플레이", "roleplay_ask"), ("롤플레이", "roleplay_problem"), ("롤플레이", "roleplay_experience"),
    ("설문 주제 B", "description"), ("설문 주제 B", "past_experience"), ("설문 주제 B", "comparison"),
    ("고난도", "comparison"), ("고난도", "issue"),
]

_COMBO_ADVANCED = [
    ("자기소개", "self_intro"),
    ("설문 주제 A", "description"), ("설문 주제 A", "past_experience"), ("설문 주제 A", "comparison"),
    ("돌발 주제 A", "description"), ("돌발 주제 A", "past_experience"), ("돌발 주제 A", "comparison"),
    ("롤플레이", "roleplay_ask"), ("롤플레이", "roleplay_problem"), ("롤플레이", "roleplay_experience"),
    ("돌발 주제 B", "past_experience"), ("돌발 주제 B", "comparison"), ("돌발 주제 B", "issue"),
    ("고난도", "issue"), ("고난도", "issue"),
]

BLUEPRINTS = {1: _COMBO_BASIC, 2: _COMBO_BASIC, 3: _COMBO_MID,
              4: _COMBO_MID, 5: _COMBO_ADVANCED, 6: _COMBO_ADVANCED}

# 설문에 없는 주제에서 나오는 돌발 문항 후보
SURPRISE_TOPICS = [
    "weather and seasons", "public transportation", "banks", "hotels", "the internet",
    "cell phones", "health and doctor visits", "restaurants", "shopping", "recycling",
    "gatherings and holidays", "housing and neighborhoods", "free time at home",
]


@dataclass
class BackgroundSurvey:
    job: str = ""
    residence: str = ""
    leisure: str = ""
    hobbies: str = ""
    sports: str = ""
    travel: str = ""

    def as_prompt(self) -> str:
        return "\n".join(
            f"- {label.split(' (')[0]}: {getattr(self, key) or '(응답 없음)'}"
            for key, label in SURVEY_FIELDS
        )


@dataclass
class ExamQuestion:
    number: int
    category: str
    function: str
    topic: str
    text: str               # 실제 출제 문항 (영어)
    guidance: str = ""      # 이 문항이 요구하는 기능 설명 (채점 후 공개)


@dataclass
class ExamAnswer:
    number: int
    question: str
    transcript: str = ""
    audio_path: str = ""
    seconds: float = 0.0
    delivery: DeliveryMetrics | None = None


@dataclass
class ExamSession:
    exam_id: str
    level: int
    survey: BackgroundSurvey
    questions: list[ExamQuestion] = field(default_factory=list)
    answers: list[ExamAnswer] = field(default_factory=list)
    created_at: str = ""


# ──────────────────────────────────────────────
# 문항 생성
# ──────────────────────────────────────────────

def generate_exam(
    survey: BackgroundSurvey,
    level: int,
    settings: dict,
) -> list[ExamQuestion]:
    """
    Background Survey + Self Assessment 난이도로 15문항 생성.

    문항 구성(콤보 배치)은 코드가 고정하고, 주제와 문장만 모델이 채운다.
    """
    cfg = settings.get("opic_coach", {})
    model = cfg.get("model", _DEFAULT_MODEL)
    blueprint = BLUEPRINTS.get(level, _COMBO_MID)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    slots = "\n".join(
        f"{i}. [{cat}] 기능={fn} ({FUNCTIONS[fn]})"
        for i, (cat, fn) in enumerate(blueprint, 1)
    )

    system = f"""\
당신은 OPIc 문항 출제자다. 실제 시험처럼 영어로 문항을 만든다.

## 규칙
- 문항 텍스트(text)는 영어로, 실제 OPIc 문항 어투를 따른다.
  (예: "I'd like to know about ...", "Tell me about ...", "Let's role play. ...")
- 아래 슬롯 구성을 그대로 따른다. 슬롯 순서·기능·개수를 바꾸지 마라.
- "설문 주제" 슬롯은 응시자가 Background Survey 에서 고른 항목에서만 뽑는다.
- "돌발 주제" 슬롯은 Background Survey 에 **없는** 주제에서 뽑는다.
  후보: {", ".join(SURPRISE_TOPICS)}
- 같은 category 안의 3문항은 하나의 콤보다. 같은 topic 을 공유하고
  묘사 → 루틴/경험 → 더 깊은 서술 순으로 난이도가 올라가야 한다.
- 롤플레이 3문항은 하나의 상황으로 이어져야 한다.
  ask(정보 요청) → problem(예상치 못한 문제 발생, 대안 제시) → experience(비슷한 실제 경험).
- 난이도 {level}단계 응시자 수준에 맞춘다: {SELF_ASSESSMENT.get(level, "")}
- guidance 는 한국어로, 이 문항이 요구하는 언어 기능을 한 줄로 적는다.

## 슬롯 구성
{slots}

## 출력 형식 (JSON만, 마크다운 코드블록 없이)
{{
  "questions": [
    {{"number": 1, "category": "<슬롯의 category>", "function": "<슬롯의 기능 키>",
      "topic": "<주제 한 단어~구>", "text": "<영어 문항>", "guidance": "<한국어 한 줄>"}}
  ]
}}
정확히 {len(blueprint)}개."""

    user_message = f"""\
### Background Survey
{survey.as_prompt()}

### Self Assessment
{level}단계 — {SELF_ASSESSMENT.get(level, "")}

위 정보로 문항 {len(blueprint)}개를 출제하라."""

    with client.messages.stream(
        model=model,
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        raw = stream.get_final_message().content[-1].text.strip()

    data = _parse_json(raw)
    questions: list[ExamQuestion] = []
    for i, (cat, fn) in enumerate(blueprint, 1):
        item = next((q for q in data.get("questions", []) if q.get("number") == i), {})
        questions.append(
            ExamQuestion(
                number=i,
                category=item.get("category", cat),
                function=fn,                       # 기능은 blueprint 를 신뢰한다
                topic=item.get("topic", ""),
                text=item.get("text", "").strip(),
                guidance=item.get("guidance", FUNCTIONS[fn]),
            )
        )
    return questions


# ──────────────────────────────────────────────
# 저장 / 로드
# ──────────────────────────────────────────────

def exam_dir(exam_id: str) -> Path:
    path = opic_dir() / "exams" / exam_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_exam_id() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def save_session(session: ExamSession) -> Path:
    """시험 상태를 JSON 으로 저장 (녹음 중단 후 이어서 채점 가능)."""
    path = exam_dir(session.exam_id) / "session.json"
    payload = {
        "exam_id": session.exam_id,
        "level": session.level,
        "created_at": session.created_at,
        "survey": asdict(session.survey),
        "questions": [asdict(q) for q in session.questions],
        "answers": [
            {**asdict(a), "delivery": asdict(a.delivery) if a.delivery else None}
            for a in session.answers
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_session(path: str | Path) -> ExamSession:
    """save_session 으로 저장한 시험 상태를 복원."""
    p = Path(path)
    if p.is_dir():
        p = p / "session.json"
    data = json.loads(p.read_text(encoding="utf-8"))

    answers = []
    for a in data.get("answers", []):
        d = a.pop("delivery", None)
        answers.append(ExamAnswer(delivery=DeliveryMetrics(**d) if d else None, **a))

    return ExamSession(
        exam_id=data["exam_id"],
        level=data["level"],
        survey=BackgroundSurvey(**data.get("survey", {})),
        questions=[ExamQuestion(**q) for q in data.get("questions", [])],
        answers=answers,
        created_at=data.get("created_at", ""),
    )


# ──────────────────────────────────────────────
# 시험 진행
# ──────────────────────────────────────────────

def run_exam(
    session: ExamSession,
    settings: dict,
    echo=print,
    input_fn=input,
    record_fn=None,
    speak_fn=None,
) -> ExamSession:
    """
    문항을 하나씩 제시하고 녹음 → 전사 → 세션에 누적.

    각 문항마다 Enter 로 녹음 시작, 다시 Enter 로 종료.
    's' 입력 시 해당 문항 건너뛴다.
    """
    from .recorder import record as default_record
    from .recorder import speak as default_speak
    from .transcriber import transcribe

    record_fn = record_fn or default_record
    speak_fn = speak_fn or default_speak

    cfg = (settings.get("opic_coach", {}) or {}).get("exam", {}) or {}
    max_seconds = cfg.get("max_answer_seconds", 120)
    read_aloud = cfg.get("read_question_aloud", True)

    directory = exam_dir(session.exam_id)
    answered = {a.number for a in session.answers}

    for q in session.questions:
        if q.number in answered:
            continue

        echo(f"\n[{q.number}/{len(session.questions)}] {q.category}")
        echo(f"  {q.text}")
        if read_aloud:
            speak_fn(q.text)

        command = input_fn(f"  Enter=녹음 시작 (최대 {max_seconds}초) / s=건너뛰기 / q=중단: ").strip().lower()
        if command == "q":
            echo("  시험을 중단합니다. 지금까지의 답변은 저장됩니다.")
            break
        if command == "s":
            echo("  건너뜀")
            continue

        echo("  ● 녹음 중... 답변을 마치면 Enter")
        recording = record_fn(directory / f"q{q.number:02d}.wav", max_seconds=max_seconds)
        note = " (시간 초과로 자동 종료)" if recording.stopped_by == "timeout" else ""
        echo(f"  ■ 녹음 종료 {recording.seconds}초{note}")
        if getattr(recording, "dropped_seconds", 0) >= 1.0:
            echo(f"  ⚠ 입력이 {recording.dropped_seconds}초 유실됐을 수 있습니다 "
                 f"(버튼 {recording.wall_seconds}초 vs 오디오 {recording.seconds}초)")

        echo("  전사 중...")
        transcript = transcribe(recording.path, settings)
        delivery = analyze_delivery(transcript)

        session.answers.append(
            ExamAnswer(
                number=q.number,
                question=q.text,
                transcript=transcript.text,
                audio_path=str(recording.path),
                seconds=recording.seconds,
                delivery=delivery,
            )
        )
        save_session(session)
        echo(f"  → {delivery.word_count}단어 / {delivery.wpm} wpm / "
             f"1초 이상 멈춤 {delivery.pause_counts.get('long', 0) + delivery.pause_counts.get('breakdown', 0)}회")

    return session


# ──────────────────────────────────────────────
# 채점
# ──────────────────────────────────────────────

def grade_exam(session: ExamSession, settings: dict, calibration_context: str = ""):
    """
    누적된 답변을 문항별로 평가하고 전체 등급까지 산출.

    Returns:
        (ratings, ProfileSummary, report_markdown)
    """
    from .profile_tracker import format_profile_report, summarize_profile
    from .rater import format_rating_report, rate_answer

    ratings = []
    details = []
    for answer in sorted(session.answers, key=lambda a: a.number):
        if not answer.transcript.strip():
            continue
        rating = rate_answer(
            question=answer.question,
            answer=answer.transcript,
            settings=settings,
            delivery=answer.delivery,
            calibration_context=calibration_context,
        )
        ratings.append(rating)
        details.append(format_rating_report(rating))

    summary = summarize_profile(ratings, settings)

    header = [
        f"# OPIc 모의고사 결과 — {session.exam_id}\n",
        f"난이도: Self Assessment {session.level}단계",
        f"응답 문항: {len(ratings)} / {len(session.questions)}\n",
        "## 출제 문항\n",
    ]
    for q in session.questions:
        answered = any(a.number == q.number and a.transcript.strip() for a in session.answers)
        mark = "✔" if answered else "—"
        header.append(f"{mark} {q.number}. [{q.category} / {FUNCTIONS.get(q.function, q.function)}] {q.text}")

    report = "\n".join(header) + "\n\n" + format_profile_report(summary, ratings)
    if details:
        report += "\n\n---\n\n" + "\n\n---\n\n".join(details)

    (exam_dir(session.exam_id) / "report.md").write_text(report, encoding="utf-8")
    return ratings, summary, report
