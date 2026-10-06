from pathlib import Path

import pytest
from typer.testing import CliRunner

from powereditor import cli
from powereditor.models import TranscriberProvider, Transcript
from powereditor.paths import AppPaths
from powereditor.pipeline.ffmpeg import FfmpegError, MediaTools
from powereditor.pipeline.runner import ProjectLayout, StageOutputError
from powereditor.transcribe.base import TranscriptionError
from powereditor.transcribe.factory import TranscriberConfigError
from tests.test_transcription_stage import _source


class RaisingTranscriber:
    def __init__(self, error: Exception) -> None:
        self.error = error

    @property
    def provider(self) -> TranscriberProvider:
        return "openai"

    @property
    def model(self) -> str:
        return "whisper-1"

    def transcribe(self, audio_path: Path, language: str | None) -> Transcript:
        raise self.error


def _project_with_audio() -> None:
    from powereditor.pipeline.ingest import IngestManifest

    layout = ProjectLayout.for_project(AppPaths.from_env(), "demo")
    layout.ensure()
    manifest = IngestManifest(sources=[_source(layout, "src-a", True)])
    layout.cache_file("ingest").write_text(manifest.model_dump_json(by_alias=True), "utf-8")


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TranscriptionError("openai_unreachable", "network down"), "openai_unreachable"),
        (FfmpegError("ffmpeg exited with code 1: bad input"), "ffmpeg_failed"),
    ],
)
def test_transcribe_cli_reports_errors_with_code(
    monkeypatch: pytest.MonkeyPatch, error: Exception, code: str
) -> None:
    _project_with_audio()
    monkeypatch.setattr(cli, "create_transcriber", lambda service: RaisingTranscriber(error))

    result = CliRunner().invoke(cli.app, ["transcribe", "demo"])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert f"{code}:" in result.output


def test_transcribe_cli_reports_config_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _project_with_audio()

    def broken(service: object) -> RaisingTranscriber:
        raise TranscriberConfigError("missing_openai_key", "Set an OpenAI API key")

    monkeypatch.setattr(cli, "create_transcriber", broken)

    result = CliRunner().invoke(cli.app, ["transcribe", "demo"])

    assert result.exit_code == 1
    assert "missing_openai_key:" in result.output


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (FfmpegError("ffmpeg exited with code 1"), "ffmpeg_failed"),
        (StageOutputError("ingest-x", [Path("x.wav")]), "stage_output_missing"),
    ],
)
def test_ingest_cli_reports_errors_with_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception, code: str
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr(MediaTools, "from_settings", lambda service: object())

    def failing(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(cli, "ingest_files", failing)

    result = CliRunner().invoke(cli.app, ["ingest", str(clip), "--project-id", "demo"])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert f"{code}:" in result.output
