import re
import tempfile
import wave
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError

from autocut.models import TranscriberProvider, Transcript
from autocut.pipeline.ffmpeg import run_ffmpeg, run_ffmpeg_stderr
from autocut.transcribe.base import (
    RawWord,
    TranscriptionError,
    filler_prompt,
    normalize_words,
    wav_duration,
)

OPENAI_API_BASE = "https://api.openai.com/v1"
OPENAI_MODEL = "whisper-1"
# Verified 2026-10-05: https://developers.openai.com/api/docs/guides/speech-to-text
# "Files can be up to 25 MB."
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_SAFETY = 0.9
MP3_BITRATE = "32k"
MIN_CHUNK_FRACTION = 0.5
SILENCE_FILTER = "silencedetect=noise=-35dB:d=0.3"
REQUEST_TIMEOUT_SECONDS = 600.0

_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")
_LANGUAGE_NAMES = {"spanish": "es", "english": "en", "portuguese": "pt", "french": "fr"}


class _ApiWord(BaseModel):
    word: str
    start: float
    end: float


class _VerboseTranscription(BaseModel):
    language: str | None = None
    words: list[_ApiWord] = []


def plan_chunks(
    duration: float, max_chunk_seconds: float, silences: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Split [0, duration] into chunks no longer than the max, cutting at silences when possible."""
    midpoints = sorted((start + end) / 2 for start, end in silences)
    chunks: list[tuple[float, float]] = []
    start = 0.0
    while duration - start > max_chunk_seconds:
        limit = start + max_chunk_seconds
        floor = start + max_chunk_seconds * MIN_CHUNK_FRACTION
        candidates = [m for m in midpoints if floor < m <= limit]
        cut = candidates[-1] if candidates else limit
        chunks.append((start, cut))
        start = cut
    chunks.append((start, duration))
    return chunks


def parse_silences(stderr: str, duration: float) -> list[tuple[float, float]]:
    silences: list[tuple[float, float]] = []
    pending: float | None = None
    for line in stderr.splitlines():
        if match := _SILENCE_START.search(line):
            pending = max(float(match.group(1)), 0.0)
        elif (match := _SILENCE_END.search(line)) and pending is not None:
            silences.append((pending, float(match.group(1))))
            pending = None
    if pending is not None:
        silences.append((pending, duration))
    return silences


class OpenAIWhisperTranscriber:
    def __init__(
        self,
        api_key: str,
        ffmpeg: str,
        *,
        transport: httpx.BaseTransport | None = None,
        base_url: str = OPENAI_API_BASE,
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
    ) -> None:
        self._api_key = api_key
        self._ffmpeg = ffmpeg
        self._transport = transport
        self._url = f"{base_url.rstrip('/')}/audio/transcriptions"
        self._max_upload_bytes = max_upload_bytes

    @property
    def provider(self) -> TranscriberProvider:
        return "openai"

    @property
    def model(self) -> str:
        return OPENAI_MODEL

    def _encode(self, audio: Path, output: Path, start: float, length: float | None) -> Path:
        window = ["-ss", f"{start:.3f}"] + ([] if length is None else ["-t", f"{length:.3f}"])
        args = ["-i", str(audio), *window, "-vn", "-ac", "1", "-ar", "16000"]
        run_ffmpeg(self._ffmpeg, [*args, "-c:a", "libmp3lame", "-b:a", MP3_BITRATE, str(output)])
        return output

    def _chunks(self, audio: Path, duration: float, full: Path) -> list[tuple[float, float]]:
        budget = self._max_upload_bytes * UPLOAD_SAFETY
        size = full.stat().st_size
        if size <= budget:
            return [(0.0, duration)]
        stderr = run_ffmpeg_stderr(
            self._ffmpeg, ["-i", str(audio), "-af", SILENCE_FILTER, "-f", "null", "-"]
        )
        max_chunk_seconds = duration * budget / size
        return plan_chunks(duration, max_chunk_seconds, parse_silences(stderr, duration))

    def _request(
        self, client: httpx.Client, upload: Path, language: str | None
    ) -> _VerboseTranscription:
        data: dict[str, str] = {
            "model": OPENAI_MODEL,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
        if language:
            data["language"] = language
        prompt = filler_prompt(language)
        if prompt:
            data["prompt"] = prompt
        try:
            response = client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                data=data,
                files={"file": ("audio.mp3", upload.read_bytes(), "audio/mpeg")},
            )
        except httpx.HTTPError as exc:
            raise TranscriptionError("openai_unreachable", f"OpenAI request failed: {exc}") from exc
        if response.status_code == 401:
            raise TranscriptionError("openai_unauthorized", "OpenAI rejected the API key")
        if response.status_code >= 400:
            raise TranscriptionError(
                "openai_http_error", f"OpenAI returned HTTP {response.status_code}"
            )
        try:
            return _VerboseTranscription.model_validate_json(response.content)
        except ValidationError as exc:
            raise TranscriptionError("openai_bad_response", "Unexpected OpenAI response") from exc

    def transcribe(self, audio_path: Path, language: str | None) -> Transcript:
        try:
            duration = wav_duration(audio_path)
        except (wave.Error, EOFError) as exc:
            raise TranscriptionError("unsupported_audio", "expected a PCM WAV file") from exc
        raw: list[RawWord] = []
        detected: str | None = None
        with (
            tempfile.TemporaryDirectory(prefix="autocut-openai-") as tmp,
            httpx.Client(transport=self._transport, timeout=REQUEST_TIMEOUT_SECONDS) as client,
        ):
            workdir = Path(tmp)
            full = self._encode(audio_path, workdir / "full.mp3", 0.0, None)
            chunks = self._chunks(audio_path, duration, full)
            for index, (start, end) in enumerate(chunks):
                upload = full
                if len(chunks) > 1:
                    upload = self._encode(audio_path, workdir / f"{index}.mp3", start, end - start)
                if upload.stat().st_size > self._max_upload_bytes:
                    raise TranscriptionError("chunk_too_large", "audio chunk exceeds upload limit")
                result = self._request(client, upload, language)
                detected = detected or result.language
                raw += [RawWord(w.word, w.start + start, w.end + start, None) for w in result.words]
        resolved_language = language or _LANGUAGE_NAMES.get((detected or "").lower())
        return Transcript(
            language=resolved_language,
            words=normalize_words(raw, duration),
            provider="openai",
            model=OPENAI_MODEL,
        )
