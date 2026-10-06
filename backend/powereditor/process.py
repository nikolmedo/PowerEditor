import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


def kill_tree(process: "subprocess.Popen[str]") -> None:
    """Kill a child process and its descendants so its pipes close."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False
        )
    process.kill()


class ProcessScope:
    """The child processes started on behalf of one cancellable job."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: set[subprocess.Popen[str]] = set()
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def add(self, process: "subprocess.Popen[str]") -> None:
        with self._lock:
            self._processes.add(process)
            cancelled = self._cancelled
        if cancelled:
            kill_tree(process)

    def discard(self, process: "subprocess.Popen[str]") -> None:
        with self._lock:
            self._processes.discard(process)

    def cancel(self) -> None:
        """Kill every tracked process tree, and any process tracked from now on."""
        with self._lock:
            self._cancelled = True
            running = list(self._processes)
        for process in running:
            if process.poll() is None:
                kill_tree(process)


_current_scope: ContextVar[ProcessScope | None] = ContextVar("process_scope", default=None)


@contextmanager
def process_scope(scope: ProcessScope) -> Iterator[ProcessScope]:
    """Make `scope` own the processes tracked by this thread until the block ends."""
    token = _current_scope.set(scope)
    try:
        yield scope
    finally:
        _current_scope.reset(token)


@contextmanager
def tracked(process: "subprocess.Popen[str]") -> Iterator[None]:
    """Register a long-running child with the current scope so a cancel can kill it."""
    scope = _current_scope.get()
    if scope is None:
        yield
        return
    scope.add(process)
    try:
        yield
    finally:
        scope.discard(process)
