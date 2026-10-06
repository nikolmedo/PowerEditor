"""Where bundled resources and external tools live, from source or from a frozen build.

A PyInstaller onedir build sets `sys.frozen` and unpacks its files to `sys._MEIPASS`
(`<app>/_internal/`). The build puts the web app at `_internal/powereditor/web` and the
Remotion renderer (prebuilt bundle, scripts, `node_modules`) at `_internal/composition`.
From source the same names point into the repository.

Tools (ffmpeg, ffprobe, node) resolve in this order: the configured path, a runtime
downloaded into `<data dir>/bin`, a runtime shipped next to the executable (`<app>/runtime`),
then `PATH`.
"""

import os
import shutil
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from powereditor.config import REPO_ROOT
from powereditor.runtime.manifest import DOWNLOADS, RuntimeDownload

ENV_WEB_DIR = "POWEREDITOR_WEB_DIR"
ENV_COMPOSITION_DIR = "POWEREDITOR_COMPOSITION_DIR"
PACKAGE_DIR = Path(__file__).resolve().parent

LEGACY_TOOL_DIRS: dict[str, tuple[str, ...]] = {"node": ("node-x64",)}
"""Folders under `bin/` used before the runtime manager existed."""

Which = Callable[[str], str | None]


@dataclass(frozen=True)
class Resources:
    frozen: bool
    bundle_dir: Path
    """Folder holding the `powereditor` package: `_internal/` frozen, `backend/` from source."""
    executable: Path

    @classmethod
    def current(cls) -> "Resources":
        frozen = bool(getattr(sys, "frozen", False))
        bundle_dir = Path(getattr(sys, "_MEIPASS", PACKAGE_DIR.parent)) if frozen else None
        return cls(
            frozen=frozen,
            bundle_dir=bundle_dir or PACKAGE_DIR.parent,
            executable=Path(sys.executable),
        )

    @property
    def runtime_dir(self) -> Path | None:
        """Runtimes shipped next to the executable; only a frozen build has them."""
        return self.executable.parent / "runtime" if self.frozen else None

    def web_dir(self) -> Path:
        """`POWEREDITOR_WEB_DIR`, then a bundled build, then the repo's `web/dist`."""
        override = os.environ.get(ENV_WEB_DIR)
        if override:
            return Path(override)
        bundled = self.bundle_dir / "powereditor" / "web"
        if (bundled / "index.html").is_file():
            return bundled
        return REPO_ROOT / "web" / "dist"

    def composition_dir(self) -> Path:
        """`POWEREDITOR_COMPOSITION_DIR`, then the bundled renderer, then the repo package."""
        override = os.environ.get(ENV_COMPOSITION_DIR)
        if override:
            return Path(override)
        if self.frozen:
            return self.bundle_dir / "composition"
        return REPO_ROOT / "packages" / "composition"

    def prebuilt_bundle(self) -> Path | None:
        """The Remotion bundle built ahead of time (`dist/bundle`), if there is one."""
        bundle = self.composition_dir() / "dist" / "bundle"
        return bundle if (bundle / "index.html").is_file() else None


def _dir_candidates(name: str, base: Path, downloads: Sequence[RuntimeDownload]) -> Iterator[Path]:
    for spec in downloads:
        if name in spec.tools:
            yield base / spec.dir_name / spec.tools[name]
    for folder in (*LEGACY_TOOL_DIRS.get(name, ()), ""):
        yield base / folder / f"{name}.exe"
        yield base / folder / name


def tool_candidates(
    name: str,
    configured: str | None,
    bin_dir: Path,
    runtime_dir: Path | None,
    which: Which | None = None,
    downloads: Sequence[RuntimeDownload] = DOWNLOADS,
) -> list[str]:
    """Every existing binary for `name`, best first, without duplicates."""
    found: list[str] = []
    if configured and Path(configured).is_file():
        found.append(configured)
    for base in (bin_dir, runtime_dir):
        if base is not None:
            found += [str(p) for p in _dir_candidates(name, base, downloads) if p.is_file()]
    system = (which or shutil.which)(name)
    if system:
        found.append(system)
    return list(dict.fromkeys(found))


def resolve_tool(
    name: str,
    configured: str | None,
    bin_dir: Path,
    runtime_dir: Path | None,
    which: Which | None = None,
    downloads: Sequence[RuntimeDownload] = DOWNLOADS,
) -> str | None:
    candidates = tool_candidates(name, configured, bin_dir, runtime_dir, which, downloads)
    return candidates[0] if candidates else None
