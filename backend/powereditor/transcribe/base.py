import wave
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from powereditor.models import TranscriberProvider, Transcript, Word

FILLER_PROMPTS: dict[str, str] = {
    "es": "Eh, este, mmm, o sea, bueno, eh... pues, este, ¿no?",
    "en": "Um, uh, hmm, like, you know, I mean, uh...",
    "pt": "É, tipo, hum, né, então, ééé...",
}


class Transcriber(Protocol):
    @property
    def provider(self) -> TranscriberProvider: ...

    @property
    def model(self) -> str: ...

    def transcribe(self, audio_path: Path, language: str | None) -> Transcript: ...


class TranscriptionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RawWord:
    text: str
    start: float
    end: float
    prob: float | None


def filler_prompt(language: str | None) -> str | None:
    """Initial prompt that nudges Whisper to keep filler words in the transcript."""
    if language is None:
        return None
    return FILLER_PROMPTS.get(language.lower().split("-")[0])


def normalize_words(raw_words: Iterable[RawWord], duration: float | None) -> list[Word]:
    """Strip text and force non-negative, monotonic, non-overlapping, bounded word times."""
    words: list[Word] = []
    previous_end = 0.0
    for raw in raw_words:
        text = raw.text.strip()
        if not text:
            continue
        start = max(raw.start, previous_end, 0.0)
        end = max(raw.end, start)
        if duration is not None:
            start = min(start, duration)
            end = min(end, duration)
        prob = None if raw.prob is None else min(max(raw.prob, 0.0), 1.0)
        words.append(Word(text=text, start=start, end=end, prob=prob))
        previous_end = end
    return words


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def audio_duration(path: Path) -> float | None:
    try:
        return wav_duration(path)
    except (wave.Error, EOFError):
        return None
