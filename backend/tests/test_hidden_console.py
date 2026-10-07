"""Child processes must not open console windows.

The desktop app runs the engine as a windowed executable, so on Windows every console
program it starts (ffmpeg, ffprobe, node, taskkill) would get a new console window on
top of the app unless the launch passes `CREATE_NO_WINDOW`.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from powereditor import process
from powereditor.process import hidden_console_flags

PACKAGE_DIR = Path(process.__file__).resolve().parent
LAUNCHERS = {"run", "Popen", "call", "check_call", "check_output"}
HELPER = hidden_console_flags.__name__
# The Explorer reveal must show its window, so it opts out on purpose.
ALLOWED = {("api/services.py", "explorer_revealer")}
CREATE_NO_WINDOW = 0x08000000


def test_flags_hide_the_console_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    assert hidden_console_flags() == CREATE_NO_WINDOW


def test_flags_keep_extra_windows_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    new_group = 0x00000200

    assert hidden_console_flags(new_group) == CREATE_NO_WINDOW | new_group


def test_flags_are_zero_elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    assert hidden_console_flags() == 0
    assert hidden_console_flags(0x00000200) == 0


def test_zero_flags_are_accepted_by_popen() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "print('ok')"],
        capture_output=True,
        text=True,
        check=True,
        creationflags=hidden_console_flags(),
    )

    assert result.stdout.strip() == "ok"


def _launches(tree: ast.AST) -> list[tuple[str, ast.Call]]:
    """Every `subprocess.<launcher>(...)` call with the function that contains it."""
    found: list[tuple[str, ast.Call]] = []

    def visit(node: ast.AST, owner: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            owner = node.name
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LAUNCHERS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
        ):
            found.append((owner, node))
        for child in ast.iter_child_nodes(node):
            visit(child, owner)

    visit(tree, "<module>")
    return found


def _hides_console(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg == "creationflags":
            return any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == HELPER
                for node in ast.walk(keyword.value)
            )
    return False


def test_every_launch_hides_its_console() -> None:
    launches: list[str] = []
    offenders: list[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        relative = path.relative_to(PACKAGE_DIR).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for owner, call in _launches(tree):
            where = f"{relative}:{call.lineno} ({owner})"
            launches.append(where)
            if (relative, owner) not in ALLOWED and not _hides_console(call):
                offenders.append(where)

    assert len(launches) >= 10, launches
    assert offenders == []
