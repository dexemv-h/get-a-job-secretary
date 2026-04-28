"""
자소서 기반 면접 예상 질문 20개 생성.

인성 10개 + 기술/직무 10개로 분류.
각 질문에 추천 답변 구조(4단계) 힌트 포함.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import anthropic
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_MODEL = "claude-opus-4-7"


@dataclass
class InterviewQuestion:
    category: str           # "인성" | "기술/직무"
    question: str
    intent: str             # 면접관이 이 질문으로 확인하는 것
    answer_hint: str        # 4단계 구조 힌트 (지표-값-근거-결과)


def generate_questions(
    cover_letter: str,
    jd_text: str,
    settings: dict,
) -> list[InterviewQuestion]:
    """
    자소서 + 공고 분석 → 면접 예상 질문 20개 생성.

    Args:
        cover_letter: 최종 제출용 자소서 본문
        jd_text: 공고 전문
        settings: settings.yaml 전체 dict

    Returns:
        InterviewQuestion 리스트 (인성 10 + 기술/직무 10)
    """
    cfg = settings.get("interview_coach", {})
    model = cfg.get("model", _DEFAULT_MODEL)
    n_personality = cfg.get("personality_questions", 10)
    n_technical = cfg.get("technical_questions", 10)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    system = f"""\
당신은 10년 경력의 채용 면접관입니다.
자소서와 공고를 분석해 실제 면접에서 나올 법한 예리한 질문을 만드세요.

각 질문은 다음 JSON 형식으로 출력합니다:
{{
  "questions": [
    {{
      "category": "인성" 또는 "기술/직무",
      "question": "질문 텍스트",
      "intent": "면접관이 확인하는 역량/가치관",
      "answer_hint": "지표(무엇을 기준으로) → 값(수치) → 근거/행동(실제 한 것) → 결과 순서로 답변 구조 제안"
    }}
  ]
}}

인성 질문 {n_personality}개 + 기술/직무 질문 {n_technical}개.
총 {n_personality + n_technical}개. JSON만 출력."""

    user_message = f"""\
### 공고
{jd_text[:1000]}

### 자소서
{cover_letter[:2000]}

위를 분석해 면접 예상 질문 {n_personality + n_technical}개를 생성하세요."""

    with client.messages.stream(
        model=model,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        raw = stream.get_final_message().content[-1].text.strip()

    data = json.loads(raw)
    questions = []
    for q in data.get("questions", []):
        questions.append(
            InterviewQuestion(
                category=q.get("category", "인성"),
                question=q.get("question", ""),
                intent=q.get("intent", ""),
                answer_hint=q.get("answer_hint", ""),
            )
        )
    return questions


def format_question_list(questions: list[InterviewQuestion]) -> str:
    """면접 질문 목록을 마크다운으로 포맷."""
    personality = [q for q in questions if q.category == "인성"]
    technical = [q for q in questions if q.category == "기술/직무"]

    lines = ["# 면접 예상 질문\n", "## 인성 질문\n"]
    for i, q in enumerate(personality, 1):
        lines += [
            f"### {i}. {q.question}",
            f"**확인 포인트:** {q.intent}",
            f"**답변 힌트:** {q.answer_hint}\n",
        ]

    lines += ["\n## 기술/직무 질문\n"]
    for i, q in enumerate(technical, 1):
        lines += [
            f"### {i}. {q.question}",
            f"**확인 포인트:** {q.intent}",
            f"**답변 힌트:** {q.answer_hint}\n",
        ]

    return "\n".join(lines)
