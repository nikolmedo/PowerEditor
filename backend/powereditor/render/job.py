"""Render a project end to end: composition render -> loudness final pass -> export."""

import re
import time
from dataclasses import dataclass
from pathlib import Path

from powereditor.models import load_project
from powereditor.pipeline.ffmpeg import MediaTools
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, no_progress
from powereditor.render.base import Renderer, RenderSettings, RenderTiming
from powereditor.render.final_pass import normalize_loudness
from powereditor.render.node_runtime import resolve_render_node
from powereditor.render.remotion_render import RemotionRenderer
from powereditor.settings_store import SettingsService
from powereditor.timeline import timeline_layout

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")


class ProjectNotFoundError(FileNotFoundError):
    code = "project_not_found"


@dataclass(frozen=True)
class RenderResult:
    output: Path
    video_seconds: float
    wall_s: float
    timing: RenderTiming

    @property
    def realtime_factor(self) -> float:
        """Seconds of video produced per second of wall time (>1 is faster than realtime)."""
        return self.video_seconds / self.wall_s if self.wall_s > 0 else 0.0


def create_renderer(service: SettingsService) -> Renderer:
    node = resolve_render_node(service.get_effective().node_path, service.paths.bin_dir)
    return RemotionRenderer(node)


def render_project(
    layout: ProjectLayout,
    service: SettingsService,
    *,
    renderer: Renderer | None = None,
    name: str = "final",
    progress: ProgressCallback = no_progress,
) -> RenderResult:
    """Render `layout`'s project to `exports/<name>.mp4`."""
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError(f"invalid export name: {name!r}")
    if not layout.project_file.is_file():
        raise ProjectNotFoundError(f"project {layout.project_id!r} has no project.json")
    project = load_project(layout.project_file)
    settings = service.get_effective()
    tools = MediaTools.from_settings(service)
    renderer = renderer or create_renderer(service)
    exports = layout.root / "exports"
    output = exports / f"{name}.mp4"
    intermediate = exports / f".{name}.render.mp4"
    video_seconds = timeline_layout(project).duration_in_frames / project.fps

    started = time.perf_counter()
    try:
        timing = renderer.render(
            project,
            layout.media_dir,
            intermediate,
            RenderSettings(audio_crossfade_ms=settings.audio_crossfade_ms),
            lambda fraction: progress("render", fraction, "composition"),
        )
        progress("final-pass", 0.0, "loudnorm")
        normalize_loudness(
            tools.ffmpeg,
            intermediate,
            output,
            settings.target_lufs,
            duration=video_seconds,
            on_progress=lambda fraction: progress("final-pass", fraction, "loudnorm"),
        )
    finally:
        intermediate.unlink(missing_ok=True)
    return RenderResult(
        output=output,
        video_seconds=video_seconds,
        wall_s=time.perf_counter() - started,
        timing=timing,
    )
