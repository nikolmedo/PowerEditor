"""Subtitles on the edited timeline: word remap, rebuilds after edits, text edits, lines.

Mirrored by `packages/composition/src/subtitles/` (`remapWords`, `groupLines`); the shared
fixture `packages/composition/test/fixtures/subtitles.json` pins both sides frame for frame.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from powereditor.models import Clip, Project, SourceWord, TimelineWord
from powereditor.timeline import clip_frames

# A pause at least this long between two words starts a new subtitle line.
LINE_PAUSE_SECONDS = 0.4
# A line stays on screen this long after its last word unless the next line starts first.
LINE_HOLD_SECONDS = 0.5
_SENTENCE_END = re.compile(r"[.!?…]$")


class TimedWord(Protocol):
    @property
    def text(self) -> str: ...
    @property
    def start(self) -> float: ...
    @property
    def end(self) -> float: ...


def _overlap(word: TimedWord, clip: Clip) -> float:
    return min(word.end, clip.out_sec) - max(word.start, clip.in_sec)


def _owner(word: TimedWord, clips: Sequence[Clip]) -> Clip | None:
    """The clip of the word's source that holds most of it (the first one on a tie)."""
    best: Clip | None = None
    best_overlap = 0.0
    for clip in clips:
        overlap = _overlap(word, clip)
        if overlap > best_overlap:
            best, best_overlap = clip, overlap
    return best


def remap_words(
    clips: Sequence[Clip], words_by_source: Mapping[str, Sequence[TimedWord]], fps: int
) -> list[TimelineWord]:
    """Source-time words → timeline frames, clamped to the clip that holds most of each word.

    Every clip of the word's source competes, removed ones included, so a word of a take
    that was not chosen is dropped instead of leaking into a neighbouring kept clip. Words
    that overlap no clip are dropped too. Frames use the timeline rounding contract.
    """
    owners: dict[tuple[str, int], str] = {}
    for source_id, words in words_by_source.items():
        candidates = [clip for clip in clips if clip.source_id == source_id]
        for index, word in enumerate(words):
            owner = _owner(word, candidates)
            if owner is not None and not owner.removed:
                owners[(source_id, index)] = owner.id
    timeline: list[TimelineWord] = []
    offset = 0
    for clip in clips:
        if clip.removed:
            continue
        length = clip_frames(clip, fps)
        for index, word in enumerate(words_by_source.get(clip.source_id, ())):
            if owners.get((clip.source_id, index)) != clip.id:
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
                    word_index=index,
                )
            )
        offset += length
    return timeline


def rebuild_subtitles(
    project: Project, words_by_source: Mapping[str, Sequence[SourceWord]] | None = None
) -> Project:
    """Recompute the timeline words after any clip edit (speed, trim, take switch, removal).

    `words_by_source` replaces the stored source words, for example after a new
    transcription; otherwise the project's own (possibly edited) source words are used.
    """
    source_words = (
        {key: list(words) for key, words in words_by_source.items()}
        if words_by_source is not None
        else project.subtitles.source_words
    )
    words = remap_words(project.clips, source_words, project.fps)
    subtitles = project.subtitles.model_copy(update={"words": words, "source_words": source_words})
    return project.model_copy(update={"subtitles": subtitles})


def retime_words(words: Sequence[SourceWord], text: str) -> list[SourceWord]:
    """Replace the words' texts with `text`, keeping their timing.

    With the same number of words each one keeps its own timing; otherwise the span from
    the first start to the last end is split in proportion to each new word's length.
    """
    tokens = text.split()
    if not words or not tokens:
        raise ValueError("an edit needs at least one word before and after")
    if len(tokens) == len(words):
        return [
            word.model_copy(update={"text": token})
            for word, token in zip(words, tokens, strict=True)
        ]
    span_start, span_end = words[0].start, words[-1].end
    total = sum(len(token) for token in tokens)
    edited: list[SourceWord] = []
    consumed = 0
    for token in tokens:
        start = span_start + (span_end - span_start) * consumed / total
        consumed += len(token)
        end = span_start + (span_end - span_start) * consumed / total
        edited.append(SourceWord(text=token, start=start, end=end))
    return edited


def edit_subtitle_text(project: Project, line: Sequence[TimelineWord], text: str) -> Project:
    """Apply a text edit to consecutive timeline words and rebuild the subtitles.

    The edit lands in the source words, so it survives every later rebuild.
    """
    clips = {clip.id: clip for clip in project.clips}
    sources = {clips[word.clip_id].source_id for word in line if word.clip_id in clips}
    indexes = [word.word_index for word in line]
    if len(sources) != 1 or None in indexes:
        raise ValueError("an edited line must come from one source")
    known = [index for index in indexes if index is not None]
    first, last = min(known), max(known)
    if sorted(known) != list(range(first, last + 1)):
        raise ValueError("an edited line must be consecutive words")
    source_id = sources.pop()
    stored = project.subtitles.source_words.get(source_id, [])
    if last >= len(stored):
        raise ValueError("the line does not match the stored source words")
    replaced = [*stored[:first], *retime_words(stored[first : last + 1], text), *stored[last + 1 :]]
    return rebuild_subtitles(project, {**project.subtitles.source_words, source_id: replaced})


@dataclass(frozen=True)
class SubtitleLine:
    words: list[TimelineWord]
    start_frame: int
    end_frame: int
    """Last frame on screen (exclusive): the hold after the last word, cut by the next line."""

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)


def _breaks_before(line: list[TimelineWord], word: TimelineWord, limit: int, pause: int) -> bool:
    previous = line[-1]
    return (
        len(line) >= limit
        or word.clip_id != previous.clip_id
        or word.start_frame - previous.end_frame >= pause
        or _SENTENCE_END.search(previous.text) is not None
    )


def group_lines(
    words: Sequence[TimelineWord],
    *,
    max_words_per_line: int,
    fps: int,
    duration_frames: int | None = None,
) -> list[SubtitleLine]:
    """Group timeline words into on-screen lines.

    A line ends at `max_words_per_line` words, at a cut between clips, at a pause of
    `LINE_PAUSE_SECONDS` and after sentence punctuation.
    """
    pause = round(LINE_PAUSE_SECONDS * fps)
    hold = round(LINE_HOLD_SECONDS * fps)
    groups: list[list[TimelineWord]] = []
    for word in words:
        if groups and not _breaks_before(groups[-1], word, max_words_per_line, pause):
            groups[-1].append(word)
        else:
            groups.append([word])
    lines: list[SubtitleLine] = []
    for index, group in enumerate(groups):
        end = group[-1].end_frame + hold
        if index + 1 < len(groups):
            end = min(end, groups[index + 1][0].start_frame)
        if duration_frames is not None:
            end = min(end, duration_frames)
        lines.append(SubtitleLine(group, group[0].start_frame, max(end, group[0].start_frame)))
    return lines
