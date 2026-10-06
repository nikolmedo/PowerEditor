"""Sample-accurate rebuild of the voice track from the edited timeline.

Remotion changes volume only at video-frame boundaries, so its audio clicks at
cuts. Renders therefore take video only from Remotion and rebuild the voice here
with one ffmpeg filtergraph: each kept clip is trimmed from its source, retimed,
padded or trimmed to exactly its timeline length, faded at both edges and
concatenated.

Duration contract: segment boundaries are the clip frame boundaries of
`timeline_layout` converted to samples cumulatively (`round(frame * rate / fps)`),
so the voice never drifts from the video, even when a frame is not a whole number
of samples. A clip's audio is trimmed to at most its slot, faded where it ends and
padded with silence up to the slot length (frame rounding can make the slot up to
half a frame longer than the audio). Edges get short fades to silence instead of
overlapping crossfades: an overlap would shorten the audio relative to the video.

Each clip reads its source as a separate ffmpeg input. A single input fanned out
with `asplit` would decode once, but every branch that concat has not reached yet
would queue its decoded audio in memory; repeated inputs cost decode time
(clips x source length, cheap for audio) and keep memory flat.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from powereditor.models import Project
from powereditor.pipeline.ffmpeg import FractionCallback, run_ffmpeg
from powereditor.timeline import timeline_layout

VOICE_LABEL = "voice"
DEFAULT_SAMPLE_RATE = 48000
ATEMPO_MIN = 0.5
ATEMPO_MAX = 2.0


@dataclass(frozen=True)
class VoiceSegment:
    clip_id: str
    source_id: str | None
    """None when the source has no audio and the segment is generated silence."""
    samples: int
    fade_samples: int


@dataclass(frozen=True)
class VoiceGraph:
    inputs: list[Path]
    filter_complex: str
    out_label: str
    segments: list[VoiceSegment]
    sample_rate: int

    @property
    def total_samples(self) -> int:
        return sum(segment.samples for segment in self.segments)

    @property
    def duration(self) -> float:
        return self.total_samples / self.sample_rate


def atempo_chain(speed: float) -> list[float]:
    """`atempo` factors whose product is `speed`, each within the filter's range."""
    stages: list[float] = []
    remaining = speed
    while remaining > ATEMPO_MAX:
        stages.append(ATEMPO_MAX)
        remaining /= ATEMPO_MAX
    while remaining < ATEMPO_MIN:
        stages.append(ATEMPO_MIN)
        remaining /= ATEMPO_MIN
    if abs(remaining - 1.0) > 1e-9:
        stages.append(remaining)
    return stages


def _num(value: float) -> str:
    return f"{value:.9g}"


def _frame_to_sample(frame: int, fps: int, sample_rate: int) -> int:
    return round(Fraction(frame * sample_rate, fps))


def _fade_filters(samples: int, fade: int) -> list[str]:
    if fade <= 0:
        return []
    return [f"afade=t=in:ss=0:ns={fade}", f"afade=t=out:ss={samples - fade}:ns={fade}"]


def build_voice_filtergraph(
    project: Project,
    crossfade_ms: int,
    media_paths: Mapping[str, Path],
    silent_sources: Collection[str] = (),
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> VoiceGraph:
    """ffmpeg inputs and `-filter_complex` that rebuild the voice of `project`.

    `media_paths` maps source ids to their mezzanine files; sources listed in
    `silent_sources` have no audio stream and contribute silence.
    """
    clips = {clip.id: clip for clip in project.clips}
    fmt = f"aformat=sample_fmts=fltp:sample_rates={sample_rate}:channel_layouts=stereo"
    fade_target = round(crossfade_ms * sample_rate / 1000)
    inputs: list[Path] = []
    segments: list[VoiceSegment] = []
    chains: list[str] = []
    for placement in timeline_layout(project).clips:
        if placement.duration_in_frames == 0:
            continue
        clip = clips[placement.clip_id]
        start = _frame_to_sample(placement.start_frame, project.fps, sample_rate)
        end_frame = placement.start_frame + placement.duration_in_frames
        samples = _frame_to_sample(end_frame, project.fps, sample_rate) - start
        label = f"a{len(segments)}"
        if clip.source_id in silent_sources:
            segments.append(VoiceSegment(clip.id, None, samples, 0))
            chains.append(
                f"anullsrc=r={sample_rate}:cl=stereo,atrim=end_sample={samples},"
                f"{fmt},asetpts=N/SR/TB[{label}]"
            )
            continue
        if clip.source_id not in media_paths:
            raise ValueError(f"no media file for source {clip.source_id}")
        # The clip's own audio can be a fraction of a frame shorter than its slot; fade
        # where that audio ends, not where the slot ends, then pad the rest with silence.
        content = min(samples, round((clip.out_sec - clip.in_sec) / clip.speed * sample_rate))
        fade = min(fade_target, content // 2)
        filters = [
            f"atrim=start={_num(clip.in_sec)}:end={_num(clip.out_sec)}",
            "asetpts=PTS-STARTPTS",
            *(f"atempo={_num(stage)}" for stage in atempo_chain(clip.speed)),
            fmt,
            f"atrim=end_sample={content}",
            "asetpts=N/SR/TB",
            f"volume={_num(clip.volume)}",
            *_fade_filters(content, fade),
            f"apad=whole_len={samples}",
        ]
        chains.append(f"[{len(inputs)}:a:0]{','.join(filters)}[{label}]")
        inputs.append(media_paths[clip.source_id])
        segments.append(VoiceSegment(clip.id, clip.source_id, samples, fade))
    if not segments:
        raise ValueError("the timeline has no audible clips")
    labels = "".join(f"[a{index}]" for index in range(len(segments)))
    chains.append(f"{labels}concat=n={len(segments)}:v=0:a=1[{VOICE_LABEL}]")
    return VoiceGraph(inputs, ";".join(chains), VOICE_LABEL, segments, sample_rate)


def voice_args(graph: VoiceGraph, output: Path) -> list[str]:
    """Render the voice to 32-bit float WAV so gains above 1.0 cannot clip before loudnorm."""
    args: list[str] = []
    for path in graph.inputs:
        args += ["-i", str(path)]
    return [
        *args,
        "-filter_complex", graph.filter_complex,
        "-map", f"[{graph.out_label}]",
        "-c:a", "pcm_f32le", "-ar", str(graph.sample_rate),
        str(output),
    ]  # fmt: skip


def render_voice(
    ffmpeg: str, graph: VoiceGraph, output: Path, on_progress: FractionCallback | None = None
) -> Path:
    run_ffmpeg(ffmpeg, voice_args(graph, output), duration=graph.duration, on_progress=on_progress)
    return output
