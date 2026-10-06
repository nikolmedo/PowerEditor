"""Final pass: mux the Remotion video with the rebuilt voice and normalize loudness.

Two-pass EBU R128: pass one measures the voice with `loudnorm`, pass two feeds the
measurement back with `linear=true` so the whole programme gets one gain instead
of dynamic compression. The video stream is copied untouched. A silent voice
(no measurable loudness) is muxed without normalization: there is nothing to
bring up and loudnorm cannot work from a -inf measurement.
"""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from powereditor.pipeline.ffmpeg import FractionCallback, run_ffmpeg, run_ffmpeg_stderr

TRUE_PEAK_DB = -1.0
LOUDNESS_RANGE = 11.0
OUTPUT_SAMPLE_RATE = "48000"
AUDIO_BITRATE = "192k"

# Below the EBU R128 absolute gate (-70 LUFS) integrated loudness is undefined.
SILENCE_FLOOR_LUFS = -70.0

_JSON_BLOCK = re.compile(r"\{[^{}]*\}")


@dataclass(frozen=True)
class LoudnormMeasurement:
    input_i: float
    input_tp: float
    input_lra: float
    input_thresh: float
    target_offset: float


@dataclass(frozen=True)
class FinalPassResult:
    measurement: LoudnormMeasurement
    normalized: bool


def parse_loudnorm_json(stderr: str) -> LoudnormMeasurement:
    """The measurement from the last JSON block `loudnorm=print_format=json` printed."""
    for block in reversed(_JSON_BLOCK.findall(stderr)):
        try:
            data = json.loads(block)
            return LoudnormMeasurement(
                input_i=float(data["input_i"]),
                input_tp=float(data["input_tp"]),
                input_lra=float(data["input_lra"]),
                input_thresh=float(data["input_thresh"]),
                target_offset=float(data["target_offset"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    raise ValueError("ffmpeg loudnorm printed no measurement")


def should_normalize(measurement: LoudnormMeasurement) -> bool:
    """False for silent or near-silent audio, which loudnorm cannot bring to a target."""
    return math.isfinite(measurement.input_i) and measurement.input_i > SILENCE_FLOOR_LUFS


def _loudnorm_target(target_lufs: float) -> str:
    return f"loudnorm=I={target_lufs}:TP={TRUE_PEAK_DB}:LRA={LOUDNESS_RANGE}"


def measure_args(source: Path, target_lufs: float) -> list[str]:
    target = _loudnorm_target(target_lufs)
    return ["-i", str(source), "-vn", "-af", f"{target}:print_format=json", "-f", "null", "-"]


def loudnorm_filter(measurement: LoudnormMeasurement, target_lufs: float) -> str:
    return (
        f"{_loudnorm_target(target_lufs)}"
        f":measured_I={measurement.input_i}:measured_TP={measurement.input_tp}"
        f":measured_LRA={measurement.input_lra}:measured_thresh={measurement.input_thresh}"
        f":offset={measurement.target_offset}:linear=true:print_format=summary"
    )


def mux_args(video: Path, voice: Path, output: Path, audio_filter: str | None) -> list[str]:
    """Copy the video of `video`, encode `voice` (optionally filtered) as AAC."""
    return [
        "-i", str(video), "-i", str(voice),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        *(["-af", audio_filter] if audio_filter else []),
        # loudnorm resamples to 192 kHz internally; bring it back to a delivery rate.
        "-ar", OUTPUT_SAMPLE_RATE,
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-movflags", "+faststart",
        str(output),
    ]  # fmt: skip


def finalize_export(
    ffmpeg: str,
    video: Path,
    voice: Path,
    output: Path,
    target_lufs: float,
    duration: float | None = None,
    on_progress: FractionCallback | None = None,
) -> FinalPassResult:
    """Write `output`: `video`'s picture plus `voice` normalized to `target_lufs`."""
    measurement = parse_loudnorm_json(run_ffmpeg_stderr(ffmpeg, measure_args(voice, target_lufs)))
    normalized = should_normalize(measurement)
    audio_filter = loudnorm_filter(measurement, target_lufs) if normalized else None
    run_ffmpeg(
        ffmpeg,
        mux_args(video, voice, output, audio_filter),
        duration=duration,
        on_progress=on_progress,
    )
    return FinalPassResult(measurement=measurement, normalized=normalized)
