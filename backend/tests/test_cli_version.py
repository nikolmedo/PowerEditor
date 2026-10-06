from importlib.metadata import version

from typer.testing import CliRunner

from powereditor import COPYRIGHT, cli
from powereditor.config import REPO_ROOT


def test_version_prints_name_version_and_copyright() -> None:
    result = CliRunner().invoke(cli.app, ["--version"])

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        f"PowerEditor {version('powereditor')}",
        "Copyright 2026 Nicolás Olmedo (https://nolmedo.dev)",
    ]


def test_copyright_matches_the_required_notice_in_license() -> None:
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert f"Required Notice: {COPYRIGHT}\n" in license_text
