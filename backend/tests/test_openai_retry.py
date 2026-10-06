import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from powereditor.models import Transcript
from powereditor.transcribe.base import TranscriptionError
from powereditor.transcribe.openai_whisper import OpenAIWhisperTranscriber

FFMPEG = shutil.which("ffmpeg")
pytestmark = [
    pytest.mark.ffmpeg,
    pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not found"),
]

OK_BODY = {"language": "spanish", "words": [{"word": "hola", "start": 0.1, "end": 0.5}]}


class ScriptedHandler:
    """Replies with a scripted status (or raises a connection error) per request."""

    def __init__(self, script: list[int | str]) -> None:
        self.script = script
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.script[min(len(self.requests), len(self.script)) - 1]
        if step == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        assert isinstance(step, int)
        return httpx.Response(step, json=OK_BODY if step == 200 else {"error": {}})


def _transcribe(tmp_path: Path, handler: ScriptedHandler, sleeps: list[float]) -> Transcript:
    assert FFMPEG is not None
    audio = tmp_path / "a.wav"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(audio),
        ],
        check=True,
    )
    transcriber = OpenAIWhisperTranscriber(
        "sk-test", FFMPEG, transport=httpx.MockTransport(handler), sleep=sleeps.append
    )
    return transcriber.transcribe(audio, "es")


@pytest.mark.parametrize("script", [[429, 503, 200], ["connect", 500, 200]])
def test_openai_retries_transient_failures_with_backoff(
    tmp_path: Path, script: list[int | str]
) -> None:
    handler = ScriptedHandler(script)
    sleeps: list[float] = []

    transcript = _transcribe(tmp_path, handler, sleeps)

    assert len(handler.requests) == 3
    assert sleeps == [1.0, 2.0]
    assert [w.text for w in transcript.words] == ["hola"]


def test_openai_gives_up_after_three_attempts(tmp_path: Path) -> None:
    handler = ScriptedHandler([503])
    sleeps: list[float] = []

    with pytest.raises(TranscriptionError) as excinfo:
        _transcribe(tmp_path, handler, sleeps)

    assert excinfo.value.code == "openai_http_error"
    assert len(handler.requests) == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize(
    ("status", "code"), [(401, "openai_unauthorized"), (400, "openai_http_error")]
)
def test_openai_does_not_retry_client_errors(tmp_path: Path, status: int, code: str) -> None:
    handler = ScriptedHandler([status, 200])
    sleeps: list[float] = []

    with pytest.raises(TranscriptionError) as excinfo:
        _transcribe(tmp_path, handler, sleeps)

    assert excinfo.value.code == code
    assert len(handler.requests) == 1
    assert sleeps == []
