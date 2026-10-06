"""Edited timeline → OpenTimelineIO, written as FCPXML (or `.otio`) for desktop NLEs.

Needs the optional `nle` extra (`opentimelineio` + `otio-fcpx-xml-adapter`). The FCPXML
adapter drops time warps, so a clip with a speed other than 1 keeps its source length
there; the `.otio` file keeps the speed as a `LinearTimeWarp`.
"""

from pathlib import Path
from typing import Any

from powereditor.models import Project

ADAPTERS = {".fcpxml": "fcpx_xml", ".otio": "otio_json"}


class NleExportUnavailableError(RuntimeError):
    code = "nle_export_unavailable"


def _otio() -> Any:
    try:
        import opentimelineio
    except ImportError as exc:
        raise NleExportUnavailableError(
            "NLE export needs the optional 'nle' extra: uv sync --extra nle"
        ) from exc
    return opentimelineio


def _media_url(path: str) -> str:
    """A file URL for an absolute path; other paths are passed through unchanged."""
    try:
        return Path(path).as_uri()
    except ValueError:
        return path


def build_timeline(project: Project) -> Any:
    """One video track with every kept clip, in source frames at the project rate."""
    otio = _otio()
    fps = project.fps
    rational, time_range = otio.opentime.RationalTime, otio.opentime.TimeRange
    sources = {source.id: source for source in project.sources}
    # The project does not store source durations; the furthest clip end bounds what is used.
    spans: dict[str, int] = {}
    for clip in project.clips:
        spans[clip.source_id] = max(spans.get(clip.source_id, 0), round(clip.out_sec * fps))
    timeline = otio.schema.Timeline(name="PowerEditor", global_start_time=rational(0, fps))
    track = otio.schema.Track(name="Video", kind=otio.schema.TrackKind.Video)
    timeline.tracks.append(track)
    for clip in project.clips:
        if clip.removed:
            continue
        reference = otio.schema.ExternalReference(
            target_url=_media_url(sources[clip.source_id].original_path),
            available_range=time_range(rational(0, fps), rational(spans[clip.source_id], fps)),
        )
        start = round(clip.in_sec * fps)
        length = round((clip.out_sec - clip.in_sec) * fps)
        item = otio.schema.Clip(
            name=clip.id,
            media_reference=reference,
            source_range=time_range(rational(start, fps), rational(length, fps)),
        )
        if clip.speed != 1.0:
            item.effects.append(otio.schema.LinearTimeWarp(time_scalar=clip.speed))
        track.append(item)
    return timeline


def export_nle(project: Project, output: Path) -> Path:
    """Write the timeline; the adapter follows the suffix (`.fcpxml` or `.otio`)."""
    adapter = ADAPTERS.get(output.suffix.lower())
    if adapter is None:
        raise ValueError(f"unsupported NLE file type {output.suffix!r}; use .fcpxml or .otio")
    otio = _otio()
    output.parent.mkdir(parents=True, exist_ok=True)
    otio.adapters.write_to_file(build_timeline(project), str(output), adapter_name=adapter)
    return output
