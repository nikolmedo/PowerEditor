from pathlib import Path

import pytest

from powereditor.config import REPO_ROOT
from powereditor.resources import (
    ENV_COMPOSITION_DIR,
    ENV_WEB_DIR,
    Resources,
    resolve_tool,
    tool_candidates,
)
from powereditor.runtime.manifest import RuntimeDownload


def _file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _frozen(tmp_path: Path) -> Resources:
    """A onedir build: `PowerEditor/powereditor.exe` with its files in `_internal/`."""
    app = tmp_path / "PowerEditor"
    return Resources(frozen=True, bundle_dir=app / "_internal", executable=app / "powereditor.exe")


def _source(tmp_path: Path) -> Resources:
    return Resources(frozen=False, bundle_dir=tmp_path / "backend", executable=tmp_path / "py.exe")


def test_current_reads_the_frozen_state_of_the_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path / "_internal"), raising=False)
    monkeypatch.setattr("sys.executable", str(tmp_path / "powereditor.exe"))

    resources = Resources.current()

    assert resources == Resources(
        frozen=True, bundle_dir=tmp_path / "_internal", executable=tmp_path / "powereditor.exe"
    )
    assert resources.runtime_dir == tmp_path / "runtime"


def test_from_source_the_bundle_dir_holds_the_package_and_there_is_no_runtime_dir() -> None:
    resources = Resources.current()

    assert not resources.frozen
    assert (resources.bundle_dir / "powereditor" / "resources.py").is_file()
    assert resources.runtime_dir is None


def test_web_dir_prefers_env_then_bundled_build_then_repo_dist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resources = _frozen(tmp_path)
    monkeypatch.delenv(ENV_WEB_DIR, raising=False)
    assert resources.web_dir() == REPO_ROOT / "web" / "dist"

    bundled = _file(tmp_path / "PowerEditor" / "_internal" / "powereditor" / "web" / "index.html")
    assert resources.web_dir() == bundled.parent

    monkeypatch.setenv(ENV_WEB_DIR, str(tmp_path / "custom"))
    assert resources.web_dir() == tmp_path / "custom"


def test_composition_dir_is_bundled_when_frozen_and_the_package_from_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_COMPOSITION_DIR, raising=False)
    assert _frozen(tmp_path).composition_dir() == tmp_path / "PowerEditor/_internal/composition"
    assert _source(tmp_path).composition_dir() == REPO_ROOT / "packages" / "composition"

    monkeypatch.setenv(ENV_COMPOSITION_DIR, str(tmp_path / "comp"))
    assert _source(tmp_path).composition_dir() == tmp_path / "comp"


def test_prebuilt_bundle_is_used_only_when_its_index_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_COMPOSITION_DIR, str(tmp_path / "comp"))
    resources = _source(tmp_path)
    assert resources.prebuilt_bundle() is None

    index = _file(tmp_path / "comp" / "dist" / "bundle" / "index.html")
    assert resources.prebuilt_bundle() == index.parent


SPEC = RuntimeDownload(
    name="ffmpeg",
    version="8.1.3",
    url="https://example.invalid/ffmpeg.zip",
    sha256="0" * 64,
    size=1,
    tools={"ffmpeg": "bin/ffmpeg.exe"},
)


def test_tools_resolve_configured_then_downloaded_then_bundled_then_path(tmp_path: Path) -> None:
    bin_dir = tmp_path / "data" / "bin"
    runtime_dir = tmp_path / "app" / "runtime"

    def resolve(configured: str | None = None) -> str | None:
        return resolve_tool(
            "ffmpeg",
            configured,
            bin_dir,
            runtime_dir,
            which=lambda name: f"/usr/bin/{name}",
            downloads=(SPEC,),
        )

    assert resolve() == "/usr/bin/ffmpeg"
    bundled = _file(runtime_dir / "ffmpeg.exe")
    assert resolve() == str(bundled)
    legacy = _file(bin_dir / "ffmpeg.exe")
    assert resolve() == str(legacy)
    downloaded = _file(bin_dir / "ffmpeg-8.1.3" / "bin" / "ffmpeg.exe")
    assert resolve() == str(downloaded)
    configured = _file(tmp_path / "custom" / "ffmpeg.exe")
    assert resolve(str(configured)) == str(configured)
    assert resolve(str(tmp_path / "missing.exe")) == str(downloaded)


def test_node_candidates_keep_the_legacy_x64_folder_and_drop_duplicates(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    legacy = _file(bin_dir / "node-x64" / "node.exe")

    candidates = tool_candidates(
        "node", str(legacy), bin_dir, None, which=lambda _: str(legacy), downloads=()
    )

    assert candidates == [str(legacy)]


def test_without_any_candidate_the_tool_is_unresolved(tmp_path: Path) -> None:
    assert resolve_tool("ffprobe", None, tmp_path, None, which=lambda _: None) is None
