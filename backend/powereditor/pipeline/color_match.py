"""Automatic color match between sources, from the mean color of each one.

Every source gets per-channel gains that move its mean red, green and blue to the
mean of all sources, which matches brightness (all three channels move together) and
white balance (they move apart) at once. Gains are capped so a very dark or tinted
source is helped, not blown out, and differences under `TOLERANCE` are left alone.
The means are measured on gamma-encoded frames and the gains apply to gamma-encoded
pixels in the composition, so the match is a first-order one, good for footage of
the same scene under different cameras or light.
"""

from collections.abc import Mapping

from powereditor.models import ColorCorrection, ColorStats

MAX_GAIN = 1.5
MIN_GAIN = 1 / MAX_GAIN
TOLERANCE = 0.01
"""Gains closer than this to 1 on every channel mean "no correction"."""
_FLOOR = 1e-3


def _gain(target: float, value: float) -> float:
    return round(min(MAX_GAIN, max(MIN_GAIN, target / max(value, _FLOOR))), 4)


def match_colors(stats: Mapping[str, ColorStats]) -> dict[str, ColorCorrection | None]:
    """Correction per source id toward the mean of all sources (None = leave as is)."""
    if len(stats) < 2:
        return dict.fromkeys(stats)
    count = len(stats)
    target = (
        sum(s.mean_r for s in stats.values()) / count,
        sum(s.mean_g for s in stats.values()) / count,
        sum(s.mean_b for s in stats.values()) / count,
    )
    corrections: dict[str, ColorCorrection | None] = {}
    for source_id, source in stats.items():
        gains = [
            _gain(goal, value)
            for goal, value in zip(
                target, (source.mean_r, source.mean_g, source.mean_b), strict=True
            )
        ]
        if all(abs(gain - 1.0) < TOLERANCE for gain in gains):
            corrections[source_id] = None
        else:
            red, green, blue = gains
            corrections[source_id] = ColorCorrection(red_gain=red, green_gain=green, blue_gain=blue)
    return corrections
