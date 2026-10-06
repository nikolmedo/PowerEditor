import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from powereditor.models import Project
from powereditor.pipeline.ffmpeg import run_capture, run_capture_bytes
from powereditor.render import audio_mix
from powereditor.render.audio_mix import (
    VoiceSegment,
    atempo_chain,
    batch_graph,
    build_voice_filtergraph,
    render_voice,
)
from tests.media import FFMPEG, FFPROBE, ffmpeg_lavfi, needs_ffmpeg

FIXTURE = (
    Path(__file__).parents[2] / "packages" / "composition" / "test" / "fixtures" / "project.json"
)
MEDIA = {"s1": Path("media/s1.mezzanine.mp4")}
RATE = 48000


def _fixture_project() -> Project:
    return Project.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8"))["project"])


def _project(clips: list[tuple[str, str, float, float, float]], fps: int = 30) -> Project:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))["project"]
    template = data["sources"][0]
    sources = sorted({clip[1] for clip in clips})
    data["fps"] = fps
    data["sources"] = [{**template, "id": sid, "mezzaninePath": f"{sid}.wav"} for sid in sources]
    clip_template = data["clips"][0]
    data["clips"] = [
        {**clip_template, "id": cid, "sourceId": sid, "inSec": start, "outSec": end, "speed": speed}
        for cid, sid, start, end, speed in clips
    ]
    return Project.model_validate(data)


# --- graph builder --------------------------------------------------------------------


def test_segments_follow_kept_clips_and_match_video_frames_exactly() -> None:
    graph = build_voice_filtergraph(_fixture_project(), 15, MEDIA)

    # c3 is removed and c4 is zero frames long; 1600 samples per frame at 30 fps.
    assert graph.segments == [
        VoiceSegment("c1", "s1", samples=34 * 1600, fade_samples=720),
        VoiceSegment("c2", "s1", samples=38 * 1600, fade_samples=720),
        VoiceSegment("c5", "s1", samples=88 * 1600, fade_samples=720),
    ]
    assert graph.total_samples == 160 * 1600
    assert graph.inputs == [MEDIA["s1"]] * 3
    assert graph.out_label == "voice"


def test_each_segment_is_trimmed_retimed_padded_and_faded_in_samples() -> None:
    graph = build_voice_filtergraph(_fixture_project(), 15, MEDIA)

    chains = graph.filter_complex.split(";")
    assert chains[2] == (
        "[2:a:0]atrim=start=7.1:end=9.3,asetpts=PTS-STARTPTS,atempo=0.75,"
        "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        "atrim=end_sample=140800,asetpts=N/SR/TB,volume=1,"
        "afade=t=in:ss=0:ns=720,afade=t=out:ss=140080:ns=720,apad=whole_len=140800[a2]"
    )
    # c2 holds 1.25 s of audio in a 38-frame (1.2667 s) slot: fade the audio, then pad.
    assert chains[1].endswith(
        "atrim=end_sample=60000,asetpts=N/SR/TB,volume=1,"
        "afade=t=in:ss=0:ns=720,afade=t=out:ss=59280:ns=720,apad=whole_len=60800[a1]"
    )
    assert chains[0].startswith("[0:a:0]atrim=start=0:end=1.15,asetpts=PTS-STARTPTS,aformat=")
    assert chains[-1] == "[a0][a1][a2]concat=n=3:v=0:a=1[voice]"


def test_sample_boundaries_are_cumulative_so_odd_rates_never_drift() -> None:
    # 44100 / 24 = 1837.5 samples per frame: rounding each clip alone would drift.
    project = _project([(f"c{i}", "s1", i, i + 1 / 24, 1.0) for i in range(5)], fps=24)

    graph = build_voice_filtergraph(project, 0, {"s1": Path("s1.wav")}, sample_rate=44100)

    assert [s.samples for s in graph.segments] == [1838, 1837, 1837, 1838, 1838]
    assert graph.total_samples == round(5 * 44100 / 24)


def test_fades_are_clamped_to_half_a_clip_and_disabled_at_zero() -> None:
    project = _project([("c1", "s1", 0.0, 0.1, 1.0)])

    long_fade = build_voice_filtergraph(project, 1000, {"s1": Path("s1.wav")})
    no_fade = build_voice_filtergraph(project, 0, {"s1": Path("s1.wav")})

    assert long_fade.segments[0].fade_samples == 4800 // 2
    assert "afade=t=out:ss=2400:ns=2400" in long_fade.filter_complex
    assert no_fade.segments[0].fade_samples == 0
    assert "afade" not in no_fade.filter_complex


def test_sources_without_audio_become_silence_of_the_clip_length() -> None:
    project = _project([("c1", "loud", 0.0, 1.0, 1.0), ("c2", "mute", 0.0, 0.5, 1.0)])
    media = {"loud": Path("loud.wav"), "mute": Path("mute.mp4")}

    graph = build_voice_filtergraph(project, 15, media, silent_sources={"mute"})

    assert graph.inputs == [Path("loud.wav")]
    assert graph.segments[1] == VoiceSegment("c2", None, samples=24000, fade_samples=0)
    assert graph.filter_complex.split(";")[1] == (
        "anullsrc=r=48000:cl=stereo,atrim=end_sample=24000,"
        "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,asetpts=N/SR/TB[a1]"
    )


def test_builder_rejects_an_empty_timeline_and_unknown_media() -> None:
    project = _project([("c1", "s1", 2.0, 2.0, 1.0)])
    with pytest.raises(ValueError, match="no audible clips"):
        build_voice_filtergraph(project, 15, {"s1": Path("s1.wav")})
    with pytest.raises(ValueError, match="s1"):
        build_voice_filtergraph(_project([("c1", "s1", 0.0, 1.0, 1.0)]), 15, {})


@pytest.mark.parametrize(
    ("speed", "stages"),
    [(1.0, []), (0.75, [0.75]), (2.0, [2.0]), (3.0, [2.0, 1.5]), (0.25, [0.5, 0.5])],
)
def test_atempo_chain_keeps_every_stage_in_range(speed: float, stages: list[float]) -> None:
    assert atempo_chain(speed) == stages


# --- rendering ------------------------------------------------------------------------


def _tone(path: Path, expression: str, seconds: float = 3.0) -> Path:
    return ffmpeg_lavfi(
        path,
        "-f", "lavfi", "-i", f"aevalsrc='{expression}':s={RATE}:d={seconds}",
        "-c:a", "pcm_s16le",
    )  # fmt: skip


def _decode_mono(path: Path) -> NDArray[np.int32]:
    assert FFMPEG is not None
    raw = run_capture_bytes(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-",
        ]
    )
    return np.frombuffer(raw, dtype="<i2").astype(np.int32)


def _cut_jump_ratio(samples: NDArray[np.int32], cut: int, window: int) -> float:
    """Largest sample step around a cut relative to the steady steps on either side."""
    deltas = np.abs(np.diff(samples))
    guard = window + 480
    before = deltas[cut - guard - 9600 : cut - guard]
    after = deltas[cut + guard : cut + guard + 9600]
    assert before.size == after.size == 9600
    steady = max(int(before.max()), int(after.max()))
    return float(deltas[cut - window : cut + window].max()) / steady


def _two_tone_cut(tmp_path: Path, crossfade_ms: int) -> tuple[NDArray[np.int32], list[int]]:
    assert FFMPEG is not None
    media = {
        "a": _tone(tmp_path / "a.wav", "0.5*sin(2*PI*330*t)"),
        "b": _tone(tmp_path / "b.wav", "0.5*sin(2*PI*523*t+1.3)"),
    }
    # Cut points away from zero crossings so a hard cut jumps; c1 and c2 last a fraction
    # of a frame less than their timeline slot, so their segments end in padding.
    project = _project(
        [("c1", "a", 0.2061, 0.6961, 1.0), ("c2", "b", 1.0, 1.52, 1.0), ("c3", "a", 0.5, 1.5, 1.0)]
    )
    graph = build_voice_filtergraph(project, crossfade_ms, media)
    voice = render_voice(FFMPEG, graph, tmp_path / f"voice{crossfade_ms}.wav")
    boundaries = list(np.cumsum([s.samples for s in graph.segments])[:-1])
    return _decode_mono(voice), [int(b) for b in boundaries]


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_rebuilt_voice_has_no_click_at_cuts(tmp_path: Path) -> None:
    samples, cuts = _two_tone_cut(tmp_path, crossfade_ms=15)

    assert len(cuts) == 2
    for cut in cuts:
        assert _cut_jump_ratio(samples, cut, window=960) <= 1.5


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_hard_cuts_without_fades_are_detected_as_clicks(tmp_path: Path) -> None:
    samples, cuts = _two_tone_cut(tmp_path, crossfade_ms=0)

    assert max(_cut_jump_ratio(samples, cut, window=960) for cut in cuts) > 3.0


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_rendered_voice_length_matches_the_timeline_with_speed_and_silence(
    tmp_path: Path,
) -> None:
    assert FFMPEG is not None and FFPROBE is not None
    tone = _tone(tmp_path / "a.wav", "0.5*sin(2*PI*330*t)")
    silent = ffmpeg_lavfi(
        tmp_path / "v.mp4",
        "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
    )  # fmt: skip
    # c2 asks for more source audio than exists (tone ends at 3 s): it must be padded.
    project = _project(
        [("c1", "a", 0.1, 1.0, 1.5), ("c2", "a", 2.5, 3.6, 1.0), ("c3", "v", 0.0, 0.7, 1.0)]
    )
    graph = build_voice_filtergraph(project, 15, {"a": tone, "v": silent}, silent_sources={"v"})

    voice = render_voice(FFMPEG, graph, tmp_path / "voice.wav")

    probe = run_capture(
        [FFPROBE, "-v", "error", "-count_packets", "-show_entries",
         "stream=sample_rate,channels,duration_ts", "-of", "json", str(voice)]
    )  # fmt: skip
    stream = json.loads(probe)["streams"][0]
    assert stream["sample_rate"] == "48000"
    assert stream["channels"] == 2
    assert int(stream["duration_ts"]) == graph.total_samples == (18 + 33 + 21) * 1600
    tail = _decode_mono(voice)[-(21 * 1600) :]
    assert int(np.abs(tail).max()) == 0


def test_batch_graph_renumbers_inputs_and_keeps_silence_without_inputs() -> None:
    project = _project([("c1", "s1", 0.0, 1.0, 1.0), ("c2", "mute", 0.0, 1.0, 1.0)] * 2)
    media = {"s1": Path("s1.wav"), "mute": Path("mute.mp4")}
    graph = build_voice_filtergraph(project, 15, media, silent_sources={"mute"})

    inputs, filter_complex = batch_graph(graph, 1, 4)

    assert inputs == [Path("s1.wav")]
    assert filter_complex.startswith("anullsrc=")
    assert "[0:a:0]" in filter_complex and "[1:a:0]" not in filter_complex
    assert filter_complex.endswith("[a0][a1][a2]concat=n=3:v=0:a=1[voice]")


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_many_clips_render_in_batches_with_exact_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert FFMPEG is not None and FFPROBE is not None
    monkeypatch.setattr(audio_mix, "BATCH_CLIPS", 3)
    tone = _tone(tmp_path / "a b's.wav", "0.5*sin(2*PI*330*t)")
    project = _project([(f"c{i}", "a", 0.1 * i, 0.1 * i + 0.3, 1.0) for i in range(8)])
    graph = build_voice_filtergraph(project, 15, {"a": tone})

    voice = render_voice(FFMPEG, graph, tmp_path / "voice.wav")

    probe = run_capture(
        [FFPROBE, "-v", "error", "-count_packets", "-show_entries",
         "stream=duration_ts", "-of", "json", str(voice)]
    )  # fmt: skip
    assert int(json.loads(probe)["streams"][0]["duration_ts"]) == graph.total_samples
    assert not list(tmp_path.glob(".voice-*"))
