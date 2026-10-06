"""Mean color of a source, sampled from a few downscaled proxy frames."""

from pathlib import Path

import numpy as np

from powereditor.models import ColorStats
from powereditor.pipeline.ffmpeg import run_capture_bytes
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, no_progress, run_stage

COLOR_STAGE_VERSION = 1
SAMPLE_FRAMES = 8
SAMPLE_WIDTH = 64
REC709 = (0.2126, 0.7152, 0.0722)


def rgb_means(raw_rgb24: bytes) -> ColorStats:
    """Channel means and Rec. 709 luma of packed RGB24 pixels, all in [0, 1]."""
    if len(raw_rgb24) < 3:
        raise ValueError("no pixels to measure")
    usable = len(raw_rgb24) - len(raw_rgb24) % 3
    pixels = np.frombuffer(raw_rgb24[:usable], dtype=np.uint8).reshape(-1, 3)
    r, g, b = (float(v) for v in pixels.mean(axis=0) / 255.0)
    luma = REC709[0] * r + REC709[1] * g + REC709[2] * b
    return ColorStats(mean_luma=luma, mean_r=r, mean_g=g, mean_b=b)


def measure_color(
    layout: ProjectLayout,
    source_id: str,
    video: Path,
    duration: float,
    ffmpeg: str,
    progress: ProgressCallback = no_progress,
) -> ColorStats:
    """Evenly sample `SAMPLE_FRAMES` frames of `video`; cached as `color-<id>`."""

    def compute() -> ColorStats:
        rate = f"{SAMPLE_FRAMES}/{duration:.3f}" if duration > 0 else "1"
        args = [
            ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
            "-i", str(video),
            "-vf", f"fps={rate},scale={SAMPLE_WIDTH}:-2",
            "-frames:v", str(SAMPLE_FRAMES),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ]  # fmt: skip
        return rgb_means(run_capture_bytes(args))

    params = {"frames": SAMPLE_FRAMES, "width": SAMPLE_WIDTH}
    return run_stage(
        layout,
        f"color-{source_id}",
        COLOR_STAGE_VERSION,
        [video],
        params,
        ColorStats,
        compute,
        progress=progress,
    )
