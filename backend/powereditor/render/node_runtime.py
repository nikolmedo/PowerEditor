"""Locate a Node.js binary able to run Remotion's native compositor.

Remotion publishes a compositor for win32-x64 but not win32-arm64, so on Windows
the renderer needs an x64 Node (it runs under emulation on ARM64 hosts). The host
architecture cannot be read from Python here: an emulated x64 Python reports AMD64.
Each candidate is therefore asked for its own `process.arch`.
"""

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

PROBE_TIMEOUT_S = 15
BUNDLED_NODE_DIR = "node-x64"

ArchProbe = Callable[[str], str | None]


class NodeRuntimeError(RuntimeError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def probe_node_arch(node: str) -> str | None:
    """`process.arch` of a Node binary, or None if it cannot be run."""
    try:
        result = subprocess.run(
            [node, "-p", "process.arch"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def resolve_render_node(
    configured: str | None,
    bin_dir: Path,
    probe_arch: ArchProbe = probe_node_arch,
    which: Callable[[str], str | None] = shutil.which,
    platform: str = sys.platform,
) -> str:
    """First usable Node: configured path, then the app's bundled x64 Node, then PATH."""
    required = "x64" if platform == "win32" else None
    candidates: list[str] = []
    if configured and Path(configured).is_file():
        candidates.append(configured)
    bundled_dir = bin_dir / BUNDLED_NODE_DIR
    candidates += [str(p) for p in (bundled_dir / "node.exe", bundled_dir / "node") if p.is_file()]
    system = which("node")
    if system:
        candidates.append(system)
    for candidate in candidates:
        arch = probe_arch(candidate)
        if arch is not None and (required is None or arch == required):
            return candidate
    if required is None:
        raise NodeRuntimeError("Node.js not found; configure nodePath in settings", "missing_node")
    raise NodeRuntimeError(
        f"rendering on {platform} needs an {required} Node.js (Remotion has no compositor for "
        f"other architectures); set nodePath or install one under {bin_dir / BUNDLED_NODE_DIR}",
        f"missing_node_{required}",
    )
