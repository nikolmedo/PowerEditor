"""Edited-timeline layout shared with the Remotion composition (`src/timeline.ts`).

Both sides must agree frame for frame; the shared fixture in
`packages/composition/test/fixtures/project.json` pins the contract.
"""

from powereditor.models import CamelModel, Clip, Project


class ClipPlacement(CamelModel):
    clip_id: str
    start_frame: int
    duration_in_frames: int
    source_start_frame: int


class TimelineLayout(CamelModel):
    duration_in_frames: int
    clips: list[ClipPlacement]


def clip_frames(clip: Clip, fps: int) -> int:
    """Timeline length of a clip in frames (Python's round(): ties to even)."""
    return round((clip.out_sec - clip.in_sec) / clip.speed * fps)


def timeline_layout(project: Project) -> TimelineLayout:
    """Back-to-back placement of every kept clip."""
    placements: list[ClipPlacement] = []
    offset = 0
    for clip in project.clips:
        if clip.removed:
            continue
        length = clip_frames(clip, project.fps)
        placements.append(
            ClipPlacement(
                clip_id=clip.id,
                start_frame=offset,
                duration_in_frames=length,
                source_start_frame=round(clip.in_sec * project.fps),
            )
        )
        offset += length
    return TimelineLayout(duration_in_frames=offset, clips=placements)
