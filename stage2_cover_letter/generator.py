"""
자소서 초안 생성.

공고(JD) + 내 프로필을 받아 Claude가 첫 번째 초안을 작성.
이후 scorer.py가 채점-수정 루프를 담당.
"""
from __future__ import annotations

import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_MODEL = "claude-opus-4-7"

_SYSTEM_PROMPT = """\
당신은 10년 경력의 취업 컨설턴트입니다.
다음 규칙을 반드시 따르세요:

1. 핵심 내용을 첫 문장에 — 두괄식 작성
2. 수치/숫자를 최소 2곳 이상 포함
3. AI투 표현 금지: "활용할 수 있습니다", "하도록 하겠습니다", "기여할 수 있을 것입니다" 등
4. 가운뎃점(·) 사용 금지
5. 한 문단 최대 5줄
6. 공고 요구 역량 키워드를 자연스럽게 녹여낼 것
7. 지원자의 실제 경험과 해당 직무를 구체적으로 연결할 것
"""


def generate_draft(
    jd_text: str,
    profile_text: str,
    question: str = "",
    char_limit: int = 0,
    model: str = _DEFAULT_MODEL,
) -> str:
    """
    자소서 초안 생성.

    Args:
        jd_text: 공고 전문(Job Description)
        profile_text: 지원자 경력/프로필 요약
        question: 자소서 문항 (없으면 종합 자기소개)
        char_limit: 글자 수 제한 (0이면 제한 없음)
        model: 사용할 Claude 모델

    Returns:
        생성된 자소서 초안 텍스트
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    question_section = f"\n### 자소서 문항\n{question}" if question else ""
    limit_section = f"\n### 글자 수 제한\n{char_limit}자 ±10% 이내" if char_limit else ""

    user_message = f"""\
아래 공고와 지원자 프로필을 바탕으로 자소서를 작성해 주세요.
{question_section}
{limit_section}

### 공고 (JD)
{jd_text}

### 지원자 프로필
{profile_text}

자소서 본문만 출력하세요. 추가 설명이나 제목 없이 본문만."""

    with client.messages.stream(
        model=model,
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        return stream.get_final_message().content[-1].text


def load_profile(profile_path: str | None = None) -> str:
    """프로필 파일 로드. 경로 미지정 시 config/profile.txt 사용."""
    if profile_path:
        return Path(profile_path).read_text(encoding="utf-8")
    default = Path(__file__).parent.parent / "config" / "profile.txt"
    if default.exists():
        return default.read_text(encoding="utf-8")
    return ""
