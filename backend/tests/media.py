"""Shared synthetic media helpers for tests."""

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="ffmpeg/ffprobe not found"
)
SAMPLE_RATE = 16000
GATED_TONE = "sine=frequency=440:duration={seconds},volume='if(lt(mod(t,2),1),1,0)':eval=frame"


def write_wav(path: Path, samples: NDArray[np.float64], rate: int = SAMPLE_RATE) -> Path:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return path


def gated_tone(seconds: float, rate: int = SAMPLE_RATE) -> NDArray[np.float64]:
    """A 440 Hz tone that is on for the first second of every two seconds."""
    t = np.arange(int(seconds * rate)) / rate
    gate = (np.mod(t, 2.0) < 1.0).astype(np.float64)
    return 0.25 * np.sin(2 * np.pi * 440 * t) * gate


def ffmpeg_lavfi(output: Path, *inputs_and_args: str) -> Path:
    assert FFMPEG is not None
    subprocess.run([FFMPEG, "-v", "error", "-y", *inputs_and_args, str(output)], check=True)
    return output


def gated_tone_clip(output: Path, seconds: int, size: str = "320x240") -> Path:
    """A video with a gated tone: speech-like bursts in [2k, 2k+1) seconds."""
    return ffmpeg_lavfi(
        output,
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", GATED_TONE.format(seconds=seconds),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
    )  # fmt: skip
