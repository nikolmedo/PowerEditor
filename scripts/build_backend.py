"""Build the standalone backend (PyInstaller onedir) into `dist/backend/powereditor/`.

Usage (from the repo root, any Python 3.12+; it only drives other tools):

    python scripts/build_backend.py [--skip-web] [--skip-bundle] [--smoke]

Steps: build the web app, bundle the Remotion composition ahead of time, stage the
standalone renderer (`build/composition`), run PyInstaller through `uv run --with pyinstaller`
(so PyInstaller never becomes a project dependency), then copy the renderer into the build.
`--smoke` starts the built sidecar on a free port and checks `/api/health` and `/`.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
COMPOSITION = REPO / "packages" / "composition"
BUILD = REPO / "build"
DIST = REPO / "dist" / "backend"
PYINSTALLER = "pyinstaller==6.22.3"
READY_PREFIX = "POWEREDITOR_READY"
SMOKE_TIMEOUT_S = 120


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
    # Copied as is (see powereditor.spec): Resources.composition_dir() reads it from here.
    shutil.copytree(staged, app / "_internal" / "composition")
    print(f"built {app} ({folder_size(app) / 2**20:.0f} MiB)")
    return app


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
        line = ""
        while not line.startswith(READY_PREFIX):
            line = server.stdout.readline()
            if not line or time.monotonic() - started > SMOKE_TIMEOUT_S:
                sys.exit("the sidecar exited or never printed its READY line")
        port = json.loads(line.split(" ", 1)[1])["port"]
        print(f"ready on port {port} after {time.monotonic() - started:.1f}s")
        for path in ("/api/health", "/"):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=30) as response:
                body = response.read(200).decode("utf-8", "replace")
                print(f"GET {path}: {response.status} {body[:80]!r}")
    finally:
        server.terminate()
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
