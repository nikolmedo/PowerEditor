from pathlib import Path

import numpy as np
import pytest

from powereditor.paths import AppPaths
from powereditor.pipeline.runner import ProjectLayout
from powereditor.pipeline.vad import (
    EnergyDetector,
    SileroDetector,
    detect_voice,
    energy_dbfs,
    intersect_ranges,
    pad_and_merge,
    ranges_above_floor,
)
from tests.media import SAMPLE_RATE, gated_tone, write_wav


def test_pad_and_merge_pads_merges_and_clamps() -> None:
    ranges = [(0.05, 1.0), (1.1, 2.0), (3.0, 3.5), (9.8, 10.0)]

    merged = pad_and_merge(ranges, 0.1, 10.0)

    assert [(round(s, 3), round(e, 3)) for s, e in merged] == [(0.0, 2.1), (2.9, 3.6), (9.7, 10.0)]


def test_pad_and_merge_sorts_and_handles_empty() -> None:
    assert pad_and_merge([], 0.1, 5.0) == []
    assert pad_and_merge([(3.0, 4.0), (0.0, 1.0)], 0.0, 5.0) == [(0.0, 1.0), (3.0, 4.0)]


def test_intersect_ranges() -> None:
    a = [(0.0, 2.0), (3.0, 6.0)]
    b = [(1.0, 4.0), (5.0, 5.5), (7.0, 8.0)]

    assert intersect_ranges(a, b) == [(1.0, 2.0), (3.0, 4.0), (5.0, 5.5)]
    assert intersect_ranges(a, []) == []


def test_energy_dbfs_measures_rms_per_window() -> None:
    full_scale_square = np.where(np.arange(SAMPLE_RATE) % 2 == 0, 1.0, -1.0)
    silence = np.zeros(SAMPLE_RATE)

    levels = energy_dbfs(np.concatenate([full_scale_square, silence]), SAMPLE_RATE, 0.5)

    assert len(levels) == 4
    assert levels[0] == pytest.approx(0.0, abs=0.01)
    assert levels[3] < -100


def test_ranges_above_floor_bridges_short_gaps_and_drops_blips() -> None:
    levels = np.array([-80, -20, -20, -80, -20, -80, -80, -80, -20, -80], dtype=np.float64)

    ranges = ranges_above_floor(levels, 0.1, floor_dbfs=-45, min_gap_s=0.15, min_speech_s=0.15)

    assert [(round(s, 3), round(e, 3)) for s, e in ranges] == [(0.1, 0.5)]


def test_energy_detector_finds_tone_bursts() -> None:
    samples = gated_tone(6.0)

    ranges = EnergyDetector()(samples, SAMPLE_RATE)

    assert len(ranges) == 3
    for index, (start, end) in enumerate(ranges):
        assert start == pytest.approx(2 * index, abs=0.05)
        assert end == pytest.approx(2 * index + 1, abs=0.05)


def test_silero_detector_runs_bundled_model_and_ignores_non_speech() -> None:
    rng = np.random.default_rng(0)
    samples = np.concatenate([np.zeros(SAMPLE_RATE), 0.05 * rng.standard_normal(SAMPLE_RATE)])

    assert SileroDetector()(samples, SAMPLE_RATE) == []


def test_detect_voice_stage_is_cached_per_detector(tmp_path: Path) -> None:
    layout = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    layout.ensure()
    wav = write_wav(layout.media_dir / "src-a.wav", gated_tone(4.0))
    calls: list[str] = []

    class CountingDetector(EnergyDetector):
        def __call__(self, samples: np.ndarray, rate: int) -> list[tuple[float, float]]:
            calls.append(self.name)
            return super().__call__(samples, rate)

    first = detect_voice(layout, "src-a", wav, padding_ms=100, detector=CountingDetector())
    second = detect_voice(layout, "src-a", wav, padding_ms=100, detector=CountingDetector())
    detect_voice(layout, "src-a", wav, padding_ms=200, detector=CountingDetector())

    assert first == second
    assert len(calls) == 2
    assert first.duration == pytest.approx(4.0)
    assert [(round(r.start, 1), round(r.end, 1)) for r in first.speech] == [(0.0, 1.0), (2.0, 3.0)]
    assert [(round(r.start, 1), round(r.end, 1)) for r in first.padded] == [(0.0, 1.1), (1.9, 3.1)]
    assert layout.cache_file("vad-src-a").is_file()
