"""
AI 취준 자소서 비서 — CLI 진입점.

Usage:
  python -m main briefing              # Stage 1: 오늘의 채용 브리핑
  python -m main cover-letter write    # Stage 2: 자소서 초안 생성 + 채점 루프
  python -m main linkedin optimize     # Stage 3: LinkedIn 프로필 최적화
  python -m main interview questions   # Stage 4: 면접 예상 질문 생성
  python -m main interview practice    # Stage 4: 대화형 면접 연습
  python -m main kb add <주제>          # Stage 5: 지식 카드 생성
  python -m main tracker create-note   # Stage 1: 회사 노트 생성
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()
console = Console()


def _load_settings() -> dict:
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ──────────────────────────────────────────────
# Root
# ──────────────────────────────────────────────

@click.group()
def cli():
    """AI 취준 자소서 비서"""


# ──────────────────────────────────────────────
# Stage 1: 채용 브리핑
# ──────────────────────────────────────────────

@cli.command("briefing")
@click.option("--days-back", default=1, show_default=True, help="최근 며칠치 메일 조회")
@click.option("--dry-run", is_flag=True, help="트래커 파일 수정 없이 결과만 출력")
def briefing(days_back: int, dry_run: bool):
    """Stage 1: 오늘의 채용 브리핑 생성."""
    from stage1_job_collector.daily_briefing import run_daily_briefing
    run_daily_briefing(days_back=days_back, dry_run=dry_run)


# ──────────────────────────────────────────────
# Stage 1: 트래커
# ──────────────────────────────────────────────

@cli.group("tracker")
def tracker():
    """Stage 1: 트래커 관련 명령."""


@tracker.command("create-note")
@click.argument("url")
def tracker_create_note(url: str):
    """공고 URL로 회사 노트 생성."""
    from stage1_job_collector.job_fetcher import fetch_job_detail
    from stage1_job_collector.tracker import create_company_note

    console.print(f"[cyan]공고 조회 중: {url}[/cyan]")
    posting = fetch_job_detail(url)
    if not posting:
        console.print("[red]공고를 불러오지 못했습니다.[/red]")
        sys.exit(1)

    note_path = create_company_note(posting)
    console.print(f"[green]노트 생성: {note_path}[/green]")


# ──────────────────────────────────────────────
# Stage 2: 자소서
# ──────────────────────────────────────────────

@cli.group("cover-letter")
def cover_letter():
    """Stage 2: 자소서 생성 + 채점 루프."""


@cover_letter.command("write")
@click.option("--jd", "jd_path", required=True, type=click.Path(exists=True), help="공고 텍스트 파일")
@click.option("--profile", "profile_path", default=None, type=click.Path(), help="프로필 파일 (기본: config/profile.txt)")
@click.option("--question", default="", help="자소서 문항")
@click.option("--char-limit", default=0, help="글자 수 제한")
@click.option("--output", default=None, type=click.Path(), help="결과 저장 파일 경로")
def cover_letter_write(jd_path, profile_path, question, char_limit, output):
    """자소서 초안 생성 → 88점 채점 루프 → 최종 출력."""
    from stage2_cover_letter.generator import generate_draft, load_profile
    from stage2_cover_letter.scorer import run_scoring_loop
    from stage2_cover_letter.checklist import run_checklist, get_manual_checklist

    settings = _load_settings()
    jd_text = Path(jd_path).read_text(encoding="utf-8")
    profile_text = load_profile(profile_path)

    if not profile_text:
        console.print("[yellow]⚠ config/profile.txt 없음 — 프로필 없이 생성합니다.[/yellow]")

    console.print("[bold cyan]✍ 자소서 초안 생성 중...[/bold cyan]")
    draft = generate_draft(jd_text, profile_text, question=question, char_limit=char_limit)

    console.print("[bold cyan]📊 채점 루프 시작...[/bold cyan]")
    loop = run_scoring_loop(draft, jd_text, settings)

    status = "[green]✅ 통과[/green]" if loop.passed else "[yellow]⚠ 미달 (최고점 선택)[/yellow]"
    console.print(
        Panel(
            f"최종 점수: [bold]{loop.final_score}/100[/bold] {status}\n"
            f"반복 횟수: {loop.iterations}회\n"
            f"기준 점수: {settings['cover_letter']['pass_score']}점",
            title="채점 결과",
        )
    )

    # 체크리스트
    cl_result = run_checklist(loop.final_text, settings, char_limit=char_limit)
    if cl_result.failures:
        console.print("[red]체크리스트 실패:[/red]")
        for f in cl_result.failures:
            console.print(f"  ✗ {f}")
    else:
        console.print("[green]✅ 체크리스트 전항목 통과[/green]")

    manual = get_manual_checklist(settings)
    if manual:
        console.print("\n[dim]수동 확인 항목:[/dim]")
        for item in manual:
            console.print(f"  □ {item}")

    console.print("\n[bold]── 최종 자소서 ──[/bold]")
    console.print(loop.final_text)

    if output:
        Path(output).write_text(loop.final_text, encoding="utf-8")
        console.print(f"\n[green]저장: {output}[/green]")


# ──────────────────────────────────────────────
# Stage 3: LinkedIn
# ──────────────────────────────────────────────

@cli.group("linkedin")
def linkedin():
    """Stage 3: LinkedIn 프로필 최적화."""


@linkedin.command("optimize")
@click.option("--jd-dir", "jd_dir", default=".", type=click.Path(exists=True), help="공고 텍스트 파일들이 있는 디렉토리")
@click.option("--profile", "profile_path", required=True, type=click.Path(exists=True), help="현재 LinkedIn 프로필 JSON 파일")
@click.option("--target-role", default="PM", help="타겟 직무")
@click.option("--output", default=None, type=click.Path(), help="결과 저장 경로")
def linkedin_optimize(jd_dir, profile_path, target_role, output):
    """공고 목록으로 LinkedIn 키워드 추출 → 프로필 재작성."""
    import json as _json
    from stage3_linkedin.optimizer import (
        extract_keywords, optimize_profile,
        LinkedInProfile, format_profile_report,
    )

    jd_texts = []
    for p in Path(jd_dir).glob("*.txt"):
        jd_texts.append(p.read_text(encoding="utf-8"))

    if not jd_texts:
        console.print("[red]*.txt 공고 파일을 찾을 수 없습니다.[/red]")
        sys.exit(1)

    console.print(f"[cyan]{len(jd_texts)}개 공고에서 키워드 추출 중...[/cyan]")
    keywords = extract_keywords(jd_texts)
    console.print(f"추출 키워드: {', '.join(keywords[:10])} ...")

    raw_profile = _json.loads(Path(profile_path).read_text(encoding="utf-8"))
    current = LinkedInProfile(
        headline=raw_profile.get("headline", ""),
        about=raw_profile.get("about", ""),
        experience_bullets=raw_profile.get("experience_bullets", {}),
        skills=raw_profile.get("skills", []),
    )

    console.print("[cyan]프로필 재작성 중...[/cyan]")
    optimized = optimize_profile(current, keywords, target_role)
    report = format_profile_report(current, optimized)

    console.print(report)

    if output:
        Path(output).write_text(report, encoding="utf-8")
        console.print(f"[green]저장: {output}[/green]")


# ──────────────────────────────────────────────
# Stage 4: 면접 코치
# ──────────────────────────────────────────────

@cli.group("interview")
def interview():
    """Stage 4: 면접 예상 질문 생성 + 답변 연습."""


@interview.command("questions")
@click.option("--cover-letter", "cl_path", required=True, type=click.Path(exists=True), help="자소서 파일")
@click.option("--jd", "jd_path", required=True, type=click.Path(exists=True), help="공고 파일")
@click.option("--output", default=None, type=click.Path(), help="결과 저장 경로")
def interview_questions(cl_path, jd_path, output):
    """자소서 + 공고 분석 → 면접 예상 질문 20개 생성."""
    from stage4_interview_coach.question_generator import generate_questions, format_question_list

    settings = _load_settings()
    cover_letter_text = Path(cl_path).read_text(encoding="utf-8")
    jd_text = Path(jd_path).read_text(encoding="utf-8")

    console.print("[cyan]면접 질문 생성 중...[/cyan]")
    questions = generate_questions(cover_letter_text, jd_text, settings)
    report = format_question_list(questions)

    console.print(report)

    if output:
        Path(output).write_text(report, encoding="utf-8")
        console.print(f"[green]저장: {output}[/green]")


@interview.command("practice")
@click.option("--questions", "q_path", required=True, type=click.Path(exists=True), help="질문 파일 (줄마다 질문 하나)")
def interview_practice(q_path: str):
    """대화형 면접 답변 연습 + 즉각 채점."""
    from stage4_interview_coach.answer_scorer import run_practice_session

    settings = _load_settings()
    questions = [
        line.strip()
        for line in Path(q_path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    console.print(f"[bold]면접 연습 시작 — {len(questions)}개 질문[/bold]")
    run_practice_session(questions, settings)


# ──────────────────────────────────────────────
# Stage 5: 지식 카드
# ──────────────────────────────────────────────

@cli.group("kb")
def kb():
    """Stage 5: 면접 지식 카드 관리."""


@kb.command("add")
@click.argument("topic")
@click.option("--category", default="기술",
              type=click.Choice(["경험", "기술", "설계", "개선", "리서치"]),
              help="카드 분류")
@click.option("--context", default="", help="추가 맥락")
def kb_add(topic: str, category: str, context: str):
    """새 지식 카드 생성."""
    from stage5_knowledge_base.card_manager import generate_card, save_card, rebuild_index

    console.print(f"[cyan]'{topic}' 카드 생성 중...[/cyan]")
    card = generate_card(topic, context=context, category=category)
    card_path = save_card(card)
    index_path = rebuild_index()

    console.print(f"[green]카드 저장: {card_path}[/green]")
    console.print(f"[dim]인덱스 갱신: {index_path}[/dim]")
    console.print(f"\n[bold]30초 요약:[/bold] {card.summary_30s}")


@kb.command("index")
def kb_index():
    """지식 카드 인덱스 재생성."""
    from stage5_knowledge_base.card_manager import rebuild_index
    index_path = rebuild_index()
    console.print(f"[green]인덱스 재생성: {index_path}[/green]")


# ──────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────

if __name__ == "__main__":
    cli()
