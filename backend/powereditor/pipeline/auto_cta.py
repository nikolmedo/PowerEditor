"""Automatic call-to-action graphics over the segments that ask the viewer to act.

The takes stage flags each segment (`SegmentFlags.has_cta`, answered by the model assigned to
`cta_detection` or by the heuristic). A flagged segment gets a `cta` overlay over its clip's
span on the timeline. A flagged take that was not chosen lends its call to action to the kept
take of its group; a removed remark has no place on the timeline and gets none. Back-to-back
spans merge into one overlay, so a call to action split over two clips animates once.
"""

from collections.abc import Collection, Mapping

from powereditor.models import Clip, Overlay, Project
from powereditor.timeline import timeline_layout

CTA_TEXT = {"es": "¡Sígueme para más!", "en": "Follow for more!"}


def cta_text(language: str | None) -> str:
    """The starter text in the project language: Spanish unless it is English."""
    return CTA_TEXT["en"] if (language or "").lower().startswith("en") else CTA_TEXT["es"]


def _kept_clip(clip: Clip, clips: list[Clip]) -> Clip | None:
    if not clip.removed:
        return clip
    if clip.take_group_id is None:
        return None
    return next((c for c in clips if c.take_group_id == clip.take_group_id and not c.removed), None)


def cta_overlays(
    project: Project,
    segment_clips: Mapping[str, str],
    cta_segment_ids: Collection[str],
    language: str | None,
) -> list[Overlay]:
    """`cta` overlays for the flagged segments; `segment_clips` maps segment ids to clip ids."""
    by_id = {clip.id: clip for clip in project.clips}
    kept_ids: set[str] = set()
    for segment_id in cta_segment_ids:
        clip = by_id.get(segment_clips.get(segment_id, ""))
        kept = _kept_clip(clip, project.clips) if clip else None
        if kept is not None:
            kept_ids.add(kept.id)

    spans: list[tuple[str, int, int]] = []
    for placement in timeline_layout(project).clips:
        if placement.clip_id not in kept_ids or placement.duration_in_frames == 0:
            continue
        end = placement.start_frame + placement.duration_in_frames
        if spans and spans[-1][2] == placement.start_frame:
            spans[-1] = (spans[-1][0], spans[-1][1], end)
        else:
            spans.append((placement.clip_id, placement.start_frame, end))

    props = {"text": cta_text(language), "position": "bottom"}
    return [
        Overlay(
            id=f"cta-{clip_id}",
            template_id="cta",
            start_frame=start,
            end_frame=end,
            props=dict(props),
            auto_generated=True,
        )
        for clip_id, start, end in spans
    ]
