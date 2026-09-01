"""
음성 → transcript 변환 (faster-whisper 로컬 실행).

오디오는 외부로 나가지 않는다. word 단위 timestamp 를 함께 받아
delivery.py 에서 pause / 발화 속도 / 덩어리 길이를 계산한다.

주의:
  Whisper 계열은 "읽기 좋은" 전사를 만들도록 학습돼 있어
  um / uh 같은 filler 를 빼먹거나 false start 를 정리해 버리는 경향이 있다.
  initial_prompt 로 verbatim 을 유도하지만 완벽하지 않다.
  다만 filler 가 빠져도 그 자리는 pause 로 남으므로 hesitation 자체는 포착된다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# verbatim 전사를 유도하는 프롬프트. 실제 시험 발화의 hesitation 을 살리기 위함.
_VERBATIM_PROMPT = (
    "Um, uh, I mean, you know, like... so, this is a verbatim transcript "
    "that keeps every filler, false start, and repetition exactly as spoken."
)

_DEFAULT_STT = {
    "backend": "faster-whisper",
    "model": "small",
    "device": "auto",
    "compute_type": "int8",
    "language": "en",
    "beam_size": 5,
    "vad_filter": True,
    "verbatim_prompt": True,
}


@dataclass
class Word:
    text: str
    start: float
    end: float
    probability: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Transcript:
    text: str
    words: list[Word] = field(default_factory=list)
    duration: float = 0.0          # 오디오 전체 길이 (초)
    language: str = "en"
    audio_path: str = ""
    model: str = ""

    @property
    def word_count(self) -> int:
        return len(self.words)


def _stt_config(settings: dict) -> dict:
    cfg = dict(_DEFAULT_STT)
    cfg.update((settings.get("opic_coach", {}) or {}).get("stt", {}) or {})
    return cfg


def transcribe(audio_path: str | Path, settings: dict) -> Transcript:
    """
    오디오 파일을 전사하고 word timestamp 를 포함한 Transcript 를 반환.

    faster-whisper 는 무거운 선택 의존성이라 호출 시점에 import 한다.
    (설치: pip install -r requirements-audio.txt)
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError(
            "faster-whisper 가 설치돼 있지 않습니다. "
            "pip install -r requirements-audio.txt 로 설치하세요."
        ) from exc

    cfg = _stt_config(settings)
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"오디오 파일이 없습니다: {path}")

    model = WhisperModel(
        cfg["model"],
        device=cfg["device"],
        compute_type=cfg["compute_type"],
    )

    segments, info = model.transcribe(
        str(path),
        language=cfg["language"] or None,
        beam_size=cfg["beam_size"],
        word_timestamps=True,
        vad_filter=cfg["vad_filter"],
        condition_on_previous_text=False,
        initial_prompt=_VERBATIM_PROMPT if cfg["verbatim_prompt"] else None,
    )

    words: list[Word] = []
    texts: list[str] = []
    for seg in segments:                      # generator — 순회해야 실제 디코딩됨
        texts.append(seg.text)
        for w in (seg.words or []):
            words.append(
                Word(
                    text=w.word.strip(),
                    start=round(w.start, 3),
                    end=round(w.end, 3),
                    probability=round(w.probability, 4),
                )
            )

    return Transcript(
        text=" ".join(t.strip() for t in texts).strip(),
        words=words,
        duration=round(getattr(info, "duration", 0.0), 3),
        language=getattr(info, "language", cfg["language"]),
        audio_path=str(path),
        model=cfg["model"],
    )


def save_transcript(transcript: Transcript, path: str | Path) -> Path:
    """전사 결과를 JSON 으로 저장 (재전사 비용을 아끼기 위한 캐시)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(asdict(transcript), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


def load_transcript(path: str | Path) -> Transcript:
    """save_transcript 로 저장한 JSON 을 다시 읽는다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    words = [Word(**w) for w in data.pop("words", [])]
    return Transcript(words=words, **data)
