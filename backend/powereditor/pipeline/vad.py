"""Voice activity detection on the 16 kHz ingest WAV."""

import wave
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol

import numpy as np
from numpy.typing import NDArray

from powereditor.models import CamelModel
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, no_progress, run_stage

VAD_STAGE_VERSION = 1
SILENCE_DBFS = -120.0

Range = tuple[float, float]
Samples = NDArray[np.float64]


class TimeRange(CamelModel):
    start: float
    end: float


class VadResult(CamelModel):
    source_id: str
    duration: float
    detector: str
    speech: list[TimeRange]
    padded: list[TimeRange]


class SpeechDetector(Protocol):
    name: ClassVar[str]
    __dataclass_fields__: ClassVar[dict[str, Any]]

    def __call__(self, samples: Samples, rate: int) -> list[Range]: ...


def pad_and_merge(ranges: Sequence[Range], pad: float, duration: float) -> list[Range]:
    """Grow every range by `pad` on both sides, clamp to [0, duration], merge overlaps."""
    merged: list[Range] = []
    for start, end in sorted(ranges):
        start, end = max(start - pad, 0.0), min(end + pad, duration)
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def intersect_ranges(a: Sequence[Range], b: Sequence[Range]) -> list[Range]:
    """Intersection of two sorted, non-overlapping range lists."""
    result: list[Range] = []
    i = j = 0
    while i < len(a) and j < len(b):
        start, end = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if start < end:
            result.append((start, end))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return result


def energy_dbfs(samples: Samples, rate: int, window_s: float) -> Samples:
    """RMS level in dBFS of consecutive non-overlapping windows (last partial window kept)."""
    size = max(round(window_s * rate), 1)
    count = -(-len(samples) // size)
    padded = np.zeros(count * size)
    padded[: len(samples)] = samples
    rms = np.sqrt(np.mean(padded.reshape(count, size) ** 2, axis=1))
    with np.errstate(divide="ignore"):
        levels: Samples = 20 * np.log10(rms)
    return np.maximum(levels, SILENCE_DBFS)


def ranges_above_floor(
    levels: Samples, window_s: float, floor_dbfs: float, min_gap_s: float, min_speech_s: float
) -> list[Range]:
    """Runs of windows louder than the floor, bridging short gaps and dropping short blips."""
    loud = np.concatenate([[False], levels > floor_dbfs, [False]])
    edges = np.flatnonzero(np.diff(loud.astype(np.int8)))
    raw = [
        (float(s) * window_s, float(e) * window_s)
        for s, e in zip(edges[::2], edges[1::2], strict=True)
    ]
    bridged: list[Range] = []
    for start, end in raw:
        if bridged and start - bridged[-1][1] < min_gap_s:
            bridged[-1] = (bridged[-1][0], end)
        else:
            bridged.append((start, end))
    return [(start, end) for start, end in bridged if end - start >= min_speech_s]


@dataclass(frozen=True)
class EnergyDetector:
    """Speech = windows above a dBFS floor. Detects any loud sound, not only voice."""

    name: ClassVar[str] = "energy"
    floor_dbfs: float = -45.0
    window_ms: int = 20
    min_gap_ms: int = 200
    min_speech_ms: int = 100

    def __call__(self, samples: Samples, rate: int) -> list[Range]:
        window = self.window_ms / 1000
        levels = energy_dbfs(samples, rate, window)
        return [
            (start, min(end, len(samples) / rate))
            for start, end in ranges_above_floor(
                levels, window, self.floor_dbfs, self.min_gap_ms / 1000, self.min_speech_ms / 1000
            )
        ]


@dataclass(frozen=True)
class SileroDetector:
    """Silero VAD (ONNX model bundled with faster-whisper) intersected with a dBFS floor."""

    name: ClassVar[str] = "silero"
    threshold: float = 0.5
    min_silence_ms: int = 300
    floor_dbfs: float = -45.0

    def __call__(self, samples: Samples, rate: int) -> list[Range]:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        options = VadOptions(
            threshold=self.threshold, min_silence_duration_ms=self.min_silence_ms, speech_pad_ms=0
        )
        stamps = get_speech_timestamps(samples.astype(np.float32), options, sampling_rate=rate)
        voiced = [(stamp["start"] / rate, stamp["end"] / rate) for stamp in stamps]
        floor = EnergyDetector(floor_dbfs=self.floor_dbfs, min_gap_ms=0, min_speech_ms=0)
        return [r for r in intersect_ranges(voiced, floor(samples, rate)) if r[1] - r[0] > 0.05]


def read_wav(path: Path) -> tuple[Samples, int]:
    """Mono float samples in [-1, 1] from a 16-bit PCM WAV."""
    with wave.open(str(path), "rb") as handle:
        channels, rate = handle.getnchannels(), handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    return pcm, rate


def _ranges(ranges: Sequence[Range]) -> list[TimeRange]:
    return [TimeRange(start=start, end=end) for start, end in ranges]


def detect_voice(
    layout: ProjectLayout,
    source_id: str,
    wav: Path,
    *,
    padding_ms: int,
    detector: SpeechDetector,
    progress: ProgressCallback = no_progress,
) -> VadResult:
    """Speech ranges of one source, raw and padded by `padding_ms`; cached as `vad-<id>`."""

    def compute() -> VadResult:
        samples, rate = read_wav(wav)
        duration = len(samples) / rate
        speech = detector(samples, rate)
        return VadResult(
            source_id=source_id,
            duration=duration,
            detector=detector.name,
            speech=_ranges(speech),
            padded=_ranges(pad_and_merge(speech, padding_ms / 1000, duration)),
        )

    params = {"detector": detector.name, "options": asdict(detector), "paddingMs": padding_ms}
    return run_stage(
        layout,
        f"vad-{source_id}",
        VAD_STAGE_VERSION,
        [wav],
        params,
        VadResult,
        compute,
        progress=progress,
    )
