"""Locate a Node.js binary able to run Remotion's native compositor.

Remotion publishes a compositor for win32-x64 but not win32-arm64. On Windows the
renderer therefore accepts an x64 Node or a native arm64 one: under arm64, the render
script points Remotion at the x64 compositor (`binariesDirectory`), which runs as its own
process that Windows emulates. The host architecture cannot be read from Python here: an
emulated x64 Python reports AMD64. Each candidate is therefore asked for its own
`process.arch`.
"""

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from powereditor.process import hidden_console_flags
from powereditor.resources import tool_candidates

PROBE_TIMEOUT_S = 15
# Node architectures that can drive the win32-x64 compositor.
WINDOWS_ARCHES = frozenset({"x64", "arm64"})

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
            creationflags=hidden_console_flags(),
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
    *,
    runtime_dir: Path | None = None,
) -> str:
    """First usable Node, in the order of `resources.tool_candidates`, checked for its arch."""
    accepted = WINDOWS_ARCHES if platform == "win32" else None
    candidates = tool_candidates("node", configured, bin_dir, runtime_dir, which)
    for candidate in candidates:
        arch = probe_arch(candidate)
        if arch is not None and (accepted is None or arch in accepted):
            return candidate
    if accepted is None:
        raise NodeRuntimeError("Node.js not found; configure nodePath in settings", "missing_node")
    raise NodeRuntimeError(
        f"rendering on {platform} needs an x64 or arm64 Node.js (Remotion has no compositor "
        f"for other architectures); set nodePath or run `powereditor runtime install node`",
        "missing_node_x64",
    )
