"""Map source-time words onto the edited timeline."""

from collections.abc import Mapping, Sequence

from powereditor.models import Clip, TimelineWord, Word
from powereditor.timeline import clip_frames


def _overlap(word: Word, clip: Clip) -> float:
    return min(word.end, clip.out_sec) - max(word.start, clip.in_sec)


def remap_words(
    clips: Sequence[Clip], words_by_source: Mapping[str, Sequence[Word]], fps: int
) -> list[TimelineWord]:
    """Place each word in the kept clip it overlaps most, clamped to that clip, in frames.

    Words that overlap no kept clip of their source are dropped.
    """
    kept = [clip for clip in clips if not clip.removed]
    owner: dict[tuple[str, int], str] = {}
    for source_id, words in words_by_source.items():
        candidates = [clip for clip in kept if clip.source_id == source_id]
        for index, word in enumerate(words):
            best = max(candidates, key=lambda clip: _overlap(word, clip), default=None)
            if best is not None and _overlap(word, best) > 0:
                owner[(source_id, index)] = best.id
    timeline: list[TimelineWord] = []
    offset = 0
    for clip in kept:
        length = clip_frames(clip, fps)
        for index, word in enumerate(words_by_source.get(clip.source_id, ())):
            if owner.get((clip.source_id, index)) != clip.id:
                continue
            start = (max(word.start, clip.in_sec) - clip.in_sec) / clip.speed
            end = (min(word.end, clip.out_sec) - clip.in_sec) / clip.speed
            start_frame = offset + min(round(start * fps), length)
            end_frame = offset + min(round(end * fps), length)
            timeline.append(
                TimelineWord(
                    text=word.text,
                    start_frame=start_frame,
                    end_frame=max(end_frame, start_frame),
                    clip_id=clip.id,
                )
            )
        offset += length
    return timeline
