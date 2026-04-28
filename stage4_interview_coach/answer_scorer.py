"""
면접 답변 4단계 채점기.

4단계 구조: 지표(metric) → 값(value) → 근거/행동(action_basis) → 결과(result)
각 항목 25점 만점, 총 100점.
실시간 답변 입력 + 즉각 피드백 루프 지원.
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
class AnswerScore:
    metric: int         # 지표 명시 (0-25)
    value: int          # 수치 값 존재 (0-25)
    action_basis: int   # 행동/근거 (0-25)
    result: int         # 결과 명시 (0-25)
    total: int
    feedback: str
    model_answer: str   # 개선된 모범 답변


def score_answer(
    question: str,
    answer: str,
    settings: dict,
) -> AnswerScore:
    """
    면접 답변을 4단계 기준으로 채점하고 모범 답변 생성.

    Args:
        question: 면접 질문
        answer: 지원자 답변
        settings: settings.yaml 전체 dict

    Returns:
        AnswerScore (채점 결과 + 모범 답변)
    """
    cfg = settings.get("interview_coach", {})
    model = cfg.get("model", _DEFAULT_MODEL)
    rubric = cfg.get("answer_rubric", [])
    time_limit = cfg.get("answer_time_limit_seconds", 60)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    rubric_text = "\n".join(
        f"- {r['name']} ({r['id']}): {r['max_score']}점" for r in rubric
    )

    system = f"""\
당신은 면접관 겸 코치입니다.
4단계 답변 구조로 지원자 답변을 채점하고, 개선된 모범 답변을 제시합니다.

## 채점 기준 (총 100점)
{rubric_text}

## 채점 가이드
- metric(지표): "저는 ~를 기준으로" 또는 "~지표를 관리했습니다" 같은 측정 기준이 있으면 고득점
- value(값): 구체적 숫자(%, 건수, 금액, 기간 등)가 있으면 고득점
- action_basis(행동): "제가 직접 ~했습니다" 처럼 책임 나열이 아닌 실제 행동이면 고득점
- result(결과): 정량/정성 결과가 명시되면 고득점

## 출력 형식 (JSON만, 마크다운 코드블록 없이)
{{
  "scores": {{
    "metric": <0-25>,
    "value": <0-25>,
    "action_basis": <0-25>,
    "result": <0-25>
  }},
  "total": <합계>,
  "feedback": "<한국어로 가장 부족한 1-2가지 개선점>",
  "model_answer": "<4단계 구조를 갖춘 개선된 모범 답변 (약 {time_limit}초 분량)>"
}}"""

    user_message = f"""\
### 면접 질문
{question}

### 지원자 답변
{answer}

위 답변을 채점하고 모범 답변을 제시하세요."""

    with client.messages.stream(
        model=model,
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        raw = stream.get_final_message().content[-1].text.strip()

    data = json.loads(raw)
    scores = data.get("scores", {})

    return AnswerScore(
        metric=scores.get("metric", 0),
        value=scores.get("value", 0),
        action_basis=scores.get("action_basis", 0),
        result=scores.get("result", 0),
        total=data.get("total", sum(scores.values())),
        feedback=data.get("feedback", ""),
        model_answer=data.get("model_answer", ""),
    )


def run_practice_session(
    questions: list[str],
    settings: dict,
    input_fn=input,
) -> list[tuple[str, str, AnswerScore]]:
    """
    대화형 면접 연습 세션.

    Args:
        questions: 면접 질문 목록
        settings: settings.yaml 전체 dict
        input_fn: 입력 함수 (테스트 시 주입 가능)

    Returns:
        (질문, 답변, 채점결과) 튜플 리스트
    """
    results = []
    for i, q in enumerate(questions, 1):
        print(f"\n[{i}/{len(questions)}] {q}")
        print("답변 입력 (입력 완료 후 빈 줄 + Enter):")

        lines = []
        while True:
            line = input_fn()
            if line == "":
                break
            lines.append(line)
        answer = "\n".join(lines)

        if not answer.strip():
            print("  [건너뜀]")
            continue

        score = score_answer(q, answer, settings)
        print(f"\n  점수: {score.total}/100")
        print(f"  피드백: {score.feedback}")
        print(f"\n  모범 답변:\n  {score.model_answer}")

        results.append((q, answer, score))

    return results
