import wave
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from powereditor.models import AudioTrack
from powereditor.pipeline.ffmpeg import run_capture_bytes, run_ffmpeg_stderr
from powereditor.pipeline.loudness import parse_integrated_lufs
from powereditor.render.final_pass import finalize_export
from powereditor.render.music_mix import build_mix_filtergraph, mix_args, render_mix
from tests.media import FFMPEG, ffmpeg_lavfi, needs_ffmpeg

RATE = 48000
MUSIC = AudioTrack(
    id="music", kind="music", source_path="song.mp3", volume=0.5, ducking_enabled=True
)


def test_music_is_looped_trimmed_faded_ducked_and_mixed_under_the_voice() -> None:
    graph = build_mix_filtergraph(MUSIC, [(1.0, 2.0)], total_samples=480000, sample_rate=RATE)

    music, mix = graph.split(";")
    assert music == (
        "[1:a:0]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        "asetpts=N/SR/TB,atrim=end_sample=480000,"
        "afade=t=in:ss=0:ns=48000,afade=t=out:ss=384000:ns=96000,"
        "asetnsamples=n=256:p=0,"
        "volume=volume='0.5*pow(10,-12*(clip((t-0.85)/0.15,0,1)*clip((2.4-t)/0.4,0,1))/20)'"
        ":eval=frame[music]"
    )
    assert mix == "[0:a:0][music]amix=inputs=2:duration=first:normalize=0[mix]"


def test_music_without_ducking_keeps_a_constant_volume() -> None:
    track = MUSIC.model_copy(update={"ducking_enabled": False})
    graph = build_mix_filtergraph(track, [(1.0, 2.0)], total_samples=480000, sample_rate=RATE)
    assert "volume=volume='0.5':eval=frame[music]" in graph


def test_short_timelines_shorten_the_music_fades() -> None:
    graph = build_mix_filtergraph(MUSIC, [], total_samples=48000, sample_rate=RATE)
    assert "afade=t=in:ss=0:ns=24000,afade=t=out:ss=24000:ns=24000" in graph


def test_mix_loops_the_music_input_and_writes_float_pcm() -> None:
    args = mix_args(Path("voice.wav"), Path("song.mp3"), Path("mix.txt"), Path("mix.wav"), RATE)
    assert args == [
        "-i", "voice.wav",
        "-stream_loop", "-1", "-i", "song.mp3",
        "-/filter_complex", "mix.txt",
        "-map", "[mix]", "-c:a", "pcm_f32le", "-ar", "48000",
        "mix.wav",
    ]  # fmt: skip


# --- rendering ------------------------------------------------------------------------

VOICE_HZ = 1000.0
MUSIC_HZ = 220.0
SPEECH = [(2.0, 3.0), (6.0, 7.0)]


def _write_voice(path: Path, seconds: float) -> Path:
    t = np.arange(round(seconds * RATE)) / RATE
    gate = np.zeros_like(t)
    for start, end in SPEECH:
        gate[(t >= start) & (t < end)] = 1.0
    tone = (0.3 * np.sin(2 * np.pi * VOICE_HZ * t) * gate * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(np.repeat(tone, 2).tobytes())
    return path


def _decode(path: Path) -> NDArray[np.float32]:
    assert FFMPEG is not None
    raw = run_capture_bytes(
        [FFMPEG, "-v", "error", "-i", str(path), "-ac", "1", "-f", "f32le", "pipe:1"]
    )
    return np.frombuffer(raw, dtype="<f4")


def _band_db(samples: NDArray[np.float32], start: float, end: float, hz: float) -> float:
    """Level of one sine component in a window, by correlation with that frequency."""
    window = samples[round(start * RATE) : round(end * RATE)].astype(np.float64)
    t = np.arange(len(window)) / RATE
    amplitude = 2 * abs(np.mean(window * np.exp(-2j * np.pi * hz * t)))
    return float(20 * np.log10(max(amplitude, 1e-9)))


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_rendered_mix_ducks_music_under_speech_with_exact_length(tmp_path: Path) -> None:
    seconds = 10.0
    voice = _write_voice(tmp_path / "voice.wav", seconds)
    # A 3 s file, so the 10 s timeline needs it looped.
    music = ffmpeg_lavfi(
        tmp_path / "song.wav",
        "-f", "lavfi", "-i", f"sine=frequency={MUSIC_HZ}:sample_rate={RATE}:duration=3",
    )  # fmt: skip
    total = round(seconds * RATE)

    output = render_mix(
        FFMPEG or "ffmpeg", voice, music, MUSIC, SPEECH, total, tmp_path / "mix.wav", RATE
    )

    mixed = _decode(output)
    assert len(mixed) == total
    gap = _band_db(mixed, 4.0, 5.0, MUSIC_HZ)
    speech = _band_db(mixed, 2.2, 2.8, MUSIC_HZ)
    looped = _band_db(mixed, 7.5, 7.95, MUSIC_HZ)
    assert gap - speech == pytest.approx(12.0, abs=1.0)
    assert looped == pytest.approx(gap, abs=1.0)
    voice_level = _band_db(_decode(voice), 2.2, 2.8, VOICE_HZ)
    assert _band_db(mixed, 2.2, 2.8, VOICE_HZ) == pytest.approx(voice_level, abs=0.5)

    video = ffmpeg_lavfi(
        tmp_path / "video.mp4",
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30:duration=10",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
    )  # fmt: skip
    final = tmp_path / "final.mp4"
    finalize_export(FFMPEG or "ffmpeg", video, output, final, -14.0, duration=seconds)
    stderr = run_ffmpeg_stderr(
        FFMPEG or "ffmpeg", ["-i", str(final), "-af", "ebur128=framelog=quiet", "-f", "null", "-"]
    )
    assert parse_integrated_lufs(stderr) == pytest.approx(-14.0, abs=1.0)


def test_timelines_too_short_for_fades_mix_without_them() -> None:
    graph = build_mix_filtergraph(MUSIC, [], total_samples=1, sample_rate=RATE)
    assert "afade" not in graph
    assert "atrim=end_sample=1," in graph


def test_an_empty_voice_cannot_be_mixed() -> None:
    with pytest.raises(ValueError, match="no samples"):
        build_mix_filtergraph(MUSIC, [], total_samples=0, sample_rate=RATE)
