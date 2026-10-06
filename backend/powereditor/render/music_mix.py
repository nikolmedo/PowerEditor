"""Mix a music track under the rebuilt voice.

The music input is looped (`-stream_loop -1`) and trimmed to exactly the voice's
length in samples, faded in and out, and ducked under speech with the deterministic
envelope of `render.ducking` (a `volume` expression of `t`, evaluated every 256
samples so the ramps stay smooth). `amix` with `normalize=0` adds it to the voice
unscaled and ends with the voice, so the mix keeps the voice's exact length; the
final pass then normalizes the mix to the target loudness.

The envelope expression grows with the number of speech intervals, so the graph goes
through a `-/filter_complex` script file like the voice graph does.
"""

from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from powereditor.models import AudioTrack
from powereditor.pipeline.ffmpeg import FractionCallback, run_ffmpeg
from powereditor.render.ducking import FADE_IN_S, FADE_OUT_S, Interval, ducking_expression

MIX_LABEL = "mix"
ENVELOPE_FRAME_SAMPLES = 256


def _num(value: float) -> str:
    return f"{value:.9g}"


def build_mix_filtergraph(
    track: AudioTrack, speech: Sequence[Interval], total_samples: int, sample_rate: int
) -> str:
    """Filtergraph mixing input 1 (the music) under input 0 (the voice).

    The fades share the timeline, each taking at most half of it; a timeline too short for
    a one-sample fade gets none (`afade` refuses zero samples).
    """
    if total_samples <= 0:
        raise ValueError("the voice has no samples to mix music under")
    fade_in = min(round(FADE_IN_S * sample_rate), total_samples // 2)
    fade_out = min(round(FADE_OUT_S * sample_rate), total_samples // 2)
    duck = ducking_expression(speech, track.ducking_db) if track.ducking_enabled else "1"
    gain = _num(track.volume) if duck == "1" else f"{_num(track.volume)}*{duck}"
    fades = [
        *([f"afade=t=in:ss=0:ns={fade_in}"] if fade_in > 0 else []),
        *([f"afade=t=out:ss={total_samples - fade_out}:ns={fade_out}"] if fade_out > 0 else []),
    ]
    music = ",".join(
        [
            f"aformat=sample_fmts=fltp:sample_rates={sample_rate}:channel_layouts=stereo",
            "asetpts=N/SR/TB",
            f"atrim=end_sample={total_samples}",
            *fades,
            f"asetnsamples=n={ENVELOPE_FRAME_SAMPLES}:p=0",
            f"volume=volume='{gain}':eval=frame",
        ]
    )
    return (
        f"[1:a:0]{music}[music];[0:a:0][music]amix=inputs=2:duration=first:normalize=0[{MIX_LABEL}]"
    )


def mix_args(voice: Path, music: Path, script: Path, output: Path, sample_rate: int) -> list[str]:
    return [
        "-i", str(voice),
        "-stream_loop", "-1", "-i", str(music),
        "-/filter_complex", str(script),
        "-map", f"[{MIX_LABEL}]", "-c:a", "pcm_f32le", "-ar", str(sample_rate),
        str(output),
    ]  # fmt: skip


def render_mix(
    ffmpeg: str,
    voice: Path,
    music: Path,
    track: AudioTrack,
    speech: Sequence[Interval],
    total_samples: int,
    output: Path,
    sample_rate: int,
    on_progress: FractionCallback | None = None,
) -> Path:
    """Write `voice` with `track`'s music mixed under it to `output` (32-bit float WAV)."""
    graph = build_mix_filtergraph(track, speech, total_samples, sample_rate)
    with TemporaryDirectory(prefix=".mix-", dir=output.parent) as tmp:
        script = Path(tmp, "mix.txt")
        script.write_bytes(graph.encode("utf-8"))
        run_ffmpeg(
            ffmpeg,
            mix_args(voice, music, script, output, sample_rate),
            duration=total_samples / sample_rate,
            on_progress=on_progress,
        )
    return output
