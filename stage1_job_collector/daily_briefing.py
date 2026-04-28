"""
매일 아침 채용 브리핑 생성.

흐름:
  Gmail IMAP → 사람인/잡코리아 메일 파싱 → URL 추출
  → 각 URL 실제 조회(지역/직무 확인) → 필터 통과
  → 트래커 기록 → 터미널 브리핑 출력
"""
from __future__ import annotations

import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .gmail_imap import connect, fetch_alert_emails
from .saramin_parser import extract_job_urls as saramin_urls
from .jobkorea_parser import extract_job_urls as jobkorea_urls
from .job_fetcher import fetch_and_filter, JobPosting
from .tracker import append_to_daily_log, create_company_note

import yaml

load_dotenv()
console = Console()


def load_settings() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_daily_briefing(days_back: int = 1, dry_run: bool = False) -> list[JobPosting]:
    """
    오늘의 채용 브리핑을 생성하고 트래커에 기록.

    Args:
        days_back: 최근 며칠치 메일을 가져올지
        dry_run: True면 트래커 파일 수정 없이 결과만 반환

    Returns:
        필터 통과한 공고 목록
    """
    settings = load_settings()
    gmail_cfg = settings.get("gmail", {})

    address = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]

    console.print("[bold cyan]📬 Gmail 연결 중...[/bold cyan]")
    mail = connect(address, password)

    all_urls: list[str] = []

    # 사람인 알림 메일
    for msg in fetch_alert_emails(mail, gmail_cfg.get("saramin_sender", ""), days_back):
        console.print(f"  [dim]사람인 메일: {msg['subject'][:60]}[/dim]")
        all_urls.extend(saramin_urls(msg["body_text"]))

    # 잡코리아 알림 메일
    for msg in fetch_alert_emails(mail, gmail_cfg.get("jobkorea_sender", ""), days_back):
        console.print(f"  [dim]잡코리아 메일: {msg['subject'][:60]}[/dim]")
        all_urls.extend(jobkorea_urls(msg["body_text"]))

    mail.logout()

    console.print(f"\n[yellow]총 {len(all_urls)}개 URL 발견 → 상세 조회 및 필터링...[/yellow]")

    # URL 중복 제거
    unique_urls = list(dict.fromkeys(all_urls))
    passed = fetch_and_filter(unique_urls, settings)

    if not passed:
        console.print("[red]필터를 통과한 공고가 없습니다.[/red]")
        return []

    # 터미널 테이블 출력
    table = Table(title=f"오늘의 채용 브리핑 ({len(passed)}건)", show_lines=True)
    table.add_column("회사", style="bold")
    table.add_column("포지션")
    table.add_column("지역", style="cyan")
    table.add_column("경력")
    table.add_column("마감")

    for p in passed:
        table.add_row(p.company, p.title, p.location, p.experience, p.deadline)

    console.print(table)

    if not dry_run:
        log_path = append_to_daily_log(passed)
        console.print(f"\n[green]✅ 트래커 기록: {log_path}[/green]")
        console.print("[dim]지원할 회사의 노트를 생성하려면: python -m main tracker create-note <URL>[/dim]")

    return passed
