import itertools
from pathlib import Path

import pytest
from typer.testing import CliRunner

from powereditor import cli
from powereditor.models import TranscriberProvider, Transcript, Word, load_project
from powereditor.paths import AppPaths
from powereditor.pipeline import analyze as analyze_module
from powereditor.pipeline.analyze import analyze_project
from powereditor.pipeline.runner import ProjectLayout
from powereditor.pipeline.vad import EnergyDetector
from powereditor.settings_store import SettingsService
from tests.media import gated_tone_clip, needs_ffmpeg

pytestmark = [pytest.mark.ffmpeg, needs_ffmpeg]

BURSTS = 5


class BurstTranscriber:
    """Fake transcriber: one sentence per tone burst at [2k + 0.1, 2k + 0.9]."""

    def __init__(self) -> None:
        self.calls = 0
        self.languages: list[str | None] = []

    @property
    def provider(self) -> TranscriberProvider:
        return "local"

    @property
    def model(self) -> str:
        return "fake-bursts"

    def transcribe(self, audio_path: Path, language: str | None) -> Transcript:
        self.calls += 1
        self.languages.append(language)
        words = [
            word
            for k in range(BURSTS)
            for word in (
                Word(text=f"palabra{k}", start=2 * k + 0.1, end=2 * k + 0.5),
                Word(text=f"fin{k}.", start=2 * k + 0.5, end=2 * k + 0.9),
            )
        ]
        return Transcript(language=language, words=words, provider="local", model="fake-bursts")


@pytest.fixture(scope="module")
def burst_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return gated_tone_clip(tmp_path_factory.mktemp("media") / "bursts.mp4", 2 * BURSTS)


def test_analyze_project_removes_silence_end_to_end(burst_clip: Path, tmp_path: Path) -> None:
    service = SettingsService.default()
    layout = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    events: list[str] = []
    fake = BurstTranscriber()

    result = analyze_project(
        layout,
        service,
        files=[burst_clip],
        transcriber=fake,
        detector=EnergyDetector(),
        progress=lambda stage, fraction, message: events.append(stage),
    )

    project = load_project(result.project_path)
    assert project == result.project
    assert result.project_path == layout.project_file
    assert result.original_seconds == pytest.approx(2 * BURSTS, abs=0.2)
    assert BURSTS * 0.8 < result.kept_seconds < result.original_seconds * 0.75
    assert len(project.clips) == BURSTS
    bounds = [(c.in_sec, c.out_sec) for c in project.clips]
    assert all(a_out <= b_in for (_, a_out), (b_in, _) in itertools.pairwise(bounds))
    for k, (in_sec, out_sec) in enumerate(bounds):
        assert in_sec == pytest.approx(2 * k + 0.1 - 0.12, abs=0.06)
        assert out_sec == pytest.approx(2 * k + 0.9 + 0.12, abs=0.06)
    frames = [(w.start_frame, w.end_frame) for w in project.subtitles.words]
    assert len(frames) == 2 * BURSTS
    assert all(s <= e for s, e in frames)
    assert all(a[1] <= b[0] for a, b in itertools.pairwise(frames))
    assert project.sources[0].loudness_lufs > -40
    stages = {e.split("-")[0] for e in events}
    assert {"vad", "segments", "loudness", "color", "takes", "draft"} <= stages
    assert result.takes.decisions == []
    assert layout.cache_file("takes").is_file()

    analyze_project(
        layout, service, files=[burst_clip], transcriber=fake, detector=EnergyDetector()
    )
    assert fake.calls == 1


def test_project_language_overrides_the_setting(burst_clip: Path, tmp_path: Path) -> None:
    service = SettingsService.default()
    layout = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    fake = BurstTranscriber()

    analyze_project(
        layout,
        service,
        files=[burst_clip],
        transcriber=fake,
        detector=EnergyDetector(),
        language="en",
    )

    assert service.get_effective().language == "es"
    assert fake.languages == ["en"]


def test_analyze_cli_prints_summary(
    burst_clip: Path, isolated_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(analyze_module, "create_transcriber", lambda service: BurstTranscriber())

    result = CliRunner().invoke(
        cli.app,
        [
            "analyze",
            str(burst_clip),
            "--project-id",
            "demo",
            "--vad",
            "energy",
            "--preset",
            "reel_9x16",
        ],
    )

    assert result.exit_code == 0, result.output
    layout = ProjectLayout.for_project(AppPaths.from_env(), "demo")
    output = result.output.replace("\n", "")
    assert str(layout.project_file) in output
    assert f"{BURSTS} clips" in output
    assert load_project(layout.project_file).preset == "reel_9x16"
