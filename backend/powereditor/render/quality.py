"""Export quality presets: how much the Remotion render and the final pass spend.

`standard` passes nothing, so it renders exactly as before the presets existed (Remotion's
own defaults: full resolution, CRF 18, its default x264 preset, JPEG frames at 80).
`draft` renders at half resolution with a fast, smaller encode for a quick look; `high`
spends more bits and encoder time. The final pass copies the video stream, so only its audio
bitrate follows the preset.
"""

from dataclasses import dataclass
from typing import Literal

RenderQuality = Literal["draft", "standard", "high"]


@dataclass(frozen=True)
class QualityProfile:
    audio_bitrate: str
    scale: float | None = None
    """Output size relative to the composition (Remotion `scale`)."""
    crf: int | None = None
    x264_preset: str | None = None
    jpeg_quality: int | None = None
    """Quality of the frames Chrome captures before encoding (Remotion `jpegQuality`)."""


QUALITY_PROFILES: dict[RenderQuality, QualityProfile] = {
    "draft": QualityProfile(
        audio_bitrate="128k", scale=0.5, crf=28, x264_preset="veryfast", jpeg_quality=60
    ),
    "standard": QualityProfile(audio_bitrate="192k"),
    "high": QualityProfile(audio_bitrate="256k", crf=15, x264_preset="slow", jpeg_quality=95),
}


def remotion_args(profile: QualityProfile) -> list[str]:
    """`render.mjs` flags for `profile`; unset values keep Remotion's defaults."""
    flags: list[tuple[str, object]] = [
        ("--scale", profile.scale),
        ("--crf", profile.crf),
        ("--x264-preset", profile.x264_preset),
        ("--jpeg-quality", profile.jpeg_quality),
    ]
    return [part for flag, value in flags if value is not None for part in (flag, str(value))]
