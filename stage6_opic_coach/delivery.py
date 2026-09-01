"""
word timestamp → delivery 지표.

transcript 텍스트만으로는 사라지는 정보(멈춤, 속도, 발화 덩어리 크기)를
객관 수치로 뽑아 평가 근거로 넘긴다.

이 수치들은 "근거"이지 "점수"가 아니다.
수치가 좋다는 이유만으로 등급을 올리지 않는다는 원칙은 rater.py 프롬프트에서 다시 강제한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .transcriber import Transcript, Word

# 명백한 hesitation marker. 다른 뜻으로 쓰일 여지가 거의 없다.
CORE_FILLERS = {"um", "uh", "uhm", "erm", "er", "ah", "eh", "mm", "hmm", "mmm", "hm"}

# 담화 표지. 자연스러운 쓰임과 메우기용 쓰임이 섞여 있어 따로 센다.
DISCOURSE_MARKERS = {
    "like", "well", "so", "actually", "basically", "literally",
    "okay", "right", "anyway", "yeah",
}
DISCOURSE_PHRASES = ["you know", "i mean", "kind of", "sort of", "and stuff", "or something"]

# pause 구간 정의 (초)
PAUSE_MIN = 0.25
PAUSE_BUCKETS = [
    ("micro", 0.25, 0.6),      # 자연스러운 호흡
    ("short", 0.6, 1.0),
    ("long", 1.0, 2.0),        # 청자가 인지하는 멈춤
    ("breakdown", 2.0, 1e9),   # 말문이 막힌 수준
]

# 발화 덩어리를 나누는 기준 — 이 이상 쉬면 다른 덩어리로 본다.
RUN_BREAK_PAUSE = 1.0

# 원어민 대화 속도 참고 범위 (일반적으로 인용되는 값). 등급 기준이 아니다.
NATIVE_CONVERSATION_WPM = (140, 180)


@dataclass
class DeliveryMetrics:
    total_seconds: float          # 오디오 전체 길이
    speech_seconds: float         # 실제 단어를 발음한 시간의 합
    pause_seconds: float          # 단어 사이 멈춤의 합 (첫 단어 전 침묵은 lead_in_seconds)
    pause_ratio: float            # pause_seconds / total_seconds
    word_count: int

    lead_in_seconds: float        # 문항 시작부터 첫 단어까지 걸린 시간
    wpm: float                    # 전체 시간 기준 발화 속도
    articulation_rate: float      # 멈춤을 뺀 순수 조음 속도

    pause_counts: dict[str, int] = field(default_factory=dict)
    longest_pause: float = 0.0
    long_pauses_per_minute: float = 0.0

    core_filler_count: int = 0
    core_filler_per_100w: float = 0.0
    discourse_marker_count: int = 0
    discourse_marker_per_100w: float = 0.0

    immediate_repetitions: int = 0   # "I I went" 같은 즉시 반복
    mean_run_length: float = 0.0     # 긴 멈춤 사이 평균 단어 수
    longest_run_length: int = 0
    run_count: int = 0

    type_token_ratio: float = 0.0
    mattr: float = 0.0               # 길이 편향이 적은 어휘 다양성 지표

    low_confidence_ratio: float = 0.0  # 전사 신뢰도가 낮은 단어 비율


def _normalize(word: str) -> str:
    return re.sub(r"[^a-z']", "", word.lower())


def _mattr(tokens: list[str], window: int = 50) -> float:
    """Moving-Average Type-Token Ratio. 길이가 다른 답변끼리 비교하려면 TTR보다 안전하다."""
    if not tokens:
        return 0.0
    if len(tokens) <= window:
        return len(set(tokens)) / len(tokens)
    ratios = [
        len(set(tokens[i:i + window])) / window
        for i in range(len(tokens) - window + 1)
    ]
    return sum(ratios) / len(ratios)


def analyze_delivery(transcript: Transcript) -> DeliveryMetrics:
    """Transcript 의 word timestamp 로 delivery 지표를 계산."""
    words: list[Word] = [w for w in transcript.words if _normalize(w.text)]
    n = len(words)

    if n == 0:
        return DeliveryMetrics(
            total_seconds=transcript.duration, speech_seconds=0.0, pause_seconds=0.0,
            pause_ratio=0.0, word_count=0, lead_in_seconds=transcript.duration,
            wpm=0.0, articulation_rate=0.0,
            pause_counts={name: 0 for name, _, _ in PAUSE_BUCKETS},
        )

    total = transcript.duration or (words[-1].end - words[0].start)
    speech = sum(w.duration for w in words)

    # pause 계산
    gaps = []
    for prev, cur in zip(words, words[1:]):
        gap = cur.start - prev.end
        if gap >= PAUSE_MIN:
            gaps.append(gap)

    counts = {name: 0 for name, _, _ in PAUSE_BUCKETS}
    for gap in gaps:
        for name, lo, hi in PAUSE_BUCKETS:
            if lo <= gap < hi:
                counts[name] += 1
                break

    pause_total = sum(gaps)
    minutes = total / 60 if total else 0.0
    long_pauses = counts["long"] + counts["breakdown"]

    # filler / 담화 표지
    normalized = [_normalize(w.text) for w in words]
    core_fillers = sum(1 for t in normalized if t in CORE_FILLERS)
    markers = sum(1 for t in normalized if t in DISCOURSE_MARKERS)
    joined = " ".join(normalized)
    markers += sum(joined.count(p) for p in DISCOURSE_PHRASES)

    # 즉시 반복
    repeats = sum(
        1 for a, b in zip(normalized, normalized[1:])
        if a and a == b and a not in CORE_FILLERS
    )

    # 발화 덩어리 (긴 멈춤으로 분리) — text type 판단의 객관 근거
    runs: list[int] = []
    current = 1
    for prev, cur in zip(words, words[1:]):
        if cur.start - prev.end >= RUN_BREAK_PAUSE:
            runs.append(current)
            current = 1
        else:
            current += 1
    runs.append(current)

    content = [t for t in normalized if t and t not in CORE_FILLERS]
    low_conf = sum(1 for w in words if 0 < w.probability < 0.5)

    return DeliveryMetrics(
        total_seconds=round(total, 2),
        speech_seconds=round(speech, 2),
        pause_seconds=round(pause_total, 2),
        pause_ratio=round(pause_total / total, 3) if total else 0.0,
        word_count=n,
        lead_in_seconds=round(words[0].start, 2),
        wpm=round(n / minutes, 1) if minutes else 0.0,
        articulation_rate=round(n / (speech / 60), 1) if speech else 0.0,
        pause_counts=counts,
        longest_pause=round(max(gaps), 2) if gaps else 0.0,
        long_pauses_per_minute=round(long_pauses / minutes, 2) if minutes else 0.0,
        core_filler_count=core_fillers,
        core_filler_per_100w=round(core_fillers / n * 100, 1),
        discourse_marker_count=markers,
        discourse_marker_per_100w=round(markers / n * 100, 1),
        immediate_repetitions=repeats,
        mean_run_length=round(sum(runs) / len(runs), 1),
        longest_run_length=max(runs),
        run_count=len(runs),
        type_token_ratio=round(len(set(content)) / len(content), 3) if content else 0.0,
        mattr=round(_mattr(content), 3),
        low_confidence_ratio=round(low_conf / n, 3),
    )


def format_delivery_summary(m: DeliveryMetrics) -> str:
    """리포트 / 프롬프트 주입용 요약 텍스트."""
    if m.word_count == 0:
        return "delivery 지표: 인식된 단어가 없어 계산 불가"

    lo, hi = NATIVE_CONVERSATION_WPM
    return "\n".join([
        f"- 총 발화 시간: {m.total_seconds}초 (실제 발음 {m.speech_seconds}초, 단어 사이 멈춤 {m.pause_seconds}초 = {m.pause_ratio:.0%})",
        f"- 첫 단어까지 걸린 시간: {m.lead_in_seconds}초",
        f"- 단어 수: {m.word_count}개 / 속도 {m.wpm} wpm "
        f"(멈춤 제외 조음속도 {m.articulation_rate} wpm, 원어민 대화 통상 {lo}~{hi} wpm)",
        f"- 멈춤 분포: 0.25~0.6초 {m.pause_counts.get('micro', 0)}회 / "
        f"0.6~1초 {m.pause_counts.get('short', 0)}회 / "
        f"1~2초 {m.pause_counts.get('long', 0)}회 / "
        f"2초 이상 {m.pause_counts.get('breakdown', 0)}회, 최장 {m.longest_pause}초",
        f"- 1분당 1초 이상 멈춤: {m.long_pauses_per_minute}회",
        f"- 발화 덩어리: {m.run_count}개, 평균 {m.mean_run_length}단어, 최장 {m.longest_run_length}단어 "
        f"(1초 이상 멈춤을 경계로 분할)",
        f"- 명시적 filler(um/uh 등): {m.core_filler_count}회 = 100단어당 {m.core_filler_per_100w}회",
        f"- 담화 표지(like/you know 등): {m.discourse_marker_count}회 = 100단어당 {m.discourse_marker_per_100w}회",
        f"- 즉시 반복(I I went 형태): {m.immediate_repetitions}회",
        f"- 어휘 다양성: MATTR {m.mattr} (TTR {m.type_token_ratio})",
        f"- 전사 저신뢰 단어 비율: {m.low_confidence_ratio:.0%}"
        + ("  ← 높으면 발음 명료도 문제이거나 전사 오류일 수 있음" if m.low_confidence_ratio > 0.15 else ""),
    ])
