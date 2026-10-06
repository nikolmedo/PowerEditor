import json
import os
from pathlib import Path

import pytest

from autocut.models import CamelModel
from autocut.paths import AppPaths
from autocut.pipeline.runner import ProjectLayout, run_stage


class Doubled(CamelModel):
    value: int


def _layout(tmp_path: Path) -> ProjectLayout:
    layout = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    layout.ensure()
    return layout


def test_project_layout_creates_expected_dirs(tmp_path: Path) -> None:
    layout = _layout(tmp_path)

    assert layout.root == tmp_path / "projects" / "demo"
    assert layout.media_dir.is_dir()
    assert layout.cache_dir.is_dir()
    assert layout.project_file == layout.root / "project.json"
    assert layout.cache_file("ingest") == layout.cache_dir / "ingest.json"


@pytest.mark.parametrize("project_id", ["", "..", "a/b", "a\\b", "x:y"])
def test_project_layout_rejects_unsafe_ids(tmp_path: Path, project_id: str) -> None:
    with pytest.raises(ValueError):
        ProjectLayout.for_project(AppPaths(data_dir=tmp_path), project_id)


def test_run_stage_caches_until_inputs_or_params_change(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    source = tmp_path / "input.txt"
    source.write_text("21", encoding="utf-8")
    calls: list[int] = []

    def compute() -> Doubled:
        value = int(source.read_text(encoding="utf-8")) * 2
        calls.append(value)
        return Doubled(value=value)

    def run(params: dict[str, object]) -> Doubled:
        return run_stage(layout, "double", 1, [source], params, Doubled, compute)

    assert run({"factor": 2}).value == 42
    assert run({"factor": 2}).value == 42
    assert calls == [42]

    assert run({"factor": 3}).value == 42
    assert len(calls) == 2

    source.write_text("50", encoding="utf-8")
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert run({"factor": 3}).value == 100
    assert calls == [42, 42, 100]

    record = json.loads(layout.cache_file("double").read_text(encoding="utf-8"))
    assert record["result"] == {"value": 100}


def test_run_stage_recomputes_on_version_bump_missing_output_or_corrupt_cache(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    output = layout.media_dir / "out.bin"
    calls: list[str] = []

    def compute() -> Doubled:
        calls.append("run")
        output.write_bytes(b"x")
        return Doubled(value=len(calls))

    def run(version: int) -> Doubled:
        return run_stage(layout, "s", version, [], {}, Doubled, compute, outputs=[output])

    assert run(1).value == 1
    assert run(1).value == 1
    assert run(2).value == 2
    output.unlink()
    assert run(2).value == 3
    layout.cache_file("s").write_text("{broken", encoding="utf-8")
    assert run(2).value == 4
    assert run(2).value == 4


def test_run_stage_reports_progress_and_cache_hits(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    events: list[tuple[str, float, str]] = []

    def record(stage: str, fraction: float, message: str) -> None:
        events.append((stage, fraction, message))

    for _ in range(2):
        run_stage(layout, "s", 1, [], {}, Doubled, lambda: Doubled(value=1), progress=record)

    assert events == [("s", 0.0, "running"), ("s", 1.0, "done"), ("s", 1.0, "cached")]
