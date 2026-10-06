"""Download, verify and install the runtimes the packaged app needs (see `manifest`).

A download is streamed to a temporary folder inside `<data dir>/bin`, checked against its
pinned SHA-256, extracted (only the files the app uses, with the archive's top-level folder
stripped) and renamed into `bin/<name>-<version>/` in one step, so a folder with that name
is always a complete install. A lock file per runtime keeps a second installer (the CLI
next to the app, say) waiting instead of downloading the same archive again.

The Chrome Headless Shell Remotion renders with is installed by Remotion itself
(`ensure-browser.mjs` under the render Node), into `bin/remotion/node_modules/.remotion`.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import httpx

from powereditor.models import CamelModel
from powereditor.process import tracked
from powereditor.resources import Resources
from powereditor.runtime.manifest import DOWNLOADS, RuntimeDownload

if TYPE_CHECKING:
    from powereditor.settings_store import SettingsService

Progress = Callable[[float], None]

CHUNK_BYTES = 1 << 20
DOWNLOAD_TIMEOUT = httpx.Timeout(30.0, read=120.0)
RENAME_ATTEMPTS = 5
RENAME_RETRY_DELAY_S = 0.5
LOCK_POLL_S = 0.2
LOCK_TIMEOUT_S = 30 * 60.0
BROWSER = "browser"
BROWSER_CACHE_DIR = "remotion"
_BROWSER_EXECUTABLES = {
    "win32": "win64/chrome-headless-shell-win64/chrome-headless-shell.exe",
    "linux": "linux64/chrome-headless-shell-linux64/chrome-headless-shell",
}


class RuntimeInstallError(RuntimeError):
    code = "runtime_install_failed"


class RuntimeChecksumError(RuntimeInstallError):
    code = "runtime_checksum_mismatch"


class RuntimeUnsupportedError(RuntimeInstallError):
    code = "runtime_unsupported_platform"


class UnknownRuntimeError(LookupError):
    code = "unknown_runtime"


class RuntimeStatus(CamelModel):
    name: str
    version: str | None
    supported: bool
    installed: bool
    path: str | None
    """The installed executable (the first tool of a download)."""
    download_bytes: int | None


def _download(
    spec: RuntimeDownload, target: Path, client: httpx.Client, progress: Progress
) -> None:
    digest = hashlib.sha256()
    done = 0
    with client.stream("GET", spec.url) as response, target.open("wb") as out:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or spec.size) or 1
        for chunk in response.iter_bytes(CHUNK_BYTES):
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            progress(min(done / total, 1.0))
    if digest.hexdigest() != spec.sha256:
        raise RuntimeChecksumError(
            f"{spec.name} {spec.version}: SHA-256 {digest.hexdigest()} does not match the "
            f"pinned {spec.sha256}"
        )
    progress(1.0)


def _member_path(info: zipfile.ZipInfo) -> PurePosixPath:
    """The member's path below the archive's top-level folder, refusing unsafe members."""
    name = info.filename
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or ":" in name:
        raise RuntimeInstallError(f"archive member has an unsafe path: {name}")
    if stat.S_ISLNK(info.external_attr >> 16):
        raise RuntimeInstallError(f"archive member is a symbolic link: {name}")
    return PurePosixPath(*path.parts[1:])


def _kept(path: PurePosixPath, keep: Sequence[str]) -> bool:
    return not keep or any(
        path == PurePosixPath(k) or PurePosixPath(k) in path.parents for k in keep
    )


def _extract(archive: Path, destination: Path, spec: RuntimeDownload) -> None:
    with zipfile.ZipFile(archive) as zipped:
        members = [(info, _member_path(info)) for info in zipped.infolist()]
        for info, path in members:
            if info.is_dir() or not path.parts or not _kept(path, spec.keep):
                continue
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(info) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out, CHUNK_BYTES)
    missing = [tool for tool in spec.tools.values() if not (destination / tool).is_file()]
    if missing:
        raise RuntimeInstallError(f"{spec.name} archive lacks {', '.join(missing)}")


@contextmanager
def _install_lock(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive lock on `lock_path` (between processes and between threads)."""
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    with lock_path.open("a+b") as handle:
        while not _try_lock(handle.fileno()):
            if time.monotonic() > deadline:
                raise RuntimeInstallError(f"another install holds {lock_path.name}")
            time.sleep(LOCK_POLL_S)
        try:
            yield
        finally:
            _unlock(handle.fileno())


if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _rename_with_retry(source: Path, target: Path) -> None:
    """Rename, retrying while Windows reports the fresh files as in use (antivirus, indexer)."""
    for attempt in range(1, RENAME_ATTEMPTS + 1):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == RENAME_ATTEMPTS:
                raise
            time.sleep(RENAME_RETRY_DELAY_S * attempt)


def install_download(
    spec: RuntimeDownload,
    bin_dir: Path,
    *,
    transport: httpx.BaseTransport | None = None,
    progress: Progress | None = None,
    platform: str = sys.platform,
) -> Path:
    """Install `spec` into `bin_dir/<name>-<version>` (a no-op when it is already there)."""
    if platform != spec.platform:
        raise RuntimeUnsupportedError(f"{spec.name} is only packaged for {spec.platform}")
    target = bin_dir / spec.dir_name
    if target.is_dir():
        return target
    bin_dir.mkdir(parents=True, exist_ok=True)
    with _install_lock(bin_dir / f".{spec.dir_name}.lock"):
        if target.is_dir():  # another install finished while this one waited
            return target
        with (
            tempfile.TemporaryDirectory(dir=bin_dir, prefix=f".{spec.dir_name}-") as scratch,
            httpx.Client(
                transport=transport, follow_redirects=True, timeout=DOWNLOAD_TIMEOUT
            ) as client,
        ):
            archive = Path(scratch) / "download.zip"
            try:
                _download(spec, archive, client, progress or (lambda _: None))
            except httpx.HTTPError as exc:
                raise RuntimeInstallError(f"downloading {spec.name} failed: {exc}") from exc
            staging = Path(scratch) / "extracted"
            _extract(archive, staging, spec)
            _rename_with_retry(staging, target)
    return target


def browser_cache_dir(bin_dir: Path) -> Path:
    return bin_dir / BROWSER_CACHE_DIR


def prepare_browser_cache(cache_dir: Path) -> Path:
    """A folder with a `package.json`, so Remotion keeps its browser below it."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = cache_dir / "package.json"
    if not manifest.is_file():
        manifest.write_text('{"private": true}\n', encoding="utf-8")
    return cache_dir


def browser_executable(cache_dir: Path, platform: str = sys.platform) -> Path | None:
    relative = _BROWSER_EXECUTABLES.get(platform)
    if relative is None:
        return None
    return cache_dir / "node_modules" / ".remotion" / "chrome-headless-shell" / relative


def install_browser(node: str, script: Path, cache_dir: Path, progress: Progress) -> Path:
    """Run `ensure-browser.mjs` and return the browser it reports."""
    prepare_browser_cache(cache_dir)
    path: str | None = None
    failure: str | None = None
    other: list[str] = []
    try:
        with (
            subprocess.Popen(
                [node, str(script)],
                cwd=cache_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            ) as process,
            tracked(process),
        ):
            assert process.stdout is not None
            for line in process.stdout:
                event = _event(line)
                kind, fraction, reported = (
                    event.get("event"),
                    event.get("fraction"),
                    event.get("path"),
                )
                if kind == "progress" and isinstance(fraction, int | float):
                    progress(min(float(fraction), 1.0))
                elif kind == "done" and isinstance(reported, str):
                    path = reported
                elif kind == "error":
                    failure = str(event.get("message"))
                elif not event:
                    other.append(line)
            returncode = process.wait()
    except OSError as exc:
        raise RuntimeInstallError(f"installing the render browser failed: {exc}") from exc
    if returncode != 0 or path is None:
        cause = failure or "".join(other).strip()[-2000:] or f"exit code {returncode}"
        raise RuntimeInstallError(f"installing the render browser failed: {cause}")
    return Path(path)


def _event(line: str) -> dict[str, object]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return {}
    return event if isinstance(event, dict) else {}


@dataclass
class RuntimeManager:
    bin_dir: Path
    downloads: Sequence[RuntimeDownload] = DOWNLOADS
    transport: httpx.BaseTransport | None = None
    platform: str = sys.platform
    node: Callable[[], str] | None = None
    """Resolves the render Node, which installs the browser."""
    composition_dir: Path | None = None

    def names(self) -> list[str]:
        return [spec.name for spec in self.downloads] + [BROWSER]

    def statuses(self) -> list[RuntimeStatus]:
        statuses = []
        for spec in self.downloads:
            folder = self.bin_dir / spec.dir_name
            tool = folder / next(iter(spec.tools.values()))
            installed = folder.is_dir() and tool.is_file()
            statuses.append(
                RuntimeStatus(
                    name=spec.name,
                    version=spec.version,
                    supported=spec.platform == self.platform,
                    installed=installed,
                    path=str(tool) if installed else None,
                    download_bytes=spec.size,
                )
            )
        browser = browser_executable(browser_cache_dir(self.bin_dir), self.platform)
        browser_found = browser is not None and browser.is_file()
        statuses.append(
            RuntimeStatus(
                name=BROWSER,
                version=None,
                supported=browser is not None,
                installed=browser_found,
                path=str(browser) if browser_found else None,
                download_bytes=None,
            )
        )
        return statuses

    def install(self, name: str, progress: Progress) -> RuntimeStatus:
        if name == BROWSER:
            if self.node is None or self.composition_dir is None:
                raise RuntimeInstallError("the render browser needs Node and the composition")
            script = self.composition_dir / "scripts" / "ensure-browser.mjs"
            install_browser(self.node(), script, browser_cache_dir(self.bin_dir), progress)
        else:
            spec = next((s for s in self.downloads if s.name == name), None)
            if spec is None:
                raise UnknownRuntimeError(f"unknown runtime {name!r}; known: {self.names()}")
            install_download(
                spec,
                self.bin_dir,
                transport=self.transport,
                progress=progress,
                platform=self.platform,
            )
        return next(status for status in self.statuses() if status.name == name)


def manager_for(
    service: "SettingsService",
    downloads: Sequence[RuntimeDownload] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> RuntimeManager:
    """The manager for the app's data dir, installing the browser with the render Node."""
    from powereditor.render.node_runtime import resolve_render_node

    resources = Resources.current()
    return RuntimeManager(
        bin_dir=service.paths.bin_dir,
        downloads=DOWNLOADS if downloads is None else downloads,
        transport=transport,
        node=lambda: resolve_render_node(
            service.get_effective().node_path,
            service.paths.bin_dir,
            runtime_dir=resources.runtime_dir,
        ),
        composition_dir=resources.composition_dir(),
    )
