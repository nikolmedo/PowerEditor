"""Final pass over a rendered video: two-pass EBU R128 loudness normalization.

Pass one measures with `loudnorm`, pass two feeds the measurement back with
`linear=true` so the whole programme gets one gain instead of dynamic compression.
The video stream is copied untouched.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from powereditor.pipeline.ffmpeg import FractionCallback, run_ffmpeg, run_ffmpeg_stderr

TRUE_PEAK_DB = -1.0
LOUDNESS_RANGE = 11.0
OUTPUT_SAMPLE_RATE = "48000"
AUDIO_BITRATE = "192k"

_JSON_BLOCK = re.compile(r"\{[^{}]*\}")


@dataclass(frozen=True)
class LoudnormMeasurement:
    input_i: float
    input_tp: float
    input_lra: float
    input_thresh: float
    target_offset: float


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


def _loudnorm_target(target_lufs: float) -> str:
    return f"loudnorm=I={target_lufs}:TP={TRUE_PEAK_DB}:LRA={LOUDNESS_RANGE}"


def measure_args(source: Path, target_lufs: float) -> list[str]:
    target = _loudnorm_target(target_lufs)
    return ["-i", str(source), "-vn", "-af", f"{target}:print_format=json", "-f", "null", "-"]


def apply_loudnorm_args(
    source: Path, output: Path, measurement: LoudnormMeasurement, target_lufs: float
) -> list[str]:
    audio_filter = (
        f"{_loudnorm_target(target_lufs)}"
        f":measured_I={measurement.input_i}:measured_TP={measurement.input_tp}"
        f":measured_LRA={measurement.input_lra}:measured_thresh={measurement.input_thresh}"
        f":offset={measurement.target_offset}:linear=true:print_format=summary"
    )
    return [
        "-i", str(source),
        "-map", "0:v:0?", "-map", "0:a:0",
        "-c:v", "copy",
        "-af", audio_filter,
        # loudnorm resamples to 192 kHz internally; bring it back to a delivery rate.
        "-ar", OUTPUT_SAMPLE_RATE,
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-movflags", "+faststart",
        str(output),
    ]  # fmt: skip


def normalize_loudness(
    ffmpeg: str,
    source: Path,
    output: Path,
    target_lufs: float,
    duration: float | None = None,
    on_progress: FractionCallback | None = None,
) -> LoudnormMeasurement:
    """Write `source` to `output` with its audio normalized to `target_lufs`."""
    measurement = parse_loudnorm_json(run_ffmpeg_stderr(ffmpeg, measure_args(source, target_lufs)))
    run_ffmpeg(
        ffmpeg,
        apply_loudnorm_args(source, output, measurement, target_lufs),
        duration=duration,
        on_progress=on_progress,
    )
    return measurement
