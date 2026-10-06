"""Build the Windows installer (per-user NSIS, x64) into `dist/installer/`.

Usage (from the repo root, any Python 3.12+; it only drives other tools):

    python scripts/build_installer.py [--skip-backend] [--smoke]

Steps: build the standalone backend (`scripts/build_backend.py`, with `--smoke` forwarded),
compile the Electron shell (`desktop/`), then run electron-builder, which copies
`dist/backend/powereditor` into the app's `resources/backend` and writes
`dist/installer/PowerEditor-Setup-<version>-x64.exe`.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND_BUILD = REPO / "dist" / "backend" / "powereditor"
INSTALLER_DIR = REPO / "dist" / "installer"


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=REPO, env=env, check=True)


def pnpm_works() -> bool:
    found = shutil.which("pnpm")
    if found is None:
        return False
    result = subprocess.run([found, "--version"], cwd=REPO, capture_output=True, text=True)
    return result.returncode == 0


def builder_env(shim_dir: Path, corepack: str) -> dict[str, str]:
    """electron-builder runs a bare `pnpm` to list modules; when the `pnpm` on PATH is
    missing or broken (a stale nvm shim, say), put one that calls Corepack first on PATH."""
    env = dict(os.environ)
    if pnpm_works():
        return env
    (shim_dir / "pnpm.cmd").write_text(f'@"{corepack}" pnpm %*\n', encoding="utf-8")
    env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-backend", action="store_true", help="reuse dist/backend")
    parser.add_argument("--smoke", action="store_true", help="smoke-test the backend build")
    args = parser.parse_args()
    corepack = shutil.which("corepack")
    if corepack is None:
        sys.exit("corepack not found on PATH")
    started = time.monotonic()
    if not args.skip_backend:
        run([sys.executable, "scripts/build_backend.py", *(["--smoke"] if args.smoke else [])])
    if not (BACKEND_BUILD / "powereditor-sidecar.exe").is_file():
        sys.exit(f"{BACKEND_BUILD} has no powereditor-sidecar.exe; build the backend first")
    run([corepack, "pnpm", "--filter", "@powereditor/desktop", "build"])
    with tempfile.TemporaryDirectory(prefix="pnpm-shim-") as shim_dir:
        env = builder_env(Path(shim_dir), corepack)
        run([corepack, "pnpm", "--filter", "@powereditor/desktop", "dist"], env)
    for installer in sorted(INSTALLER_DIR.glob("*.exe")):
        print(f"built {installer} ({installer.stat().st_size / 2**20:.0f} MiB)")
    print(f"done in {time.monotonic() - started:.0f}s")


if __name__ == "__main__":
    main()
