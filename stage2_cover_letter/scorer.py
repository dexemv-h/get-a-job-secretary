"""
자소서 88점 채점-수정 루프.

흐름:
  초안 → Claude 채점 → 점수 < 88이면 피드백 기반 재작성 → 반복 (최대 5회)
  → 최종 자소서 + 채점 내역 반환

채점 기준은 settings.yaml scoring_rubric에서 로드.
시스템 프롬프트(루브릭)는 매 루프 동일하므로 prompt caching 적용.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ScoreResult:
    total: int
    breakdown: dict[str, int]   # rubric id → 획득 점수
    feedback: str               # 개선 포인트 (Korean)
    revised_text: str           # 수정된 자소서 (채점과 동시에 재작성)


@dataclass
class ScoringLoop:
    final_text: str
    final_score: int
    iterations: int
    history: list[ScoreResult] = field(default_factory=list)
    passed: bool = False


def _build_rubric_text(rubric: list[dict]) -> str:
    lines = ["## 채점 기준표 (총 100점)\n"]
    for item in rubric:
        lines.append(f"- [{item['id']}] {item['name']}: {item['max_score']}점")
    return "\n".join(lines)


def _scoring_system_prompt(rubric_text: str) -> str:
    return f"""\
당신은 엄격한 자소서 채점관입니다.
아래 기준표로 자소서를 채점하고, 동시에 수정본을 출력합니다.

{rubric_text}

## 출력 형식 (반드시 아래 JSON만 출력, 마크다운 코드블록 없이)
{{
  "scores": {{
    "core_first_sentence": <0-15>,
    "numbers_present": <0-15>,
    "no_ai_tone": <0-10>,
    "conciseness": <0-10>,
    "jd_keyword_coverage": <0-20>,
    "experience_link": <0-20>,
    "company_fit": <0-10>
  }},
  "total": <합계>,
  "feedback": "<한국어로 주요 개선점 3가지 이내>",
  "revised_text": "<수정된 자소서 전문>"
}}

채점 기준:
- no_ai_tone: "활용할 수 있습니다", "하도록 하겠습니다", "기여할 수 있을 것입니다" 등 AI투 문장이 있으면 0점
- numbers_present: 구체적 수치/숫자가 2개 이상이면 만점
- core_first_sentence: 첫 문장에 핵심 성과/역할이 바로 나오면 만점
"""


def score_and_revise(
    cover_letter: str,
    jd_text: str,
    rubric: list[dict],
    model: str = "claude-opus-4-7",
) -> ScoreResult:
    """한 번의 채점 + 수정을 수행하고 ScoreResult 반환."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    rubric_text = _build_rubric_text(rubric)
    system = _scoring_system_prompt(rubric_text)

    user_message = f"""\
### 공고 요약
{jd_text[:800]}

### 채점할 자소서
{cover_letter}

위 자소서를 채점하고, 점수가 낮은 항목을 개선한 수정본을 출력하세요."""

    with client.messages.stream(
        model=model,
        max_tokens=3000,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},  # 루브릭 캐싱
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        raw = stream.get_final_message().content[-1].text.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # JSON 파싱 실패 시 재시도 없이 현재 텍스트 유지
        return ScoreResult(
            total=0,
            breakdown={},
            feedback="JSON 파싱 실패 — 채점을 재시도하세요.",
            revised_text=cover_letter,
        )

    return ScoreResult(
        total=data.get("total", sum(data.get("scores", {}).values())),
        breakdown=data.get("scores", {}),
        feedback=data.get("feedback", ""),
        revised_text=data.get("revised_text", cover_letter),
    )


def run_scoring_loop(
    initial_draft: str,
    jd_text: str,
    settings: dict,
) -> ScoringLoop:
    """
    88점 달성까지 채점-수정 루프 실행.

    Args:
        initial_draft: generator.py가 만든 첫 초안
        jd_text: 공고 전문
        settings: settings.yaml 전체 dict

    Returns:
        ScoringLoop: 최종 자소서, 최종 점수, 반복 횟수, 히스토리
    """
    cfg = settings.get("cover_letter", {})
    pass_score: int = cfg.get("pass_score", 88)
    max_iterations: int = cfg.get("max_iterations", 5)
    rubric: list[dict] = cfg.get("scoring_rubric", [])
    model: str = cfg.get("model", "claude-opus-4-7")

    current_text = initial_draft
    history: list[ScoreResult] = []

    for i in range(max_iterations):
        result = score_and_revise(current_text, jd_text, rubric, model)
        history.append(result)
        current_text = result.revised_text

        if result.total >= pass_score:
            return ScoringLoop(
                final_text=current_text,
                final_score=result.total,
                iterations=i + 1,
                history=history,
                passed=True,
            )

    # max_iterations 소진 — 최고 점수 버전 선택
    best = max(history, key=lambda r: r.total)
    best_idx = history.index(best)
    best_text = history[best_idx].revised_text

    return ScoringLoop(
        final_text=best_text,
        final_score=best.total,
        iterations=max_iterations,
        history=history,
        passed=False,
    )
