import hashlib
import io
import stat
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from powereditor import cli
from powereditor.runtime import manager
from powereditor.runtime.manager import (
    RuntimeChecksumError,
    RuntimeInstallError,
    RuntimeManager,
    RuntimeUnsupportedError,
    UnknownRuntimeError,
    install_browser,
    install_download,
)
from powereditor.runtime.manifest import RuntimeDownload

URL = "https://downloads.example/tool-1.0.zip"
MIRROR = "https://objects.example/tool-1.0.zip"


def make_zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


ARCHIVE = make_zip(
    {
        "tool-1.0/bin/tool.exe": b"binary",
        "tool-1.0/bin/extra.exe": b"not wanted",
        "tool-1.0/doc/readme.html": b"docs",
        "tool-1.0/LICENSE.txt": b"license",
    }
)


def spec_for(archive: bytes, **overrides: object) -> RuntimeDownload:
    values: dict[str, object] = {
        "name": "tool",
        "version": "1.0",
        "url": URL,
        "sha256": hashlib.sha256(archive).hexdigest(),
        "size": len(archive),
        "tools": {"tool": "bin/tool.exe"},
        "keep": ("bin/tool.exe", "LICENSE.txt"),
        "platform": sys.platform,
    }
    values.update(overrides)
    return RuntimeDownload(**values)  # type: ignore[arg-type]


def redirecting_transport(archive: bytes) -> httpx.MockTransport:
    """Like GitHub release assets: the URL redirects to a storage host."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == URL:
            return httpx.Response(302, headers={"Location": MIRROR})
        if str(request.url) == MIRROR:
            return httpx.Response(200, content=archive)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def entries(bin_dir: Path) -> list[str]:
    """What an install left in `bin_dir`, without the per-runtime lock files."""
    return sorted(p.name for p in bin_dir.iterdir() if p.suffix != ".lock")


def files_under(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def test_install_follows_redirects_verifies_and_extracts_only_kept_files(tmp_path: Path) -> None:
    fractions: list[float] = []
    bin_dir = tmp_path / "bin"

    target = install_download(
        spec_for(ARCHIVE),
        bin_dir,
        transport=redirecting_transport(ARCHIVE),
        progress=fractions.append,
    )

    assert target == bin_dir / "tool-1.0"
    assert files_under(target) == ["LICENSE.txt", "bin/tool.exe"]
    assert (target / "bin" / "tool.exe").read_bytes() == b"binary"
    assert entries(bin_dir) == ["tool-1.0"]
    assert fractions[-1] == 1.0
    assert fractions == sorted(fractions)


def test_install_rejects_a_checksum_mismatch_and_leaves_nothing(tmp_path: Path) -> None:
    spec = spec_for(ARCHIVE, sha256="0" * 64)

    with pytest.raises(RuntimeChecksumError) as excinfo:
        install_download(spec, tmp_path / "bin", transport=redirecting_transport(ARCHIVE))

    assert excinfo.value.code == "runtime_checksum_mismatch"
    assert entries(tmp_path / "bin") == []


def test_install_refuses_members_that_escape_the_target(tmp_path: Path) -> None:
    archive = make_zip({"tool-1.0/bin/tool.exe": b"x", "tool-1.0/../../evil.exe": b"x"})

    with pytest.raises(RuntimeInstallError, match="unsafe path"):
        install_download(
            spec_for(archive, keep=()), tmp_path / "bin", transport=redirecting_transport(archive)
        )

    assert not (tmp_path / "evil.exe").exists()
    assert entries(tmp_path / "bin") == []


def test_install_refuses_symbolic_links(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("tool-1.0/bin/tool.exe", b"x")
        link = zipfile.ZipInfo("tool-1.0/bin/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "../../../../evil")
    data = buffer.getvalue()

    with pytest.raises(RuntimeInstallError, match="symbolic link"):
        install_download(
            spec_for(data, keep=()), tmp_path / "bin", transport=redirecting_transport(data)
        )

    assert entries(tmp_path / "bin") == []


def test_install_retries_a_rename_blocked_by_another_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Antivirus and indexers briefly lock fresh files on Windows."""
    real_rename = Path.rename
    failures = [PermissionError("locked"), PermissionError("locked")]

    def flaky_rename(self: Path, target: Path) -> Path:
        if failures:
            raise failures.pop()
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)
    monkeypatch.setattr(manager, "RENAME_RETRY_DELAY_S", 0.0)

    target = install_download(
        spec_for(ARCHIVE), tmp_path / "bin", transport=redirecting_transport(ARCHIVE)
    )

    assert failures == []
    assert (target / "bin" / "tool.exe").read_bytes() == b"binary"


def test_concurrent_installs_download_once(tmp_path: Path) -> None:
    downloads: list[str] = []
    inner = redirecting_transport(ARCHIVE)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == MIRROR:
            downloads.append(str(request.url))
            time.sleep(0.3)
        return inner.handle_request(request)

    transport = httpx.MockTransport(handler)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: install_download(
                    spec_for(ARCHIVE), tmp_path / "bin", transport=transport
                ),
                range(2),
            )
        )

    assert results == [tmp_path / "bin" / "tool-1.0"] * 2
    assert len(downloads) == 1
    assert files_under(results[0]) == ["LICENSE.txt", "bin/tool.exe"]


def test_install_fails_when_the_archive_lacks_a_tool(tmp_path: Path) -> None:
    archive = make_zip({"tool-1.0/README": b"x"})

    with pytest.raises(RuntimeInstallError, match=r"bin/tool\.exe"):
        install_download(
            spec_for(archive, keep=()), tmp_path / "bin", transport=redirecting_transport(archive)
        )


def test_install_refuses_another_platform(tmp_path: Path) -> None:
    spec = spec_for(ARCHIVE, platform="plan9")

    with pytest.raises(RuntimeUnsupportedError):
        install_download(spec, tmp_path / "bin", transport=redirecting_transport(ARCHIVE))


def test_manager_reports_status_before_and_after_an_install(tmp_path: Path) -> None:
    manager = RuntimeManager(
        bin_dir=tmp_path / "bin",
        downloads=(spec_for(ARCHIVE),),
        transport=redirecting_transport(ARCHIVE),
    )

    before = {status.name: status for status in manager.statuses()}
    manager.install("tool", lambda _: None)
    after = {status.name: status for status in manager.statuses()}

    assert sorted(before) == ["browser", "tool"]
    assert (before["tool"].installed, before["tool"].path) == (False, None)
    assert after["tool"].installed
    assert after["tool"].path == str(tmp_path / "bin" / "tool-1.0" / "bin" / "tool.exe")
    assert after["tool"].version == "1.0"
    assert after["browser"].installed is False
    with pytest.raises(UnknownRuntimeError):
        manager.install("nope", lambda _: None)


FAKE_ENSURE_BROWSER = r"""
import json, os, pathlib, sys
mode = os.environ["FAKE_BROWSER_MODE"]
if mode == "error":
    print(json.dumps({"event": "error", "message": "download refused"}), flush=True)
    sys.exit(1)
print("noise", flush=True)
for fraction in (0.5, 1.0):
    print(json.dumps({"event": "progress", "fraction": fraction}), flush=True)
exe = pathlib.Path(os.getcwd()) / "node_modules" / ".remotion" / "chrome.exe"
exe.parent.mkdir(parents=True)
exe.write_bytes(b"")
print(json.dumps({"event": "done", "path": str(exe), "type": "local-puppeteer-browser"}))
"""


def test_install_browser_runs_the_script_in_a_writable_package_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BROWSER_MODE", "ok")
    script = tmp_path / "ensure_browser.py"
    script.write_text(FAKE_ENSURE_BROWSER, encoding="utf-8")
    cache = tmp_path / "bin" / "remotion"
    fractions: list[float] = []

    path = install_browser(sys.executable, script, cache, fractions.append)

    assert path == cache / "node_modules" / ".remotion" / "chrome.exe"
    assert (cache / "package.json").is_file()
    assert fractions == [0.5, 1.0]


def test_install_browser_reports_the_script_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BROWSER_MODE", "error")
    script = tmp_path / "ensure_browser.py"
    script.write_text(FAKE_ENSURE_BROWSER, encoding="utf-8")

    with pytest.raises(RuntimeInstallError, match="download refused"):
        install_browser(sys.executable, script, tmp_path / "cache", lambda _: None)


def test_cli_installs_and_reports_runtimes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = RuntimeManager(
        bin_dir=tmp_path / "bin",
        downloads=(spec_for(ARCHIVE),),
        transport=redirecting_transport(ARCHIVE),
    )
    monkeypatch.setattr(cli, "runtime_manager", lambda _service: manager)
    runner = CliRunner()

    before = runner.invoke(cli.app, ["runtime", "status"])
    install = runner.invoke(cli.app, ["runtime", "install", "tool"])
    after = runner.invoke(cli.app, ["runtime", "status"])
    unknown = runner.invoke(cli.app, ["runtime", "install", "nope"])

    assert "tool" in before.output and "missing" in before.output
    assert install.exit_code == 0, install.output
    assert "tool 1.0 installed" in install.output
    assert after.output.count("installed") == 1
    assert unknown.exit_code == 1
    assert "unknown_runtime" in unknown.output
