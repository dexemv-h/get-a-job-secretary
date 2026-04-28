"""
제출 전 최종 체크리스트 검증.

settings.yaml personal_checklist 항목을 규칙 기반으로 체크하고,
AI 톤 탐지 등 패턴 매칭을 병행.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_AI_TONE_PATTERNS = [
    r"활용할\s*수\s*있습니다",
    r"하도록\s*하겠습니다",
    r"기여할\s*수\s*있을\s*것입니다",
    r"노력하겠습니다",
    r"최선을\s*다하겠습니다",
    r"발휘할\s*수\s*있",
    r"도움이\s*될\s*것입니다",
]

_MIDPOINT_RE = re.compile(r"·")  # 가운뎃점
_FORBIDDEN_PHRASES = [
    "활용할 수 있습니다",
    "하도록 하겠습니다",
]


@dataclass
class ChecklistResult:
    passed: bool
    failures: list[str]   # 실패한 항목 메시지 목록


def run_checklist(text: str, settings: dict, char_limit: int = 0) -> ChecklistResult:
    """
    제출 전 최종 체크리스트 실행.

    Args:
        text: 검사할 자소서 본문
        settings: settings.yaml 전체 dict
        char_limit: 공고 글자 수 제한 (0이면 생략)

    Returns:
        ChecklistResult
    """
    failures: list[str] = []

    # 1) 가운뎃점 검사
    if _MIDPOINT_RE.search(text):
        failures.append("가운뎃점(·) 발견 — 삭제 필요")

    # 2) AI 톤 패턴 검사
    for pattern in _AI_TONE_PATTERNS:
        if re.search(pattern, text):
            matches = re.findall(pattern, text)
            failures.append(f"AI투 표현 발견: '{matches[0]}' — 직접화법으로 교체 필요")

    # 3) 금지 문구 검사
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in text:
            failures.append(f"금지 문구: '{phrase}'")

    # 4) 문단 줄 수 검사 (빈줄로 구분)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for idx, para in enumerate(paragraphs, 1):
        lines = [l for l in para.split("\n") if l.strip()]
        if len(lines) > 5:
            failures.append(f"{idx}번째 문단 {len(lines)}줄 — 5줄 이내로 단축 필요")

    # 5) 글자 수 검사
    if char_limit:
        actual = len(text.replace(" ", "").replace("\n", ""))
        lower = int(char_limit * 0.9)
        upper = int(char_limit * 1.1)
        if not (lower <= actual <= upper):
            failures.append(
                f"글자 수 {actual}자 — 허용 범위 {lower}~{upper}자 벗어남"
            )

    # 6) settings.yaml personal_checklist 중 규칙 기반 검사로 커버 못한 항목 안내
    cl_items = settings.get("cover_letter", {}).get("personal_checklist", [])
    auto_checked = {
        "가운뎃점(·) 미사용",
        '"활용할 수 있습니다" 문구 없음',
        '"하도록 하겠습니다" 문구 없음',
        "한 문단 최대 5줄",
        "글자 수 공고 기준 ±10% 이내",
    }
    manual_items = [item for item in cl_items if item not in auto_checked]
    # manual 항목은 실패로 처리하지 않고 별도 안내용으로만 노출
    # (호출자가 manual_items를 별도 표시)

    return ChecklistResult(passed=len(failures) == 0, failures=failures)


def get_manual_checklist(settings: dict) -> list[str]:
    """자동 검사 불가한 수동 확인 항목 반환."""
    cl_items = settings.get("cover_letter", {}).get("personal_checklist", [])
    auto_checked = {
        "가운뎃점(·) 미사용",
        '"활용할 수 있습니다" 문구 없음',
        '"하도록 하겠습니다" 문구 없음',
        "한 문단 최대 5줄",
        "글자 수 공고 기준 ±10% 이내",
    }
    return [item for item in cl_items if item not in auto_checked]
