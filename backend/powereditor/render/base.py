from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from powereditor.models import Project
from powereditor.pipeline.ffmpeg import FractionCallback
from powereditor.render.quality import RenderQuality


@dataclass(frozen=True)
class RenderSettings:
    audio_crossfade_ms: int
    punch_in_scale: float = 1.1
    quality: RenderQuality = "standard"
    concurrency: int | None = None
    """Browser tabs Remotion renders with; None leaves Remotion's default."""


@dataclass(frozen=True)
class RenderTiming:
    """Wall-clock split of a render; `setup_s` covers one-off work such as bundling."""

    setup_s: float
    render_s: float


class Renderer(Protocol):
    """Turns a project into a video file (Remotion today; an FFmpeg plan B may follow)."""

    def render(
        self,
        project: Project,
        media_dir: Path,
        output: Path,
        settings: RenderSettings,
        on_progress: FractionCallback | None = None,
    ) -> RenderTiming: ...
