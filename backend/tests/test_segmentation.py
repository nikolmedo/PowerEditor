from pathlib import Path

from powereditor.models import Segment, Word
from powereditor.paths import AppPaths
from powereditor.pipeline.runner import ProjectLayout
from powereditor.pipeline.segmentation import (
    segment_source,
    segment_words,
    segments_from_speech,
    silences,
)


def _words(*spec: tuple[str, float, float]) -> list[Word]:
    return [Word(text=text, start=start, end=end) for text, start, end in spec]


def _summary(segments: list[Segment]) -> list[tuple[str, float, float]]:
    return [(s.text, round(s.start, 2), round(s.end, 2)) for s in segments]


def test_silences_are_the_complement_of_speech() -> None:
    assert silences([(1.0, 2.0), (3.0, 4.0)], 5.0) == [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]
    assert silences([], 2.0) == [(0.0, 2.0)]
    assert silences([(0.0, 2.0)], 2.0) == []


def test_splits_on_long_pauses_between_words() -> None:
    words = _words(("hola", 0.0, 0.4), ("a", 0.5, 0.6), ("todos", 1.5, 2.0), ("hoy", 2.1, 2.4))

    segments = segment_words("src-a", words, [(0.0, 2.4)], 2.4, pause_s=0.6)

    assert _summary(segments) == [("hola a", 0.0, 0.6), ("todos hoy", 1.5, 2.4)]
    assert segments[0].id == "seg-src-a-0000"
    assert segments[1].id == "seg-src-a-0001"
    assert [w.text for w in segments[1].words] == ["todos", "hoy"]
    assert all(s.source_id == "src-a" for s in segments)


def test_splits_after_sentence_final_punctuation() -> None:
    words = _words(
        ("Listo.", 0.0, 0.4), ("¿Seguimos?", 0.5, 1.0), ("Sí", 1.1, 1.3), ("vamos", 1.4, 1.8)
    )

    segments = segment_words("s", words, [(0.0, 2.0)], 2.0, pause_s=0.6)

    assert [s.text for s in segments] == ["Listo.", "¿Seguimos?", "Sí vamos"]


def test_splits_on_internal_vad_silence_hidden_by_stretched_word_times() -> None:
    words = _words(("uno", 0.0, 1.9), ("dos", 2.0, 2.5))
    speech = [(0.0, 0.5), (1.8, 2.5)]

    segments = segment_words("s", words, speech, 2.5, pause_s=0.6)

    assert _summary(segments) == [("uno", 0.0, 0.5), ("dos", 2.0, 2.5)]


def test_trims_segment_bounds_to_speech() -> None:
    words = _words(("hola", 0.2, 1.0), ("mundo", 1.1, 1.6))

    segments = segment_words("s", words, [(0.5, 1.4)], 3.0, pause_s=0.6)

    assert _summary(segments) == [("hola mundo", 0.5, 1.4)]


def test_drops_a_segment_whose_trimmed_span_holds_none_of_its_words() -> None:
    words = _words(("uno", 0.0, 0.5), ("dos", 0.5, 4.0), ("tres", 4.0, 4.5))

    segments = segment_words("s", words, [(0.0, 0.5), (4.0, 4.5)], 5.0, pause_s=0.6)

    assert _summary(segments) == [("uno", 0.0, 0.5), ("tres", 4.0, 4.5)]
    assert [s.id for s in segments] == ["seg-s-0000", "seg-s-0002"]


def test_drops_a_zero_length_span_inside_a_stretched_word() -> None:
    words = _words(("uno", 0.0, 0.5), ("dos", 0.5, 4.0), ("tres", 4.0, 4.5))
    speech = [(0.0, 0.5), (2.0, 2.0), (4.0, 4.5)]

    segments = segment_words("s", words, speech, 5.0, pause_s=0.6)

    assert [s.text for s in segments] == ["uno", "tres"]


def test_segment_outside_any_speech_keeps_word_bounds() -> None:
    words = _words(("eco", 2.0, 2.5))

    segments = segment_words("s", words, [(0.0, 1.0)], 3.0, pause_s=0.6)

    assert _summary(segments) == [("eco", 2.0, 2.5)]


def test_segments_from_speech_without_words_merges_short_gaps() -> None:
    segments = segments_from_speech("s", [(0.0, 1.0), (1.2, 2.0), (3.0, 4.0)], pause_s=0.6)

    assert _summary(segments) == [("", 0.0, 2.0), ("", 3.0, 4.0)]
    assert all(s.words == [] for s in segments)


def test_segment_source_stage_is_cached(tmp_path: Path) -> None:
    layout = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    layout.ensure()
    words = _words(("uno", 0.0, 0.5), ("dos", 2.0, 2.5))

    first = segment_source(layout, "s", words, [(0.0, 0.5), (2.0, 2.5)], 3.0, pause_s=0.6)
    again = segment_source(layout, "s", words, [(0.0, 0.5), (2.0, 2.5)], 3.0, pause_s=0.6)

    assert first == again
    assert [s.text for s in first] == ["uno", "dos"]
    assert layout.cache_file("segments-s").is_file()
