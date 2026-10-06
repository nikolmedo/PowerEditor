import shutil
import wave
from pathlib import Path

import pytest
from typer.testing import CliRunner

from powereditor.cli import app
from powereditor.models import TranscriberProvider, Transcript, Word
from powereditor.paths import AppPaths
from powereditor.pipeline.ingest import IngestedSource, IngestManifest, ProbeResult, load_manifest
from powereditor.pipeline.runner import ProjectLayout
from powereditor.pipeline.transcription import transcribe_project

FFMPEG = shutil.which("ffmpeg")


class FakeTranscriber:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str | None]] = []

    @property
    def provider(self) -> TranscriberProvider:
        return "local"

    @property
    def model(self) -> str:
        return "fake"

    def transcribe(self, audio_path: Path, language: str | None) -> Transcript:
        self.calls.append((audio_path, language))
        word = Word(text=audio_path.stem, start=0.0, end=0.5, prob=None)
        return Transcript(language=language, words=[word], provider="local", model="fake")


def _source(layout: ProjectLayout, name: str, with_audio: bool) -> IngestedSource:
    wav_path: str | None = None
    if with_audio:
        wav = layout.media_dir / f"{name}.wav"
        with wave.open(str(wav), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x00\x00" * 16000)
        wav_path = str(wav)
    probe = ProbeResult(
        duration=1.0,
        width=320,
        height=240,
        rotation=0,
        r_frame_rate=30.0,
        avg_frame_rate=30.0,
        has_audio=with_audio,
        video_codec="h264",
        audio_codec="aac" if with_audio else None,
    )
    return IngestedSource(
        source_id=name,
        original_path=name,
        probe=probe,
        fps=30,
        video_encoder="libx264",
        mezzanine_path="m",
        proxy_path="p",
        wav_path=wav_path,
    )


def test_transcribe_project_caches_per_source_and_skips_silent_sources(tmp_path: Path) -> None:
    layout = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    layout.ensure()
    manifest = IngestManifest(
        sources=[_source(layout, "src-a", True), _source(layout, "src-b", False)]
    )
    layout.cache_file("ingest").write_text(manifest.model_dump_json(by_alias=True), "utf-8")
    fake = FakeTranscriber()

    first = transcribe_project(layout, fake, "es")
    second = transcribe_project(layout, fake, "es")

    assert list(first) == ["src-a"]
    assert first["src-a"].words[0].text == "src-a"
    assert second == first
    assert len(fake.calls) == 1
    assert layout.cache_file("transcribe-src-a").is_file()

    transcribe_project(layout, fake, "en")
    assert [language for _, language in fake.calls] == ["es", "en"]


def test_transcribe_cli_reports_missing_project(isolated_environment: Path) -> None:
    result = CliRunner().invoke(app, ["transcribe", "nope"])

    assert result.exit_code == 1
    assert "no ingested sources" in result.output


@pytest.mark.ffmpeg
@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not found")
def test_ingest_cli_creates_project(isolated_environment: Path, tmp_path: Path) -> None:
    import subprocess

    assert FFMPEG is not None
    clip = tmp_path / "carpeta con espacio" / "tomá 1.mp4"
    clip.parent.mkdir()
    video = "testsrc2=size=320x240:rate=30:duration=1"
    inputs = ["-f", "lavfi", "-i", video, "-f", "lavfi", "-i", "sine=duration=1"]
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", *inputs, "-shortest", str(clip)],
        check=True,
    )

    result = CliRunner().invoke(app, ["ingest", str(clip), "--project-id", "demo"])

    assert result.exit_code == 0, result.output
    layout = ProjectLayout.for_project(AppPaths.from_env(), "demo")
    assert str(layout.root) in result.output.replace("\n", "")
    sources = load_manifest(layout).sources
    assert len(sources) == 1
    assert Path(sources[0].proxy_path).is_file()
