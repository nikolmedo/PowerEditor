"""Deterministic per-take features; every count and comparison lives here, not in a model."""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz

from powereditor.models import Take, TakeFeatures, Word
from powereditor.pipeline.take_text import content_tokens, count_fillers, looks_cut_off, tokens
from powereditor.pipeline.vad import Samples
from powereditor.pipeline.visual import NullVisualExtractor, VisualFeatureExtractor

CLIPPING_LEVEL = 0.999
CLIPPING_MAX_FRACTION = 0.001
SILENCE_FLOOR_DBFS = -90.0
MAX_RESTART_WORDS = 3
_SCRIPT_BREAK = re.compile(r"(?<=[.!?…])\s+|\n+")


@dataclass(frozen=True)
class AudioClip:
    """A source's mono samples in [-1, 1]."""

    samples: Samples
    rate: int


def script_lines(script: str) -> list[str]:
    """Split a script into lines and sentences."""
    return [line.strip() for line in _SCRIPT_BREAK.split(script) if line.strip()]


def spoken_tokens(text: str, language: str | None) -> tuple[list[str], int]:
    """Filler-free tokens without stutters, plus how many repetitions were dropped.

    A repetition is a word cut with a hyphen ("ha- hablar") or a restart that says the
    same one to `MAX_RESTART_WORDS` words twice in a row ("the three, the three").
    """
    raw_words = text.split()
    whole = [raw for raw in raw_words if not raw.rstrip(",;:").endswith("-")]
    repetitions = len(raw_words) - len(whole)
    kept: list[str] = []
    for token in content_tokens(" ".join(whole), language):
        kept.append(token)
        for size in range(MAX_RESTART_WORDS, 0, -1):
            if len(kept) >= 2 * size and kept[-size:] == kept[-2 * size : -size]:
                del kept[-size:]
                repetitions += 1
                break
    return kept, repetitions


def coverage(reference: Sequence[str], spoken: Sequence[str]) -> float:
    """Share of the reference words (with multiplicity) that were spoken."""
    if not reference:
        return 1.0
    matched = Counter(reference) & Counter(spoken)
    return sum(matched.values()) / len(reference)


def _reference(spoken: Sequence[str], script: Sequence[str], language: str | None) -> list[str]:
    text = " ".join(spoken)
    best = max(script, key=lambda line: fuzz.partial_ratio(text, " ".join(tokens(line))))
    return spoken_tokens(best, language)[0]


def _speech_rate(take: Take, words: Sequence[Word], token_count: int) -> float:
    if words:
        duration = words[-1].end - words[0].start
        return len(words) / duration if duration > 0 else 0.0
    duration = take.end - take.start
    return token_count / duration if duration > 0 else 0.0


def _mean_prob(words: Sequence[Word]) -> float | None:
    probs = [word.prob for word in words if word.prob is not None]
    return sum(probs) / len(probs) if probs else None


def _level(take: Take, audio: AudioClip) -> tuple[float, bool]:
    """RMS level in dBFS (a stand-in for LUFS on a short slice) and whether it clips."""
    start = max(round(take.start * audio.rate), 0)
    chunk = audio.samples[start : round(take.end * audio.rate)]
    if chunk.size == 0:
        return SILENCE_FLOOR_DBFS, False
    rms = float(np.sqrt(np.mean(chunk**2)))
    level = 20 * np.log10(rms) if rms > 0 else SILENCE_FLOOR_DBFS
    clipped = float(np.mean(np.abs(chunk) >= CLIPPING_LEVEL))
    return max(float(level), SILENCE_FLOOR_DBFS), clipped > CLIPPING_MAX_FRACTION


def cluster_features(
    takes: Sequence[Take],
    *,
    language: str | None,
    script: Sequence[str] = (),
    words: Mapping[str, Sequence[Word]] | None = None,
    audio: Mapping[str, AudioClip] | None = None,
    visual: VisualFeatureExtractor | None = None,
) -> list[TakeFeatures]:
    """Features of each take in one cluster, in recording order.

    Completeness compares against the closest script line, or the longest take of the
    cluster when there is no script. `words` and `audio` are keyed by take id and
    source id; missing entries leave the matching features unknown.
    """
    visual = visual or NullVisualExtractor()
    spoken = [spoken_tokens(take.text, language) for take in takes]
    longest = max((clean for clean, _ in spoken), key=len)
    features: list[TakeFeatures] = []
    for index, (take, (clean, repetitions)) in enumerate(zip(takes, spoken, strict=True)):
        take_words = (words or {}).get(take.id, ())
        reference = _reference(clean, script, language) if script else longest
        loudness, clipping = (None, False)
        source_audio = (audio or {}).get(take.source_id)
        if source_audio is not None:
            loudness, clipping = _level(take, source_audio)
        face_centered, sharpness = visual.measure(take)
        features.append(
            TakeFeatures(
                take_id=take.id,
                completeness=coverage(reference, clean),
                filler_count=count_fillers(tokens(take.text), language),
                repetition_count=repetitions,
                cut_off=looks_cut_off(take.text, language),
                speech_rate_wps=_speech_rate(take, take_words, len(tokens(take.text))),
                mean_word_prob=_mean_prob(take_words),
                loudness_lufs=loudness,
                clipping=clipping,
                face_centered=face_centered,
                sharpness=sharpness,
                is_last_take=index == len(takes) - 1,
            )
        )
    return features
