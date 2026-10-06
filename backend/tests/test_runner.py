import json
import os
from pathlib import Path

import pytest

from powereditor.models import CamelModel
from powereditor.paths import AppPaths
from powereditor.pipeline.runner import ProjectLayout, StageOutputError, run_stage


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


def test_run_stage_drops_cache_record_when_compute_crashes(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    output = layout.media_dir / "out.bin"
    attempts: list[str] = []

    def compute_ok() -> Doubled:
        attempts.append("ok")
        output.write_bytes(b"complete")
        return Doubled(value=1)

    def compute_crash() -> Doubled:
        attempts.append("crash")
        output.write_bytes(b"part")
        raise RuntimeError("boom")

    run_stage(layout, "s", 1, [], {}, Doubled, compute_ok, outputs=[output])
    output.unlink()
    with pytest.raises(RuntimeError):
        run_stage(layout, "s", 1, [], {}, Doubled, compute_crash, outputs=[output])

    assert not layout.cache_file("s").exists()
    assert run_stage(layout, "s", 1, [], {}, Doubled, compute_ok, outputs=[output]).value == 1
    assert attempts == ["ok", "crash", "ok"]


def test_run_stage_rejects_missing_or_empty_outputs_without_caching(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    output = layout.media_dir / "out.bin"

    def compute_empty() -> Doubled:
        output.write_bytes(b"")
        return Doubled(value=1)

    with pytest.raises(StageOutputError) as excinfo:
        run_stage(layout, "s", 1, [], {}, Doubled, compute_empty, outputs=[output])

    assert excinfo.value.code == "stage_output_missing"
    assert not layout.cache_file("s").exists()


def test_run_stage_outputs_can_depend_on_result(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    extra = layout.media_dir / "extra.bin"
    calls: list[int] = []

    def compute() -> Doubled:
        calls.append(1)
        extra.write_bytes(b"x")
        return Doubled(value=len(calls))

    def outputs(result: Doubled) -> list[Path]:
        return [extra] if result.value > 0 else []

    def run() -> Doubled:
        return run_stage(layout, "s", 1, [], {}, Doubled, compute, outputs=outputs)

    run()
    run()
    assert len(calls) == 1
    extra.unlink()
    run()
    assert len(calls) == 2


def test_run_stage_validator_failure_is_a_cache_miss(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    output = layout.media_dir / "out.bin"
    calls: list[int] = []

    def compute() -> Doubled:
        calls.append(1)
        output.write_bytes(b"good")
        return Doubled(value=1)

    def valid(_: Doubled) -> bool:
        return output.read_bytes() == b"good"

    def run() -> Doubled:
        return run_stage(layout, "s", 1, [], {}, Doubled, compute, outputs=[output], validate=valid)

    run()
    output.write_bytes(b"bad")
    run()
    assert len(calls) == 2
