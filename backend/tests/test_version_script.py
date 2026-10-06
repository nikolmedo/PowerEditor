import importlib.util
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


version = _load("version")

FILES = {
    "VERSION": "1.2.3\n",
    "backend/pyproject.toml": (
        '[project]\nname = "powereditor"\nversion = "1.2.3"\n\n[tool.other]\nversion = "9.9.9"\n'
    ),
    "backend/powereditor/__init__.py": '"""Doc."""\n\n__version__ = "1.2.3"\n',
    "backend/uv.lock": (
        '[[package]]\nname = "httpx"\nversion = "0.28.1"\n\n'
        '[[package]]\nname = "powereditor"\nversion = "1.2.3"\nsource = { editable = "." }\n'
    ),
    "packages/composition/package.json": '{\n  "name": "c",\n  "version": "1.2.3"\n}\n',
    "web/package.json": '{\n  "name": "w",\n  "version": "1.2.3",\n  "x": {"version": "5"}\n}\n',
    "desktop/package.json": '{\n  "name": "d",\n  "version": "1.2.3"\n}\n',
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for name, text in FILES.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    return tmp_path


def test_a_consistent_repo_has_no_mismatches(repo: Path) -> None:
    assert version.read_version(repo) == "1.2.3"
    assert version.mismatches(repo) == []


def test_check_names_every_file_that_disagrees(repo: Path) -> None:
    web = repo / "web" / "package.json"
    web.write_bytes(web.read_bytes().replace(b'"version": "1.2.3"', b'"version": "1.2.4"'))
    (repo / "backend" / "powereditor" / "__init__.py").write_bytes(b'"""No version."""\n')

    assert version.mismatches(repo) == [
        "backend/powereditor/__init__.py: no version found",
        "web/package.json: 1.2.4 (expected 1.2.3)",
    ]


def test_set_updates_only_the_version_fields(repo: Path) -> None:
    version.set_version(repo, "2.0.10")

    assert version.read_version(repo) == "2.0.10"
    assert version.mismatches(repo) == []
    pyproject = (repo / "backend" / "pyproject.toml").read_text()
    assert 'version = "2.0.10"' in pyproject and 'version = "9.9.9"' in pyproject
    lock = (repo / "backend" / "uv.lock").read_text()
    assert 'name = "httpx"\nversion = "0.28.1"' in lock
    assert 'name = "powereditor"\nversion = "2.0.10"' in lock
    assert '"x": {"version": "5"}' in (repo / "web" / "package.json").read_text()


def test_set_keeps_windows_line_endings(repo: Path) -> None:
    init = repo / "backend" / "powereditor" / "__init__.py"
    init.write_bytes(b'"""Doc."""\r\n\r\n__version__ = "1.2.3"\r\n')

    version.set_version(repo, "1.3.0")

    assert init.read_bytes() == b'"""Doc."""\r\n\r\n__version__ = "1.3.0"\r\n'


@pytest.mark.parametrize("bad", ["1.2", "v1.2.3", "01.2.3", "1.2.3-beta", " 1.2.3"])
def test_set_refuses_a_version_that_is_not_plain_semver(repo: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="semver"):
        version.set_version(repo, bad)

    assert version.read_version(repo) == "1.2.3"


def test_a_failed_write_leaves_every_file_as_it_was(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = {name: (repo / name).read_bytes() for name in FILES}
    real_replace = version.os.replace
    calls = 0

    def replace_then_fail(source: str, target: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("disk full")
        real_replace(source, target)

    monkeypatch.setattr(version.os, "replace", replace_then_fail)

    with pytest.raises(OSError, match="disk full"):
        version.set_version(repo, "2.0.0")

    monkeypatch.undo()
    assert {name: (repo / name).read_bytes() for name in FILES} == before
    left = sorted(str(path.relative_to(repo)) for path in repo.rglob("*") if path.is_file())
    assert left == sorted(str(Path(name)) for name in FILES)


def test_set_writes_nothing_when_one_file_has_no_version(repo: Path) -> None:
    before = {name: (repo / name).read_bytes() for name in FILES}
    (repo / "desktop" / "package.json").write_bytes(b"{}\n")
    before["desktop/package.json"] = b"{}\n"

    with pytest.raises(ValueError, match=r"desktop/package.json: no version found"):
        version.set_version(repo, "2.0.0")

    assert {name: (repo / name).read_bytes() for name in FILES} == before


def test_check_command_compares_the_release_tag(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert version.main(["check", "--tag", "v1.2.3"], repo) == 0
    assert version.main(["check", "--tag", "v1.2.4"], repo) == 1
    assert "tag v1.2.4 does not match VERSION 1.2.3" in capsys.readouterr().err


def test_the_repository_versions_agree() -> None:
    assert version.mismatches(REPO_ROOT) == []
