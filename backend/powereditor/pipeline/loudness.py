"""Integrated loudness (EBU R128) per source via ffmpeg's ebur128 filter."""

import math
import re
from pathlib import Path

from powereditor.models import CamelModel
from powereditor.pipeline.ffmpeg import run_ffmpeg_stderr
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, no_progress, run_stage

LOUDNESS_STAGE_VERSION = 1
SILENT_LUFS = -70.0

_INTEGRATED = re.compile(r"Integrated loudness:\s*\n\s*I:\s*(-?inf|-?[\d.]+)\s*LUFS")


class LoudnessResult(CamelModel):
    integrated_lufs: float


def parse_integrated_lufs(stderr: str) -> float:
    """Integrated loudness from the ebur128 summary, clamped to the -70 LUFS gate."""
    matches = _INTEGRATED.findall(stderr)
    if not matches:
        return SILENT_LUFS
    value = float(matches[-1])
    return SILENT_LUFS if not math.isfinite(value) else max(value, SILENT_LUFS)


def measure_loudness(
    layout: ProjectLayout,
    source_id: str,
    audio: Path | None,
    ffmpeg: str,
    progress: ProgressCallback = no_progress,
) -> float:
    """Integrated LUFS of `audio`; sources without audio are reported as silent."""
    if audio is None:
        return SILENT_LUFS

    def compute() -> LoudnessResult:
        args = ["-i", str(audio), "-af", "ebur128=framelog=quiet", "-f", "null", "-"]
        return LoudnessResult(
            integrated_lufs=parse_integrated_lufs(run_ffmpeg_stderr(ffmpeg, args))
        )

    result = run_stage(
        layout,
        f"loudness-{source_id}",
        LOUDNESS_STAGE_VERSION,
        [audio],
        {},
        LoudnessResult,
        compute,
        progress=progress,
    )
    return result.integrated_lufs
