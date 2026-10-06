import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic.json_schema import GenerateJsonSchema

from autocut.config import REPO_ROOT
from autocut.models import Project

DEFAULT_OUTPUT = REPO_ROOT / "packages" / "composition" / "schema" / "project.schema.json"


class _NoFieldTitles(GenerateJsonSchema):
    def field_title_should_be_set(self, schema: object) -> bool:
        return False


def render_schema() -> str:
    schema = Project.model_json_schema(by_alias=True, schema_generator=_NoFieldTitles)
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the Project JSON Schema.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args(argv)
    output: Path = args.output
    expected = render_schema().encode("utf-8")
    if args.check:
        on_disk = output.read_bytes().replace(b"\r\n", b"\n") if output.is_file() else None
        if on_disk != expected:
            print(f"{output} is stale; run `uv run python -m autocut.schema_gen`", file=sys.stderr)
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(expected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
