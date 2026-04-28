"""
면접 지식 카드 관리.

카드 구조:
  30초 요약 / 2분 설명 / 10분 심화
  카테고리: 경험-스토리 / 기술-용어사전 / 설계-케이스 / 더-나은-설계 / 최신-리서치

카드는 Obsidian 호환 마크다운으로 저장.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_MODEL = "claude-opus-4-7"

CATEGORIES = {
    "경험": "01-경험-스토리",
    "기술": "02-기술-용어사전",
    "설계": "03-설계-케이스",
    "개선": "04-더-나은-설계",
    "리서치": "05-최신-리서치",
}


@dataclass
class KnowledgeCard:
    title: str
    category: str
    summary_30s: str    # 30초 엘리베이터 피치
    explanation_2m: str  # 2분 상세 설명
    deep_dive_10m: str  # 10분 심화 (배경, 트레이드오프, 사례)
    tags: list[str]


def _kb_dir() -> Path:
    path = Path(os.environ.get("KB_DIR", "~/interview-kb")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    for subdir in CATEGORIES.values():
        (path / subdir).mkdir(exist_ok=True)
    return path


def generate_card(
    topic: str,
    context: str = "",
    category: str = "기술",
    model: str = _DEFAULT_MODEL,
) -> KnowledgeCard:
    """
    주제를 입력받아 3가지 깊이의 지식 카드 자동 생성.

    Args:
        topic: 카드 주제 (예: "사용자 인터뷰 방법론", "OKR vs KPI")
        context: 추가 맥락 (옵션)
        category: 카드 분류 키 (경험/기술/설계/개선/리서치)
        model: 사용할 Claude 모델

    Returns:
        KnowledgeCard
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    system = """\
당신은 면접 준비 전문 코치입니다.
주어진 주제를 3가지 깊이로 설명하는 지식 카드를 만드세요.

출력 형식 (JSON만, 마크다운 코드블록 없이):
{
  "summary_30s": "30초 안에 말할 수 있는 핵심 1-2문장. 숫자/근거 포함.",
  "explanation_2m": "2분 설명. 정의 → 내 경험 또는 사례 → 왜 중요한지. 3-4문단.",
  "deep_dive_10m": "10분 심화. 배경/역사 → 핵심 개념 → 트레이드오프 → 실제 적용 사례 → 최신 트렌드. 충분히 상세하게.",
  "tags": ["태그1", "태그2", "태그3"]
}"""

    context_section = f"\n추가 맥락: {context}" if context else ""
    user_message = f"주제: {topic}{context_section}\n\n위 주제로 면접 지식 카드를 작성하세요."

    with client.messages.stream(
        model=model,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        raw = stream.get_final_message().content[-1].text.strip()

    data = json.loads(raw)

    return KnowledgeCard(
        title=topic,
        category=category,
        summary_30s=data.get("summary_30s", ""),
        explanation_2m=data.get("explanation_2m", ""),
        deep_dive_10m=data.get("deep_dive_10m", ""),
        tags=data.get("tags", []),
    )


def save_card(card: KnowledgeCard) -> Path:
    """카드를 마크다운 파일로 저장."""
    kb_dir = _kb_dir()
    subdir_name = CATEGORIES.get(card.category, "02-기술-용어사전")
    subdir = kb_dir / subdir_name

    today = datetime.now().strftime("%Y-%m-%d")
    safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in card.title)
    card_path = subdir / f"{today}-{safe_title}.md"

    tags_str = " ".join(f"#{t}" for t in card.tags)
    content = f"""---
title: {card.title}
category: {card.category}
date: {today}
tags: [{", ".join(card.tags)}]
---

# {card.title}

{tags_str}

## 30초 요약
{card.summary_30s}

## 2분 설명
{card.explanation_2m}

## 10분 심화
{card.deep_dive_10m}
"""
    card_path.write_text(content, encoding="utf-8")
    return card_path


def rebuild_index() -> Path:
    """카드 전체 목록으로 00-INDEX.md 재생성."""
    kb_dir = _kb_dir()
    index_path = kb_dir / "00-INDEX.md"

    lines = ["# 면접 지식 카드 인덱스\n"]

    for cat_key, subdir_name in CATEGORIES.items():
        subdir = kb_dir / subdir_name
        cards = sorted(subdir.glob("*.md"))
        if not cards:
            continue
        lines.append(f"\n## {subdir_name}\n")
        for card_path in cards:
            name = card_path.stem
            lines.append(f"- [[{subdir_name}/{card_path.name}|{name}]]")

    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index_path
