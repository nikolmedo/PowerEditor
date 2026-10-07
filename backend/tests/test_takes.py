from pathlib import Path

from powereditor.decide.heuristic import HeuristicEngine
from powereditor.models import ColorStats, Segment, Word
from powereditor.paths import AppPaths
from powereditor.pipeline.clustering import TextSimilarity
from powereditor.pipeline.draft_builder import DraftSource, build_draft
from powereditor.pipeline.runner import ProjectLayout
from powereditor.pipeline.takes import select_project_takes, select_takes
from tests.test_draft_builder import _ingested

LINES = [
    (0.0, "Hola a todos, hoy vamos a hablar de"),
    (3.0, "Corta, otra vez."),
    (5.0, "Hola a todos, hoy vamos a hablar de café."),
    (9.0, "El café llegó a Europa en el siglo diecisiete."),
    (13.0, "Eh, el café, eh, llegó a Europa en el siglo diecisiete."),
]


def _segments(source_id: str = "a", lines: list[tuple[float, str]] = LINES) -> list[Segment]:
    segments = []
    for index, (start, text) in enumerate(lines):
        step = 0.3
        words = [
            Word(text=word, start=start + i * step, end=start + (i + 1) * step)
            for i, word in enumerate(text.split())
        ]
        segments.append(
            Segment(
                id=f"seg-{source_id}-{index:04d}",
                source_id=source_id,
                start=start,
                end=words[-1].end,
                text=text,
                words=words,
            )
        )
    return segments


def test_select_takes_orders_entries_and_flags_alternatives() -> None:
    selection = select_takes(
        _segments(), HeuristicEngine(), TextSimilarity(language="es"), language="es"
    )

    entries = [(e.segment_id, e.take_group_id, e.removed) for e in selection.entries]
    assert entries == [
        ("seg-a-0000", "grp-a-0000", True),
        ("seg-a-0002", "grp-a-0000", False),
        ("seg-a-0001", None, True),
        ("seg-a-0003", "grp-a-0003", False),
        ("seg-a-0004", "grp-a-0003", True),
    ]
    chosen = selection.entries[1]
    assert chosen.alternative_segment_ids == ["seg-a-0000"]
    assert chosen.decision_confidence is not None and chosen.decision_confidence > 0.5
    assert [flag.is_audience_content for flag in selection.flags] == [True, False, True, True, True]
    assert {d.cluster_id: d.chosen_take_id for d in selection.decisions} == {
        "grp-a-0000": "take-a-0002",
        "grp-a-0003": "take-a-0003",
    }


def test_select_takes_removes_fragments_said_around_the_chosen_take() -> None:
    lines = [
        (0.0, "Me hubiera gustado saber esto antes de empezar a correr"),
        (4.0, "antes"),
        (5.0, "a correr"),
        (6.0, "Ojalá alguien me hubiera contado esto antes de empezar a correr"),
        (10.0, "Me hubiera"),
        (11.0, "El calzado es lo más importante cuando empezás a correr"),
    ]

    selection = select_takes(
        _segments(lines=lines), HeuristicEngine(), TextSimilarity(language="es"), language="es"
    )

    kept = [e.segment_id for e in selection.entries if not e.removed]
    assert len(kept) == 2
    assert kept[1] == "seg-a-0005"
    assert {e.take_group_id for e in selection.entries[:5]} == {"grp-a-0000"}


def test_build_draft_applies_take_entries() -> None:
    segments = _segments()
    words = [word for segment in segments for word in segment.words]
    ingested = _ingested("a", 1080, 1920)
    long_probe = ingested.probe.model_copy(update={"duration": 20.0})
    draft = DraftSource(
        ingested=ingested.model_copy(update={"probe": long_probe}),
        segments=segments,
        words=words,
        loudness_lufs=-18.0,
        color_stats=ColorStats(mean_luma=0.5, mean_r=0.5, mean_g=0.5, mean_b=0.5),
    )
    selection = select_takes(
        segments, HeuristicEngine(), TextSimilarity(language="es"), language="es"
    )

    project = build_draft([draft], padding_s=0.1, entries=selection.entries)

    clips = [(c.id, c.removed, c.take_group_id, c.alternative_take_ids) for c in project.clips]
    assert clips == [
        ("clip-a-0000", True, "grp-a-0000", []),
        ("clip-a-0002", False, "grp-a-0000", ["clip-a-0000"]),
        ("clip-a-0001", True, None, []),
        ("clip-a-0003", False, "grp-a-0003", ["clip-a-0004"]),
        ("clip-a-0004", True, "grp-a-0003", []),
    ]
    assert project.clips[1].decision_confidence == selection.entries[1].decision_confidence
    assert {w.clip_id for w in project.subtitles.words} == {"clip-a-0002", "clip-a-0003"}


class _CountingSimilarity(TextSimilarity):
    def __init__(self) -> None:
        super().__init__(language="es")
        self.calls = 0

    def __call__(self, first: str, second: str) -> float:
        self.calls += 1
        return super().__call__(first, second)


def test_select_project_takes_is_a_cached_stage(tmp_path: Path) -> None:
    layout = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    layout.ensure()
    similarity = _CountingSimilarity()

    first = select_project_takes(layout, _segments(), HeuristicEngine(), similarity, language="es")
    calls = similarity.calls
    second = select_project_takes(layout, _segments(), HeuristicEngine(), similarity, language="es")

    assert calls > 0
    assert similarity.calls == calls
    assert second == first
    assert layout.cache_file("takes").is_file()
