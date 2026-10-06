"""Render a project end to end: voice rebuild -> music mix -> video render -> final pass -> export.

Every intermediate lives next to the export (same filesystem) and the export is
written as `<name>.part.mp4`, then moved into place only once the final pass
succeeds, so a failed render never leaves a truncated or half-written export.
"""

import re
import time
from dataclasses import dataclass
from pathlib import Path

from powereditor.models import AudioTrack, Project, load_project
from powereditor.pipeline.ffmpeg import MediaTools
from powereditor.pipeline.ingest import probe_media
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, no_progress
from powereditor.render.audio_mix import VoiceGraph, build_voice_filtergraph, render_voice
from powereditor.render.base import Renderer, RenderSettings, RenderTiming
from powereditor.render.ducking import project_speech
from powereditor.render.final_pass import finalize_export
from powereditor.render.music_mix import render_mix
from powereditor.render.node_runtime import resolve_render_node
from powereditor.render.remotion_render import RemotionRenderer
from powereditor.settings_store import SettingsService
from powereditor.timeline import timeline_layout

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")


class ProjectNotFoundError(FileNotFoundError):
    code = "project_not_found"


class EmptyTimelineError(ValueError):
    code = "empty_timeline"


class MusicNotFoundError(FileNotFoundError):
    code = "music_not_found"


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


def _voice_graph(project: Project, media_dir: Path, ffprobe: str, crossfade_ms: int) -> VoiceGraph:
    media = {s.id: media_dir / Path(s.mezzanine_path).name for s in project.sources}
    used = {clip.source_id for clip in project.clips if not clip.removed}
    silent = {
        source_id
        for source_id in used
        if source_id in media and not probe_media(ffprobe, media[source_id]).has_audio
    }
    return build_voice_filtergraph(project, crossfade_ms, media, silent_sources=silent)


def music_track(project: Project, media_dir: Path) -> tuple[AudioTrack, Path] | None:
    """The project's music track and its file in `media_dir`, if it has one."""
    track = next((t for t in project.audio_tracks if t.kind == "music" and t.source_path), None)
    if track is None or track.source_path is None:
        return None
    path = media_dir / Path(track.source_path).name
    if not path.is_file():
        raise MusicNotFoundError(f"music file {path.name} is not in {media_dir}")
    return track, path


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
    frames = timeline_layout(project).duration_in_frames
    if frames == 0:
        raise EmptyTimelineError(f"project {layout.project_id!r} has no clips left to render")
    video_seconds = frames / project.fps
    music = music_track(project, layout.media_dir)
    settings = service.get_effective()
    tools = MediaTools.from_settings(service)
    renderer = renderer or create_renderer(service)
    exports = layout.root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    output = exports / f"{name}.mp4"
    partial = exports / f"{name}.part.mp4"
    video = exports / f".{name}.video.mp4"
    voice = exports / f".{name}.voice.wav"
    mix = exports / f".{name}.mix.wav"

    started = time.perf_counter()
    try:
        progress("audio", 0.0, "voice")
        graph = _voice_graph(project, layout.media_dir, tools.ffprobe, settings.audio_crossfade_ms)
        render_voice(
            tools.ffmpeg,
            graph,
            voice,
            on_progress=lambda fraction: progress("audio", fraction, "voice"),
        )
        if music is not None:
            track, music_file = music
            render_mix(
                tools.ffmpeg,
                voice,
                music_file,
                track,
                project_speech(project),
                graph.total_samples,
                mix,
                graph.sample_rate,
                on_progress=lambda fraction: progress("audio", fraction, "music"),
            )
        timing = renderer.render(
            project,
            layout.media_dir,
            video,
            RenderSettings(
                audio_crossfade_ms=settings.audio_crossfade_ms,
                punch_in_scale=settings.punch_in_scale,
            ),
            lambda fraction: progress("render", fraction, "composition"),
        )
        progress("final-pass", 0.0, "loudnorm")
        finalize_export(
            tools.ffmpeg,
            video,
            mix if music is not None else voice,
            partial,
            settings.target_lufs,
            duration=video_seconds,
            on_progress=lambda fraction: progress("final-pass", fraction, "loudnorm"),
        )
        partial.replace(output)
    finally:
        for temporary in (video, voice, mix, partial):
            temporary.unlink(missing_ok=True)
    return RenderResult(
        output=output,
        video_seconds=video_seconds,
        wall_s=time.perf_counter() - started,
        timing=timing,
    )
