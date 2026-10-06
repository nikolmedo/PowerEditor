from pathlib import Path

import numpy as np
import pytest

from powereditor.paths import AppPaths
from powereditor.pipeline.color_stats import measure_color, rgb_means
from powereditor.pipeline.loudness import SILENT_LUFS, measure_loudness, parse_integrated_lufs
from powereditor.pipeline.runner import ProjectLayout
from tests.media import FFMPEG, ffmpeg_lavfi, needs_ffmpeg

EBUR128_TAIL = """[Parsed_ebur128_0 @ 0x1] t: 1.9 TARGET:-23 LUFS M: -21.8 S: -21.8 I: -21.9 LUFS
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -18.4 LUFS
    Threshold: -28.4 LUFS
"""


def _layout(tmp_path: Path) -> ProjectLayout:
    layout = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    layout.ensure()
    return layout


def test_parse_integrated_lufs_reads_the_summary_value() -> None:
    assert parse_integrated_lufs(EBUR128_TAIL) == -18.4


@pytest.mark.parametrize("stderr", ["", "Integrated loudness:\n    I:         -inf LUFS\n"])
def test_parse_integrated_lufs_clamps_missing_or_infinite(stderr: str) -> None:
    assert parse_integrated_lufs(stderr) == SILENT_LUFS


def test_parse_integrated_lufs_clamps_below_floor() -> None:
    assert parse_integrated_lufs("Integrated loudness:\n    I:  -91.0 LUFS\n") == SILENT_LUFS


def test_rgb_means_normalizes_to_unit_range() -> None:
    pixels = np.array([[255, 0, 0], [255, 0, 0], [0, 0, 255], [0, 255, 0]], dtype=np.uint8)

    stats = rgb_means(pixels.tobytes())

    assert (stats.mean_r, stats.mean_g, stats.mean_b) == pytest.approx((0.5, 0.25, 0.25))
    expected_luma = 0.2126 * 0.5 + 0.7152 * 0.25 + 0.0722 * 0.25
    assert stats.mean_luma == pytest.approx(expected_luma)


def test_rgb_means_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        rgb_means(b"")


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_measure_loudness_tracks_gain_and_caches(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    assert FFMPEG is not None
    loud = ffmpeg_lavfi(tmp_path / "loud.wav", "-f", "lavfi", "-i", "sine=duration=3")
    quiet = ffmpeg_lavfi(
        tmp_path / "quiet.wav", "-f", "lavfi", "-i", "sine=duration=3,volume=-10dB"
    )

    loud_lufs = measure_loudness(layout, "a", loud, FFMPEG)
    quiet_lufs = measure_loudness(layout, "b", quiet, FFMPEG)

    assert -40.0 < loud_lufs < -5.0
    assert loud_lufs - quiet_lufs == pytest.approx(10.0, abs=0.5)
    assert layout.cache_file("loudness-a").is_file()
    assert measure_loudness(layout, "a", loud, FFMPEG) == loud_lufs


def test_measure_loudness_without_audio_is_silent(tmp_path: Path) -> None:
    assert measure_loudness(_layout(tmp_path), "a", None, "ffmpeg-not-needed") == SILENT_LUFS


@pytest.mark.ffmpeg
@needs_ffmpeg
@pytest.mark.parametrize(("color", "rgb"), [("red", (1, 0, 0)), ("0x0000FF", (0, 0, 1))])
def test_measure_color_samples_proxy_frames(
    tmp_path: Path, color: str, rgb: tuple[int, int, int]
) -> None:
    assert FFMPEG is not None
    video = ffmpeg_lavfi(
        tmp_path / f"{color}.mp4",
        "-f", "lavfi", "-i", f"color=c={color}:size=160x120:rate=30:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
    )  # fmt: skip

    stats = measure_color(_layout(tmp_path), color, video, 2.0, FFMPEG)

    assert (stats.mean_r, stats.mean_g, stats.mean_b) == pytest.approx(rgb, abs=0.06)
    assert 0.0 < stats.mean_luma < 0.35
