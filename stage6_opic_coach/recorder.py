"""
마이크 녹음 (로컬 실행 전용).

Whisper 가 기대하는 16kHz mono wav 로 저장한다.
Enter 를 누르면 답변 종료, max_seconds 에 도달하면 자동 종료.

원격/컨테이너 환경에는 마이크가 없다. is_available() 로 먼저 확인할 것.
"""
from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 16000
CHANNELS = 1


@dataclass
class Recording:
    path: Path
    seconds: float          # 실제 저장된 오디오 길이 (샘플 수 기준)
    wall_seconds: float     # 녹음 버튼을 누르고 있던 실제 시간
    stopped_by: str         # "user" | "timeout"
    overflows: int = 0      # 입력 버퍼 overflow 횟수

    @property
    def dropped_seconds(self) -> float:
        """녹음 시간과 저장된 오디오 길이의 차이. 0보다 크면 입력이 유실된 것."""
        return round(max(0.0, self.wall_seconds - self.seconds), 2)


def is_available() -> tuple[bool, str]:
    """녹음 가능 여부와 사유를 반환."""
    try:
        import sounddevice as sd
    except ImportError:
        return False, "sounddevice 가 없습니다. pip install -r requirements-audio.txt"
    except OSError as exc:                       # PortAudio 미설치 등
        return False, f"오디오 백엔드를 열 수 없습니다: {exc}"

    try:
        devices = [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
    except Exception as exc:                     # pragma: no cover - 환경 의존
        return False, f"입력 장치를 조회할 수 없습니다: {exc}"

    if not devices:
        return False, "입력 장치(마이크)가 없습니다. 로컬 머신에서 실행하세요."
    return True, devices[0]["name"]


def record(
    path: str | Path,
    max_seconds: int = 120,
    samplerate: int = SAMPLE_RATE,
    input_fn=input,
) -> Recording:
    """
    마이크로 녹음해 wav 로 저장.

    Args:
        path: 저장 경로 (.wav)
        max_seconds: 최대 녹음 길이 (초)
        samplerate: 샘플레이트 (Whisper 는 16000 을 기대)
        input_fn: 종료 대기 입력 함수 (테스트 주입용)
    """
    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    frames: queue.Queue = queue.Queue()
    stop = threading.Event()
    overflows = 0

    def callback(indata, _frames, _time, status):
        nonlocal overflows
        if status and getattr(status, "input_overflow", False):
            overflows += 1
        frames.put(indata.copy())

    def wait_for_enter():
        try:
            input_fn()
        except (EOFError, KeyboardInterrupt):
            pass
        stop.set()

    waiter = threading.Thread(target=wait_for_enter, daemon=True)
    waiter.start()

    started = time.monotonic()
    stopped_by = "user"
    with sd.InputStream(samplerate=samplerate, channels=CHANNELS,
                        dtype="float32", callback=callback):
        while not stop.is_set():
            if time.monotonic() - started >= max_seconds:
                stopped_by = "timeout"
                break
            time.sleep(0.05)

    elapsed = time.monotonic() - started

    # 스트림이 닫힌 뒤 콜백이 마지막 블록을 넣는 중일 수 있어 잠깐 여유를 준다.
    # (queue.empty() 만 믿고 바로 비우면 끝부분이 잘린다)
    time.sleep(0.2)
    chunks = []
    while True:
        try:
            chunks.append(frames.get_nowait())
        except queue.Empty:
            break

    audio = np.concatenate(chunks) if chunks else np.zeros((0, CHANNELS), dtype="float32")
    sf.write(str(out), audio, samplerate)

    return Recording(
        path=out,
        seconds=round(len(audio) / samplerate, 1),
        wall_seconds=round(elapsed, 1),
        stopped_by=stopped_by,
        overflows=overflows,
    )


def speak(text: str) -> bool:
    """
    질문을 소리로 읽어 준다 (실제 시험은 음성으로 문항이 나온다).

    macOS `say`, Linux `espeak`/`espeak-ng` 가 있으면 사용하고 없으면 조용히 건너뛴다.
    """
    for cmd in (["say", "-r", "170"], ["espeak-ng", "-s", "150"], ["espeak", "-s", "150"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run([*cmd, text], check=False, capture_output=True, timeout=90)
                return True
            except (subprocess.SubprocessError, OSError):
                return False
    return False
