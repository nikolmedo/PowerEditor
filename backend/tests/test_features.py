import numpy as np
import pytest

from powereditor.models import Take, Word
from powereditor.pipeline.features import AudioClip, cluster_features, script_lines


def _take(index: int, text: str, start: float = 0.0, end: float = 2.0) -> Take:
    return Take(
        id=f"take-{index}",
        segment_id=f"seg-{index}",
        source_id="a",
        start=start,
        end=end,
        text=text,
    )


def test_cluster_features_measure_text_quality() -> None:
    takes = [
        _take(0, "Eh, hoy vamos a hablar de"),
        _take(1, "Hoy hoy vamos a ha- hablar de café, mmm, y de su historia."),
        _take(2, "Hoy vamos a hablar de café y de su historia."),
    ]

    features = cluster_features(takes, language="es")

    assert [f.take_id for f in features] == ["take-0", "take-1", "take-2"]
    assert [f.filler_count for f in features] == [1, 1, 0]
    assert [f.repetition_count for f in features] == [0, 2, 0]
    assert [f.cut_off for f in features] == [True, False, False]
    assert features[0].completeness == pytest.approx(5 / 10)
    assert features[2].completeness == 1.0
    assert [f.is_last_take for f in features] == [False, False, True]


def test_completeness_uses_the_best_matching_script_line() -> None:
    script = script_lines("Hola a todos.\nHoy vamos a hablar de café y de su historia. Empecemos.")
    takes = [
        _take(0, "Hoy vamos a hablar de café"),
        _take(1, "Hoy vamos a hablar de café y de su historia"),
    ]

    features = cluster_features(takes, language="es", script=script)

    assert script == ["Hola a todos.", "Hoy vamos a hablar de café y de su historia.", "Empecemos."]
    assert features[0].completeness == pytest.approx(6 / 10)
    assert features[1].completeness == 1.0


def test_speech_rate_and_mean_probability_come_from_words() -> None:
    words = [
        Word(text="hola", start=0.0, end=0.5, prob=0.9),
        Word(text="mundo", start=0.5, end=1.0, prob=0.7),
    ]
    take = _take(0, "hola mundo", start=0.0, end=1.0)

    with_words = cluster_features([take], language="es", words={"take-0": words})[0]
    without = cluster_features([take], language="es")[0]

    assert with_words.speech_rate_wps == pytest.approx(2.0)
    assert with_words.mean_word_prob == pytest.approx(0.8)
    assert without.mean_word_prob is None
    assert without.speech_rate_wps == pytest.approx(2.0)


def test_audio_features_report_level_and_clipping() -> None:
    rate = 1000
    quiet = np.full(rate, 0.1)
    loud = np.concatenate([np.full(rate // 2, 0.1), np.full(rate // 2, 1.0)])
    audio = {"a": AudioClip(samples=np.concatenate([quiet, loud]), rate=rate)}
    takes = [_take(0, "uno dos", 0.0, 1.0), _take(1, "uno dos", 1.0, 2.0)]

    features = cluster_features(takes, language="es", audio=audio)

    assert features[0].loudness_lufs == pytest.approx(-20.0, abs=0.01)
    assert (features[0].clipping, features[1].clipping) == (False, True)


class _FixedVisual:
    name = "fixed"

    def measure(self, take: Take) -> tuple[float | None, float | None]:
        return (0.9, 0.4)


def test_visual_features_come_from_the_extractor() -> None:
    features = cluster_features([_take(0, "hola")], language="es", visual=_FixedVisual())

    assert (features[0].face_centered, features[0].sharpness) == (0.9, 0.4)


def test_restarted_phrases_count_as_repetitions_not_extra_content() -> None:
    takes = [
        _take(0, "Write down the three things that matter most."),
        _take(1, "Write down the three, uh, the three things that, um, matter most."),
    ]

    features = cluster_features(takes, language="en")

    assert [f.repetition_count for f in features] == [0, 1]
    assert [f.completeness for f in features] == [1.0, 1.0]
