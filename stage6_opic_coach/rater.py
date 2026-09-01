"""
단일 OPIc 답변 평가기.

한 문제의 답변만으로는 시험 전체 등급을 확정하지 않는다.
"이 답변 단독 기준 예상 수행 수준"만 산출하고,
전체 등급은 stage6_opic_coach.profile_tracker 에서 여러 답변을 누적해 추정한다.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import anthropic
from dotenv import load_dotenv

from .delivery import DeliveryMetrics, format_delivery_summary
from .rubric import (
    EVALUATION_PHILOSOPHY,
    FUNCTION_ITEMS,
    GRADES,
    NO_AUDIO_PRONUNCIATION,
    PRONUNCIATION_NOT_HEARD,
    format_range,
    grade_index,
    next_grade,
    status_label,
)

load_dotenv()

_DEFAULT_MODEL = "claude-opus-4-7"


@dataclass
class FunctionCheck:
    """기능 분석 1개 항목."""
    key: str            # FUNCTION_ITEMS 의 키
    status: str         # stable | partial | weak | na
    comment: str        # 근거 (실제 답변 인용 포함)


@dataclass
class DimensionAnalysis:
    """Fluency / Vocabulary / Grammar 등 상세 분석 1개 축."""
    strength: str
    problem: str
    evidence: str       # 실제 답변 근거 (인용)


@dataclass
class SentenceFix:
    """문장 교정 1건."""
    original: str
    problem: str
    natural: str        # 자연스러운 수정
    higher_level: str   # 더 높은 OPIc 수준의 표현


@dataclass
class OpicRating:
    """단일 답변 평가 결과."""
    question: str
    answer: str
    has_audio: bool                 # 음성 파일이 존재하고 delivery 지표를 뽑았는지

    level_low: str                  # 예상 수행 수준 하한
    level_high: str                 # 예상 수행 수준 상한 (단일이면 low와 동일)
    confidence: str                 # 높음 | 보통 | 낮음
    task_difficulty: str            # 질문 자체의 난이도
    verdict: str                    # 핵심 판정 (왜 이 등급인지 + 왜 바로 위가 아닌지)

    functions: list[FunctionCheck] = field(default_factory=list)
    fluency: DimensionAnalysis | None = None
    vocabulary: DimensionAnalysis | None = None
    grammar: DimensionAnalysis | None = None
    pronunciation: str = NO_AUDIO_PRONUNCIATION
    delivery: DeliveryMetrics | None = None

    blockers: list[str] = field(default_factory=list)      # 상위 등급을 막는 핵심 요소 TOP 3
    fixes: list[SentenceFix] = field(default_factory=list)
    upgraded_answer: str = ""                              # 한 단계 위 수준 답변 예시
    practice_points: list[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        """'IH' 또는 'IH~AL' 형태의 수행 수준 문자열."""
        return format_range(self.level_low, self.level_high)

    def function_status(self, key: str) -> str:
        """기능 항목의 status 키를 조회. 없으면 'na'."""
        for f in self.functions:
            if f.key == key:
                return f.status
        return "na"


def _parse_json(raw: str) -> dict:
    """모델 출력에서 JSON 본문만 추출해 파싱."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _clamp_grade(value: str, fallback: str = "IM2") -> str:
    """모델이 준 등급 문자열을 사다리 위 값으로 정규화."""
    if not value:
        return fallback
    g = value.strip().upper()
    return g if grade_index(g) >= 0 else fallback


def _build_system_prompt(
    has_delivery: bool,
    max_fixes: int,
    calibration_context: str = "",
) -> str:
    function_keys = "\n".join(f'  - "{k}": {label}' for k, label in FUNCTION_ITEMS.items())
    audio_rule = (
        "음성에서 뽑은 delivery 지표가 함께 주어진다. 이는 멈춤·속도·발화 덩어리 크기 등\n"
        "시간 정보이지 발음 정보가 아니다. Fluency와 Text Type 판단의 객관 근거로만 쓰고,\n"
        "수치가 좋다는 이유만으로 등급을 올리지 마라. 특히 말이 빠르다는 것은 유창성이 아니다.\n"
        "발음/억양은 어떤 경우에도 판정하지 마라."
        if has_delivery
        else "delivery 지표가 없다. 멈춤·속도·발음에 대해 추측하지 마라."
    )
    calib_block = (
        f"\n## 캘리브레이션 참고 기준\n"
        f"아래는 확인된 실제 응시 샘플에서 반복적으로 확인된 내 예측 편향이다.\n"
        f"공식 proficiency 원칙을 덮어쓰는 규칙이 아니라, 예측을 보정하는 참고 기준으로만 사용하라.\n"
        f"{calibration_context}\n"
        if calibration_context
        else ""
    )

    return f"""{EVALUATION_PHILOSOPHY}
{calib_block}
## 이번 과제
답변 1개만 주어졌다. 시험 전체 등급을 확정하지 마라.
"이 답변 단독 기준 예상 수행 수준"만 산출하고, 확신이 낮으면 level_low != level_high 로 경계를 제시하라.

{audio_rule}

## 출력 형식 (JSON만, 마크다운 코드블록 없이)
{{
  "level_low": "{'|'.join(GRADES)} 중 하나",
  "level_high": "동일 목록 중 하나 (단일 등급이면 level_low와 같게)",
  "confidence": "높음|보통|낮음",
  "task_difficulty": "질문 자체가 요구하는 과제 난이도 한 줄 설명",
  "verdict": "3~5문장. 이 답변이 왜 이 수준인지 + 반드시 '왜 바로 위 등급이 아닌가'를 포함",
  "functions": [
    {{"key": "<아래 키 중 하나>", "status": "stable|partial|weak|na", "comment": "실제 답변 인용 포함 근거"}}
  ],
  "fluency":    {{"strength": "", "problem": "", "evidence": "답변에서 인용"}},
  "vocabulary": {{"strength": "", "problem": "", "evidence": "답변에서 인용"}},
  "grammar":    {{"strength": "", "problem": "", "evidence": "답변에서 인용"}},
  "blockers": ["바로 위 등급을 막는 핵심 요소 3개. 사소한 문법 실수는 넣지 마라."],
  "fixes": [
    {{"original": "원문 문장", "problem": "무엇이 문제인지",
      "natural": "자연스러운 수정", "higher_level": "더 높은 OPIc 수준의 표현"}}
  ],
  "upgraded_answer": "사용자의 원래 내용과 경험을 유지한 채 한 단계 높은 수준으로 다시 쓴 답변. 새 이야기를 지어내지 마라.",
  "practice_points": ["다음 답변에서 집중할 행동 1~3개"]
}}

functions 배열에는 아래 9개 키를 모두 정확히 한 번씩 포함하라.
{function_keys}

fixes 는 개선 가치가 높은 순으로 최대 {max_fixes}개.
실제 시험장에서 말하기 어려울 만큼 과도하게 고급스럽거나 암기 티가 나는 표현은 피하라.
한국어로 설명하고, 영어 예시 문장만 영어로 쓴다. JSON만 출력."""


def rate_answer(
    question: str,
    answer: str,
    settings: dict,
    delivery: DeliveryMetrics | None = None,
    calibration_context: str = "",
) -> OpicRating:
    """
    단일 OPIc 답변을 평가.

    Args:
        question: OPIc 질문
        answer: 답변 transcript
        settings: settings.yaml 전체 dict
        delivery: 음성에서 뽑은 delivery 지표 (없으면 텍스트만으로 평가)
        calibration_context: build_calibration_context() 결과 (없으면 빈 문자열)

    Returns:
        OpicRating

    Note:
        발음/억양은 어떤 경우에도 평가하지 않는다. 모델이 오디오를 직접 듣지 않기 때문이다.
    """
    cfg = settings.get("opic_coach", {})
    model = cfg.get("model", _DEFAULT_MODEL)
    max_fixes = cfg.get("max_sentence_fixes", 5)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    system = _build_system_prompt(delivery is not None, max_fixes, calibration_context)
    delivery_block = (
        f"\n### 음성에서 측정한 delivery 지표 (객관 수치, 발음 정보 아님)\n"
        f"{format_delivery_summary(delivery)}\n"
        if delivery
        else "\n### 음성 제공 여부\n제공되지 않음 (transcript만)\n"
    )
    user_message = f"""\
### OPIc 질문
{question}

### 수험생 답변 (transcript)
{answer}
{delivery_block}
위 답변을 평가하라."""

    with client.messages.stream(
        model=model,
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        raw = stream.get_final_message().content[-1].text.strip()

    data = _parse_json(raw)

    level_low = _clamp_grade(data.get("level_low", ""))
    level_high = _clamp_grade(data.get("level_high", ""), fallback=level_low)
    if grade_index(level_high) < grade_index(level_low):
        level_low, level_high = level_high, level_low

    functions = [
        FunctionCheck(
            key=f.get("key", ""),
            status=f.get("status", "na"),
            comment=f.get("comment", ""),
        )
        for f in data.get("functions", [])
        if f.get("key") in FUNCTION_ITEMS
    ]

    def _dim(key: str) -> DimensionAnalysis:
        d = data.get(key) or {}
        return DimensionAnalysis(
            strength=d.get("strength", ""),
            problem=d.get("problem", ""),
            evidence=d.get("evidence", ""),
        )

    fixes = [
        SentenceFix(
            original=f.get("original", ""),
            problem=f.get("problem", ""),
            natural=f.get("natural", ""),
            higher_level=f.get("higher_level", ""),
        )
        for f in data.get("fixes", [])[:max_fixes]
    ]

    if delivery is None:
        pronunciation = NO_AUDIO_PRONUNCIATION
    else:
        pronunciation = (
            f"{PRONUNCIATION_NOT_HEARD}\n"
            f"  명료도 참고치: 전사 저신뢰 단어 비율 {delivery.low_confidence_ratio:.0%}"
        )

    return OpicRating(
        question=question,
        answer=answer,
        has_audio=delivery is not None,
        level_low=level_low,
        level_high=level_high,
        confidence=data.get("confidence", "보통"),
        task_difficulty=data.get("task_difficulty", ""),
        verdict=data.get("verdict", ""),
        functions=functions,
        fluency=_dim("fluency"),
        vocabulary=_dim("vocabulary"),
        grammar=_dim("grammar"),
        pronunciation=pronunciation,
        delivery=delivery,
        blockers=data.get("blockers", [])[:3],
        fixes=fixes,
        upgraded_answer=data.get("upgraded_answer", ""),
        practice_points=data.get("practice_points", [])[:3],
    )


def format_rating_report(
    rating: OpicRating,
    overall_grade: str = "판단 보류",
    floor: str = "판단 보류",
    ceiling: str = "판단 보류",
) -> str:
    """
    평가 결과를 지정된 출력 형식의 마크다운으로 포맷.

    Args:
        rating: 단일 답변 평가 결과
        overall_grade: 시험 전체 예상 등급 (답변이 부족하면 "판단 보류")
        floor: 누적 데이터 기반 Floor
        ceiling: 누적 데이터 기반 Ceiling
    """
    above = next_grade(rating.level_high)
    above_text = (
        f"바로 위 등급은 {above}. 미도달 근거는 위 핵심 판정에 포함되어야 한다."
        if above
        else "현재 사다리의 최상위 등급이므로 위 등급 비교 없음."
    )

    lines = [
        "# OPIc 예상 수준\n",
        f"예상 수행 수준: 이 답변 단독 기준 {rating.level}",
        f"가능 범위: 하한 {rating.level_low} / 상한 {rating.level_high}",
        f"판단 확신도: {rating.confidence}\n",
        f"시험 전체 예상 등급: {overall_grade}",
    ]
    if overall_grade == "판단 보류":
        lines.append("→ 시험 전체 등급은 여러 질문에서의 지속적인 수행을 확인해야 한다.")
    lines += [
        "",
        f"Floor: {floor}",
        f"Ceiling: {ceiling}\n",
        "# 핵심 판정\n",
        f"과제 난이도: {rating.task_difficulty}\n",
        f"{rating.verdict}\n",
        f"{above_text}\n",
        "# OPIc 기능 분석\n",
    ]

    for key, label in FUNCTION_ITEMS.items():
        check = next((f for f in rating.functions if f.key == key), None)
        if check is None:
            lines.append(f"- {label}: {status_label('na')}")
            continue
        comment = f" — {check.comment}" if check.comment else ""
        lines.append(f"- {label}: {status_label(check.status)}{comment}")

    lines.append("\n# 상세 분석\n")
    for title, dim in (
        ("Fluency", rating.fluency),
        ("Vocabulary", rating.vocabulary),
        ("Grammar", rating.grammar),
    ):
        d = dim or DimensionAnalysis("", "", "")
        lines += [
            f"## {title}",
            f"강점: {d.strength}",
            f"문제: {d.problem}",
            f"실제 답변 근거: {d.evidence}\n",
        ]

    lines += [
        "## Pronunciation / Intonation",
        rating.pronunciation,
        "",
    ]
    if rating.delivery is not None:
        lines += [
            "## Delivery 지표 (음성 시간 정보)",
            format_delivery_summary(rating.delivery),
            "",
        ]
    lines.append("# 등급을 막는 핵심 요소 TOP 3\n")
    if rating.blockers:
        lines += [f"{i}. {b}" for i, b in enumerate(rating.blockers, 1)]
    else:
        lines.append("(도출된 항목 없음)")

    lines.append("\n# 문장 교정\n")
    if rating.fixes:
        for i, fix in enumerate(rating.fixes, 1):
            lines += [
                f"### {i}",
                f"원문: {fix.original}",
                f"문제: {fix.problem}",
                f"자연스러운 수정: {fix.natural}",
                f"더 높은 OPIc 수준의 표현: {fix.higher_level}\n",
            ]
    else:
        lines.append("(교정 대상 없음)\n")

    lines += [
        "# 더 높은 등급으로 바꾼다면\n",
        rating.upgraded_answer or "(제시 없음)",
        "",
        "# 다음 연습 포인트\n",
    ]
    if rating.practice_points:
        lines += [f"{i}. {p}" for i, p in enumerate(rating.practice_points, 1)]
    else:
        lines.append("(제시 없음)")

    return "\n".join(lines) + "\n"
