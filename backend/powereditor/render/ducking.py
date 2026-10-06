"""Music ducking under speech: a deterministic gain envelope from the timeline words.

Speech is where the edited timeline has words (`subtitles.words`), which are rebuilt
after every edit, so the Player preview and the render compute the same envelope from
the same data. The envelope is a ramp, not a compressor: the duck starts `ATTACK_S`
before a word and ends `RELEASE_S` after it, and words closer than those two together
merge into one interval so the music does not pump between words.

`packages/composition/src/audio/ducking.ts` mirrors these functions for the preview;
both are pinned by `packages/composition/test/fixtures/audio.json`.
"""

from collections.abc import Iterable, Sequence

from powereditor.models import Project

ATTACK_S = 0.15
RELEASE_S = 0.4
FADE_IN_S = 1.0
FADE_OUT_S = 2.0

Interval = tuple[float, float]


def _num(value: float) -> str:
    return f"{value:.9g}"


def speech_intervals(words: Iterable[tuple[int, int]], fps: int) -> list[Interval]:
    """Timeline seconds with speech: `(start_frame, end_frame)` words merged across short gaps."""
    merged: list[Interval] = []
    for start_frame, end_frame in sorted(words):
        start, end = start_frame / fps, end_frame / fps
        if merged and start - merged[-1][1] < ATTACK_S + RELEASE_S:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def project_speech(project: Project) -> list[Interval]:
    return speech_intervals(
        ((word.start_frame, word.end_frame) for word in project.subtitles.words), project.fps
    )


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, value))


def duck_fraction(t: float, intervals: Sequence[Interval]) -> float:
    """0 away from speech, 1 during it, with linear attack and release ramps."""
    return sum(
        _clip01((t - start + ATTACK_S) / ATTACK_S) * _clip01((end + RELEASE_S - t) / RELEASE_S)
        for start, end in intervals
    )


def fade_gain(t: float, duration: float) -> float:
    """Linear fade-in at the start and fade-out at the end, each at most half the length."""
    fade_in = min(FADE_IN_S, duration / 2)
    fade_out = min(FADE_OUT_S, duration / 2)
    gain_in = _clip01(t / fade_in) if fade_in > 0 else 1.0
    gain_out = _clip01((duration - t) / fade_out) if fade_out > 0 else 1.0
    return gain_in * gain_out


def music_gain(
    t: float, intervals: Sequence[Interval], *, volume: float, ducking_db: float, duration: float
) -> float:
    """Gain of a music track at `t` timeline seconds."""
    ducked = 10 ** (-ducking_db * duck_fraction(t, intervals) / 20)
    return volume * fade_gain(t, duration) * ducked


def ducking_expression(intervals: Sequence[Interval], ducking_db: float) -> str:
    """`duck_fraction` as an ffmpeg `volume` expression of `t`.

    Merged intervals are at least `ATTACK_S + RELEASE_S` apart, so their ramps never
    overlap and the sum of one product per interval stays within [0, 1].
    """
    if not intervals or ducking_db <= 0:
        return "1"
    terms = "+".join(
        f"clip((t-{_num(start - ATTACK_S)})/{_num(ATTACK_S)},0,1)"
        f"*clip(({_num(end + RELEASE_S)}-t)/{_num(RELEASE_S)},0,1)"
        for start, end in intervals
    )
    return f"pow(10,-{_num(ducking_db)}*({terms})/20)"
