import json
from pathlib import Path
from typing import Any

import pytest

from powereditor.render.ducking import (
    duck_fraction,
    ducking_expression,
    music_gain,
    speech_intervals,
)

FIXTURE: dict[str, Any] = json.loads(
    (
        Path(__file__).parents[2] / "packages" / "composition" / "test" / "fixtures" / "audio.json"
    ).read_text(encoding="utf-8")
)
WORDS = [(word["startFrame"], word["endFrame"]) for word in FIXTURE["words"]]
INTERVALS = [tuple(pair) for pair in FIXTURE["speechIntervals"]]
DURATION = FIXTURE["durationInFrames"] / FIXTURE["fps"]


def test_speech_merges_words_closer_than_a_release_and_attack() -> None:
    assert speech_intervals(WORDS, FIXTURE["fps"]) == INTERVALS


def test_speech_is_empty_without_words() -> None:
    assert speech_intervals([], 30) == []


@pytest.mark.parametrize(("t", "expected"), FIXTURE["duckFraction"])
def test_duck_fraction_ramps_before_and_after_speech(t: float, expected: float) -> None:
    assert duck_fraction(t, INTERVALS) == pytest.approx(expected)


@pytest.mark.parametrize(("t", "expected"), FIXTURE["musicGain"])
def test_music_gain_combines_volume_fades_and_ducking(t: float, expected: float) -> None:
    music = FIXTURE["music"]
    gain = music_gain(
        t, INTERVALS, volume=music["volume"], ducking_db=music["duckingDb"], duration=DURATION
    )
    assert gain == pytest.approx(expected, rel=1e-6)


def test_music_without_ducking_only_fades() -> None:
    assert music_gain(1.5, INTERVALS, volume=0.5, ducking_db=0.0, duration=DURATION) == 0.5


def test_ducking_expression_is_one_ramp_term_per_interval() -> None:
    expression = ducking_expression([(1.0, 2.0), (5.0, 6.0)], 12.0)
    assert expression == (
        "pow(10,-12*(clip((t-0.85)/0.15,0,1)*clip((2.4-t)/0.4,0,1)"
        "+clip((t-4.85)/0.15,0,1)*clip((6.4-t)/0.4,0,1))/20)"
    )


def test_ducking_expression_is_unity_without_speech() -> None:
    assert ducking_expression([], 12.0) == "1"
