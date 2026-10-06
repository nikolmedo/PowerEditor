import json
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from powereditor.config import Settings, WhisperDevice
from powereditor.models import Transcript
from powereditor.paths import AppPaths
from powereditor.settings_store import InMemorySecretStore, SettingsService
from powereditor.transcribe.base import (
    RawWord,
    TranscriptionError,
    filler_prompt,
    normalize_words,
    wav_duration,
)
from powereditor.transcribe.factory import TranscriberConfigError, create_transcriber
from powereditor.transcribe.local_whisper import LocalWhisperTranscriber
from powereditor.transcribe.openai_whisper import (
    OpenAIWhisperTranscriber,
    parse_silences,
    plan_chunks,
)

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not found")


def test_filler_prompt_is_language_dependent() -> None:
    spanish = filler_prompt("es")
    assert spanish is not None
    assert spanish.startswith("Eh, este, mmm")
    assert filler_prompt("en") != spanish
    assert filler_prompt("xx") is None
    assert filler_prompt(None) is None


def test_normalize_words_enforces_monotonic_bounded_times() -> None:
    words = normalize_words(
        [
            RawWord(" Hola", -0.2, 0.5, 0.9),
            RawWord(" ", 0.5, 0.6, 0.5),
            RawWord("mundo,", 0.4, 0.9, 1.2),
            RawWord("fin", 2.5, 3.5, None),
        ],
        duration=3.0,
    )

    assert [(w.text, w.start, w.end, w.prob) for w in words] == [
        ("Hola", 0.0, 0.5, 0.9),
        ("mundo,", 0.5, 0.9, 1.0),
        ("fin", 2.5, 3.0, None),
    ]


def test_plan_chunks_prefers_silences_and_falls_back_to_hard_split() -> None:
    assert plan_chunks(50.0, 60.0, []) == [(0.0, 50.0)]
    assert plan_chunks(100.0, 40.0, [(30.0, 32.0), (65.0, 66.0)]) == [
        (0.0, 31.0),
        (31.0, 65.5),
        (65.5, 100.0),
    ]
    assert plan_chunks(100.0, 40.0, [(5.0, 6.0)]) == [(0.0, 40.0), (40.0, 80.0), (80.0, 100.0)]


def test_parse_silences_reads_silencedetect_output() -> None:
    stderr = (
        "[silencedetect @ 0x1] silence_start: 1.5\n"
        "[silencedetect @ 0x1] silence_end: 2.25 | silence_duration: 0.75\n"
        "[silencedetect @ 0x1] silence_start: 9\n"
    )
    assert parse_silences(stderr, duration=10.0) == [(1.5, 2.25), (9.0, 10.0)]


@dataclass
class FakeWord:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class FakeSegment:
    words: list[FakeWord] | None


@dataclass
class FakeInfo:
    language: str


@dataclass
class FakeWhisperModel:
    segments: list[FakeSegment]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def transcribe(self, audio: object, **kwargs: Any) -> tuple[Iterable[FakeSegment], FakeInfo]:
        self.calls.append({"audio": audio, **kwargs})
        return iter(self.segments), FakeInfo(language="es")


def _local(
    model: FakeWhisperModel, tmp_path: Path, device: WhisperDevice = "auto", cuda: bool = False
) -> tuple[LocalWhisperTranscriber, list[tuple[str, str, str, Path]]]:
    loads: list[tuple[str, str, str, Path]] = []

    def loader(name: str, dev: str, compute_type: str, root: Path) -> FakeWhisperModel:
        loads.append((name, dev, compute_type, root))
        return model

    transcriber = LocalWhisperTranscriber(
        "small",
        device,
        tmp_path / "models",
        cuda_available=cuda,
        loader=loader,
    )
    return transcriber, loads


def _write_wav(path: Path, seconds: float, rate: int = 16000) -> Path:
    import wave

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def test_local_transcriber_passes_other_audio_as_a_path(tmp_path: Path) -> None:
    model = _fake_model()
    audio = _write_wav(tmp_path / "a.wav", 1.0, rate=44100)
    transcriber, _ = _local(model, tmp_path)

    transcriber.transcribe(audio, "es")

    assert model.calls[0]["audio"] == str(audio)


SPOKEN = [("Eh,", 0.1, 0.4), ("hola", 0.5, 0.9), ("a", 0.95, 1.1), ("todos.", 1.1, 1.6)]


def _fake_model() -> FakeWhisperModel:
    return FakeWhisperModel(
        segments=[
            FakeSegment([FakeWord(f" {t}", s, e, 0.8) for t, s, e in SPOKEN[:2]]),
            FakeSegment(None),
            FakeSegment([FakeWord(f" {t}", s, e, 0.7) for t, s, e in SPOKEN[2:]]),
        ]
    )


def test_local_transcriber_uses_word_timestamps_prompt_and_cpu_int8(tmp_path: Path) -> None:
    model = _fake_model()
    audio = _write_wav(tmp_path / "a.wav", 2.0)
    transcriber, loads = _local(model, tmp_path)

    transcript = transcriber.transcribe(audio, "es")
    transcriber.transcribe(audio, "es")

    assert loads == [("small", "cpu", "int8", tmp_path / "models")]
    call = model.calls[0]
    # A 16 kHz WAV is decoded here, so faster-whisper never needs PyAV for it.
    assert isinstance(call["audio"], np.ndarray)
    assert (call["audio"].dtype, call["audio"].shape) == (np.float32, (32000,))
    assert call["word_timestamps"] is True
    assert call["vad_filter"] is False
    assert call["language"] == "es"
    assert call["initial_prompt"] == filler_prompt("es")
    assert [w.text for w in transcript.words] == ["Eh,", "hola", "a", "todos."]
    assert transcript.words[0].prob == 0.8
    assert (transcript.provider, transcript.model, transcript.language) == ("local", "small", "es")


@pytest.mark.parametrize(
    ("device", "cuda", "expected"),
    [
        ("auto", True, ("cuda", "float16")),
        ("cpu", True, ("cpu", "int8")),
        ("cuda", False, ("cuda", "float16")),
    ],
)
def test_local_transcriber_device_resolution(
    tmp_path: Path, device: WhisperDevice, cuda: bool, expected: tuple[str, str]
) -> None:
    transcriber, loads = _local(_fake_model(), tmp_path, device=device, cuda=cuda)
    transcriber.transcribe(_write_wav(tmp_path / "a.wav", 2.0), None)

    assert loads[0][1:3] == expected


def _verbose_json(words: Sequence[tuple[str, float, float]], offset: float = 0.0) -> dict[str, Any]:
    return {
        "task": "transcribe",
        "language": "spanish",
        "duration": 2.0,
        "text": " ".join(w for w, _, _ in words),
        "words": [{"word": w, "start": s - offset, "end": e - offset} for w, s, e in words],
        "segments": [],
    }


class RecordingHandler:
    def __init__(self, responses: list[dict[str, Any]], status: int = 200) -> None:
        self.responses = responses
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        return httpx.Response(self.status, json=body)


def _openai(
    handler: RecordingHandler, max_upload_bytes: int = 25 * 1024 * 1024
) -> OpenAIWhisperTranscriber:
    assert FFMPEG is not None
    return OpenAIWhisperTranscriber(
        api_key="sk-test",
        ffmpeg=FFMPEG,
        transport=httpx.MockTransport(handler),
        max_upload_bytes=max_upload_bytes,
    )


def _tone_wav(path: Path, gaps: bool = False) -> Path:
    assert FFMPEG is not None
    source = (
        "sine=frequency=440:duration=6,volume='if(between(t,2.8,3.4),0,1)':eval=frame"
        if gaps
        else "sine=frequency=440:duration=2"
    )
    encode = ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", source, *encode, str(path)],
        check=True,
    )
    return path


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_openai_transcriber_sends_verbose_json_word_request(tmp_path: Path) -> None:
    handler = RecordingHandler([_verbose_json(SPOKEN)])
    audio = _tone_wav(tmp_path / "tomá 1.wav")

    transcript = _openai(handler).transcribe(audio, "es")

    assert len(handler.requests) == 1
    request = handler.requests[0]
    assert str(request.url) == "https://api.openai.com/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer sk-test"
    body = request.content
    for name, value in [
        (b"model", b"whisper-1"),
        (b"response_format", b"verbose_json"),
        (b"timestamp_granularities[]", b"word"),
        (b"language", b"es"),
    ]:
        assert b'name="' + name + b'"\r\n\r\n' + value + b"\r\n" in body
    prompt = filler_prompt("es")
    assert prompt is not None
    assert prompt.encode("utf-8") in body
    assert b'filename="audio.mp3"' in body
    assert [w.text for w in transcript.words] == ["Eh,", "hola", "a", "todos."]
    assert all(w.prob is None for w in transcript.words)
    assert (transcript.provider, transcript.model, transcript.language) == (
        "openai",
        "whisper-1",
        "es",
    )


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_openai_transcriber_splits_large_audio_at_silence_and_offsets(tmp_path: Path) -> None:
    first = [("uno", 0.5, 1.0), ("dos", 2.0, 2.5)]
    second = [("tres", 4.0, 4.5), ("cuatro", 5.0, 5.5)]
    handler = RecordingHandler([_verbose_json(first), _verbose_json(second, offset=3.1)])
    audio = _tone_wav(tmp_path / "long.wav", gaps=True)

    transcript = _openai(handler, max_upload_bytes=20_000).transcribe(audio, "es")

    assert len(handler.requests) == 2
    assert [(w.text, round(w.start, 1)) for w in transcript.words] == [
        ("uno", 0.5),
        ("dos", 2.0),
        ("tres", 4.0),
        ("cuatro", 5.0),
    ]


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_openai_http_error_has_code_without_leaking_key(tmp_path: Path) -> None:
    handler = RecordingHandler([{"error": {"message": "bad key"}}], status=401)
    audio = _tone_wav(tmp_path / "a.wav")

    with pytest.raises(TranscriptionError) as excinfo:
        _openai(handler).transcribe(audio, "es")

    assert excinfo.value.code == "openai_unauthorized"
    assert "sk-test" not in str(excinfo.value)


def _settings_service(tmp_path: Path, **file_settings: Any) -> SettingsService:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "settings.json").write_text(json.dumps(file_settings), encoding="utf-8")
    return SettingsService(
        paths=AppPaths(data_dir=data_dir),
        secrets=InMemorySecretStore(),
        env=Settings(_env_file=None),
        cuda_available=lambda: False,
    )


def test_factory_picks_provider_and_requires_openai_key(tmp_path: Path) -> None:
    local = create_transcriber(_settings_service(tmp_path / "a", transcriber="local"))
    assert isinstance(local, LocalWhisperTranscriber)
    assert local.model == "small"

    service = _settings_service(tmp_path / "b", transcriber="openai", ffmpegPath=FFMPEG)
    with pytest.raises(TranscriberConfigError) as excinfo:
        create_transcriber(service)
    assert excinfo.value.code == "missing_openai_key"

    service.set_secret("openai_api_key", "sk-x")
    assert isinstance(create_transcriber(service), OpenAIWhisperTranscriber)


def _assert_valid(transcript: Transcript, duration: float) -> None:
    assert len(transcript.words) == 4
    for previous, current in zip(transcript.words, transcript.words[1:], strict=False):
        assert previous.end <= current.start
    for word in transcript.words:
        assert 0.0 <= word.start <= word.end <= duration
        assert word.text == word.text.strip() != ""


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_local_and_openai_transcripts_share_schema(tmp_path: Path) -> None:
    audio = _tone_wav(tmp_path / "same.wav")
    duration = wav_duration(audio)
    local, _ = _local(_fake_model(), tmp_path)
    openai = _openai(RecordingHandler([_verbose_json(SPOKEN)]))

    transcripts = [local.transcribe(audio, "es"), openai.transcribe(audio, "es")]

    schema_keys = [set(t.model_dump(by_alias=True)) for t in transcripts]
    assert schema_keys[0] == schema_keys[1] == {"language", "words", "provider", "model"}
    for transcript in transcripts:
        _assert_valid(Transcript.model_validate_json(transcript.model_dump_json()), duration)
    assert [w.text for w in transcripts[0].words] == [w.text for w in transcripts[1].words]


@pytest.mark.slow
@pytest.mark.ffmpeg
@needs_ffmpeg
def test_real_tiny_model_on_tone(tmp_path: Path) -> None:
    from powereditor.transcribe.local_whisper import ensure_model

    models = AppPaths.from_env().models_dir
    ensure_model("tiny", models)
    transcriber = LocalWhisperTranscriber("tiny", "cpu", models, cuda_available=False)

    transcript = transcriber.transcribe(_tone_wav(tmp_path / "tone.wav"), "es")

    assert transcript.provider == "local"
    assert all(w.end <= 2.0 for w in transcript.words)
