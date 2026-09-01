"""
Calibration dataset 관리.

사용자가 제공한 실제 OPIc 응시 샘플로 등급 예측 기준을 보정한다.

신뢰도 구분:
  A = Verified Actual Result   실제 시험 결과가 확인된 응시자
  B = Claimed Result           작성자가 등급을 주장하지만 검증 어려움
  C = Model / Instructor Answer 강사·학습용 모범답안

Calibration에는 A를 가장 높은 신뢰도로 사용하고, C는 실제 응시 샘플과 분리해 보관한다.
한 개의 샘플로 전체 기준을 바꾸지 않는다.
같은 편향 태그가 calibration_min_repeat 회 이상 반복될 때만 판단 기준에 반영한다.

저장 위치: $OPIC_DIR (기본 ~/opic-coach)
  samples.jsonl   샘플 원본
  notes.jsonl     예측 vs 실제 비교 결과 (Calibration Note)
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .rater import _parse_json, rate_answer
from .rubric import EVALUATION_PHILOSOPHY, GRADES, grade_index

load_dotenv()

_DEFAULT_MODEL = "claude-opus-4-7"

EVIDENCE_LEVELS = {
    "A": "Verified Actual Result (실제 시험 결과 확인)",
    "B": "Claimed Result (본인 주장, 검증 어려움)",
    "C": "Model / Instructor Answer (강사·학습용 모범답안)",
}

# 예측 편향 태그. 자유 서술이 아니라 고정 taxonomy 를 써야
# "여러 샘플에서 반복되는 특징"만 골라낼 수 있다.
BIAS_TAGS = {
    # 과대평가 방향
    "fluency_overweight": "유창성 하나를 등급 근거로 과대 반영했다",
    "length_as_proficiency": "답변 길이/paragraph length를 Advanced proficiency와 동일시했다",
    "timeframe_underweight": "time frame control 붕괴를 과소평가했다",
    "complication_unverified": "complication handling을 확인하지 않고 상위 등급을 줬다",
    "memorized_as_spontaneous": "암기형 발화를 spontaneous language로 오인했다",
    "listing_as_narration": "단순 나열을 narration으로 인정했다",
    "error_count_overweight": "문법 오류가 적다는 이유로 과대평가했다",
    "vocabulary_showpiece": "idiom/고급 어휘 개수를 과대 반영했다",
    "single_answer_generalization": "한 답변의 최고 수행을 전체 수준으로 일반화했다",
    # 과소평가 방향
    "accuracy_overpenalized": "local error를 breakdown처럼 과하게 감점했다",
    "discourse_underrated": "실제 paragraph-level discourse를 과소 인정했다",
    "intermediate_floor_underrated": "안정적인 Intermediate floor를 과소 인정했다",
    "hesitation_overpenalized": "hesitation/self-correction을 과하게 감점했다",
    "topic_difficulty_ignored": "질문 자체의 과제 난이도를 고려하지 않았다",
}


@dataclass
class CalibrationSample:
    sample_id: str
    actual_grade: str
    question: str
    answer: str
    has_audio: bool = False
    audio_path: str = ""    # 있으면 blind 예측 때 delivery 지표까지 사용
    source: str = ""
    evidence: str = "A"     # A | B | C
    note: str = ""
    added_at: str = ""


@dataclass
class CalibrationNote:
    sample_id: str
    evidence: str
    predicted_low: str
    predicted_high: str
    actual_grade: str
    direction: str          # 과대평가 | 과소평가 | 일치
    gap: int                # 등급 사다리 상의 거리 (일치면 0)
    bias_tags: list[str] = field(default_factory=list)
    analysis: str = ""
    created_at: str = ""


def opic_dir() -> Path:
    """캘리브레이션/세션 파일 저장 디렉토리 ($OPIC_DIR, 기본 ~/opic-coach)."""
    path = Path(os.environ.get("OPIC_DIR", "~/opic-coach")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _samples_path() -> Path:
    return opic_dir() / "samples.jsonl"


def _notes_path() -> Path:
    return opic_dir() / "notes.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _append_jsonl(path: Path, row: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ──────────────────────────────────────────────
# 샘플 저장 / 조회
# ──────────────────────────────────────────────

def add_sample(sample: CalibrationSample) -> Path:
    """캘리브레이션 샘플 저장. evidence 가 유효하지 않으면 ValueError."""
    if sample.evidence not in EVIDENCE_LEVELS:
        raise ValueError(f"evidence 는 {list(EVIDENCE_LEVELS)} 중 하나여야 합니다: {sample.evidence}")
    if grade_index(sample.actual_grade) < 0:
        raise ValueError(f"actual_grade 는 {GRADES} 중 하나여야 합니다: {sample.actual_grade}")

    sample.actual_grade = sample.actual_grade.strip().upper()
    sample.added_at = sample.added_at or datetime.now().isoformat(timespec="seconds")

    path = _samples_path()
    _append_jsonl(path, asdict(sample))
    return path


def load_samples(evidence_levels: list[str] | None = None) -> list[CalibrationSample]:
    """저장된 샘플 로드. evidence_levels 로 신뢰도 필터."""
    samples = [CalibrationSample(**row) for row in _read_jsonl(_samples_path())]
    if evidence_levels:
        allowed = {e.upper() for e in evidence_levels}
        samples = [s for s in samples if s.evidence.upper() in allowed]
    return samples


def get_sample(sample_id: str) -> CalibrationSample | None:
    """sample_id 로 샘플 1건 조회 (같은 id가 여러 번 저장됐으면 마지막 것)."""
    found = [s for s in load_samples() if s.sample_id == sample_id]
    return found[-1] if found else None


def load_notes() -> list[CalibrationNote]:
    """저장된 Calibration Note 로드."""
    return [CalibrationNote(**row) for row in _read_jsonl(_notes_path())]


# ──────────────────────────────────────────────
# 캘리브레이션 실행
# ──────────────────────────────────────────────

def _analyze_gap(
    sample: CalibrationSample,
    predicted_low: str,
    predicted_high: str,
    direction: str,
    settings: dict,
) -> tuple[list[str], str]:
    """예측과 실제의 차이를 분석해 (편향 태그, 분석문) 반환."""
    cfg = settings.get("opic_coach", {})
    model = cfg.get("model", _DEFAULT_MODEL)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    tag_list = "\n".join(f'  - "{k}": {v}' for k, v in BIAS_TAGS.items())

    system = f"""{EVALUATION_PHILOSOPHY}

## 이번 과제
당신은 방금 이 답변의 등급을 예측했고, 이제 실제 응시 등급을 확인했다.
"틀렸다"로 끝내지 말고 왜 어긋났는지 분석하라.

Calibration Note 는 공식 proficiency 원칙을 덮어쓰는 규칙이 아니라
실전 OPIc 등급 예측을 보정하는 참고 기준이다. 원칙 자체를 폐기하는 결론은 쓰지 마라.

## 사용 가능한 편향 태그 (이 목록 밖의 태그는 만들지 마라)
{tag_list}

## 출력 형식 (JSON만, 마크다운 코드블록 없이)
{{
  "bias_tags": ["가장 설명력 높은 태그 1~3개. 방향(과대/과소)에 맞는 것만."],
  "analysis": "3~5문장. 답변의 어떤 부분을 어떻게 잘못 읽었는지, 실제 답변을 인용해 한국어로."
}}"""

    user_message = f"""\
### 내 예측
{predicted_low}~{predicted_high}

### 실제 등급
{sample.actual_grade} (신뢰도 {sample.evidence}: {EVIDENCE_LEVELS[sample.evidence]})

### 방향
{direction}

### 질문
{sample.question}

### 답변
{sample.answer}

왜 이렇게 어긋났는지 분석하라."""

    with client.messages.stream(
        model=model,
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        raw = stream.get_final_message().content[-1].text.strip()

    data = _parse_json(raw)
    tags = [t for t in data.get("bias_tags", []) if t in BIAS_TAGS][:3]
    return tags, data.get("analysis", "")


def run_calibration(sample: CalibrationSample, settings: dict) -> CalibrationNote:
    """
    샘플 1건으로 캘리브레이션 실행.

    실제 등급을 보지 않은 상태에서 먼저 독립적으로 예측하고(blind),
    그 다음 실제 등급과 비교해 Calibration Note 를 저장한다.
    """
    # 1) blind prediction — 실제 등급도, 기존 보정 컨텍스트도 주지 않는다.
    delivery = None
    if sample.audio_path and Path(sample.audio_path).exists():
        from .delivery import analyze_delivery
        from .transcriber import transcribe

        delivery = analyze_delivery(transcribe(sample.audio_path, settings))

    rating = rate_answer(
        question=sample.question,
        answer=sample.answer,
        settings=settings,
        delivery=delivery,
        calibration_context="",
    )

    lo, hi = grade_index(rating.level_low), grade_index(rating.level_high)
    actual = grade_index(sample.actual_grade)

    if lo <= actual <= hi:
        direction, gap = "일치", 0
    elif actual < lo:
        direction, gap = "과대평가", lo - actual
    else:
        direction, gap = "과소평가", actual - hi

    tags: list[str] = []
    analysis = "예측 범위 안에 실제 등급이 들어왔다. 별도 보정 없음."
    if direction != "일치":
        tags, analysis = _analyze_gap(
            sample, rating.level_low, rating.level_high, direction, settings
        )

    note = CalibrationNote(
        sample_id=sample.sample_id,
        evidence=sample.evidence,
        predicted_low=rating.level_low,
        predicted_high=rating.level_high,
        actual_grade=sample.actual_grade,
        direction=direction,
        gap=gap,
        bias_tags=tags,
        analysis=analysis,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    _append_jsonl(_notes_path(), asdict(note))
    return note


# ──────────────────────────────────────────────
# 보정 컨텍스트 생성
# ──────────────────────────────────────────────

def build_calibration_context(settings: dict) -> str:
    """
    누적된 Calibration Note 에서 반복 편향만 추려 프롬프트용 텍스트로 만든다.

    한 개의 샘플만으로 기준을 바꾸지 않기 위해,
    같은 태그가 calibration_min_repeat 회 이상 나타난 경우만 포함한다.
    """
    cfg = settings.get("opic_coach", {})
    min_repeat = cfg.get("calibration_min_repeat", 2)
    allowed = {e.upper() for e in cfg.get("calibration_evidence_levels", ["A"])}

    notes = [n for n in load_notes() if n.evidence.upper() in allowed]
    if not notes:
        return ""

    counts: dict[str, int] = {}
    for n in notes:
        for tag in n.bias_tags:
            counts[tag] = counts.get(tag, 0) + 1

    repeated = sorted(
        ((t, c) for t, c in counts.items() if c >= min_repeat),
        key=lambda x: -x[1],
    )
    if not repeated:
        return ""

    over = sum(1 for n in notes if n.direction == "과대평가")
    under = sum(1 for n in notes if n.direction == "과소평가")
    hit = sum(1 for n in notes if n.direction == "일치")

    lines = [
        f"확인된 샘플 {len(notes)}건 기준 — 일치 {hit} / 과대평가 {over} / 과소평가 {under}",
        "반복 확인된 편향:",
    ]
    lines += [f"- {BIAS_TAGS[t]} ({c}건 반복)" for t, c in repeated]
    return "\n".join(lines)


def format_notes_report(settings: dict) -> str:
    """Calibration Note 전체를 마크다운 리포트로 포맷."""
    notes = load_notes()
    if not notes:
        return "# Calibration Note\n\n저장된 노트가 없습니다. `opic calibrate run` 을 먼저 실행하세요.\n"

    lines = ["# Calibration Note\n"]
    for n in notes:
        tags = ", ".join(n.bias_tags) if n.bias_tags else "-"
        lines += [
            f"## {n.sample_id} — 예측 {n.predicted_low}~{n.predicted_high} / 실제 {n.actual_grade}",
            f"- 방향: {n.direction} (거리 {n.gap})",
            f"- 신뢰도: {n.evidence} ({EVIDENCE_LEVELS.get(n.evidence, '?')})",
            f"- 편향 태그: {tags}",
            f"- 분석: {n.analysis}",
            f"- 기록: {n.created_at}\n",
        ]

    context = build_calibration_context(settings)
    lines += ["## 현재 적용 중인 보정 기준\n"]
    lines.append(context if context else "(반복 확인된 편향이 아직 없어 보정 없이 원칙만 적용 중)")
    return "\n".join(lines) + "\n"
