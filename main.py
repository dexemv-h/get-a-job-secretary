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
  python -m main opic rate             # Stage 6: OPIc 답변 1개 등급 예측
  python -m main opic session          # Stage 6: 여러 답변 누적 → Floor/Ceiling
  python -m main opic calibrate add    # Stage 6: 실제 응시 샘플 등록
  python -m main opic calibrate run    # Stage 6: 예측 vs 실제 비교 → 보정
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
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
# Stage 6: OPIc 등급 예측 / 캘리브레이션
# ──────────────────────────────────────────────

@cli.group("opic")
def opic():
    """Stage 6: OPIc 예상 등급 판정 + 캘리브레이션."""


def _read_question(question: str, question_file: str | None) -> str:
    """--question 또는 --question-file 중 하나에서 질문 읽기."""
    if question_file:
        return Path(question_file).read_text(encoding="utf-8").strip()
    if question:
        return question.strip()
    console.print("[red]--question 또는 --question-file 중 하나는 필요합니다.[/red]")
    sys.exit(1)


def _parse_answer_file(path: Path) -> tuple[str, str]:
    """
    답변 파일 파싱.

    형식:
      Q: <질문>
      <답변 transcript ...>

    'Q:' 줄이 없으면 파일명을 질문 대신 사용한다.
    """
    text = path.read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    if lines and lines[0].strip().upper().startswith("Q:"):
        question = lines[0].split(":", 1)[1].strip()
        answer = "\n".join(lines[1:]).strip()
        return question, answer
    return path.stem, text


AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm")


def _find_audio(stem_path: Path) -> Path | None:
    """같은 이름의 음성 파일(q1.txt ↔ q1.wav)을 찾는다."""
    for suffix in AUDIO_SUFFIXES:
        candidate = stem_path.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def _transcribe_audio(audio_path: Path, settings: dict):
    """음성 → (transcript 텍스트, DeliveryMetrics)."""
    from stage6_opic_coach.delivery import analyze_delivery
    from stage6_opic_coach.transcriber import transcribe

    console.print(f"[dim]전사 중: {audio_path.name}[/dim]")
    transcript = transcribe(audio_path, settings)
    return transcript.text, analyze_delivery(transcript)


def _calibration_context(settings: dict, use_calibration: bool) -> str:
    from stage6_opic_coach.calibration import build_calibration_context

    if not use_calibration:
        return ""
    ctx = build_calibration_context(settings)
    if ctx:
        console.print("[dim]캘리브레이션 보정 기준 적용 중[/dim]")
    return ctx


@opic.command("rate")
@click.option("--question", default="", help="OPIc 질문 (직접 입력)")
@click.option("--question-file", default=None, type=click.Path(exists=True), help="질문 파일")
@click.option("--answer", "answer_file", default=None, type=click.Path(exists=True), help="답변 transcript 파일")
@click.option("--audio", "audio_file", default=None, type=click.Path(exists=True),
              help="답변 음성 파일 (전사 + delivery 지표 자동 추출)")
@click.option("--no-calibration", is_flag=True, help="누적 보정 기준을 적용하지 않음")
@click.option("--output", default=None, type=click.Path(), help="리포트 저장 경로")
def opic_rate(question, question_file, answer_file, audio_file, no_calibration, output):
    """답변 1개 → 예상 수행 수준 + 상세 분석 (전체 등급은 판단 보류)."""
    from stage6_opic_coach.rater import format_rating_report, rate_answer

    settings = _load_settings()
    q = _read_question(question, question_file)

    if not answer_file and not audio_file:
        console.print("[red]--answer 또는 --audio 중 하나는 필요합니다.[/red]")
        sys.exit(1)

    delivery = None
    if audio_file:
        a, delivery = _transcribe_audio(Path(audio_file), settings)
        console.print(f"[dim]전사 결과 {len(a.split())}단어[/dim]")
    else:
        a = Path(answer_file).read_text(encoding="utf-8").strip()

    if not a:
        console.print("[red]답변이 비어 있습니다.[/red]")
        sys.exit(1)

    ctx = _calibration_context(settings, not no_calibration)

    console.print("[bold cyan]🎧 OPIc 답변 분석 중...[/bold cyan]")
    rating = rate_answer(q, a, settings, delivery=delivery, calibration_context=ctx)
    report = format_rating_report(rating)

    console.print(report)
    console.print(
        Panel(
            f"이 답변 단독 기준: [bold]{rating.level}[/bold] (확신도 {rating.confidence})\n"
            f"시험 전체 등급: 판단 보류 — 여러 질문에서의 지속적인 수행 확인 필요",
            title="요약",
        )
    )

    if output:
        Path(output).write_text(report, encoding="utf-8")
        console.print(f"[green]저장: {output}[/green]")


@opic.command("session")
@click.option("--dir", "answers_dir", required=True, type=click.Path(exists=True),
              help="답변 디렉토리. q1.txt 첫 줄에 'Q: 질문', 같은 이름의 q1.wav 가 있으면 음성 사용")
@click.option("--no-calibration", is_flag=True, help="누적 보정 기준을 적용하지 않음")
@click.option("--detail", is_flag=True, help="답변별 상세 리포트까지 출력")
@click.option("--output", default=None, type=click.Path(), help="리포트 저장 경로 (미지정 시 $OPIC_DIR/sessions)")
def opic_session(answers_dir, no_calibration, detail, output):
    """여러 답변 누적 평가 → Floor / Ceiling / 전체 예상 등급."""
    from stage6_opic_coach.profile_tracker import (
        format_profile_report, save_session_report, summarize_profile,
    )
    from stage6_opic_coach.rater import format_rating_report, rate_answer

    settings = _load_settings()
    files = sorted(Path(answers_dir).glob("*.txt"))
    if not files:
        console.print("[red]*.txt 답변 파일을 찾을 수 없습니다.[/red]")
        sys.exit(1)

    ctx = _calibration_context(settings, not no_calibration)

    ratings = []
    detail_reports = []
    for i, path in enumerate(files, 1):
        q, a = _parse_answer_file(path)
        console.print(f"[cyan][{i}/{len(files)}] {path.name} 분석 중...[/cyan]")

        delivery = None
        audio_path = _find_audio(path)
        if audio_path:
            a, delivery = _transcribe_audio(audio_path, settings)

        if not a:
            console.print(f"[yellow]⚠ {path.name}: 답변이 비어 있어 건너뜁니다.[/yellow]")
            continue

        rating = rate_answer(q, a, settings, delivery=delivery, calibration_context=ctx)
        ratings.append(rating)
        detail_reports.append(format_rating_report(rating))
        console.print(f"  → {rating.level} (확신도 {rating.confidence})")

    if not ratings:
        console.print("[red]평가된 답변이 없습니다.[/red]")
        sys.exit(1)

    summary = summarize_profile(ratings, settings)
    profile_report = format_profile_report(summary, ratings)

    if detail:
        for r in detail_reports:
            console.print(r)

    console.print(profile_report)
    console.print(
        Panel(
            f"Floor: [bold]{summary.floor}[/bold]  /  Ceiling: [bold]{summary.ceiling}[/bold]\n"
            f"예상 OPIc: [bold]{summary.predicted_grade}[/bold]  (AL 가능성 {summary.al_probability}%)\n"
            f"Advanced 성공 {summary.advanced_success}/{summary.advanced_total}",
            title="누적 판정",
        )
    )

    full_report = profile_report + "\n\n---\n\n" + "\n\n---\n\n".join(detail_reports)
    if output:
        Path(output).write_text(full_report, encoding="utf-8")
        console.print(f"[green]저장: {output}[/green]")
    else:
        saved = save_session_report(full_report, name=Path(answers_dir).name)
        console.print(f"[green]저장: {saved}[/green]")


@opic.command("transcribe")
@click.option("--audio", "audio_file", required=True, type=click.Path(exists=True), help="음성 파일")
@click.option("--output", default=None, type=click.Path(), help="transcript JSON 저장 경로")
def opic_transcribe(audio_file, output):
    """음성 → 전사 + delivery 지표 (등급 판정 없음)."""
    from stage6_opic_coach.delivery import analyze_delivery, format_delivery_summary
    from stage6_opic_coach.transcriber import save_transcript, transcribe

    settings = _load_settings()
    console.print(f"[cyan]전사 중: {audio_file}[/cyan]")
    transcript = transcribe(audio_file, settings)
    metrics = analyze_delivery(transcript)

    console.print(Panel(transcript.text or "(인식된 발화 없음)", title="Transcript"))
    console.print("\n[bold]Delivery 지표[/bold]")
    console.print(format_delivery_summary(metrics))
    console.print(
        "\n[dim]발음·억양은 이 지표로 판단하지 않습니다 — 모델이 오디오를 직접 듣지 않습니다.[/dim]"
    )

    if output:
        console.print(f"[green]저장: {save_transcript(transcript, output)}[/green]")


@opic.group("profile")
def opic_profile():
    """Stage 6: 실제 응시 등급 기준선 관리."""


@opic_profile.command("set")
@click.option("--grade", required=True, help="실제로 받았던 OPIc 등급 (예: IM2)")
@click.option("--taken", default="", help="응시 시점 (예: 2024-08)")
@click.option("--target", default="", help="목표 등급 (예: IH)")
@click.option("--note", default="", help="비고")
def opic_profile_set(grade, taken, target, note):
    """실제 응시 등급을 기준선으로 저장 (채점 프롬프트에는 주입되지 않음)."""
    from stage6_opic_coach.profile_tracker import UserBaseline, save_baseline

    try:
        path = save_baseline(UserBaseline(
            actual_grade=grade, taken_on=taken, target_grade=target, note=note,
        ))
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)

    console.print(f"[green]기준선 저장: 실제 {grade.upper()}"
                  f"{' / 목표 ' + target.upper() if target else ''}[/green]")
    console.print(f"[dim]{path}[/dim]")
    console.print("[dim]이 등급은 채점 프롬프트에 들어가지 않습니다 — "
                  "앵커링을 막기 위해 결과 비교에만 사용합니다.[/dim]")


@opic_profile.command("show")
def opic_profile_show():
    """저장된 기준선 확인."""
    from stage6_opic_coach.profile_tracker import load_baseline

    baseline = load_baseline()
    if not baseline:
        console.print("[yellow]저장된 기준선이 없습니다. opic profile set --grade IM2[/yellow]")
        return

    console.print(Panel(
        f"실제 등급: [bold]{baseline.actual_grade}[/bold]\n"
        f"응시 시점: {baseline.taken_on or '미기재'}\n"
        f"목표 등급: {baseline.target_grade or '미설정'}\n"
        f"비고: {baseline.note or '-'}\n"
        f"갱신: {baseline.updated_at}",
        title="기준선",
    ))


@opic.group("exam")
def opic_exam():
    """Stage 6: OPIc 모의고사 (출제 → 녹음 → 전사 → 등급)."""


def _collect_survey(input_fn=None):
    """Background Survey 를 대화형으로 수집."""
    from stage6_opic_coach.exam import SURVEY_FIELDS, BackgroundSurvey

    console.print("[bold]Background Survey[/bold] — 실제 시험처럼 답변 주제가 여기서 정해집니다.\n")
    values = {}
    for key, label in SURVEY_FIELDS:
        values[key] = (input_fn or click.prompt)(f"  {label}", default="", show_default=False)
    return BackgroundSurvey(**values)


def _pick_level() -> int:
    from stage6_opic_coach.exam import SELF_ASSESSMENT

    console.print("\n[bold]Self Assessment[/bold] — 난이도를 고르면 문항 구성이 달라집니다.")
    for n, desc in SELF_ASSESSMENT.items():
        console.print(f"  {n}. {desc}")
    return click.prompt("난이도", type=click.IntRange(1, 6), default=4)


@opic_exam.command("check")
def opic_exam_check():
    """마이크 / 음성 의존성 사용 가능 여부 확인."""
    from stage6_opic_coach.recorder import is_available

    ok, detail = is_available()
    if ok:
        console.print(f"[green]✅ 녹음 가능 — 입력 장치: {detail}[/green]")
    else:
        console.print(f"[red]❌ 녹음 불가 — {detail}[/red]")

    import importlib.util

    if importlib.util.find_spec("faster_whisper"):
        console.print("[green]✅ faster-whisper 설치됨[/green]")
    else:
        console.print("[red]❌ faster-whisper 없음 — pip install -r requirements-audio.txt[/red]")


@opic_exam.command("questions")
@click.option("--level", type=click.IntRange(1, 6), default=None, help="Self Assessment 난이도")
@click.option("--output", default=None, type=click.Path(), help="문항 저장 경로")
def opic_exam_questions(level, output):
    """문항만 생성 (녹음 없이 출제 형태만 확인)."""
    from stage6_opic_coach.exam import FUNCTIONS, generate_exam

    settings = _load_settings()
    survey = _collect_survey()
    level = level or _pick_level()

    console.print("\n[cyan]문항 생성 중...[/cyan]")
    questions = generate_exam(survey, level, settings)

    lines = [f"# OPIc 모의고사 문항 (난이도 {level})\n"]
    for q in questions:
        lines += [
            f"## {q.number}. [{q.category}] {q.topic}",
            f"{q.text}",
            f"[dim]요구 기능: {FUNCTIONS.get(q.function, q.function)} — {q.guidance}[/dim]\n",
        ]
    report = "\n".join(lines)
    console.print(report)

    if output:
        Path(output).write_text(report.replace("[dim]", "").replace("[/dim]", ""), encoding="utf-8")
        console.print(f"[green]저장: {output}[/green]")


@opic_exam.command("start")
@click.option("--level", type=click.IntRange(1, 6), default=None, help="Self Assessment 난이도")
@click.option("--no-calibration", is_flag=True, help="누적 보정 기준을 적용하지 않음")
@click.option("--skip-mic-check", is_flag=True, help="마이크 확인 없이 진행")
def opic_exam_start(level, no_calibration, skip_mic_check):
    """모의고사 시작 — 문항 출제 → 문항별 녹음 → 전사 → 최종 등급."""
    from stage6_opic_coach.exam import (
        ExamSession, generate_exam, grade_exam, new_exam_id, run_exam, save_session,
    )
    from stage6_opic_coach.recorder import is_available

    settings = _load_settings()

    if not skip_mic_check:
        ok, detail = is_available()
        if not ok:
            console.print(f"[red]녹음할 수 없습니다 — {detail}[/red]")
            console.print("[dim]로컬 머신에서 실행하거나, 폰으로 녹음한 파일을 "
                          "opic session --dir 로 채점하세요.[/dim]")
            sys.exit(1)
        console.print(f"[green]입력 장치: {detail}[/green]")

    survey = _collect_survey()
    level = level or _pick_level()

    console.print("\n[cyan]문항 생성 중...[/cyan]")
    questions = generate_exam(survey, level, settings)

    session = ExamSession(
        exam_id=new_exam_id(),
        level=level,
        survey=survey,
        questions=questions,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    save_session(session)

    console.print(Panel(
        f"문항 {len(questions)}개 준비 완료\n"
        f"각 문항: Enter=녹음 시작 → 답변 → Enter=종료\n"
        f"중간에 그만두려면 q — 지금까지 답변만으로 채점합니다.",
        title=f"모의고사 {session.exam_id}",
    ))

    session = run_exam(session, settings, echo=console.print)
    save_session(session)

    answered = [a for a in session.answers if a.transcript.strip()]
    if not answered:
        console.print("[yellow]답변이 없어 채점을 건너뜁니다.[/yellow]")
        return

    ctx = _calibration_context(settings, not no_calibration)
    console.print(f"\n[bold cyan]📊 {len(answered)}개 답변 채점 중...[/bold cyan]")
    _, summary, report = grade_exam(session, settings, calibration_context=ctx)

    console.print(report)
    console.print(Panel(
        f"Floor: [bold]{summary.floor}[/bold]  /  Ceiling: [bold]{summary.ceiling}[/bold]\n"
        f"예상 OPIc: [bold]{summary.predicted_grade}[/bold]  (AL 가능성 {summary.al_probability}%)\n"
        f"Advanced 성공 {summary.advanced_success}/{summary.advanced_total}",
        title="모의고사 결과",
    ))


@opic_exam.command("grade")
@click.option("--dir", "session_dir", required=True, type=click.Path(exists=True),
              help="$OPIC_DIR/exams/<exam_id> 디렉토리 또는 session.json")
@click.option("--no-calibration", is_flag=True, help="누적 보정 기준을 적용하지 않음")
def opic_exam_grade(session_dir, no_calibration):
    """저장된 모의고사를 다시 채점 (녹음 없이)."""
    from stage6_opic_coach.exam import grade_exam, load_session

    settings = _load_settings()
    session = load_session(session_dir)
    answered = [a for a in session.answers if a.transcript.strip()]

    if not answered:
        console.print("[red]채점할 답변이 없습니다.[/red]")
        sys.exit(1)

    ctx = _calibration_context(settings, not no_calibration)
    console.print(f"[cyan]{len(answered)}개 답변 채점 중...[/cyan]")
    _, summary, report = grade_exam(session, settings, calibration_context=ctx)

    console.print(report)
    console.print(f"[green]저장: {Path(session_dir)}/report.md[/green]")


@opic.group("calibrate")
def opic_calibrate():
    """Stage 6: 실제 응시 샘플로 판단 기준 보정."""


@opic_calibrate.command("add")
@click.option("--sample-id", required=True, help="샘플 식별자")
@click.option("--grade", required=True, help="실제 OPIc 등급 (NL/NM/NH/IL/IM1/IM2/IM3/IH/AL)")
@click.option("--question", default="", help="질문 (직접 입력)")
@click.option("--question-file", default=None, type=click.Path(exists=True), help="질문 파일")
@click.option("--answer", "answer_file", required=True, type=click.Path(exists=True), help="답변 transcript 파일")
@click.option("--evidence", default="A", type=click.Choice(["A", "B", "C"]),
              help="A=실제 결과 확인 / B=본인 주장 / C=강사 모범답안")
@click.option("--source", default="", help="출처")
@click.option("--audio", "audio_file", default=None, type=click.Path(exists=True),
              help="샘플 음성 파일 (있으면 blind 예측에 delivery 지표 사용)")
@click.option("--note", default="", help="비고")
def opic_calibrate_add(sample_id, grade, question, question_file, answer_file,
                       evidence, source, audio_file, note):
    """캘리브레이션 샘플 등록."""
    from stage6_opic_coach.calibration import CalibrationSample, add_sample

    q = _read_question(question, question_file)
    a = Path(answer_file).read_text(encoding="utf-8").strip()

    sample = CalibrationSample(
        sample_id=sample_id,
        actual_grade=grade,
        question=q,
        answer=a,
        has_audio=bool(audio_file),
        audio_path=str(Path(audio_file).resolve()) if audio_file else "",
        source=source,
        evidence=evidence,
        note=note,
    )
    try:
        path = add_sample(sample)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)

    console.print(f"[green]샘플 등록: {sample_id} (실제 {sample.actual_grade}, 신뢰도 {evidence})[/green]")
    console.print(f"[dim]{path}[/dim]")
    if evidence != "A":
        console.print("[yellow]⚠ 신뢰도 A(실제 결과 확인) 샘플이 아니므로 기본 보정에는 반영되지 않습니다.[/yellow]")


@opic_calibrate.command("list")
def opic_calibrate_list():
    """등록된 샘플 목록."""
    from stage6_opic_coach.calibration import EVIDENCE_LEVELS, load_samples

    samples = load_samples()
    if not samples:
        console.print("[yellow]등록된 샘플이 없습니다.[/yellow]")
        return
    for s in samples:
        console.print(
            f"- [bold]{s.sample_id}[/bold] | 실제 {s.actual_grade} | "
            f"{s.evidence} ({EVIDENCE_LEVELS[s.evidence]}) | "
            f"음성 {'있음' if s.has_audio else '없음'} | {s.source or '출처 미기재'}"
        )


@opic_calibrate.command("run")
@click.option("--sample-id", default=None, help="특정 샘플만 실행 (미지정 시 전체)")
@click.option("--evidence", default=None, type=click.Choice(["A", "B", "C"]),
              help="해당 신뢰도 샘플만 실행")
def opic_calibrate_run(sample_id, evidence):
    """실제 등급을 보지 않고 먼저 예측 → 실제와 비교 → Calibration Note 저장."""
    from stage6_opic_coach.calibration import get_sample, load_samples, run_calibration

    settings = _load_settings()

    if sample_id:
        sample = get_sample(sample_id)
        if not sample:
            console.print(f"[red]샘플을 찾을 수 없습니다: {sample_id}[/red]")
            sys.exit(1)
        samples = [sample]
    else:
        samples = load_samples([evidence] if evidence else None)

    if not samples:
        console.print("[yellow]대상 샘플이 없습니다.[/yellow]")
        return

    for s in samples:
        console.print(f"[cyan]{s.sample_id} blind 예측 중...[/cyan]")
        note = run_calibration(s, settings)
        color = "green" if note.direction == "일치" else "yellow"
        console.print(
            f"  예상: {note.predicted_low}~{note.predicted_high} / "
            f"실제: {note.actual_grade} → [{color}]{note.direction}[/{color}] (거리 {note.gap})"
        )
        if note.bias_tags:
            console.print(f"  편향 태그: {', '.join(note.bias_tags)}")
        console.print(f"  분석: {note.analysis}\n")


@opic_calibrate.command("notes")
@click.option("--output", default=None, type=click.Path(), help="리포트 저장 경로")
def opic_calibrate_notes(output):
    """누적된 Calibration Note + 현재 적용 중인 보정 기준 출력."""
    from stage6_opic_coach.calibration import format_notes_report

    settings = _load_settings()
    report = format_notes_report(settings)
    console.print(report)

    if output:
        Path(output).write_text(report, encoding="utf-8")
        console.print(f"[green]저장: {output}[/green]")


# ──────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────

if __name__ == "__main__":
    cli()
