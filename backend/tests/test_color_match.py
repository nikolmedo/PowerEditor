import pytest

from powereditor.models import ColorCorrection, ColorStats
from powereditor.pipeline.color_match import match_colors


def _stats(r: float, g: float, b: float) -> ColorStats:
    return ColorStats(mean_luma=0.2126 * r + 0.7152 * g + 0.0722 * b, mean_r=r, mean_g=g, mean_b=b)


def _gains(correction: ColorCorrection | None) -> tuple[float, float, float] | None:
    if correction is None:
        return None
    return (correction.red_gain, correction.green_gain, correction.blue_gain)


def test_sources_are_balanced_toward_the_project_mean() -> None:
    corrections = match_colors({"warm": _stats(0.6, 0.5, 0.4), "cool": _stats(0.4, 0.5, 0.6)})

    assert _gains(corrections["warm"]) == pytest.approx((0.8333, 1.0, 1.25))
    assert _gains(corrections["cool"]) == pytest.approx((1.25, 1.0, 0.8333))


def test_brightness_differences_are_matched_too_but_capped() -> None:
    corrections = match_colors({"dark": _stats(0.1, 0.1, 0.1), "bright": _stats(0.9, 0.9, 0.9)})

    assert _gains(corrections["dark"]) == pytest.approx((1.5, 1.5, 1.5))
    assert _gains(corrections["bright"]) == pytest.approx((0.6667, 0.6667, 0.6667))


def test_matching_sources_and_single_sources_need_no_correction() -> None:
    same = _stats(0.5, 0.45, 0.4)
    assert match_colors({"a": same, "b": same}) == {"a": None, "b": None}
    assert match_colors({"only": _stats(0.9, 0.2, 0.1)}) == {"only": None}
    assert match_colors({}) == {}


def test_tiny_differences_are_left_alone() -> None:
    corrections = match_colors({"a": _stats(0.500, 0.5, 0.5), "b": _stats(0.504, 0.5, 0.5)})
    assert corrections == {"a": None, "b": None}
