"""
필터 통과한 공고를 Obsidian 호환 마크다운 트래커에 기록.

파일 구조:
  {TRACKER_DIR}/
    YYYY-MM-DD.md       ← 날짜별 브리핑 파일
    companies/
      {company}-{date}.md  ← 회사별 상세 노트
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from .job_fetcher import JobPosting


def _tracker_dir() -> Path:
    path = Path(os.environ.get("TRACKER_DIR", "~/job-tracker")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    (path / "companies").mkdir(exist_ok=True)
    return path


def append_to_daily_log(postings: list[JobPosting]) -> Path:
    """오늘 날짜의 브리핑 파일에 새 공고 목록을 추가."""
    tracker_dir = _tracker_dir()
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = tracker_dir / f"{today}.md"

    lines = []
    if not log_path.exists():
        lines.append(f"# {today} 채용 브리핑\n\n")
        lines.append("| 회사 | 포지션 | 지역 | 경력 | 마감 | URL |\n")
        lines.append("|------|--------|------|------|------|-----|\n")

    for p in postings:
        row = (
            f"| {p.company} | {p.title} | {p.location} "
            f"| {p.experience} | {p.deadline} | [링크]({p.url}) |\n"
        )
        lines.append(row)

    with open(log_path, "a", encoding="utf-8") as f:
        f.writelines(lines)

    return log_path


def create_company_note(posting: JobPosting) -> Path:
    """
    회사별 상세 노트 생성.
    자소서 작성 시 이 파일에 공고 내용 + 자소서 초안을 기록.
    """
    tracker_dir = _tracker_dir()
    today = datetime.now().strftime("%Y-%m-%d")
    safe_company = "".join(c if c.isalnum() or c in "-_" else "_" for c in posting.company)
    note_path = tracker_dir / "companies" / f"{safe_company}-{today}.md"

    content = f"""# {posting.company} — {posting.title}

## 공고 정보
- **지역**: {posting.location}
- **경력**: {posting.experience}
- **마감**: {posting.deadline}
- **출처**: {posting.source}
- **URL**: {posting.url}

## 상태
- [ ] 자소서 작성
- [ ] 제출 완료
- [ ] 서류 결과
- [ ] 면접 일정

## 자소서 초안
(여기에 자소서를 작성하거나 stage2 결과물을 붙여넣기)

## 면접 준비
(서류 통과 시 stage4 예상질문 결과물을 붙여넣기)
"""
    note_path.write_text(content, encoding="utf-8")
    return note_path
