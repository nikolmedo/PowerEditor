"""Subtitle remap, rebuild after edits, text edits and line grouping."""

import json
from pathlib import Path
from typing import Any

import pytest

from powereditor.export.subtitles import (
    edit_subtitle_text,
    group_lines,
    rebuild_subtitles,
    remap_words,
    retime_words,
)
from powereditor.models import Project, SourceWord

FIXTURE = (
    Path(__file__).parents[2] / "packages" / "composition" / "test" / "fixtures" / "subtitles.json"
)


def _fixture() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def _project() -> Project:
    return Project.model_validate(_fixture()["project"])


def _words(project: Project) -> list[tuple[str, int, int, str]]:
    return [(w.text, w.start_frame, w.end_frame, w.clip_id) for w in project.subtitles.words]


def _with_clip(project: Project, clip_id: str, **update: Any) -> Project:
    clips = [c.model_copy(update=update) if c.id == clip_id else c for c in project.clips]
    return project.model_copy(update={"clips": clips})


def test_remap_matches_the_shared_fixture() -> None:
    project = _project()

    words = remap_words(project.clips, project.subtitles.source_words, project.fps)

    expected = _fixture()["expectedWords"]
    assert [w.model_dump(by_alias=True) for w in words] == expected


def test_lines_match_the_shared_fixture() -> None:
    project = rebuild_subtitles(_project())

    lines = group_lines(project.subtitles.words, max_words_per_line=3, fps=30, duration_frames=114)

    assert [(line.text, line.start_frame, line.end_frame) for line in lines] == [
        (line["text"], line["startFrame"], line["endFrame"]) for line in _fixture()["expectedLines"]
    ]


def test_rebuild_keeps_words_in_sync_after_a_speed_change() -> None:
    project = _with_clip(_project(), "c1", speed=1.5)

    rebuilt = rebuild_subtitles(project)

    # c1 shrinks from 34 to 23 frames; its words scale and everything after shifts by -11.
    assert _words(rebuilt)[:4] == [
        ("Hola", 2, 8, "c1"),
        ("a", 9, 11, "c1"),
        ("todos.", 12, 23, "c1"),
        ("Ahora", 23, 29, "c3"),
    ]
    assert _words(rebuilt)[-1] == ("aquí", 88, 97, "c4")


def test_rebuild_uses_the_new_take_after_switching_takes() -> None:
    project = _with_clip(_with_clip(_project(), "c3", removed=True), "c2", removed=False)

    rebuilt = rebuild_subtitles(project)

    texts = [w.text for w in rebuilt.subtitles.words if w.clip_id == "c2"]
    assert texts == ["corta", "uh"]
    assert all(w.clip_id != "c3" for w in rebuilt.subtitles.words)
    # c2 (30 frames at 1x) replaces c3 (20 frames), so the next clip starts 10 frames later.
    assert _words(rebuilt)[5] == ("Nuevo", 64, 76, "c4")


def test_rebuild_can_replace_the_stored_source_words() -> None:
    words = {"s2": [SourceWord(text="solo", start=1.0, end=1.2)]}

    rebuilt = rebuild_subtitles(_project(), words)

    assert _words(rebuilt) == [("solo", 69, 75, "c4")]
    assert rebuilt.subtitles.source_words == words


def test_retime_keeps_timing_when_the_word_count_is_unchanged() -> None:
    words = [SourceWord(text="ola", start=1.0, end=1.3), SourceWord(text="mundo", start=1.5, end=2)]

    edited = retime_words(words, "Hola mundo!")

    assert edited == [
        SourceWord(text="Hola", start=1.0, end=1.3),
        SourceWord(text="mundo!", start=1.5, end=2.0),
    ]


def test_retime_spreads_a_different_word_count_by_character_length() -> None:
    words = [SourceWord(text="porfavor", start=2.0, end=3.0)]

    edited = retime_words(words, "por favor ya")

    assert [w.text for w in edited] == ["por", "favor", "ya"]
    assert [(w.start, w.end) for w in edited] == [
        pytest.approx((2.0, 2.3)),
        pytest.approx((2.3, 2.8)),
        pytest.approx((2.8, 3.0)),
    ]


def test_retime_rejects_an_empty_edit_or_selection() -> None:
    with pytest.raises(ValueError):
        retime_words([SourceWord(text="a", start=0, end=1)], "   ")
    with pytest.raises(ValueError):
        retime_words([], "hola")


def test_text_edit_survives_later_rebuilds() -> None:
    project = rebuild_subtitles(_project())
    line = project.subtitles.words[3:6]  # "Ahora Esto va" from s1, word indexes 5..7

    edited = edit_subtitle_text(project, line, "Ahora esto vuela")
    rebuilt = rebuild_subtitles(_with_clip(edited, "c3", speed=1.0))

    assert [w.text for w in rebuilt.subtitles.words[3:6]] == ["Ahora", "esto", "vuela"]
    assert [w.text for w in edited.subtitles.source_words["s1"][5:8]] == ["Ahora", "esto", "vuela"]


def test_text_edit_needs_words_from_one_source() -> None:
    project = rebuild_subtitles(_project())

    with pytest.raises(ValueError):
        edit_subtitle_text(project, project.subtitles.words[5:7], "Mezcla")


def test_lines_break_on_word_limit() -> None:
    project = rebuild_subtitles(_project())

    lines = group_lines(project.subtitles.words, max_words_per_line=2, fps=30)

    assert [line.text for line in lines] == [
        "Hola a",
        "todos.",
        "Ahora Esto",
        "va",
        "Nuevo tema",
        "aquí",
    ]
    assert lines[-1].end_frame == 123
