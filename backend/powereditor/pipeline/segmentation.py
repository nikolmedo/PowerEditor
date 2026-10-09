"""Split a source transcript into phrases using pauses, punctuation and VAD silences."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from powereditor.models import CamelModel, Segment, Word
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, no_progress, run_stage
from powereditor.pipeline.vad import Range

SEGMENT_STAGE_VERSION = 2
DEFAULT_PAUSE_S = 0.6
SENTENCE_END = (".", "?", "!", "…")


class SegmentList(CamelModel):
    segments: list[Segment]


@dataclass
class _Group:
    words: list[Word] = field(default_factory=list)
    floor_start: float = 0.0
    cap_end: float = float("inf")


def silences(speech: Sequence[Range], duration: float) -> list[Range]:
    """Complement of sorted speech ranges within [0, duration]."""
    gaps: list[Range] = []
    cursor = 0.0
    for start, end in speech:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        gaps.append((cursor, duration))
    return gaps


def _split_silence(prev: Word, word: Word, gaps: Sequence[Range], pause_s: float) -> Range | None:
    inside = [g for g in gaps if g[1] - g[0] >= pause_s and prev.start <= g[0] and g[1] <= word.end]
    return max(inside, key=lambda g: g[1] - g[0], default=None)


def _inside(t: float, speech: Sequence[Range]) -> bool:
    return any(start <= t <= end for start, end in speech)


def _trim(start: float, end: float, speech: Sequence[Range]) -> Range:
    if speech and not _inside(start, speech):
        later = [s for s, _ in speech if start < s < end]
        start = later[0] if later else start
    if speech and not _inside(end, speech):
        earlier = [e for _, e in speech if start < e < end]
        end = earlier[-1] if earlier else end
    return start, end


def _segment(source_id: str, index: int, start: float, end: float, words: list[Word]) -> Segment:
    text = " ".join(w.text for w in words)
    return Segment(
        id=f"seg-{source_id}-{index:04d}",
        source_id=source_id,
        start=start,
        end=end,
        text=text,
        words=words,
    )


def segment_words(
    source_id: str,
    words: Sequence[Word],
    speech: Sequence[Range],
    duration: float,
    pause_s: float = DEFAULT_PAUSE_S,
) -> list[Segment]:
    """Group words into phrases; split on pauses, sentence ends and long VAD silences.

    A phrase whose span, once trimmed to speech, overlaps none of its words is dropped:
    it would be a clip with nothing said in it. Ids keep the phrase's index either way.
    """
    gaps = silences(speech, duration)
    groups: list[_Group] = []
    for word in words:
        if not groups:
            groups.append(_Group(words=[word]))
            continue
        prev = groups[-1].words[-1]
        silence = _split_silence(prev, word, gaps, pause_s)
        if silence is not None:
            groups[-1].cap_end = silence[0]
            groups.append(_Group(words=[word], floor_start=silence[1]))
        elif word.start - prev.end >= pause_s or prev.text.endswith(SENTENCE_END):
            groups.append(_Group(words=[word]))
        else:
            groups[-1].words.append(word)
    segments: list[Segment] = []
    for index, group in enumerate(groups):
        first, last = group.words[0], group.words[-1]
        start = max(first.start, group.floor_start)
        end = max(min(last.end, group.cap_end), start)
        start, end = _trim(start, end, speech)
        if end > start and any(w.start < end and w.end > start for w in group.words):
            segments.append(_segment(source_id, index, start, end, group.words))
    return segments


def segments_from_speech(
    source_id: str, speech: Sequence[Range], pause_s: float = DEFAULT_PAUSE_S
) -> list[Segment]:
    """Word-less phrases straight from VAD, for sources without a transcript."""
    merged: list[Range] = []
    for start, end in speech:
        if merged and start - merged[-1][1] < pause_s:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return [_segment(source_id, i, s, e, []) for i, (s, e) in enumerate(merged)]


def segment_source(
    layout: ProjectLayout,
    source_id: str,
    words: Sequence[Word],
    speech: Sequence[Range],
    duration: float,
    *,
    pause_s: float = DEFAULT_PAUSE_S,
    progress: ProgressCallback = no_progress,
) -> list[Segment]:
    """Cached `segments-<id>` stage; falls back to VAD phrases when there are no words."""

    def compute() -> SegmentList:
        if words:
            return SegmentList(segments=segment_words(source_id, words, speech, duration, pause_s))
        return SegmentList(segments=segments_from_speech(source_id, speech, pause_s))

    params = {
        "words": [w.model_dump(mode="json") for w in words],
        "speech": [list(r) for r in speech],
        "duration": duration,
        "pauseS": pause_s,
    }
    result = run_stage(
        layout,
        f"segments-{source_id}",
        SEGMENT_STAGE_VERSION,
        [],
        params,
        SegmentList,
        compute,
        progress=progress,
    )
    return result.segments
