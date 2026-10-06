"""Assemble the first editable `project.json` from the analysis stages."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from powereditor.export.subtitles import remap_words
from powereditor.models import (
    AudioTrack,
    Clip,
    ColorGrade,
    ColorStats,
    Project,
    ProjectPreset,
    Segment,
    Source,
    Subtitles,
    SubtitleStyle,
    TransitionIn,
    Word,
    save_project,
)
from powereditor.pipeline.ingest import IngestedSource
from powereditor.pipeline.runner import ProjectLayout
from powereditor.pipeline.vad import Range

# Okabe-Ito palette: distinguishable with common color-vision deficiencies.
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#999999"]
DEFAULT_SUBTITLE_STYLE = SubtitleStyle(
    preset="karaoke_highlight",
    font_size=64,
    position="bottom",
    highlight_color="#FFD400",
    max_words_per_line=4,
)
NEUTRAL_GRADE = ColorGrade(
    preset="natural", brightness=1.0, contrast=1.0, saturation=1.0, temperature=0.0
)


@dataclass(frozen=True)
class DraftSource:
    ingested: IngestedSource
    segments: list[Segment]
    words: list[Word]
    loudness_lufs: float
    color_stats: ColorStats


def clip_bounds(segments: Sequence[Range], pad: float, duration: float) -> list[Range]:
    """Pad sorted segments by `pad`, clamped to the source and never overlapping a neighbor."""
    bounds: list[Range] = []
    for index, (start, end) in enumerate(segments):
        next_start = segments[index + 1][0] if index + 1 < len(segments) else duration
        previous_end = bounds[-1][1] if bounds else 0.0
        in_sec = max(start - pad, previous_end, 0.0)
        out_sec = max(min(end + pad, next_start, duration), in_sec)
        bounds.append((round(in_sec, 3), round(out_sec, 3)))
    return bounds


def _preset_for(source: IngestedSource) -> ProjectPreset:
    portrait = source.probe.display_width < source.probe.display_height
    return "reel_9x16" if portrait else "landscape_16x9"


def _source(index: int, draft: DraftSource) -> Source:
    entry = draft.ingested
    return Source(
        id=entry.source_id,
        original_path=entry.original_path,
        mezzanine_path=entry.mezzanine_path,
        proxy_path=entry.proxy_path,
        display_color=PALETTE[index % len(PALETTE)],
        loudness_lufs=draft.loudness_lufs,
        color_stats=draft.color_stats,
    )


def _clips(draft: DraftSource, padding_s: float) -> list[Clip]:
    ordered = sorted(draft.segments, key=lambda segment: segment.start)
    ranges = [(segment.start, segment.end) for segment in ordered]
    source_id = draft.ingested.source_id
    return [
        Clip(
            id=f"clip-{source_id}-{index:04d}",
            source_id=source_id,
            in_sec=in_sec,
            out_sec=out_sec,
            speed=1.0,
            volume=1.0,
            transition_in=TransitionIn(type="cut", duration_frames=0),
            alternative_take_ids=[],
            removed=False,
        )
        for index, (in_sec, out_sec) in enumerate(
            clip_bounds(ranges, padding_s, draft.ingested.probe.duration)
        )
        if out_sec > in_sec
    ]


def build_draft(
    sources: Sequence[DraftSource], *, padding_s: float, preset: ProjectPreset | None = None
) -> Project:
    """One clip per segment, in source order, with cut transitions (take selection comes later)."""
    if not sources:
        raise ValueError("a draft needs at least one source")
    fps = sources[0].ingested.fps
    clips = [clip for draft in sources for clip in _clips(draft, padding_s)]
    words = {draft.ingested.source_id: draft.words for draft in sources}
    return Project(
        version=1,
        preset=preset or _preset_for(sources[0].ingested),
        fps=fps,
        sources=[_source(index, draft) for index, draft in enumerate(sources)],
        clips=clips,
        audio_tracks=[AudioTrack(id="voice", kind="voice", volume=1.0, ducking_enabled=False)],
        subtitles=Subtitles(style=DEFAULT_SUBTITLE_STYLE, words=remap_words(clips, words, fps)),
        overlays=[],
        color_grade=NEUTRAL_GRADE,
    )


def write_draft(layout: ProjectLayout, project: Project) -> Path:
    save_project(project, layout.project_file)
    return layout.project_file
