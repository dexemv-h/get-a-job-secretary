"""
OPIc 평가 기준 정의.

공식 OPIc의 비공개 내부 채점 알고리즘이 아니라
공개된 ACTFL/OPIc proficiency 원칙 + 사용자가 제공한 실제 응시 샘플을 근거로
"예상 등급"을 산출하기 위한 기준표.

핵심 원칙:
  문법 + 어휘 + 발음 + 유창성의 합산 점수가 아니라
  Functions / Text Type / Context / Accuracy 4축으로 먼저 판단하고,
  Floor(안정적으로 반복 가능한 수준)와 Ceiling(시도하지만 무너지는 수준)을 분리한다.
"""
from __future__ import annotations

# ──────────────────────────────────────────────
# 등급 사다리
# ──────────────────────────────────────────────

GRADES = ["NL", "NM", "NH", "IL", "IM1", "IM2", "IM3", "IH", "AL"]

GRADE_MODEL = {
    "NL": "주로 단어, 외운 표현, 아주 짧은 구에 의존. 자발적인 문장 생성이 거의 없음.",
    "NM": "외운 표현과 짧은 구 중심. 자발적 문장 생성 능력이 제한적.",
    "NH": "익숙한 주제에서 간단한 문장은 만들 수 있으나 지속적인 연결 발화가 어려움.",
    "IL": "익숙한 일상 주제에서 sentence-level 답변은 비교적 안정적. "
          "길게 연결된 서술이나 복잡한 상황 처리에는 제한.",
    "IM1": "Intermediate 기능이 나타나지만 발화 확장성·안정성·연결성이 상대적으로 낮음.",
    "IM2": "익숙한 주제에서 여러 문장을 연결하고 이유·경험·설명을 비교적 안정적으로 수행.",
    "IM3": "Intermediate 기능이 매우 안정적이고 일부 확장된 narration/description이 나타나지만, "
           "IH 수준의 안정적인 Advanced 시도에는 아직 부족.",
    "IH": "Intermediate 기능이 매우 안정적이고 Advanced 기능(긴 narration, description, "
          "paragraph-level discourse, 다중 시간대, 예상치 못한 상황 처리)을 상당 부분 시도하지만, "
          "여러 문제·여러 주제에서 지속적으로 유지하지는 못함.",
    "AL": "Advanced 기능을 여러 주제에서 안정적으로 수행. 과거 사건의 chronological narration, "
          "충분한 description, 과거/현재/미래 시간대 통제, paragraph-length discourse, "
          "complication 대응, 원인→사건→대응→결과 구조화가 반복적으로 유지됨.",
}

# IM1/IM2/IM3 세부 경계는 공개적으로 완전히 명확하지 않다.
# 절대적인 공식 알고리즘처럼 표현하지 않기 위한 주의 문구.
IM_BOUNDARY_CAVEAT = (
    "IM1 / IM2 / IM3의 세부 경계는 공개적으로 완전히 명확하지 않다. "
    "공식 알고리즘처럼 단정하지 말고, 확인된 실제 응시 샘플(Calibration Sample)이 쌓인 만큼만 보정한다."
)

# ──────────────────────────────────────────────
# 기능 분석 항목
# ──────────────────────────────────────────────

FUNCTION_ITEMS = {
    "functions_tasks": "Functions / Tasks",
    "text_type": "Text Type",
    "context_content": "Context / Content",
    "time_frame": "Time Frame",
    "narration": "Narration",
    "description": "Description",
    "complication_handling": "Complication Handling",
    "accuracy": "Accuracy",
    "comprehensibility": "Comprehensibility",
}

STATUS_SYMBOLS = {
    "stable": "✅ 안정적",
    "partial": "△ 부분적",
    "weak": "❌ 부족",
    "na": "N/A 평가 불가",
}

# Floor/Ceiling 및 AL 판정에서 "Advanced 기능"으로 카운트하는 항목
DEFAULT_ADVANCED_FUNCTIONS = [
    "text_type",
    "time_frame",
    "narration",
    "description",
    "complication_handling",
]

# 발음/억양 항목 고정 문구.
# 이 파이프라인은 오디오를 모델에 직접 넣지 않는다(모델이 소리를 듣지 못한다).
# 따라서 발음·억양·강세·rhythm 은 어떤 경우에도 모델이 판정하지 않는다.
NO_AUDIO_PRONUNCIATION = "발음/억양: 평가 불가 — 음성 정보가 제공되지 않음"
PRONUNCIATION_NOT_HEARD = (
    "발음/억양: 평가 불가 — 모델이 오디오를 직접 듣지 않음 "
    "(전사 텍스트와 시간 정보만 사용). 아래 명료도 참고치는 발음 점수가 아님."
)

# ──────────────────────────────────────────────
# 평가 철학 (LLM system prompt 공통 블록)
# ──────────────────────────────────────────────

EVALUATION_PHILOSOPHY = f"""\
당신은 한국 OPIc 수험생의 말하기 수행을 분석하는 OPIc Rating & Calibration Coach다.
목적은 영어 문장을 자연스럽게 고쳐 주는 것이 아니라, 예상 OPIc 등급을 판단하고
왜 그 등급인지, 바로 위 등급이 나오지 않는 이유가 무엇인지 설명하는 것이다.

공식 OPIc의 비공개 내부 채점 알고리즘을 알고 있다고 주장하지 마라.
공개된 ACTFL/OPIc proficiency 원칙과 확인된 실제 응시 샘플만을 근거로 "예상 등급"을 산출한다.

## 1. 판단 순서
1) Functions / Tasks — 해당 레벨이 요구하는 언어 기능(설명, 묘사, 경험 서술, 과거 사건 서술,
   비교, 이유 설명, 문제 상황 처리, 예상치 못한 complication 대응, 시간대 처리)을 수행하는가.
2) Text Type — 단어/구 / 단문 / 연결된 문장 / paragraph-length discourse / 확장된 discourse 중 어디인가.
   답변이 길다는 것만으로 상위 text type으로 판단하지 마라.
3) Context / Content — 질문에 적절하고 구체적으로 대응하는가.
4) Accuracy / Comprehensibility — 문법·어휘·발음·유창성 문제가 의미 전달을 실제로 얼마나 방해하는가.

## 2. Floor / Ceiling
Floor = 여러 문제·여러 주제에서 안정적으로 반복 수행 가능한 최고 수준.
Ceiling = 시도는 하지만 지속하지 못하고 breakdown이 발생하는 수준.
한 개의 좋은 답변만으로 높은 등급을 주지 마라.

## 3. 등급별 판단 모델
{chr(10).join(f"- {g}: {d}" for g, d in GRADE_MODEL.items())}

{IM_BOUNDARY_CAVEAT}

## 4. IH vs AL 특별 판정
IH와 AL의 경계는 매우 엄격하게 본다. 다음이 보이면 AL 판정을 신중하게 하라.
- 내용은 많지만 단순 문장 나열 중심
- and / so / because 의존 과다
- 긴 답변에서 시제가 자주 붕괴
- 과거 이야기를 chronological하게 조직하지 못함
- description은 되지만 narration이 약함
- 예상치 못한 문제 상황에서 말이 급격히 단순해짐
- 외운 듯한 표현은 많지만 spontaneous language가 부족함
- 질문이 어려워지면 회피하거나 일반론으로 전환
- paragraph-length 답변이 한두 문제에서만 나타남
AL에 가까울수록 여러 종류의 질문에서 Advanced 기능이 반복적·안정적으로 나타나야 한다.

## 5. 문법 / 어휘 / 유창성
문법 오류의 개수만 세지 마라. 다음을 구분한다.
- Local Error: 오류가 있으나 의미 전달에는 거의 문제 없음
- Systematic Error: 반복되는 패턴성 오류
- Breakdown Error: 청자가 의미를 이해하기 어렵게 만드는 오류
높은 수준에서는 오류 자체보다 "복잡한 내용을 말할 때도 accuracy가 유지되는가"를 본다.

어휘는 어려운 단어/idiom 개수가 아니라 의미에 맞는 자연스러움, collocation, 반복 여부,
구체성, paraphrasing 능력, 상황별 표현 선택을 본다.

유창성은 의미 있는 pause / 지나친 hesitation / filler / self-correction / repetition /
false start / 문장 연결 / 사고 때문에 흐름이 끊기는 정도를 본다.
filler를 썼다는 이유만으로 가산점을 주지 마라.

## 6. 발음
너는 오디오를 직접 듣지 않는다. 따라서 발음·억양·강세·rhythm 은 절대 판정하지 마라.
텍스트나 수치만 보고 발음이 좋다/나쁘다고 추측하는 것은 조작이다.
원어민 accent와 다르다는 이유로 감점하는 것도 금지한다.
판단은 Comprehensibility(의미가 전달되는가) 중심으로만 한다.

## 7. 금지사항
- 사용자를 기분 좋게 하려고 등급을 높이지 마라.
- 답변이 길다는 이유만으로 높은 등급을 주지 마라.
- idiom을 많이 썼다는 이유만으로 AL이라고 하지 마라.
- filler가 자연스럽다는 이유만으로 점수를 올리지 마라.
- 문법 오류가 거의 없다는 이유만으로 AL이라고 하지 마라.
- 한 문제에서 AL 수준을 보였다는 이유만으로 전체 등급을 AL이라고 하지 마라.
- 스크립트처럼 완벽한 답변과 실제 spontaneous speech를 동일하게 평가하지 마라.
- 확신할 수 없으면 무리하게 하나의 등급을 고르지 말고 IM3~IH, IH~AL처럼 경계를 제시하라.
- 모든 판단 근거는 사용자의 실제 답변에서 인용하라.
"""


# ──────────────────────────────────────────────
# 등급 유틸
# ──────────────────────────────────────────────

def grade_index(grade: str) -> int:
    """등급 문자열을 사다리 인덱스로 변환. 알 수 없으면 -1."""
    try:
        return GRADES.index(grade.strip().upper())
    except (ValueError, AttributeError):
        return -1


def next_grade(grade: str) -> str | None:
    """바로 위 등급. 최상위(AL)면 None."""
    i = grade_index(grade)
    if i < 0 or i >= len(GRADES) - 1:
        return None
    return GRADES[i + 1]


def format_range(low: str, high: str) -> str:
    """등급 범위를 'IH~AL' 형태로 포맷. 같으면 단일 등급."""
    if not high or low == high:
        return low
    lo, hi = grade_index(low), grade_index(high)
    if lo > hi >= 0:
        low, high = high, low
    return f"{low}~{high}"


def status_label(status: str) -> str:
    """status 키를 출력용 기호 문자열로 변환."""
    return STATUS_SYMBOLS.get(status, STATUS_SYMBOLS["na"])
