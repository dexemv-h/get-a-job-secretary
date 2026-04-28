"""
LinkedIn 프로필 최적화.

흐름:
  공고 목록(JD 텍스트들) → 핵심 키워드 추출
  → 현재 프로필 + 키워드 → 섹션별 전면 재작성
  → 최종 최적화 프로필 출력
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import anthropic
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_MODEL = "claude-opus-4-7"


@dataclass
class LinkedInProfile:
    headline: str
    about: str
    experience_bullets: dict[str, list[str]]  # 회사명 → 성과 bullet list
    skills: list[str]


def extract_keywords(jd_texts: list[str], model: str = _DEFAULT_MODEL) -> list[str]:
    """
    여러 공고에서 LinkedIn 알고리즘 친화적 핵심 키워드 추출.

    Args:
        jd_texts: 공고 본문 목록
        model: 사용할 Claude 모델

    Returns:
        중복 제거 + 중요도순 정렬된 키워드 리스트
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    combined_jd = "\n\n---\n\n".join(jd_texts[:10])  # 최대 10개 공고

    system = """\
당신은 LinkedIn SEO 전문가입니다.
공고 목록에서 리크루터가 실제로 검색하는 핵심 스킬/직무 키워드만 추출하세요.

출력: 줄마다 키워드 하나, 중요도 내림차순. 최대 30개.
형식: 그냥 키워드만, 번호나 설명 없이."""

    with client.messages.stream(
        model=model,
        max_tokens=512,
        thinking={"type": "adaptive"},
        system=system,
        messages=[
            {
                "role": "user",
                "content": f"다음 공고들에서 LinkedIn 키워드를 추출하세요:\n\n{combined_jd}",
            }
        ],
    ) as stream:
        raw = stream.get_final_message().content[-1].text

    keywords = [line.strip() for line in raw.splitlines() if line.strip()]
    return keywords


def optimize_profile(
    current_profile: LinkedInProfile,
    keywords: list[str],
    target_role: str,
    model: str = _DEFAULT_MODEL,
) -> LinkedInProfile:
    """
    키워드 기반 LinkedIn 프로필 전면 재작성.

    Args:
        current_profile: 현재 프로필 내용
        keywords: extract_keywords가 뽑은 키워드 목록
        target_role: 지원 타겟 직무 (예: "PM", "서비스 기획")
        model: 사용할 Claude 모델

    Returns:
        최적화된 LinkedInProfile
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    keyword_str = ", ".join(keywords[:20])

    system = """\
당신은 LinkedIn 프로필 최적화 전문가입니다.
다음 규칙을 지키세요:

1. Headline: 120자 이내, 타겟 직무 키워드 + 핵심 강점 포함
2. About: 2,600자 이내, 첫 3줄에 가장 강한 성과, 키워드 자연스럽게 포함
3. Experience bullet: 동사 시작, 수치 포함, 1줄 80자 이내
4. Skills: 공고 키워드와 일치하는 스킬 우선 배치

JSON 형식으로만 출력:
{
  "headline": "...",
  "about": "...",
  "experience_bullets": {"회사명": ["bullet1", "bullet2", ...]},
  "skills": ["skill1", "skill2", ...]
}"""

    profile_str = f"""\
현재 Headline: {current_profile.headline}
현재 About: {current_profile.about}
경력:
{chr(10).join(f'  {comp}: {bullets}' for comp, bullets in current_profile.experience_bullets.items())}
현재 Skills: {', '.join(current_profile.skills)}"""

    user_message = f"""\
타겟 직무: {target_role}
삽입할 키워드: {keyword_str}

현재 프로필:
{profile_str}

위 프로필을 타겟 직무와 키워드에 맞게 전면 재작성하세요."""

    with client.messages.stream(
        model=model,
        max_tokens=3000,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        raw = stream.get_final_message().content[-1].text.strip()

    import json
    data = json.loads(raw)

    return LinkedInProfile(
        headline=data.get("headline", current_profile.headline),
        about=data.get("about", current_profile.about),
        experience_bullets=data.get(
            "experience_bullets", current_profile.experience_bullets
        ),
        skills=data.get("skills", current_profile.skills),
    )


def format_profile_report(original: LinkedInProfile, optimized: LinkedInProfile) -> str:
    """최적화 전후 비교 보고서 생성 (마크다운)."""
    lines = [
        "# LinkedIn 프로필 최적화 결과\n",
        "## Headline",
        f"**변경 전:** {original.headline}",
        f"**변경 후:** {optimized.headline}\n",
        "## About",
        "**변경 전:**",
        original.about,
        "\n**변경 후:**",
        optimized.about,
        "\n## Skills",
        f"**변경 전:** {', '.join(original.skills[:10])}",
        f"**변경 후:** {', '.join(optimized.skills[:10])}",
    ]
    return "\n".join(lines)
