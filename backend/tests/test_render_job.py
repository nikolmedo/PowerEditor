import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from powereditor import cli
from powereditor.models import AudioTrack, Project, load_project, save_project
from powereditor.paths import AppPaths
from powereditor.pipeline.ffmpeg import FfmpegError, FractionCallback
from powereditor.pipeline.runner import ProjectLayout
from powereditor.render import job as job_module
from powereditor.render.base import RenderSettings, RenderTiming
from powereditor.render.job import EmptyTimelineError, MusicNotFoundError, render_project
from powereditor.render.remotion_render import RenderError
from powereditor.settings_store import SettingsService
from tests.media import FFPROBE, ffmpeg_lavfi, needs_ffmpeg

pytestmark = [pytest.mark.ffmpeg, needs_ffmpeg]

FIXTURE = (
    Path(__file__).parents[2] / "packages" / "composition" / "test" / "fixtures" / "project.json"
)


class FakeRenderer:
    """Writes a silent lavfi clip as long as the timeline instead of running Remotion."""

    def __init__(self, fail: bool = False, garbage: bool = False) -> None:
        self.settings: RenderSettings | None = None
        self.calls = 0
        self.fail = fail
        self.garbage = garbage

    def render(
        self,
        project: Project,
        media_dir: Path,
        output: Path,
        settings: RenderSettings,
        on_progress: FractionCallback | None = None,
    ) -> RenderTiming:
        self.settings = settings
        self.calls += 1
        if self.fail:
            raise RenderError("Remotion render exited with code 1: boom")
        output.parent.mkdir(parents=True, exist_ok=True)
        if self.garbage:
            output.write_bytes(b"not a video")
            return RenderTiming(setup_s=0.0, render_s=0.0)
        ffmpeg_lavfi(
            output,
            "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30:duration=5.3333",
            "-frames:v", "160", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        )  # fmt: skip
        if on_progress is not None:
            on_progress(1.0)
        return RenderTiming(setup_s=0.5, render_s=1.0)


def _project_layout(data_dir: Path, remove_all: bool = False) -> ProjectLayout:
    layout = ProjectLayout.for_project(AppPaths(data_dir=data_dir), "demo")
    layout.ensure()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    project = Project.model_validate(fixture["project"])
    if remove_all:
        project = project.model_copy(
            update={"clips": [c.model_copy(update={"removed": True}) for c in project.clips]}
        )
    save_project(project, layout.project_file)
    # The fixture's clips reach 9.3 s into s1; the voice is rebuilt from this mezzanine.
    ffmpeg_lavfi(
        layout.media_dir / "s1.mezzanine.mp4",
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30:duration=10",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=10,volume=0.1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
    )  # fmt: skip
    return layout


def _durations(path: Path) -> list[float]:
    assert FFPROBE is not None
    rows = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    return [float(row) for row in rows]


def test_render_project_writes_the_normalized_export_and_reports_speed(tmp_path: Path) -> None:
    layout = _project_layout(tmp_path)
    service = SettingsService.default()
    renderer = FakeRenderer()
    fractions: list[float] = []
    stages: list[str] = []

    def progress(stage: str, fraction: float, message: str) -> None:
        stages.append(stage)
        fractions.append(fraction)

    result = render_project(layout, service, renderer=renderer, name="final", progress=progress)

    assert result.output == layout.root / "exports" / "final.mp4"
    assert result.output.is_file()
    assert sorted(p.name for p in result.output.parent.iterdir()) == ["final.mp4"]
    assert result.video_seconds == pytest.approx(160 / 30)
    assert result.realtime_factor == pytest.approx(result.video_seconds / result.wall_s)
    assert result.timing == RenderTiming(setup_s=0.5, render_s=1.0)
    assert renderer.settings is not None
    assert renderer.settings.quality == "standard"
    assert 1 <= (renderer.settings.concurrency or 0) <= 8
    assert fractions[-1] == 1.0
    assert list(dict.fromkeys(stages)) == ["audio", "render", "final-pass"]
    video_s, audio_s = _durations(result.output)
    assert video_s == pytest.approx(160 / 30, abs=1 / 30)
    assert audio_s == pytest.approx(video_s, abs=1 / 30)


def test_render_project_passes_the_quality_and_the_concurrency_override(tmp_path: Path) -> None:
    layout = _project_layout(tmp_path)
    service = SettingsService.default()
    service.update({"renderMaxConcurrency": 3})
    renderer = FakeRenderer()

    result = render_project(layout, service, renderer=renderer, quality="draft")

    assert renderer.settings is not None
    assert (renderer.settings.quality, renderer.settings.concurrency) == ("draft", 3)
    assert (result.quality, result.concurrency) == ("draft", 3)


def _add_music(layout: ProjectLayout, file_name: str = "music.wav") -> None:
    project = load_project(layout.project_file)
    music = AudioTrack(
        id="music", kind="music", source_path=file_name, volume=0.5, ducking_enabled=True
    )
    save_project(
        project.model_copy(update={"audio_tracks": [*project.audio_tracks, music]}),
        layout.project_file,
    )


def test_render_project_mixes_the_music_track_under_the_voice(tmp_path: Path) -> None:
    layout = _project_layout(tmp_path)
    _add_music(layout)
    ffmpeg_lavfi(
        layout.media_dir / "music.wav",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=2",
    )  # fmt: skip
    messages: list[str] = []

    result = render_project(
        layout,
        SettingsService.default(),
        renderer=FakeRenderer(),
        progress=lambda stage, fraction, message: messages.append(message),
    )

    assert "music" in messages
    assert sorted(p.name for p in result.output.parent.iterdir()) == ["final.mp4"]
    video_s, audio_s = _durations(result.output)
    assert audio_s == pytest.approx(video_s, abs=1 / 30)


def test_render_project_refuses_a_missing_music_file_before_rendering(tmp_path: Path) -> None:
    layout = _project_layout(tmp_path)
    _add_music(layout, "gone.mp3")
    renderer = FakeRenderer()

    with pytest.raises(MusicNotFoundError) as excinfo:
        render_project(layout, SettingsService.default(), renderer=renderer)

    assert excinfo.value.code == "music_not_found"
    assert renderer.calls == 0


def test_render_project_refuses_an_empty_timeline_before_rendering(tmp_path: Path) -> None:
    layout = _project_layout(tmp_path, remove_all=True)
    renderer = FakeRenderer()

    with pytest.raises(EmptyTimelineError) as excinfo:
        render_project(layout, SettingsService.default(), renderer=renderer)

    assert excinfo.value.code == "empty_timeline"
    assert renderer.calls == 0


@pytest.mark.parametrize("renderer", [FakeRenderer(fail=True), FakeRenderer(garbage=True)])
def test_failed_render_keeps_the_previous_export_and_leaves_no_temp_files(
    tmp_path: Path, renderer: FakeRenderer
) -> None:
    layout = _project_layout(tmp_path)
    exports = layout.root / "exports"
    exports.mkdir()
    (exports / "final.mp4").write_bytes(b"previous export")

    with pytest.raises((RenderError, FfmpegError)):
        render_project(layout, SettingsService.default(), renderer=renderer)

    assert sorted(p.name for p in exports.iterdir()) == ["final.mp4"]
    assert (exports / "final.mp4").read_bytes() == b"previous export"


def test_render_cli_prints_output_and_render_speed(
    isolated_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _project_layout(isolated_environment)
    monkeypatch.setattr(job_module, "create_renderer", lambda service: FakeRenderer())

    result = CliRunner().invoke(cli.app, ["render", "demo", "--output", "cut"])

    assert result.exit_code == 0, result.output
    output = result.output.replace("\n", "")
    assert str(layout.root / "exports" / "cut.mp4") in output
    assert "realtime" in output


def test_render_cli_rejects_a_project_without_project_file(isolated_environment: Path) -> None:
    result = CliRunner().invoke(cli.app, ["render", "missing"])

    assert result.exit_code == 1
    assert "project_not_found" in result.output


def test_render_cli_reports_an_empty_timeline(isolated_environment: Path) -> None:
    _project_layout(isolated_environment, remove_all=True)

    result = CliRunner().invoke(cli.app, ["render", "demo"])

    assert result.exit_code == 1
    assert "empty_timeline" in result.output
