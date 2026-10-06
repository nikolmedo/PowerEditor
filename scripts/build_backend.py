"""Build the standalone backend (PyInstaller onedir) into `dist/backend/powereditor/`.

Usage (from the repo root, any Python 3.12+; it only drives other tools):

    python scripts/build_backend.py [--skip-web] [--skip-bundle] [--smoke]

Steps: build the web app, bundle the Remotion composition ahead of time, stage the
standalone renderer (`build/composition`), run PyInstaller through `uv run --with pyinstaller`
(so PyInstaller never becomes a project dependency), check that no GPL library or PyAV
reached the build, then copy the renderer into the build.
`--smoke` starts the built sidecar on a free port and checks `/api/health` and `/`.
"""

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import IO

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
COMPOSITION = REPO / "packages" / "composition"
BUILD = REPO / "build"
DIST = REPO / "dist" / "backend"
PYINSTALLER = "pyinstaller==6.22.3"
READY_PREFIX = "POWEREDITOR_READY"
TOKEN_HEADER = "X-PowerEditor-Token"
SMOKE_TIMEOUT_S = 120
# GPL-licensed libraries that must not ship inside the engine (PyAV's wheel carries x264 and
# x265; postproc only exists in GPL FFmpeg builds), and PyAV itself, which the spec excludes.
GPL_FILE_PREFIXES = ("libx264", "libx265", "postproc")
PYAV_FOLDERS = ("av", "av.libs")
# Remotion's renderer: a separate program whose GPL FFmpeg is noticed with a source offer
# in THIRD_PARTY_NOTICES.md.
NOTICED_GPL_FOLDER = "composition"


def tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        sys.exit(f"{name} not found on PATH")
    return found


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def folder_size(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def gpl_findings(internal: Path) -> list[str]:
    """Paths under `internal` (the build's `_internal`) that must not ship, sorted."""
    found = [name for name in PYAV_FOLDERS if (internal / name).exists()]
    for path in internal.rglob("*"):
        relative = path.relative_to(internal)
        if relative.parts[0] == NOTICED_GPL_FOLDER:
            continue
        if path.is_file() and path.name.lower().startswith(GPL_FILE_PREFIXES):
            found.append(relative.as_posix())
    return sorted(found)


def build(skip_web: bool, skip_bundle: bool) -> Path:
    node, corepack, uv = tool("node"), tool("corepack"), tool("uv")
    if not skip_web:
        run([corepack, "pnpm", "--filter", "@powereditor/web", "build"], REPO)
    if not skip_bundle:
        run([node, "scripts/bundle.mjs"], COMPOSITION)
    staged = BUILD / "composition"
    run([node, "scripts/stage-renderer.mjs", "--out", str(staged)], COMPOSITION)
    env = {**os.environ, "POWEREDITOR_BUILD_WEB": str(REPO / "web" / "dist")}
    pyinstaller = [
        uv, "run", "--with", PYINSTALLER, "pyinstaller", "packaging/powereditor.spec",
        "--noconfirm", "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"),
    ]  # fmt: skip
    run(pyinstaller, BACKEND, env)
    app = DIST / "powereditor"
    findings = gpl_findings(app / "_internal")
    if findings:
        sys.exit(f"the build contains GPL libraries or PyAV: {', '.join(findings)}")
    print("licensing check: no GPL library or PyAV in the engine")
    # Copied as is (see powereditor.spec): Resources.composition_dir() reads it from here.
    target = app / "_internal" / "composition"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(staged, target)
    print(f"built {app} ({folder_size(app) / 2**20:.0f} MiB)")
    return app


def read_lines(stream: IO[str]) -> "queue.Queue[str | None]":
    """Lines of `stream` from a reader thread (pipes cannot be polled on Windows); None at EOF."""
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        for line in stream:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    return lines


def wait_for_ready(lines: "queue.Queue[str | None]", timeout_s: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while (left := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=left)
        except queue.Empty:
            break
        if line is None:
            sys.exit("the sidecar exited before printing its READY line")
        if line.startswith(READY_PREFIX):
            ready: dict[str, object] = json.loads(line.split(" ", 1)[1])
            return ready
    sys.exit(f"the sidecar printed no READY line within {timeout_s:.0f}s")


def smoke(app: Path) -> None:
    """Start the sidecar on a free port, then fetch the health check and the web app."""
    started = time.monotonic()
    server = subprocess.Popen(
        [str(app / "powereditor-sidecar.exe"), "serve", "--port", "0"],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert server.stdout is not None
        ready = wait_for_ready(read_lines(server.stdout), SMOKE_TIMEOUT_S)
        port, token = ready["port"], str(ready["token"])
        print(f"ready on port {port} after {time.monotonic() - started:.1f}s")
        for path in ("/api/health", "/"):
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}", headers={TOKEN_HEADER: token}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(200).decode("utf-8", "replace")
                print(f"GET {path}: {response.status} {body[:80]!r}")
    finally:
        server.terminate()
        try:
            server.wait(30)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(30)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-web", action="store_true", help="reuse the existing web/dist")
    parser.add_argument("--skip-bundle", action="store_true", help="reuse the composition bundle")
    parser.add_argument("--smoke", action="store_true", help="start the build and probe it")
    args = parser.parse_args()
    app = build(args.skip_web, args.skip_bundle)
    if args.smoke:
        smoke(app)


if __name__ == "__main__":
    main()
