"""Assemble the first editable `project.json` from the analysis stages."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from powereditor.export.subtitles import remap_words
from powereditor.models import (
    AudioTrack,
    Clip,
    ColorCorrection,
    ColorGrade,
    ColorStats,
    Project,
    ProjectPreset,
    Segment,
    Source,
    SourceWord,
    Subtitles,
    SubtitleStyle,
    TransitionIn,
    Word,
    save_project,
)
from powereditor.pipeline.auto_cta import cta_overlays
from powereditor.pipeline.color_match import match_colors
from powereditor.pipeline.ingest import IngestedSource
from powereditor.pipeline.runner import ProjectLayout
from powereditor.pipeline.takes import TakeEntry
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
# Length of fades and slides; cuts and punch-ins are instant.
TRANSITION_SECONDS = 0.3
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


def _source(index: int, draft: DraftSource, correction: ColorCorrection | None) -> Source:
    entry = draft.ingested
    return Source(
        id=entry.source_id,
        original_path=entry.original_path,
        mezzanine_path=entry.mezzanine_path,
        proxy_path=entry.proxy_path,
        display_color=PALETTE[index % len(PALETTE)],
        loudness_lufs=draft.loudness_lufs,
        color_stats=draft.color_stats,
        color_correction=correction,
    )


def _source_clips(draft: DraftSource, padding_s: float) -> dict[str, Clip]:
    """Padded clip per segment id; ids follow the segment's position in the source."""
    ordered = sorted(draft.segments, key=lambda segment: segment.start)
    ranges = [(segment.start, segment.end) for segment in ordered]
    source_id = draft.ingested.source_id
    bounds = clip_bounds(ranges, padding_s, draft.ingested.probe.duration)
    return {
        segment.id: Clip(
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
        for index, (segment, (in_sec, out_sec)) in enumerate(zip(ordered, bounds, strict=True))
        if out_sec > in_sec
    }


def _apply_entries(clips: Mapping[str, Clip], entries: Sequence[TakeEntry], fps: int) -> list[Clip]:
    placed: list[Clip] = []
    for entry in entries:
        clip = clips.get(entry.segment_id)
        if clip is None:
            continue
        instant = entry.transition in ("cut", "punch_in")
        duration = 0 if instant else round(fps * TRANSITION_SECONDS)
        placed.append(
            clip.model_copy(
                update={
                    "removed": entry.removed,
                    "take_group_id": entry.take_group_id,
                    "decision_confidence": entry.decision_confidence,
                    "alternative_take_ids": [
                        clips[segment_id].id
                        for segment_id in entry.alternative_segment_ids
                        if segment_id in clips
                    ],
                    "transition_in": TransitionIn(type=entry.transition, duration_frames=duration),
                }
            )
        )
    return placed


def build_draft(
    sources: Sequence[DraftSource],
    *,
    padding_s: float,
    preset: ProjectPreset | None = None,
    entries: Sequence[TakeEntry] | None = None,
    cta_segment_ids: Collection[str] = (),
    language: str | None = None,
) -> Project:
    """Clips in `entries` order (the takes stage), or one kept clip per segment in source order.

    A retake that was not chosen stays in the timeline as a removed clip sharing the
    chosen clip's `takeGroupId`; `alternativeTakeIds` lists those clip ids. Segments in
    `cta_segment_ids` get an automatic call-to-action overlay (`pipeline.auto_cta`) whose
    text is in `language`.
    """
    if not sources:
        raise ValueError("a draft needs at least one source")
    fps = sources[0].ingested.fps
    by_segment = {
        segment_id: clip
        for draft in sources
        for segment_id, clip in _source_clips(draft, padding_s).items()
    }
    if entries is None:
        clips = list(by_segment.values())
    else:
        clips = _apply_entries(by_segment, entries, fps)
    source_words = {
        draft.ingested.source_id: [
            SourceWord(text=word.text, start=word.start, end=word.end) for word in draft.words
        ]
        for draft in sources
    }
    corrections = match_colors({d.ingested.source_id: d.color_stats for d in sources})
    project = Project(
        version=1,
        preset=preset or _preset_for(sources[0].ingested),
        fps=fps,
        sources=[
            _source(index, draft, corrections[draft.ingested.source_id])
            for index, draft in enumerate(sources)
        ],
        clips=clips,
        audio_tracks=[AudioTrack(id="voice", kind="voice", volume=1.0, ducking_enabled=False)],
        subtitles=Subtitles(
            style=DEFAULT_SUBTITLE_STYLE,
            words=remap_words(clips, source_words, fps),
            source_words=source_words,
        ),
        overlays=[],
        color_grade=NEUTRAL_GRADE,
    )
    if not cta_segment_ids:
        return project
    segment_clips = {segment_id: clip.id for segment_id, clip in by_segment.items()}
    overlays = cta_overlays(project, segment_clips, cta_segment_ids, language)
    return project.model_copy(update={"overlays": overlays})


def write_draft(layout: ProjectLayout, project: Project) -> Path:
    save_project(project, layout.project_file)
    return layout.project_file
