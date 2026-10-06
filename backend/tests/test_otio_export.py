"""NLE export through OpenTimelineIO (skipped without the optional `nle` extra)."""

from pathlib import Path

import pytest

from powereditor.export.otio_export import export_nle
from tests.test_subtitles import _project

otio = pytest.importorskip("opentimelineio")


def test_fcpxml_holds_the_kept_clips_in_source_frames(tmp_path: Path) -> None:
    output = export_nle(_project(), tmp_path / "edit.fcpxml")

    timeline = otio.adapters.read_from_file(str(output), adapter_name="fcpx_xml")
    ranges = [
        (c.source_range.start_time.value, c.source_range.duration.value)
        for c in timeline.find_clips()
    ]
    assert ranges == [(0, 34), (90, 30), (15, 60)]


def test_otio_keeps_the_clip_speed(tmp_path: Path) -> None:
    output = export_nle(_project(), tmp_path / "edit.otio")

    timeline = otio.adapters.read_from_file(str(output))
    speeds = [[e.time_scalar for e in c.effects] for c in timeline.find_clips()]
    assert speeds == [[], [1.5], []]


def test_unknown_file_type_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        export_nle(_project(), tmp_path / "edit.xml")
