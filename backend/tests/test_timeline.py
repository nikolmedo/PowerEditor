import json
from pathlib import Path

from powereditor.models import Project
from powereditor.timeline import timeline_layout

FIXTURE = (
    Path(__file__).parents[2] / "packages" / "composition" / "test" / "fixtures" / "project.json"
)


def test_layout_matches_the_shared_composition_fixture() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    project = Project.model_validate(fixture["project"])

    layout = timeline_layout(project)

    assert layout.model_dump(by_alias=True) == fixture["expected"]


def test_layout_skips_removed_clips_and_sums_kept_frames() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    project = Project.model_validate(fixture["project"])
    kept_first = project.model_copy(
        update={
            "clips": [
                clip.model_copy(update={"removed": clip.id != "c2"}) for clip in project.clips
            ]
        }
    )

    layout = timeline_layout(kept_first)

    assert layout.duration_in_frames == 38
    assert [placement.clip_id for placement in layout.clips] == ["c2"]
    assert layout.clips[0].start_frame == 0
