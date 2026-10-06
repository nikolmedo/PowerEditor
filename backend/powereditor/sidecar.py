"""Run `powereditor serve` as a sidecar of the desktop shell.

The shell starts `powereditor serve --port 0 --parent-pid <its pid>` and reads stdout until
one line `POWEREDITOR_READY {"port": N, "token": "..."}`: the server binds a free loopback
port itself, so the line is printed only once it accepts connections. With `--parent-pid`
the server polls the parent and shuts down cleanly (running jobs are cancelled) once it is
gone, so a crashed shell never leaves an orphan backend.
"""

import json
import os
import socket
import sys
import threading
import time
from collections.abc import Callable

import uvicorn

READY_PREFIX = "POWEREDITOR_READY"
PARENT_POLL_S = 1.0


def ready_line(port: int, token: str) -> str:
    return f"{READY_PREFIX} {json.dumps({'port': port, 'token': token})}"


def announce(line: str) -> None:
    """Print one line for the parent; a windowed build may have no stdout at all."""
    if sys.stdout is not None:
        sys.stdout.write(f"{line}\n")
        sys.stdout.flush()


def bind_loopback(host: str, port: int) -> socket.socket:
    """A listening-ready socket on `host:port`; port 0 picks a free one."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259
    _ERROR_ACCESS_DENIED = 5

    def _process_alive(pid: int) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
        try:
            code = wintypes.DWORD()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and (
                code.value == _STILL_ACTIVE
            )
        finally:
            kernel32.CloseHandle(handle)

else:

    def _process_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def parent_alive(pid: int) -> bool:
    return pid > 0 and _process_alive(pid)


def watch_parent(
    pid: int, on_exit: Callable[[], None], poll_s: float = PARENT_POLL_S
) -> threading.Thread:
    """Call `on_exit` (once, from a daemon thread) when process `pid` is gone."""

    def poll() -> None:
        while parent_alive(pid):
            time.sleep(poll_s)
        on_exit()

    thread = threading.Thread(target=poll, name="parent-watch", daemon=True)
    thread.start()
    return thread


class AnnouncingServer(uvicorn.Server):
    """A uvicorn server that calls `on_started` once its sockets accept connections."""

    def __init__(self, config: uvicorn.Config, on_started: Callable[[], None]) -> None:
        super().__init__(config)
        self._on_started = on_started

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            self._on_started()
