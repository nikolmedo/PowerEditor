import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

from powereditor.config import REPO_ROOT


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_notes = _load("release_notes")
checksums = _load("checksums")


def test_notes_group_conventional_commits_and_skip_the_rest() -> None:
    subjects = [
        "feat(web): show an update banner",
        "fix: keep the window bounds",
        "chore: bump deps",
        "docs: explain releases",
        "feat!: drop the old project format",
        "Merge branch 'main'",
        "fix(desktop): verify the installer checksum",
    ]

    notes = release_notes.render_notes("0.2.0", subjects, previous_tag="v0.1.0")

    assert notes == (
        "## PowerEditor 0.2.0\n\n"
        "### Features\n\n"
        "- **web:** show an update banner\n"
        "- drop the old project format (breaking)\n\n"
        "### Fixes\n\n"
        "- keep the window bounds\n"
        "- **desktop:** verify the installer checksum\n\n"
        "### Docs\n\n"
        "- explain releases\n\n"
        "Changes since v0.1.0. Check the installer against `SHA256SUMS.txt`.\n"
    )


def test_notes_without_a_previous_tag_or_matching_commits() -> None:
    notes = release_notes.render_notes("0.1.0", ["chore: scaffold"], previous_tag=None)

    assert notes == (
        "## PowerEditor 0.1.0\n\n"
        "No feature, fix or documentation changes.\n\n"
        "First release. Check the installer against `SHA256SUMS.txt`.\n"
    )


def test_notes_read_the_git_log_of_this_repository() -> None:
    latest = release_notes.git("log", "-1", "--no-merges", "--format=%s", "HEAD")

    subjects = release_notes.commit_subjects(since=None, until="HEAD")

    assert latest in subjects  # holds on a shallow CI checkout too
    assert release_notes.commit_subjects(since="HEAD", until="HEAD") == []


def test_sha256sums_use_the_sha256sum_format(tmp_path: Path) -> None:
    installer = tmp_path / "PowerEditor-Setup-0.2.0-x64.exe"
    installer.write_bytes(b"installer")
    notices = tmp_path / "LICENSE"
    notices.write_bytes(b"license")

    text = checksums.sha256sums([installer, notices])

    assert text == (
        f"{hashlib.sha256(b'license').hexdigest()}  LICENSE\n"
        f"{hashlib.sha256(b'installer').hexdigest()}  PowerEditor-Setup-0.2.0-x64.exe\n"
    )
