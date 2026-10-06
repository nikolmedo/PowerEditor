"""Default transitions: topic changes become fades or slides, cuts inside a block punch in."""

from powereditor.decide.heuristic import HeuristicEngine
from powereditor.models import ColorStats, Segment
from powereditor.pipeline.clustering import TextSimilarity
from powereditor.pipeline.draft_builder import DraftSource, build_draft
from powereditor.pipeline.takes import TakeEntry, select_takes
from tests.test_draft_builder import _ingested

COFFEE = "El café de especialidad necesita granos frescos y molienda justa antes de prepararlo."
COFFEE_MORE = "Los granos frescos del café cambian todo el sabor de la taza que preparamos."
TRAVEL = "Mañana viajamos hacia montañas nevadas buscando paisajes increíbles para filmar juntos."


def _segment(index: int, text: str, start: float, end: float, source_id: str = "a") -> Segment:
    return Segment(
        id=f"seg-{source_id}-{index:04d}",
        source_id=source_id,
        start=start,
        end=end,
        text=text,
        words=[],
    )


def test_a_long_pause_is_a_topic_change_with_a_fade() -> None:
    engine = HeuristicEngine()
    first, second = _segment(0, COFFEE, 0, 4), _segment(1, COFFEE_MORE, 6.5, 10)

    decision = engine.transition_between(first, second, pause_s=2.5)

    assert (decision.type, decision.topic_change) == ("fade", True)


def test_a_short_pause_inside_a_block_is_a_plain_cut() -> None:
    engine = HeuristicEngine()
    first, second = _segment(0, COFFEE, 0, 4), _segment(1, TRAVEL, 4.5, 8)

    decision = engine.transition_between(first, second, pause_s=0.5)

    assert (decision.type, decision.topic_change) == ("cut", False)


def test_a_lexical_shift_after_a_medium_pause_is_a_topic_change() -> None:
    engine = HeuristicEngine()

    shift = engine.transition_between(_segment(0, COFFEE, 0, 4), _segment(1, TRAVEL, 5.2, 9), 1.2)
    same = engine.transition_between(
        _segment(0, COFFEE, 0, 4), _segment(1, COFFEE_MORE, 5.2, 9), 1.2
    )

    assert (shift.type, shift.topic_change) == ("fade", True)
    assert (same.type, same.topic_change) == ("cut", False)


def test_a_new_source_file_starts_a_block_with_a_slide() -> None:
    decision = HeuristicEngine().transition_between(
        _segment(0, COFFEE, 0, 4), _segment(0, COFFEE_MORE, 0, 4, source_id="b")
    )

    assert (decision.type, decision.topic_change) == ("slide", True)


def _transitions(segments: list[Segment]) -> list[str]:
    selection = select_takes(
        segments, HeuristicEngine(), TextSimilarity(language="es"), language="es"
    )
    return [entry.transition for entry in selection.entries if not entry.removed]


def test_cuts_inside_a_block_alternate_punch_in_and_reset_after_a_topic_change() -> None:
    texts = [
        COFFEE,
        COFFEE_MORE,
        "La temperatura del agua debe rondar los noventa y dos grados siempre.",
        "Después dejamos reposar la mezcla durante treinta segundos exactos más.",
        TRAVEL,
        "Llevaremos cámaras livianas, trípodes pequeños y baterías cargadas extra.",
    ]
    starts = [0.0, 5.0, 10.0, 15.0, 23.0, 28.0]
    segments = [
        _segment(index, text, start, start + 4.5)
        for index, (text, start) in enumerate(zip(texts, starts, strict=True))
    ]

    assert _transitions(segments) == ["cut", "punch_in", "cut", "punch_in", "fade", "punch_in"]


def test_the_pause_skips_a_removed_retake_between_kept_segments() -> None:
    segments = [
        _segment(0, COFFEE, 0.0, 4.5),
        _segment(1, "Corta, otra vez.", 4.8, 5.8),
        _segment(2, COFFEE_MORE, 6.0, 10.5),
    ]

    # 1.5 s separate the kept segments, but only 0.2 s precede the second one.
    assert _transitions(segments) == ["cut", "punch_in"]


def test_draft_gives_fades_and_slides_a_duration_and_punch_ins_none() -> None:
    segments = [_segment(i, COFFEE, i * 1.4, i * 1.4 + 1.0) for i in range(4)]
    draft = DraftSource(
        ingested=_ingested("a", 1080, 1920),
        segments=segments,
        words=[],
        loudness_lufs=-18.0,
        color_stats=ColorStats(mean_luma=0.5, mean_r=0.5, mean_g=0.5, mean_b=0.5),
    )
    entries = [
        TakeEntry(segment_id=segments[0].id, removed=False),
        TakeEntry(segment_id=segments[1].id, removed=False, transition="punch_in"),
        TakeEntry(segment_id=segments[2].id, removed=False, transition="fade"),
        TakeEntry(segment_id=segments[3].id, removed=False, transition="slide"),
    ]

    project = build_draft([draft], padding_s=0.0, entries=entries)

    assert [(c.transition_in.type, c.transition_in.duration_frames) for c in project.clips] == [
        ("cut", 0),
        ("punch_in", 0),
        ("fade", 9),
        ("slide", 9),
    ]
