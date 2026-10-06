"""Export quality presets and the RAM-aware render concurrency."""

import pytest

from powereditor.render.concurrency import (
    choose_concurrency,
    parse_meminfo_available_mb,
)
from powereditor.render.quality import QUALITY_PROFILES, remotion_args


def test_draft_renders_at_half_resolution_with_a_fast_encode() -> None:
    assert remotion_args(QUALITY_PROFILES["draft"]) == [
        "--scale", "0.5", "--crf", "28", "--x264-preset", "veryfast", "--jpeg-quality", "60",
    ]  # fmt: skip


def test_standard_keeps_remotion_defaults_and_high_spends_more_bits() -> None:
    assert remotion_args(QUALITY_PROFILES["standard"]) == []
    assert remotion_args(QUALITY_PROFILES["high"]) == [
        "--crf", "15", "--x264-preset", "slow", "--jpeg-quality", "95",
    ]  # fmt: skip


def test_quality_sets_the_export_audio_bitrate() -> None:
    bitrates = {name: profile.audio_bitrate for name, profile in QUALITY_PROFILES.items()}
    assert bitrates == {"draft": "128k", "standard": "192k", "high": "256k"}


@pytest.mark.parametrize(
    ("cpu_count", "available_mb", "frames", "expected"),
    [
        (12, 38_000, 238, 7),  # frames cap: 238 // 30
        (12, 38_000, 9000, 8),  # hard cap
        (12, 6_000, 9000, 1),  # 3000 MB of budget fits one 1536 MB browser
        (12, 12_400, 9000, 4),  # 6200 // 1536
        (4, 64_000, 9000, 2),  # leaves two cores to the system
        (2, 64_000, 9000, 1),  # never below one
        (12, None, 9000, 8),  # unknown RAM: the core and hard caps hold
        (12, 38_000, 10, 1),  # a few frames need one browser
    ],
)
def test_concurrency_is_the_smallest_of_cores_ram_frames_and_the_cap(
    cpu_count: int, available_mb: int | None, frames: int, expected: int
) -> None:
    assert choose_concurrency(cpu_count, available_mb, frames) == expected


def test_concurrency_override_wins_but_stays_in_range() -> None:
    assert choose_concurrency(12, 2_000, 100, override=6) == 6
    assert choose_concurrency(12, 2_000, 100, override=99) == 12  # never more than the cores
    assert choose_concurrency(12, 64_000, 9000, budget_mb=4096) == 7


def test_meminfo_reports_available_memory_in_megabytes() -> None:
    meminfo = "MemTotal:       16303428 kB\nMemFree:  1048576 kB\nMemAvailable:    8388608 kB\n"
    assert parse_meminfo_available_mb(meminfo) == 8192
    assert parse_meminfo_available_mb("MemTotal: 1 kB\n") is None
