import hashlib
import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

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


def test_the_newest_version_tag_compares_versions_not_text() -> None:
    tags = ["v0.9.0", "v0.10.0", "v0.2.1", "nightly", "v1.0.0-rc.1"]

    assert release_notes.newest_version_tag(tags) == "v0.10.0"
    assert release_notes.newest_version_tag(["nightly"]) is None


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def tagged_repo(tmp_path: Path) -> Path:
    """v0.9.0 → v0.10.0 → a stray `nightly` tag → HEAD (the release being built)."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    for message, tags in [
        ("feat: first", ["v0.9.0"]),
        ("feat: second", ["v0.10.0"]),
        ("chore: nightly build", ["nightly"]),
        ("fix: third", ["v0.11.0"]),
    ]:
        _git(tmp_path, "commit", "-q", "--allow-empty", "-m", message)
        for tag in tags:
            _git(tmp_path, "tag", tag)
    return tmp_path


def test_the_previous_tag_is_the_newest_earlier_version(tagged_repo: Path) -> None:
    assert release_notes.previous_tag("v0.11.0", repo=tagged_repo) == "v0.10.0"
    assert release_notes.previous_tag("v0.10.0", repo=tagged_repo) == "v0.9.0"
    assert release_notes.previous_tag("v0.9.0", repo=tagged_repo) is None


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
