import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from powereditor import cli
from powereditor.models import Project, save_project
from powereditor.paths import AppPaths
from powereditor.pipeline.ffmpeg import FractionCallback
from powereditor.pipeline.runner import ProjectLayout
from powereditor.render import job as job_module
from powereditor.render.base import RenderSettings, RenderTiming
from powereditor.render.job import render_project
from powereditor.settings_store import SettingsService
from tests.media import ffmpeg_lavfi, needs_ffmpeg

pytestmark = [pytest.mark.ffmpeg, needs_ffmpeg]

FIXTURE = (
    Path(__file__).parents[2] / "packages" / "composition" / "test" / "fixtures" / "project.json"
)


class FakeRenderer:
    """Writes a lavfi clip as long as the timeline instead of running Remotion."""

    def __init__(self) -> None:
        self.settings: RenderSettings | None = None

    def render(
        self,
        project: Project,
        media_dir: Path,
        output: Path,
        settings: RenderSettings,
        on_progress: FractionCallback | None = None,
    ) -> RenderTiming:
        self.settings = settings
        output.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg_lavfi(
            output,
            "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30:duration=5.3333",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=5.3333,volume=0.1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        )  # fmt: skip
        if on_progress is not None:
            on_progress(1.0)
        return RenderTiming(setup_s=0.5, render_s=1.0)


def _project_layout(data_dir: Path) -> ProjectLayout:
    layout = ProjectLayout.for_project(AppPaths(data_dir=data_dir), "demo")
    layout.ensure()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    save_project(Project.model_validate(fixture["project"]), layout.project_file)
    return layout


def test_render_project_writes_the_normalized_export_and_reports_speed(tmp_path: Path) -> None:
    layout = _project_layout(tmp_path)
    service = SettingsService.default()
    renderer = FakeRenderer()
    fractions: list[float] = []

    result = render_project(
        layout,
        service,
        renderer=renderer,
        name="final",
        progress=lambda stage, fraction, message: fractions.append(fraction),
    )

    assert result.output == layout.root / "exports" / "final.mp4"
    assert result.output.is_file()
    assert sorted(p.name for p in result.output.parent.iterdir()) == ["final.mp4"]
    assert result.video_seconds == pytest.approx(160 / 30)
    assert result.realtime_factor == pytest.approx(result.video_seconds / result.wall_s)
    assert result.timing == RenderTiming(setup_s=0.5, render_s=1.0)
    assert renderer.settings == RenderSettings(audio_crossfade_ms=15)
    assert fractions[-1] == 1.0


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
