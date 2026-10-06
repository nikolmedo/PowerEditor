import json
from pathlib import Path

from powereditor import schema_gen


def test_schema_uses_camel_case_and_named_definitions() -> None:
    schema = json.loads(schema_gen.render_schema())

    assert schema["title"] == "Project"
    assert "audioTracks" in schema["properties"]
    assert schema["additionalProperties"] is False
    clip = schema["$defs"]["Clip"]
    assert clip["properties"]["speed"] == {"maximum": 2.0, "minimum": 0.5, "type": "number"}
    assert "title" not in clip["properties"]["sourceId"]
    assert {"ColorGrade", "ColorGradeOverride", "TransitionIn"} <= set(schema["$defs"])


def test_render_schema_is_deterministic_with_trailing_newline() -> None:
    first = schema_gen.render_schema()

    assert first == schema_gen.render_schema()
    assert first.endswith("}\n")
    assert "\r" not in first


def test_write_then_check_passes(tmp_path: Path) -> None:
    target = tmp_path / "schema" / "project.schema.json"

    assert schema_gen.main(["--output", str(target)]) == 0
    assert schema_gen.main(["--output", str(target), "--check"]) == 0


def test_check_fails_when_file_is_stale_or_missing(tmp_path: Path) -> None:
    target = tmp_path / "project.schema.json"

    assert schema_gen.main(["--output", str(target), "--check"]) == 1

    target.write_bytes(b"{}\n")
    assert schema_gen.main(["--output", str(target), "--check"]) == 1
    assert target.read_bytes() == b"{}\n"


def test_default_output_points_at_composition_package() -> None:
    assert schema_gen.DEFAULT_OUTPUT.parts[-4:] == (
        "packages",
        "composition",
        "schema",
        "project.schema.json",
    )


def test_check_tolerates_crlf_checkout(tmp_path: Path) -> None:
    target = tmp_path / "project.schema.json"
    crlf = schema_gen.render_schema().replace(chr(10), chr(13) + chr(10))
    target.write_bytes(crlf.encode("utf-8"))

    assert schema_gen.main(["--output", str(target), "--check"]) == 0
