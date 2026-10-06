from dataclasses import replace
from pathlib import Path

import pytest

from powereditor.export.subtitles import remap_words
from powereditor.models import Clip, ColorStats, Segment, TransitionIn, Word, load_project
from powereditor.paths import AppPaths
from powereditor.pipeline.draft_builder import (
    PALETTE,
    DraftSource,
    build_draft,
    clip_bounds,
    write_draft,
)
from powereditor.pipeline.ingest import IngestedSource, ProbeResult
from powereditor.pipeline.runner import ProjectLayout


def _clip(clip_id: str, source_id: str, in_sec: float, out_sec: float, **extra: object) -> Clip:
    values: dict[str, object] = {
        "id": clip_id,
        "source_id": source_id,
        "in_sec": in_sec,
        "out_sec": out_sec,
        "speed": 1.0,
        "volume": 1.0,
        "transition_in": TransitionIn(type="cut", duration_frames=0),
        "alternative_take_ids": [],
        "removed": False,
    }
    values.update(extra)
    return Clip.model_validate(values)


def _word(text: str, start: float, end: float) -> Word:
    return Word(text=text, start=start, end=end)


def test_remap_words_offsets_by_kept_clips_and_speed() -> None:
    clips = [
        _clip("c1", "a", 1.0, 2.0),
        _clip("gone", "a", 2.5, 3.0, removed=True),
        _clip("c2", "b", 0.0, 2.0, speed=2.0),
        _clip("c3", "a", 4.0, 5.0),
    ]
    words = {
        "a": [_word("uno", 1.0, 1.5), _word("cut", 2.6, 2.9), _word("tres", 4.5, 4.9)],
        "b": [_word("dos", 1.0, 2.0)],
    }

    timeline = remap_words(clips, words, fps=30)

    assert [(w.text, w.start_frame, w.end_frame, w.clip_id) for w in timeline] == [
        ("uno", 0, 15, "c1"),
        ("dos", 45, 60, "c2"),
        ("tres", 75, 87, "c3"),
    ]


def test_remap_words_clamps_straddling_words_and_drops_outside() -> None:
    clips = [_clip("c1", "a", 1.0, 2.0)]
    words = {"a": [_word("pre", 0.0, 0.5), _word("edge", 1.8, 2.4), _word("late", 2.3, 2.6)]}

    timeline = remap_words(clips, words, fps=10)

    assert [(w.text, w.start_frame, w.end_frame) for w in timeline] == [("edge", 8, 10)]


def test_clip_bounds_pads_without_overlap() -> None:
    bounds = clip_bounds([(0.05, 1.0), (1.1, 2.0), (5.0, 6.0)], pad=0.12, duration=6.05)

    rounded = [(round(s, 3), round(e, 3)) for s, e in bounds]
    assert rounded == [(0.0, 1.1), (1.1, 2.12), (4.88, 6.05)]


def _ingested(source_id: str, width: int, height: int, audio: bool = True) -> IngestedSource:
    probe = ProbeResult(
        duration=6.0,
        width=width,
        height=height,
        rotation=0,
        r_frame_rate=30.0,
        avg_frame_rate=30.0,
        has_audio=audio,
        video_codec="h264",
        audio_codec="aac" if audio else None,
    )
    return IngestedSource(
        source_id=source_id,
        original_path=f"/in/{source_id}.mp4",
        probe=probe,
        fps=30,
        video_encoder="libx264",
        mezzanine_path=f"/m/{source_id}.mp4",
        proxy_path=f"/p/{source_id}.mp4",
        wav_path=f"/w/{source_id}.wav" if audio else None,
    )


def _segment(source_id: str, index: int, start: float, end: float, words: list[Word]) -> Segment:
    text = " ".join(w.text for w in words)
    return Segment(
        id=f"seg-{source_id}-{index}",
        source_id=source_id,
        start=start,
        end=end,
        text=text,
        words=words,
    )


def _draft_sources(width: int, height: int) -> list[DraftSource]:
    stats = ColorStats(mean_luma=0.5, mean_r=0.5, mean_g=0.5, mean_b=0.5)
    hola, chau = _word("hola", 1.0, 1.5), _word("chau", 4.0, 4.5)
    return [
        DraftSource(
            ingested=_ingested("a", width, height),
            segments=[_segment("a", 0, 1.0, 1.5, [hola]), _segment("a", 1, 4.0, 4.5, [chau])],
            words=[hola, chau],
            loudness_lufs=-18.0,
            color_stats=stats,
        ),
        DraftSource(
            ingested=_ingested("b", width, height, audio=False),
            segments=[_segment("b", 0, 0.0, 6.0, [])],
            words=[],
            loudness_lufs=-70.0,
            color_stats=stats,
        ),
    ]


def test_build_draft_creates_cut_only_timeline() -> None:
    project = build_draft(_draft_sources(1080, 1920), padding_s=0.1)

    assert project.preset == "reel_9x16"
    assert project.fps == 30
    assert [s.display_color for s in project.sources] == PALETTE[:2]
    assert [s.loudness_lufs for s in project.sources] == [-18.0, -70.0]
    assert [(c.id, c.source_id, c.in_sec, c.out_sec) for c in project.clips] == [
        ("clip-a-0000", "a", 0.9, 1.6),
        ("clip-a-0001", "a", 3.9, 4.6),
        ("clip-b-0000", "b", 0.0, 6.0),
    ]
    assert all(c.transition_in.type == "cut" and not c.removed for c in project.clips)
    assert [(w.text, w.start_frame, w.clip_id) for w in project.subtitles.words] == [
        ("hola", 3, "clip-a-0000"),
        ("chau", 24, "clip-a-0001"),
    ]
    assert [t.kind for t in project.audio_tracks] == ["voice"]
    assert project.overlays == []
    assert project.color_grade.preset == "natural"


def test_build_draft_matches_source_colors() -> None:
    sources = _draft_sources(1080, 1920)
    sources[0] = replace(
        sources[0], color_stats=ColorStats(mean_luma=0.5, mean_r=0.6, mean_g=0.5, mean_b=0.4)
    )

    project = build_draft(sources, padding_s=0.1)

    corrections = [source.color_correction for source in project.sources]
    assert [c.red_gain if c else None for c in corrections] == [0.9167, 1.1]


def test_build_draft_preset_follows_aspect_or_override() -> None:
    assert build_draft(_draft_sources(1920, 1080), padding_s=0.1).preset == "landscape_16x9"
    landscape = build_draft(_draft_sources(1920, 1080), padding_s=0.1, preset="reel_9x16")
    assert landscape.preset == "reel_9x16"


def test_build_draft_requires_sources() -> None:
    with pytest.raises(ValueError):
        build_draft([], padding_s=0.1)


def test_write_draft_round_trips(tmp_path: Path) -> None:
    layout = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    project = build_draft(_draft_sources(1080, 1920), padding_s=0.1)

    path = write_draft(layout, project)

    assert path == layout.project_file
    assert load_project(path) == project
